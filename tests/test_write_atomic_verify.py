"""原子写入「假成功」回归测试（映射云盘静默吞写）。

用户实测（v2.0.9，115 云盘映射 Z:）：日志显示「🍀 Nfo done! (new)」，
但 60 部影片的目录里一个 .nfo 都没有——os.replace 在云盘驱动上返回成功、
目标文件实际未落（静默丢失）。写后必须校验目标存在，缺失时退回直写，
仍失败则抛错让调用方走失败分支，绝不允许假报成功。
"""

import asyncio
from pathlib import Path

import pytest

from mdcx.utils.file import write_file_atomic, write_file_atomic_async


def _simulate_silent_replace(tmp: str | Path, _dst: str | Path) -> None:
    """模拟云盘驱动的静默吞写：删掉临时文件、假装替换成功。"""
    Path(tmp).unlink(missing_ok=True)


def test_atomic_write_normal(tmp_path: Path):
    target = tmp_path / "a.nfo"
    write_file_atomic(target, "内容A")
    assert target.read_text(encoding="UTF-8") == "内容A"
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_falls_back_when_replace_silently_dropped(tmp_path: Path, monkeypatch):
    import mdcx.utils.file as m

    monkeypatch.setattr(m.os, "replace", _simulate_silent_replace)
    target = tmp_path / "b.nfo"
    write_file_atomic(target, "内容B")
    # 原子路径被静默吞掉后，直写兜底仍应落盘
    assert target.read_text(encoding="UTF-8") == "内容B"


def test_async_atomic_write_falls_back_when_replace_silently_dropped(tmp_path: Path, monkeypatch):
    import mdcx.utils.file as m

    monkeypatch.setattr(m.os, "replace", _simulate_silent_replace)
    target = tmp_path / "c.nfo"
    asyncio.run(write_file_atomic_async(target, "内容C"))
    assert target.read_text(encoding="UTF-8") == "内容C"


def test_async_atomic_write_raises_when_target_still_missing(tmp_path: Path, monkeypatch):
    """原子写与直写都被吞（彻底不可写目录模拟为 exists 恒 False）时必须抛错。"""
    import mdcx.utils.file as m

    monkeypatch.setattr(m.os, "replace", _simulate_silent_replace)
    # 让 aiofiles.os.path.exists 恒为 False，模拟目标始终不可见
    import aiofiles.os

    monkeypatch.setattr(aiofiles.os.path, "exists", _always_false)

    async def _run():
        with pytest.raises(OSError):
            await write_file_atomic_async(tmp_path / "d.nfo", "内容D")

    asyncio.run(_run())


async def _always_false(_path) -> bool:
    return False
