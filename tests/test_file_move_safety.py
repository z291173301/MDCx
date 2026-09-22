from pathlib import Path

import pytest

from mdcx.utils.file import move_file_async, move_file_sync


def test_move_file_sync_rejects_directory_target(tmp_path: Path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "target"
    source.write_bytes(b"video")
    target.mkdir()

    success, error = move_file_sync(source, target)

    assert success is False
    assert "目标是目录" in error
    assert source.read_bytes() == b"video"
    assert list(target.iterdir()) == []


@pytest.mark.asyncio
async def test_move_file_async_rejects_directory_target(tmp_path: Path):
    source = tmp_path / "source.mp4"
    target = tmp_path / "target"
    source.write_bytes(b"video")
    target.mkdir()

    success, error = await move_file_async(source, target)

    assert success is False
    assert "目标是目录" in error
    assert source.read_bytes() == b"video"
    assert list(target.iterdir()) == []
