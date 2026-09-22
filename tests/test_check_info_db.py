"""校验 scripts/check_info_db.py 的静态检查逻辑。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402

from scripts import check_info_db as mod  # noqa: E402


def _make_db(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["jp", "zh_cn", "zh_tw", "keyword"])
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()


def _run_errors(rows):
    errors = []
    for check in (
        mod._check_jp_empty,
        mod._check_jp_duplicate,
        mod._check_keyword_format,
        mod._check_keyword_duplicate,
        mod._check_cn_duplicate,
    ):
        errors.extend(check(rows))
    return errors


def test_clean_rows_pass():
    rows = [
        ["マジックミラー号", "魔镜号", "魔鏡號", ",マジックミラー号,魔镜号,魔鏡號,"],
        ["土下座", "下跪", "下跪", ",土下座,下跪,"],
    ]
    assert _run_errors(rows) == []


def test_jp_empty_detected():
    rows = [["", "空", "空", ",空,"]]
    errors = _run_errors(rows)
    assert any("jp(日文名) 为空" in e for e in errors)


def test_jp_duplicate_half_full_detected():
    """全半角标点差异的 jp 应判重复。"""
    rows = [
        [
            "たとえば熟女がコスッたら!?",
            "假如熟女玩COS呢!?",
            "假如熟女玩COS呢!?",
            ",たとえば熟女がコスッたら!?,假如熟女玩COS呢!?,",
        ],
        [
            "たとえば熟女がコスッたら！？",
            "假如熟女玩COS呢！？",
            "假如熟女玩COS呢！？",
            ",たとえば熟女がコスッたら！？,假如熟女玩COS呢！？,",
        ],
    ]
    errors = _run_errors(rows)
    assert any("jp 与行" in e and "重复" in e for e in errors)


def test_delete_rows_jp_duplicate_allowed():
    """黑名单删除行（jp=删除）允许重复。"""
    rows = [
        ["删除", "删除", "删除", ",词A,"],
        ["删除", "删除", "删除", ",词B,"],
    ]
    errors = _run_errors(rows)
    assert not any("jp 与行" in e for e in errors)


def test_keyword_missing_edge_commas_detected():
    rows = [["词A", "词A", "词A", "词A"]]
    errors = _run_errors(rows)
    assert any("缺少首尾逗号" in e for e in errors)


def test_keyword_double_comma_detected():
    rows = [["M女", "M女", "M女", ",,"]]
    errors = _run_errors(rows)
    assert any("连续逗号" in e for e in errors)


def test_keyword_duplicate_half_full_detected():
    """keyword 内全半角变体应判重复（内容行）。"""
    rows = [["3P", "3P", "3P", ",3P,３P,"]]
    errors = _run_errors(rows)
    assert any("重复词" in e for e in errors)


def test_keyword_duplicate_delete_row_allowed():
    """黑名单行 keyword 重复是设计使然，不报。"""
    rows = [["删除", "删除", "删除", ",1080P,1080p,"]]
    errors = _run_errors(rows)
    assert not any("重复词" in e for e in errors)


def test_cn_duplicate_detected():
    rows = [
        ["系列A", "同一中文", "同一中文", ",系列A,同一中文,"],
        ["系列B", "同一中文", "同一中文", ",系列B,同一中文,"],
    ]
    errors = _run_errors(rows)
    assert any("zh_cn 与行" in e and "重复" in e for e in errors)


def test_delete_rows_front_pass():
    """删除行全在前，正常通过。"""
    rows = [
        ["删除", "删除", "删除", ",词A,"],
        ["删除", "删除", "删除", ",词B,"],
        ["系列A", "系列A", "系列A", ",系列A,"],
    ]
    errors = mod._check_delete_rows_front(rows)
    assert errors == []


def test_delete_rows_after_content_detected():
    """删除行出现在内容行之后应报错（黑名单会失效）。"""
    rows = [
        ["系列A", "系列A", "系列A", ",系列A,"],
        ["删除", "删除", "删除", ",词A,"],
    ]
    errors = mod._check_delete_rows_front(rows)
    assert len(errors) == 1
    assert "删除行出现在内容行之后" in errors[0]


def test_delete_rows_interleaved_detected():
    """删除行与内容行交错也应报错。"""
    rows = [
        ["删除", "删除", "删除", ",词A,"],
        ["系列A", "系列A", "系列A", ",系列A,"],
        ["删除", "删除", "删除", ",词B,"],
    ]
    errors = mod._check_delete_rows_front(rows)
    assert len(errors) == 1


def test_check_xlsx_returns_zero(tmp_path):
    p = tmp_path / "info_database.xlsx"
    _make_db(p, [["マジックミラー号", "魔镜号", "魔鏡號", ",マジックミラー号,魔镜号,魔鏡號,"]])
    assert mod.check_xlsx(p) == 0


def test_check_xlsx_returns_one_on_error(tmp_path):
    p = tmp_path / "info_database.xlsx"
    _make_db(p, [["A", "A", "A", "A"]])  # keyword 缺首尾逗号
    assert mod.check_xlsx(p) == 1
