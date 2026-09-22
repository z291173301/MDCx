"""目录创建并发回归测试（H13）：同目录并发创建不得抛 FileExistsError。

背景：13 处 makedirs 全是 `if not exists: makedirs()` 的 check-then-act 形态，
中间的 await 让点使并发协程同时通过检查、第二个 makedirs 必抛
FileExistsError。实测复现：12 并发写同一新目录，每轮 2-3 个任务失败
（extrafanart 并发下载即此场景）。修复：统一 makedirs(..., exist_ok=True)。
"""

import asyncio

import aiofiles.os
import pytest

pytestmark = pytest.mark.asyncio


async def test_concurrent_makedirs_same_dir_no_error(tmp_path):
    """并发 12 协程同时建同一新目录，全部成功、零异常。"""
    target = tmp_path / "actor" / "ABP-123"

    async def create_and_write(i: int) -> None:
        # 复刻修复后的调用形态（base/web.py download_content_with_filepath）
        await aiofiles.os.makedirs(target, exist_ok=True)
        (target / f"extra{i}.jpg").write_bytes(b"x")

    results = await asyncio.gather(*[create_and_write(i) for i in range(12)], return_exceptions=True)
    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, f"并发建目录出现异常: {errors}"
    assert len(list(target.glob("extra*.jpg"))) == 12


async def test_no_bare_makedirs_left_behind():
    """全库不得再出现不带 exist_ok 的 aiofiles/os makedirs（防回归哨兵）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "mdcx"
    offenders = []
    for py in root.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]  # 忽略注释
            if "makedirs" in code and "exist_ok" not in code and "def " not in code:
                offenders.append(f"{py.relative_to(root.parent)}:{i}: {line.strip()}")
    assert not offenders, "发现未带 exist_ok 的 makedirs（H13 回归）:\n" + "\n".join(offenders)
