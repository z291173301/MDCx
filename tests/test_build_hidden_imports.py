"""build.py hidden-import 与动态导入模块的一致性防漂移.

背景：7mmtv 爬虫模块名数字开头（7mmtv.py），无法用常规 import 语法，
在 crawlers/__init__.py 经 importlib.import_module 动态注册。
PyInstaller 对运行时字符串解析不可靠，必须显式 --hidden-import 收录；
漏收时打包版运行时刮削才崩溃，本地源码与 CI 均无法发现。

本测试锁定：全仓 `import_module("mdcx...")` / `__import__("mdcx...")` 的字面量，
要么出现在 build.py 的 hidden-import，要么在允许清单里（并说明为什么安全）。
新增动态导入时若不显式收录，这里会转红，避免漏收只在打包版暴露。

注：函数体内的**静态** import（`from x import y`）会被 PyInstaller 静态分析收集，
无需 hidden-import；本测试只针对字符串动态导入。
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 动态导入但无需 hidden-import 的模块及原因
_DYNAMIC_IMPORT_ALLOWLIST = {
    # config.enums 被全项目大量静态导入，PyInstaller 静态分析必然收集
    "mdcx.config.enums",
}


def _dynamic_mdcx_imports() -> set[str]:
    """扫描全仓字符串动态导入的 mdcx.* 模块名。"""
    pattern = re.compile(r'(?:import_module|__import__)\(\s*"(mdcx\.[\w.]+)"')
    found: set[str] = set()
    for py in (ROOT / "mdcx").rglob("*.py"):
        found |= set(pattern.findall(py.read_text(encoding="utf-8")))
    return found


def _hidden_imports() -> set[str]:
    build_py = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    return set(re.findall(r'"--hidden-import",\s*\n\s*"([\w.]+)"', build_py))


def test_dynamic_mdcx_imports_are_covered_or_allowlisted():
    dynamic = _dynamic_mdcx_imports()
    assert dynamic, "未发现动态导入，若注册方式变更请同步本测试"

    hidden = _hidden_imports()
    missing = dynamic - hidden - _DYNAMIC_IMPORT_ALLOWLIST
    assert not missing, (
        f"动态导入模块缺少 hidden-import（打包版会运行时崩溃）: {sorted(missing)}；"
        "若确认会被静态分析收集，请加入 _DYNAMIC_IMPORT_ALLOWLIST 并注明原因"
    )


def test_importlib_registered_crawlers_covered_by_hidden_import():
    init_py = (ROOT / "mdcx" / "crawlers" / "__init__.py").read_text(encoding="utf-8")

    dynamic = set(re.findall(r'import_module\(\s*"(mdcx\.crawlers\.[\w.]+)"', init_py))
    assert dynamic, "未发现动态导入爬虫，若爬虫注册方式变更请同步本测试"

    missing = dynamic - _hidden_imports()
    assert not missing, f"动态导入爬虫缺少 hidden-import（打包版会运行时崩溃）: {sorted(missing)}"


def test_build_py_hidden_import_section_exists():
    """build.py 的 hidden-import 段落存在（防止参数重构后静默丢失全部动态收录）。"""
    build_py = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    assert "mdcx.crawlers.7mmtv" in build_py, "7mmtv hidden-import 缺失：动态注册爬虫需显式收录"
