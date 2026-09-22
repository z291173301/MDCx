"""safe_copytree / safe_copytree_async same-file 预防测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mdcx.utils.file import _is_same_path, safe_copytree, safe_copytree_async


class TestIsSamePath:
    def test_identical_string(self, tmp_path: Path):
        a = tmp_path / "a"
        a.mkdir()
        assert _is_same_path(a, a) is True

    def test_different_paths(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert _is_same_path(a, b) is False

    def test_symlink_to_same_target(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        assert _is_same_path(target, link) is True

    def test_nonexistent_paths_different(self, tmp_path: Path):
        a = tmp_path / "does_not_exist_a"
        b = tmp_path / "does_not_exist_b"
        assert _is_same_path(a, b) is False

    def test_nonexistent_same_string(self, tmp_path: Path):
        a = tmp_path / "ghost"
        assert _is_same_path(a, a) is True


class TestSafeCopytree:
    def test_same_path_no_op(self, tmp_path: Path):
        """src==dst 时不应报错，不应删除源目录内容。"""
        src = tmp_path / "extrafanart"
        src.mkdir()
        (src / "1.jpg").write_bytes(b"fake jpg")
        (src / "2.jpg").write_bytes(b"fake jpg")

        safe_copytree(src, src)

        # 源目录内容必须完好
        assert (src / "1.jpg").exists()
        assert (src / "2.jpg").exists()
        assert (src / "1.jpg").read_bytes() == b"fake jpg"

    def test_different_paths_copies(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        (src / "a.jpg").write_bytes(b"aaa")
        (src / "b.jpg").write_bytes(b"bbb")

        safe_copytree(src, dst)

        assert (dst / "a.jpg").read_bytes() == b"aaa"
        assert (dst / "b.jpg").read_bytes() == b"bbb"

    def test_same_path_after_rmtree_source_survives(self, tmp_path: Path):
        """模拟实际场景：外层先 rmtree(dst) 再 copytree(src, dst)，当 src==dst 时源数据不应丢失。"""
        src = tmp_path / "extrafanart"
        src.mkdir()
        (src / "1.jpg").write_bytes(b"important")

        import shutil

        dst = src  # 配置错误：copy 目标 == 源
        if Path(dst) != src or _is_same_path(src, dst):
            # same-file 预检阻止了 rmtree
            pass
        else:
            shutil.rmtree(dst, ignore_errors=True)

        safe_copytree(src, dst)

        assert (src / "1.jpg").exists()
        assert (src / "1.jpg").read_bytes() == b"important"

    def test_symlink_same_target_no_op(self, tmp_path: Path):
        """src 和 dst 是指向同一目录的符号链接时应跳过。"""
        target = tmp_path / "real"
        target.mkdir()
        (target / "x.jpg").write_bytes(b"data")

        src = tmp_path / "link_a"
        src.symlink_to(target, target_is_directory=True)
        dst = tmp_path / "link_b"
        dst.symlink_to(target, target_is_directory=True)

        safe_copytree(src, dst)

        # 不应报错，target 内容完好
        assert (target / "x.jpg").read_bytes() == b"data"


class TestSafeCopytreeAsync:
    def test_same_path_no_op_async(self, tmp_path: Path):
        src = tmp_path / "extrafanart"
        src.mkdir()
        (src / "1.jpg").write_bytes(b"keep me")

        asyncio.run(safe_copytree_async(src, src))

        assert (src / "1.jpg").read_bytes() == b"keep me"

    def test_different_paths_copies_async(self, tmp_path: Path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        (src / "a.jpg").write_bytes(b"aaa")

        asyncio.run(safe_copytree_async(src, dst))

        assert (dst / "a.jpg").read_bytes() == b"aaa"
