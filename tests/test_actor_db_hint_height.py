"""演员库工具页提示词高度回归测试：裁字事故不再发生。

背景：QLabel.heightForWidth(221) 实测返回 26（单行高度，错误），而同字体同宽度下
QTextDocument 量出 merged=50、minnano=36（正确）。固定高度导致“默认/钮/日”等
尾字被裁。本测试锁定 wrapped_label_height 在各档宽度/字号下高度必覆盖内容，
且底边不侵入下一行。

注：合并提示词与 minnano 说明标签已从 UI 删除，下面的 CASES 仅作为
wrapped_label_height 通用函数的回归用例保留，不再对应任何界面控件。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication, QLabel

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


T1 = "扫描已有演员TMDB ID但是缺少中文姓名的条目"
T2 = "用默认程序打开xlxs查看与编辑"
MN = "从Minnano-av补全缺少的演员生日和简介信息，其中日文字段将自动翻译为中文"

# （文本， 宽度， 最小高， 最大高， 所在行顶， 下一行顶）
CASES = [
    (T1 + "，" + T2, 221, 36, 56, 80, 140),  # 最小化合并提示词
    (MN, 221, 30, 56, 140, 200),  # 最小化 minnano 说明
    (T1 + "，" + T2, 861, 32, 56, 80, 140),  # 最大化合并提示词（一行）
    (MN, 861, 30, 56, 140, 200),  # 最大化 minnano 说明（一行）
]


def _make_label(text: str) -> QLabel:
    _ensure_app()
    lbl = QLabel(text)
    lbl.setStyleSheet("color: rgb(160, 160, 160); font-size: 12px;")
    lbl.setWordWrap(True)
    lbl.ensurePolished()
    return lbl


def _doc_need(lbl: QLabel, width: int) -> float:
    doc = QTextDocument()
    doc.setDefaultFont(lbl.font())
    doc.setPlainText(lbl.text())
    doc.setTextWidth(width)
    return doc.size().height()


def test_wrapped_label_height_covers_text():
    from mdcx.views.CustomClass import wrapped_label_height

    for text, w, minh, maxh, _y, _cap in CASES:
        lbl = _make_label(text)
        h = wrapped_label_height(lbl, w, minh, maxh)
        assert h >= _doc_need(lbl, w), (text, w, h)
        assert minh <= h <= maxh, (text, w, h)


def test_wrapped_label_height_respects_next_row():
    from mdcx.views.CustomClass import wrapped_label_height

    for text, w, minh, maxh, y, cap in CASES:
        lbl = _make_label(text)
        h = wrapped_label_height(lbl, w, minh, maxh)
        assert y + h <= cap, (text, w, h)


def test_hint_labels_removed_from_design():
    """合并提示词与 minnano 说明已从 UI 删除，DESIGN 不得再收录。"""
    from mdcx.controllers.main_window.main_window import MyMAinWindow as MW

    D = MW._ACTOR_DB_TOOL_DESIGN
    assert "label_actor_db_translate_desc" not in D
    assert "label_actor_db_fill_minnano_desc" not in D


def test_wrapped_label_height_large_font_still_capped():
    """字号放大到 20px 也不能侵入下一行（极端情况宁可封顶）-operational cap."""

    from mdcx.views.CustomClass import wrapped_label_height

    _ensure_app()
    lbl = QLabel(T1 + "，" + T2)
    f = lbl.font()
    f.setPointSize(20)
    lbl.setFont(f)
    lbl.setWordWrap(True)
    lbl.ensurePolished()
    h = wrapped_label_height(lbl, 221, 36, 56)
    assert h == 56
