"""scraper 完成输出段的失败摘要接入哨兵：锁定调用位置与条件。"""

from __future__ import annotations

import ast


def _load_scraper_ast() -> ast.Module:
    with open("mdcx/core/scraper.py", encoding="utf-8") as f:
        return ast.parse(f.read())


def test_finished_output_calls_format_failed_summary_before_failed_list():
    """完成输出段：Flags.failed_list 非空分支先输出聚合摘要，再打印失败明细"""
    tree = _load_scraper_ast()
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "format_failed_summary"
    ]
    assert calls, "scraper.py 应调用 format_failed_summary"

    # 定位包含调用的 If 节点并断言守卫条件
    found_guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            guard = ast.unparse(node.test)
            if "failed_list" in guard and any(
                isinstance(n, ast.Call)
                and isinstance(getattr(n, "func", None), ast.Name)
                and n.func.id == "format_failed_summary"
                for n in ast.walk(node)
            ):
                found_guarded = True
                break
    assert found_guarded, "format_failed_summary 须在 if Flags.failed_list 分支内调用"


def test_failed_detail_still_printed_after_summary():
    """摘要之后仍逐条打印失败明细（原行为保留）"""
    tree = _load_scraper_ast()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "failed_list" in ast.unparse(node.test):
            body_src = "\n".join(ast.unparse(stmt) for stmt in node.body)
            if "format_failed_summary" in body_src:
                assert "Failed results" in body_src, "摘要输出后须保留失败明细打印"
                # 摘要先于明细: format_failed_summary 出现位置在前
                assert body_src.index("format_failed_summary") < body_src.index("Failed results")
