"""议题 #98-2 回归：停止后「继续刮削剩余任务」的可靠性与 remain.txt 落盘。

锁定四类行为：
1. 原子写：remain.txt 只以 tmp + os.replace 落盘，读取端永远看到完整版本，
   磁盘上不残留 .tmp 孤儿；
2. 脏标志竞态：后台保存线程落盘的是旧快照时，不得清掉新变化的 dirty 标志
   （旧实现无条件清，最新剩余任务永远落不了盘）；
3. save_remain_list_now：忽略 dirty 立即落盘当前快照（停止/退出兜底）；
4. 续刮子集不做全库 cleanup_missing（scraper._run 的 full_library_scan 判定）
   且 start_new_scrape 收到的是快照而非共享引用。
"""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.base.file import _remain_save_lock, _save_remain_list_sync, save_remain_list, save_remain_list_now
from mdcx.config.enums import Switch
from mdcx.models.flags import Flags


def _remain_txt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    remain_path = tmp_path / "remain.txt"
    monkeypatch.setattr("mdcx.base.file.resources.u", lambda _name: remain_path)
    return remain_path


def _save_locked(paths):
    """绕过线程入口直接驱动保存函数（与生产路径同样持锁）。"""
    assert _remain_save_lock.acquire(blocking=False), "测试并发污染：锁被占"
    try:
        _save_remain_list_sync(paths)
    finally:
        pass  # _save_remain_list_sync 自己 release（finally 里）


class _SwitchOn:
    """让 Switch.REMAIN_TASK in manager.config.switch_on 为真/假的上下文桩。"""

    def __init__(self, contains: bool):
        self._contains = contains

    def __contains__(self, item) -> bool:
        return self._contains and item is Switch.REMAIN_TASK


@pytest.fixture()
def remain_task_on(monkeypatch: pytest.MonkeyPatch):
    """REMAIN_TASK 开关置开 + 恢复。"""
    from mdcx.config.manager import manager

    original = manager.config.switch_on
    monkeypatch.setattr(manager.config, "switch_on", _SwitchOn(True))
    yield
    monkeypatch.setattr(manager.config, "switch_on", original)


def test_remain_save_is_atomic_no_tmp_left(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remain_task_on):
    """落盘走 tmp + os.replace：文件内容完整、无 .tmp 残留。"""
    remain_path = _remain_txt(monkeypatch, tmp_path)
    paths = [Path(f"/lib/movie-{i}.mp4") for i in range(3)]
    Flags.remain_list = list(paths)
    Flags.can_save_remain = True

    _save_locked(list(paths))

    content = remain_path.read_text(encoding="utf-8")
    assert "movie-0.mp4" in content and "movie-2.mp4" in content
    assert remain_path.exists()
    # 无孤儿临时文件
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    # 快照一致 → dirty 已清
    assert Flags.can_save_remain is False


def test_stale_snapshot_does_not_clear_new_dirty_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remain_task_on):
    """保存期间 remain_list 又变化：旧快照落盘后不得清 dirty（议题 #98 2.1）。

    复现序列：
      T0 快照 100 个任务 → 后台保存中
      T1 完成一部 → remain_list 99 个，dirty=True
      T2 旧线程写完 100 个任务的快照
    旧实现 T2 无条件 dirty=False → 99 个任务永不落盘。修复后 dirty 保持
    True，等下一轮定时保存。
    """
    _remain_txt(monkeypatch, tmp_path)
    snapshot = [Path(f"/lib/a-{i}.mp4") for i in range(100)]
    Flags.remain_list = list(snapshot)
    Flags.can_save_remain = True

    # T1：保存进行中，任务又完成一个（列表变化 + dirty 置位）
    Flags.remain_list = snapshot[:-1]
    Flags.can_save_remain = True

    # T2：旧快照线程结束
    _save_locked(snapshot)

    assert Flags.can_save_remain is True, "旧快照清掉了新状态的 dirty 标志"


def test_save_remain_list_now_ignores_dirty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remain_task_on):
    """save_remain_list_now 不看 dirty，立即落盘当前快照（停止/退出兜底）。"""
    remain_path = _remain_txt(monkeypatch, tmp_path)
    paths = [Path("/lib/x.mp4"), Path("/lib/y.mp4")]
    Flags.remain_list = list(paths)
    Flags.can_save_remain = False  # dirty 为假也必须落

    save_remain_list_now()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if remain_path.exists() and "x.mp4" in remain_path.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)
    assert "x.mp4" in remain_path.read_text(encoding="utf-8"), "save_remain_list_now 未落盘"


def test_timer_save_skips_when_not_dirty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remain_task_on):
    """定时保存仍尊重 dirty：不脏时不写文件。"""
    remain_path = _remain_txt(monkeypatch, tmp_path)
    Flags.remain_list = [Path("/lib/z.mp4")]
    Flags.can_save_remain = False

    save_remain_list()
    time.sleep(0.3)  # 给潜在的后台线程留窗口（不应启动）
    assert not remain_path.exists()


@pytest.mark.asyncio
async def test_subset_continue_does_not_cleanup_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """续刮子集不触发全库 cleanup_missing（议题 #98 2.4）。

    驱动 Scraper._run 的子集分支（传入 remain 子集），库里其余文件的
    scrape_state 由 cleanup_missing 负责清理——子集场景绝不能调用它。
    对拍：全量分支（movie_list=None）必须调用。
    """
    from types import SimpleNamespace

    from mdcx.core.scraper import Scraper
    from mdcx.models.enums import FileMode

    cleanup_calls: list[set] = []
    pending_calls: list[set] = []

    class _Cache:
        def is_usable(self):
            return True

        def cleanup_missing(self, existing):
            cleanup_calls.append(set(existing))

        def should_skip(self, p, mtime, force):
            return True  # 全部视为已完成（走跳过分支）

        def get_state(self, p):
            return None

        def list_pending(self, existing):
            pending_calls.append(set(existing))
            return []

    scraper = Scraper.__new__(Scraper)
    scraper._state_cache = _Cache()
    scraper._rate_estimator = None

    class _Provider:
        async def close(self):
            return None

    scraper.crawler_provider = _Provider()

    async def _run_tasks(_movie_list, _count, _thread_number):
        return

    scraper._run_tasks_with_limit = _run_tasks

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("mdcx.core.scraper.save_remain_list_now", _noop)
    monkeypatch.setattr("mdcx.core.scraper.save_success_list", _noop)
    monkeypatch.setattr("mdcx.core.scraper._clean_empty_folders", _noop)
    monkeypatch.setattr("mdcx.core.scraper._safe_mtime", _noop)
    monkeypatch.setattr(
        "mdcx.core.scraper.get_movie_path_setting",
        lambda *a, **k: SimpleNamespace(
            movie_path=tmp_path, movie_paths=[tmp_path], ignore_dirs=[], softlink_path=tmp_path / "sl"
        ),
    )

    # 全量分支的媒体库扫描桩：返回固定 3 个文件
    async def _get_movie_list(_mode, _scan_path, _ignore_dirs):
        return [Path(f"/lib/full-{i}.mp4") for i in range(3)]

    monkeypatch.setattr("mdcx.core.scraper.get_movie_list", _get_movie_list)
    monkeypatch.setattr("mdcx.core.scraper.newtdisk_creat_symlink", _noop)
    # signal 已由 conftest 的 _DummySignals 全量桩好（label_result.emit 等可用），无需覆盖

    from mdcx.config.manager import manager

    class _NoAutoExit:
        def __contains__(self, item):
            return False

    monkeypatch.setattr(manager.config, "switch_on", _NoAutoExit())
    monkeypatch.setattr(manager.config, "main_mode", 1)
    monkeypatch.setattr(manager.config, "thread_number", 2)
    monkeypatch.setattr(manager.config, "thread_time", 0)
    # 关闭刮削后自动动作（Emby 演员头像 / Kodi 演员），避免桩环境触发网络栈
    monkeypatch.setattr(manager.config, "emby_on", [])
    monkeypatch.setattr(manager.config, "actor_photo_kodi_auto", False)

    # --- 子集分支（续刮）：不清理 ---
    subset = [Path(f"/lib/remain-{i}.mp4") for i in range(30)]
    Flags.reset()
    await scraper._run(FileMode.Default, subset)
    assert cleanup_calls == [], "续刮子集触发了全库 cleanup_missing"

    # --- 全量分支（movie_list=None）：必须清理 ---
    Flags.reset()
    await scraper._run(FileMode.Default, None)
    assert cleanup_calls, "全量扫描未做库清理"


def test_continue_scrape_passes_snapshot_not_shared_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remain_task_on
):
    """get_remain_list 续刮分支：start_new_scrape 收到快照而非共享 list 对象。"""
    from mdcx.core import scraper as scraper_module

    remain_path = _remain_txt(monkeypatch, tmp_path)
    remain_path.write_text("/lib/r1.mp4\n/lib/r2.mp4\n", encoding="utf-8")

    captured: dict = {}

    def fake_start(file_mode, movie_list=None):
        captured["mode"] = file_mode
        captured["list"] = movie_list
        captured["same_object"] = movie_list is Flags.remain_list

    monkeypatch.setattr(scraper_module, "start_new_scrape", fake_start)
    monkeypatch.setattr(scraper_module, "parse_media_paths", lambda: [Path("/lib")])
    monkeypatch.setattr(scraper_module, "is_any_descendant", lambda *a, **k: True)

    class _Box:
        StandardButton = SimpleNamespace(Yes=1, No=2, Cancel=3)

        class Icon:
            Information = 0

        def __init__(self, *a, **k):
            pass

        def setStandardButtons(self, *a, **k):
            return None

        def button(self, *a, **k):
            return SimpleNamespace(setText=lambda *_: None)

        def setDefaultButton(self, *a, **k):
            return None

        def exec(self):
            return 1  # Yes：继续刮削剩余任务

    monkeypatch.setattr(scraper_module, "QMessageBox", _Box)

    assert scraper_module.get_remain_list() is True  # True = 已启动续刮

    assert captured["list"] == [Path("/lib/r1.mp4"), Path("/lib/r2.mp4")]
    assert captured["same_object"] is False, "续刮仍传递共享 list 对象"
    from mdcx.models.enums import FileMode as _FM

    assert captured["mode"] == _FM.Default
