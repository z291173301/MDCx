from pathlib import Path

import pytest

from mdcx.config.extend import MoviePathSetting
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags


def _patch_scraper_env(monkeypatch: pytest.MonkeyPatch, main_mode: int = 1):
    """注入 scraper._run 所需的最小依赖，返回 scraper_module。"""
    from mdcx.core import scraper as scraper_module

    async def fake_save_success_list(_old_path=None, _new_path=None):
        return None

    async def fake_clean_empty_folders(_path: Path, _file_mode: FileMode):
        return None

    def fake_get_movie_path_setting(_file_path=None, movie_path_override=None):
        movie_path = Path(movie_path_override) if movie_path_override is not None else Path(".")
        return MoviePathSetting(
            movie_path=movie_path,
            movie_paths=[movie_path],
            success_folder=movie_path,
            failed_folder=movie_path,
            ignore_dirs=[],
            extrafanart_folder=movie_path,
            softlink_path=movie_path,
        )

    monkeypatch.setattr(scraper_module, "save_success_list", fake_save_success_list)
    monkeypatch.setattr(scraper_module, "_clean_empty_folders", fake_clean_empty_folders)
    monkeypatch.setattr(scraper_module, "get_movie_path_setting", fake_get_movie_path_setting)
    monkeypatch.setattr(scraper_module.manager.config, "thread_number", 4)
    monkeypatch.setattr(scraper_module.manager.config, "thread_time", 0)
    monkeypatch.setattr(scraper_module.manager.config, "main_mode", main_mode)
    monkeypatch.setattr(scraper_module.manager.config, "switch_on", [])
    monkeypatch.setattr(scraper_module.manager.config, "scrape_softlink_path", False)
    monkeypatch.setattr(scraper_module.manager.config, "emby_on", [])
    monkeypatch.setattr(scraper_module.manager.config, "actor_photo_kodi_auto", False)
    return scraper_module


@pytest.mark.asyncio
async def test_run_uses_copied_remain_list(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import scraper as scraper_module

    Flags.reset()
    movie_list = [Path("MIAA-001.mp4"), Path("MIAA-002.mp4"), Path("MIAA-003.mp4"), Path("MIAA-004.mp4")]
    origin_first = movie_list[0]

    async def fake_run_tasks_with_limit(_self, scheduled_list: list[Path], _task_count: int, _thread_number: int):
        assert scheduled_list is movie_list
        assert Flags.remain_list is not scheduled_list

        Flags.remain_list.remove(origin_first)

        assert len(scheduled_list) == 4
        assert scheduled_list[0] == origin_first
        Flags.scrape_done = _task_count

    _patch_scraper_env(monkeypatch, main_mode=1)
    monkeypatch.setattr(scraper_module.Scraper, "_run_tasks_with_limit", fake_run_tasks_with_limit)

    scraper = scraper_module.Scraper(crawler_provider=object())
    await scraper._run(FileMode.Default, movie_list)

    assert movie_list == [Path("MIAA-001.mp4"), Path("MIAA-002.mp4"), Path("MIAA-003.mp4"), Path("MIAA-004.mp4")]
    assert Flags.remain_list == [Path("MIAA-002.mp4"), Path("MIAA-003.mp4"), Path("MIAA-004.mp4")]


@pytest.mark.asyncio
async def test_normal_mode_skips_done_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """普通模式（main_mode=1）：缓存标记 done 的文件应被断点续刮跳过。"""
    from mdcx.core.scrape_cache import ScrapeStateCache

    scraper_module = _patch_scraper_env(monkeypatch, main_mode=1)

    # 准备 3 个真实文件 + 缓存中标记前两个为 done
    files = []
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        p = tmp_path / name
        p.write_bytes(b"x")
        files.append(p)

    db = tmp_path / "scrape_state.db"
    cache = ScrapeStateCache(db)
    assert cache.open() is True
    for p in files[:2]:
        cache.set_done(p, mtime=p.stat().st_mtime)
    cache.close()

    scheduled: list[Path] = []

    async def fake_run_tasks_with_limit(_self, task_list: list[Path], _task_count: int, _thread_number: int):
        scheduled.extend(task_list)
        Flags.scrape_done = _task_count

    monkeypatch.setattr(scraper_module.Scraper, "_run_tasks_with_limit", fake_run_tasks_with_limit)
    monkeypatch.setattr(scraper_module.resources, "u", lambda _name: db)

    scraper = scraper_module.Scraper(crawler_provider=object())
    await scraper._run(FileMode.Default, files.copy())

    # a/b 已 done → 只剩 c
    assert scheduled == [files[2]]
    scraper._state_cache.close() if scraper._state_cache else None


@pytest.mark.asyncio
async def test_read_mode_ignores_done_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """读取模式（main_mode=4）：即使缓存标记 done 也不跳过，全部入队。"""
    from mdcx.core.scrape_cache import ScrapeStateCache

    scraper_module = _patch_scraper_env(monkeypatch, main_mode=4)

    files = []
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        p = tmp_path / name
        p.write_bytes(b"x")
        files.append(p)

    db = tmp_path / "scrape_state.db"
    cache = ScrapeStateCache(db)
    assert cache.open() is True
    for p in files:
        cache.set_done(p, mtime=p.stat().st_mtime)
    cache.close()

    scheduled: list[Path] = []

    async def fake_run_tasks_with_limit(_self, task_list: list[Path], _task_count: int, _thread_number: int):
        scheduled.extend(task_list)
        Flags.scrape_done = _task_count

    monkeypatch.setattr(scraper_module.Scraper, "_run_tasks_with_limit", fake_run_tasks_with_limit)
    monkeypatch.setattr(scraper_module.resources, "u", lambda _name: db)

    scraper = scraper_module.Scraper(crawler_provider=object())
    await scraper._run(FileMode.Default, files.copy())

    # 读取模式：全部 3 个文件都应入队，不被 done 记录跳过
    assert scheduled == files
    if scraper._state_cache:
        scraper._state_cache.close()


@pytest.mark.asyncio
async def test_unexpected_cancelled_scrape_task_is_not_silent(monkeypatch: pytest.MonkeyPatch):
    from mdcx.core import scraper as scraper_module

    Flags.reset()
    scraper_module.signal.stop = False
    Flags.stop_requested = False

    async def cancelled_process_one_file(_self, _task):
        raise scraper_module.asyncio.CancelledError

    monkeypatch.setattr(scraper_module.Scraper, "process_one_file", cancelled_process_one_file)

    scraper = scraper_module.Scraper(crawler_provider=object())
    with pytest.raises(scraper_module.UnexpectedScrapeCancellation, match="异常取消"):
        await scraper._run_tasks_with_limit([Path("MIAA-001.mp4")], 1, 1)
