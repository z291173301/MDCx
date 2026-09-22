from pathlib import Path

import pytest

from mdcx.utils.path import safe_rmtree


def test_safe_rmtree_removes_regular_directory(tmp_path: Path):
    target = tmp_path / "remove-me"
    target.mkdir()
    (target / "file.txt").write_text("x")

    safe_rmtree(target)

    assert not target.exists()


def test_safe_rmtree_rejects_empty_path():
    with pytest.raises(ValueError, match="空路径"):
        safe_rmtree("")
