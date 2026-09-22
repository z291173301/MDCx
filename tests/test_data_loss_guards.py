"""数据丢失回归测试：同路径移动与同名覆盖守卫。

来源：代码审查实测复现（2026-08-29）
- C1: 更新模式(main_mode=4) + skip_reorganize + 软链接/硬链接 + 源目标同路径时，
  move_movie 先 delete 再 link，源影片被删、剩自指向死链接，返回 True 假成功。
- C2: move_file_async 目标已存在且非同一文件时，shutil.move 静默覆盖，原内容永久丢失。

两个都会造成不可逆的用户数据丢失，行为测试锁定。
"""

import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

# conftest 已将 mdcx.config.manager / resources / signals 替换为 dummy，
# 此处补上 core/file.py 需要的最小属性（若 dummy 尚未提供）。


@pytest.fixture()
def soft_link_manager():
    """软链接模式 (soft_link=1) 的 manager dummy。"""
    mgr = sys.modules["mdcx.config.manager"]
    old = getattr(mgr, "manager", None)
    mgr.manager = types.SimpleNamespace(
        config=types.SimpleNamespace(
            soft_link=1,
            main_mode=4,
        )
    )
    yield mgr.manager
    if old is not None:
        mgr.manager = old


@pytest.fixture()
def hard_link_manager():
    """硬链接模式 (soft_link=2) 的 manager dummy。"""
    mgr = sys.modules["mdcx.config.manager"]
    old = getattr(mgr, "manager", None)
    mgr.manager = types.SimpleNamespace(
        config=types.SimpleNamespace(
            soft_link=2,
            main_mode=4,
        )
    )
    yield mgr.manager
    if old is not None:
        mgr.manager = old


async def test_c1_soft_link_same_path_keeps_source(tmp_path: Path, soft_link_manager):
    """C1: 软链接模式下源与目标同路径，源文件必须保持完好。"""
    from mdcx.core.file import move_movie
    from mdcx.models.model_types import FileInfo, OtherInfo

    video = tmp_path / "ABP-123.mp4"
    video.write_bytes(b"VIDEO-DATA")

    file_info = FileInfo.empty()
    file_info.file_path = video
    other = OtherInfo.empty()

    ok = await move_movie(other, file_info, video, video)

    assert ok is True
    # 修复后：源文件仍是普通文件且内容完好，不允许变成自指向死链接
    assert not video.is_symlink(), "源文件被替换成了软链接——数据丢失路径未修复"
    assert video.read_bytes() == b"VIDEO-DATA"


async def test_c1_hard_link_same_path_keeps_source(tmp_path: Path, hard_link_manager):
    """C1: 硬链接模式下源与目标同路径，源文件必须保持完好。"""
    from mdcx.core.file import move_movie
    from mdcx.models.model_types import FileInfo, OtherInfo

    video = tmp_path / "ABP-123.mp4"
    video.write_bytes(b"VIDEO-DATA")

    file_info = FileInfo.empty()
    file_info.file_path = video
    other = OtherInfo.empty()

    ok = await move_movie(other, file_info, video, video)

    assert ok is True
    assert video.read_bytes() == b"VIDEO-DATA", "硬链接同路径场景源文件损坏"


async def test_c2_move_overwrites_existing_only_when_conflict_saved(tmp_path: Path):
    """C2: 目标已存在且非同一文件时，不允许静默覆盖——旧内容必须被保留。"""
    from mdcx.utils.file import move_file_async

    src = tmp_path / "src.mp4"
    src.write_bytes(b"NEW")
    dst = tmp_path / "dst" / "video.mp4"
    dst.parent.mkdir()
    dst.write_bytes(b"EXISTING-VICTIM")

    ok, err = await move_file_async(src, dst)

    assert ok is True
    # 修复后：受害者内容必须仍可读（重命名保留），不允许被 NEW 覆盖丢失
    contents = {p.name: p.read_bytes() for p in dst.parent.iterdir()}
    assert b"EXISTING-VICTIM" in contents.values(), f"目标旧内容被静默覆盖丢失，目录内仅剩: {contents}"


async def test_c2_move_same_file_still_succeeds(tmp_path: Path):
    """C2 修复不得破坏原有语义：同一文件移动仍直接成功，不产生 conflict 文件。"""
    from mdcx.utils.file import move_file_async

    src = tmp_path / "a.mp4"
    src.write_bytes(b"SAME")
    ok, err = await move_file_async(src, src)
    assert ok is True
    assert src.read_bytes() == b"SAME"
    assert len(list(tmp_path.iterdir())) == 1, "同文件移动不应产生任何多余文件"


async def test_c2_overwrite_true_replaces_temp_without_conflict(tmp_path: Path):
    """overwrite=True 的「临时文件落位」语义：直接覆盖，不得留 _conflict 残留。

    场景：水印流程 image.py:241 —— poster.[MARK].jpg 移到 poster.jpg，
    目标本就是旧版本，产生 _conflict 文件会污染输出目录（审查中发现的回归，
    实测每次加水印都留一个垃圾文件）。
    """
    from mdcx.utils.file import move_file_async

    pic = tmp_path / "poster.jpg"
    pic.write_bytes(b"OLD")
    temp = tmp_path / "poster.[MARK].jpg"
    temp.write_bytes(b"NEW-WITH-MARK")

    ok, err = await move_file_async(temp, pic, overwrite=True)

    assert ok is True
    assert pic.read_bytes() == b"NEW-WITH-MARK"
    assert len(list(tmp_path.iterdir())) == 1, f"临时落位不应产生多余文件: {list(tmp_path.iterdir())}"


async def test_c2_overwrite_false_keeps_conflict_backup(tmp_path: Path):
    """overwrite=False（默认）的「素材移动」语义：冲突必须保留旧文件。"""
    from mdcx.utils.file import move_file_async

    src = tmp_path / "src.mp4"
    src.write_bytes(b"NEW-MOVIE")
    dst = tmp_path / "dst.mp4"
    dst.write_bytes(b"OLD-VICTIM")

    ok, _ = await move_file_async(src, dst)

    assert ok is True
    contents = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert b"OLD-VICTIM" in contents.values(), f"默认语义下旧文件必须保留: {contents}"
    assert dst.read_bytes() == b"NEW-MOVIE"
