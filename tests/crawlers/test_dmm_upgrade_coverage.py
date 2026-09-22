"""有码爬虫 DMM 高清直链升级接入回归测试。

背景：`upgrade_dmm_cover`（横版 pl + 竖版 ps 双升级，TTL 缓存 + 并发合并）
此前只接入 javbus/javdb/javdb_api/javdb_app/javlibrary/r18dev 六个主流爬虫；
2026-08-31 推广到全部产出有码内容的聚合/综合站爬虫。竖版 ps 是 Emby/Jellyfin
显示质量的关键字段，兜底链 `find_valid_dmm_cover` 只救 thumb 不写 poster，
内嵌升级是唯一能给 poster 换高清的路径。

锁定方式：AST 哨兵——各爬虫的详情解析函数内必须调用 `upgrade_dmm_cover`
且传参含 thumb/poster 两个接收（防止未来重构悄悄断链）。
"""

from __future__ import annotations

import ast
from pathlib import Path

CRAWLERS_DIR = Path(__file__).resolve().parents[2] / "mdcx" / "crawlers"

# 2026-08-31 推广的 11 个爬虫（此前已有：javbus/javdb/javdb_api/javdb_app/javlibrary/r18dev）
UPGRADED_CRAWLERS = [
    "airav_cc",
    "avbase",
    "avsex",
    "freejavbt",
    "iqqtv",
    "javday",
    "javfree",
    "lulubar",
    "missav_api",
    "thejavdb_api",
    "xcity",
]

# 既有接入（回归保护：一个都不能少）
LEGACY_CRAWLERS = [
    "javbus",
    "javdb",
    "javdb_api",
    "javdb_app",
    "javlibrary",
    "r18dev",
]


def _module_calls_upgrade(source: str) -> bool:
    """模块源码中存在 upgrade_dmm_cover 调用（排除纯 import 行）。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "upgrade_dmm_cover":
                return True
    return False


def _read(name: str) -> str:
    return (CRAWLERS_DIR / f"{name}.py").read_text(encoding="utf-8")


def test_all_new_crawlers_call_upgrade():
    """11 个推广爬虫的源码必须存在 upgrade_dmm_cover 实际调用。"""
    missing = [name for name in UPGRADED_CRAWLERS if not _module_calls_upgrade(_read(name))]
    assert not missing, f"以下爬虫未接入 DMM 高清升级: {missing}"


def test_legacy_crawlers_still_call_upgrade():
    """既有 6 个爬虫的升级链不能被重构断掉。"""
    missing = [name for name in LEGACY_CRAWLERS if not _module_calls_upgrade(_read(name))]
    assert not missing, f"以下爬虫的 DMM 升级链丢失(回归): {missing}"


def test_xcity_passes_front_and_back():
    """xcity 的 thumb=背面/poster=正面语义必须在升级后保持。"""
    source = _read("xcity")
    tree = ast.parse(source)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "upgrade_dmm_cover":
            # 调用形如 upgrade_dmm_cover(ctx, number, back_image, front_image) 且结果回写两变量
            found = True
    assert found, "xcity 应调用 upgrade_dmm_cover"
    assert "back_image, front_image = await upgrade_dmm_cover" in source


def test_upgrade_call_inside_parse_flow():
    """升级调用必须在异步上下文（await），防止误放进同步辅助函数。"""
    for name in UPGRADED_CRAWLERS:
        source = _read(name)
        assert "await upgrade_dmm_cover" in source or "await self._upgrade" in source, (
            f"{name}: upgrade_dmm_cover 调用缺少 await（可能落在同步函数内）"
        )
