"""赞助弹窗收款码排版回归：槽位数与三张卡的几何必须与参考图 ``resources/Img/@赞助.png`` 一致。

背景：``@赞助.png`` 从「微信 + 支付宝」两张码改成「微信 + 支付宝 + 支付宝红包」三张后，
卡尺寸 192×197 → 198×198、卡间距 23 → 16、左缘从「按总宽居中取整」改成固定 ``_CARD_X = 16``。
最后这一处是刻意偏离居中公式的：参考图里三张码的左缘（x=16）与榜单框左缘
（``_RANK_LEFT_X`` = 16）严格对齐，而 ``(657 - 3*198 - 2*16) / 2 = 15.5`` 取整会得 15，
整排码比下面的榜单框左移 1px。这两点都是肉眼可辨的版式回归，故钉死成断言。

本文件只测排版常量与控件几何，不测二维码内容（内容由生成脚本保证，见 docs/Changelog.md）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QFrame

from mdcx.views import donate_window as dw

_app: QApplication | None = None

# 参考图 @赞助.png 实测（客户区像素）：三张 198×198 纯白码，卡间距 16，左缘 16
_REF_CARD_GEOM = ((16, 66, 198, 198), (230, 66, 198, 198), (444, 66, 198, 198))


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def dialog(app):
    dlg = dw.DonateDialog()
    try:
        yield dlg
    finally:
        dlg.deleteLater()


def _cards(dlg) -> list[QFrame]:
    return [c for c in dlg.findChildren(QFrame) if c.objectName() == "donate_card"]


def test_three_card_slots_follow_intro_text_order():
    """槽位数恒为 3，且顺序与 _INTRO_TEXT 的 1/2/3 一致。"""
    assert dw._CARD_COUNT == 3
    assert len(dw.DonateDialog._donate_icons()) == dw._CARD_COUNT
    assert "1.微信支付 2.支付宝付款 3.支付宝红包" in dw._INTRO_TEXT


def test_card_geometry_matches_reference(dialog):
    """三张码的几何逐值等于参考图实测值（1:1 复刻是本窗口的硬要求）。"""
    cards = _cards(dialog)
    assert len(cards) == dw._CARD_COUNT
    assert [c.geometry().getRect() for c in cards] == [tuple(g) for g in _REF_CARD_GEOM]


def test_card_row_aligns_with_rank_boxes_and_stays_in_dialog(dialog):
    """左缘与榜单框对齐、不越界、卡底不压榜单框顶。"""
    cards = _cards(dialog)
    left = cards[0].x()
    right = cards[-1].x() + cards[-1].width()
    assert left == dw._RANK_LEFT_X == dw._CARD_X
    assert right <= dw._DIALOG_W
    assert cards[0].y() + cards[0].height() <= dw._RANK_Y


def test_cards_are_square_and_never_overlap(dialog):
    """卡是正方形（码都是 980×980 方形图），相邻卡之间恰好一个 _CARD_GAP 的缝。"""
    cards = _cards(dialog)
    for card in cards:
        assert card.width() == card.height() == dw._CARD_W == dw._CARD_H
    for prev, cur in zip(cards, cards[1:]):
        assert cur.x() - (prev.x() + prev.width()) == dw._CARD_GAP


def test_missing_icon_degrades_to_placeholder_without_shifting_cards(app, monkeypatch):
    """某张码缺资源时只显示占位文字，槽位数不变、其余卡不左移。"""
    monkeypatch.setattr(
        dw.resources, "donate_redpacket_icon", "", raising=False
    )
    dlg = dw.DonateDialog()
    try:
        cards = _cards(dlg)
        assert len(cards) == dw._CARD_COUNT
        assert [c.geometry().getRect() for c in cards] == [tuple(g) for g in _REF_CARD_GEOM]
    finally:
        dlg.deleteLater()