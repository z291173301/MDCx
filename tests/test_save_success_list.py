"""save_success_list 路径记录回归测试。

回归背景：core/scraper.py 非视频模式完成路径原先 `save_success_list(file_path, file_path)`
把移动前的旧路径写入成功列表，与视频模式分支 `save_success_list(file_path, file_new_path)`
不一致。此处验证 save_success_list 本身的行为：非软链接时应记录 new_path（新路径）。
"""

import time
from pathlib import Path

import pytest

from mdcx.base import file as file_module
from mdcx.config.enums import NoEscape
from mdcx.config.manager import manager
from mdcx.models.flags import Flags
from mdcx.signals import signal


class _FakeEmitSignal:
    def __init__(self):
        self.emitted: list = []

    def emit(self, *args):
        self.emitted.append(args)


@pytest.fixture
def _reset_flags():
    Flags.reset()
    yield
    Flags.reset()


def _enable_success_record(monkeypatch: pytest.MonkeyPatch) -> _FakeEmitSignal:
    monkeypatch.setattr(manager.config, "no_escape", [NoEscape.RECORD_SUCCESS_FILE])
    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(signal, "show_log_text", lambda *a, **k: None)
    fake_view = _FakeEmitSignal()
    monkeypatch.setattr(signal, "view_success_file_settext", fake_view)
    # 让 get_used_time(success_save_time) > 5 不成立，避免触发落盘（写文件副作用）
    Flags.success_save_time = time.time()
    return fake_view


@pytest.mark.asyncio
async def test_records_new_path_when_not_softlink(monkeypatch: pytest.MonkeyPatch, _reset_flags, tmp_path: Path):
    """非软链接模式下，成功列表应记录 new_path（移动后的新路径）而非 old_path。"""
    _enable_success_record(monkeypatch)
    old_path = tmp_path / "old" / "MIAA-001.mp4"
    new_path = tmp_path / "new" / "MIAA-001.mp4"

    await file_module.save_success_list(old_path, new_path)

    assert new_path in Flags.success_list
    assert old_path not in Flags.success_list


@pytest.mark.asyncio
async def test_records_old_path_when_softlink(monkeypatch: pytest.MonkeyPatch, _reset_flags, tmp_path: Path):
    """软链接模式（soft_link != 0）下，成功列表记录 old_path（原路径）。"""
    _enable_success_record(monkeypatch)
    monkeypatch.setattr(manager.config, "soft_link", 1)
    old_path = tmp_path / "old" / "MIAA-001.mp4"
    new_path = tmp_path / "new" / "MIAA-001.mp4"

    await file_module.save_success_list(old_path, new_path)

    assert old_path in Flags.success_list
    assert new_path not in Flags.success_list


@pytest.mark.asyncio
async def test_records_nothing_without_feature(monkeypatch: pytest.MonkeyPatch, _reset_flags, tmp_path: Path):
    """未开启「记录成功文件」配置时，成功列表不记录任何路径。"""
    _enable_success_record(monkeypatch)
    monkeypatch.setattr(manager.config, "no_escape", [])

    await file_module.save_success_list(tmp_path / "old" / "MIAA-001.mp4", tmp_path / "new" / "MIAA-001.mp4")

    assert Flags.success_list == set()
