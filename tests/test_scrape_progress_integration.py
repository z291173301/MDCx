"""scraper 进度输出的速率估算接入哨兵：锁定 estimator 创建与完成回调的 record/append。"""

from __future__ import annotations

import ast


def _load_ast() -> ast.Module:
    with open("mdcx/core/scraper.py", encoding="utf-8") as f:
        return ast.parse(f.read())


def test_run_creates_rate_estimator_with_task_count():
    """run 开始处用 task_count 创建 ScrapeRateEstimator"""
    tree = _load_ast()
    created = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "ScrapeRateEstimator"
    ]
    assert created, "scraper.py 应创建 ScrapeRateEstimator"
    call = created[0]
    assert any(isinstance(arg, ast.Name) and arg.id == "task_count" for arg in call.args), (
        "estimator 须以 task_count 为总数创建"
    )


def test_done_callback_records_and_appends_eta():
    """完成回调：record_done 调用 + show_scrape_info 经 append_eta 附加剩余时间"""
    tree = _load_ast()
    src = "\n".join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.stmt))
    assert "estimator.record_done()" in src, "完成回调须 record_done"
    # 结构断言：show_scrape_info(append_eta(...)) 调用对存在（f-string unparse 形态不跨版本稳定）
    found = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "show_scrape_info" or not node.args:
            continue
        inner = node.args[0]
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "append_eta":
            found = True
            break
    assert found, "show_scrape_info 的进度文本须经 append_eta 附加剩余时间"
