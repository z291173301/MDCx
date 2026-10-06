"""回归: 软件界面「清空结果列表」(刷子图标) 与树内「成功」两字的间距两态一致。

判据(议题: 最大化时刷子右移一个汉字宽)：刷子左缘到树内首行「成功」起点
（visualItemRect(item).left()，即树内容左缘 + 固定缩进）的距离，在最大化态
必须与还原/最小化态完全相同。

原因：结果树宽度随窗口拉伸（tree_w = int(202 × main_w/820)），若刷子钉在页面
右缘，最大化时它与「成功」的间距会被树拉得越来越远。故最大化时把刷子钉在
「树左缘 + _MAIN_TREE_CLEAR_DX(160)」上；缩进与字号两态不变 ⇒ 间距恒等。

三态纪律(MEMORY #110/#117): fresh 小窗 → 最大化 → 还原小窗, 断言
1) 还原/最小化态刷子位置与历史行为逐像素一致(贴右缘 max(page_w-60, 300),
   设计宽 820 时即 .ui 的 760);
2) 最大化态「刷子 ↔ 成功」间距 == 还原态间距(核心判据), 且确实右移到了
   统计行「失败：N」右侧;
3) 双向幂等: 最大化 → 还原后逐像素回到还原态原位。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

# 侧栏 210 + 右留白 2：窗口宽 1032 时 page_main 恰为设计宽 820
DESIGN_WINDOW_W = 1032
DESIGN_BUTTON_X = 760


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda *a, **k: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.show()
    yield window
    window.close()


@pytest.fixture()
def maxed(monkeypatch):
    """把 isMaximized 打成 True：offscreen 下无法真最大化，只驱动 _sync_page_layouts 的判态分支。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod.MyMAinWindow, "isMaximized", lambda self: True)


def _succ_gap(win) -> int:
    """刷子左缘到树内首行「成功」起点（内容左缘 + 固定缩进）的间距。

    visualItemRect 返回的是**视口**坐标，需加上树的 x 才回到 page_main 坐标系
    （树 frame 宽 0、无表头，两态偏移量恒定，不影响相等性判断）。
    """
    tree = win.Ui.treeWidget_number
    item = tree.topLevelItem(0)
    assert item is not None and item.text(0) == "成功"
    succ_left = tree.x() + tree.visualItemRect(item).left()
    return win.Ui.pushButton_tree_clear.x() - succ_left


def _right_edge_x(win) -> int:
    """历史（未改动）公式：还原/最小化态刷子贴页面右缘的位置。"""
    return max(win.Ui.page_main.width() - 20 - 40, 300)


def test_restored_state_keeps_design_position(win):
    """还原/最小化态：刷子保持在设计坐标 760，布局与改动前逐像素一致。"""
    ui = win.Ui
    win.resize(DESIGN_WINDOW_W, 700)
    win._sync_page_layouts()
    assert ui.page_main.width() == 820
    assert ui.pushButton_tree_clear.x() == DESIGN_BUTTON_X == _right_edge_x(win)
    assert ui.pushButton_tree_clear.y() == 110


def test_maximized_gap_matches_restored_gap(win, maxed):
    """核心判据：最大化态「刷子 ↔ 成功」间距必须与还原态完全相同。"""
    ui = win.Ui

    win.resize(DESIGN_WINDOW_W, 700)
    win._sync_page_layouts()
    base_x = ui.pushButton_tree_clear.x()
    base_gap = _succ_gap(win)

    win.resize(1900, 1000)
    win._sync_page_layouts()
    assert ui.treeWidget_number.width() > 202, "结果树应随窗口拉伸"
    assert _succ_gap(win) == base_gap, "最大化时刷子与「成功」的间距必须与还原态一致"
    assert ui.pushButton_tree_clear.y() == 110, "纵向不得移动"
    # 钉在树左缘 + 常量：既离开右缘、也离开「失败：N」那一段
    assert ui.pushButton_tree_clear.x() == ui.treeWidget_number.x() + win._MAIN_TREE_CLEAR_DX
    assert ui.pushButton_tree_clear.x() < _right_edge_x(win)
    assert ui.pushButton_tree_clear.x() != base_x, "最大化必须位移"


def test_gap_stable_across_widths(win, maxed):
    """最大化态下逐档拉宽：间距恒定（真正锚在树左缘而非页面右缘）。"""
    ui = win.Ui
    win.resize(DESIGN_WINDOW_W, 700)
    win._sync_page_layouts()
    base_gap = _succ_gap(win)

    for w, h in ((1400, 900), (1700, 1000), (1900, 1000), (2400, 1200)):
        win.resize(w, h)
        win._sync_page_layouts()
        assert _succ_gap(win) == base_gap, f"窗宽 {w} 下间距漂移"
        assert ui.pushButton_tree_clear.x() + ui.pushButton_tree_clear.width() <= ui.page_main.width(), (
            f"窗宽 {w} 下刷子不得越出页面右缘"
        )


def test_restored_and_maximized_agree_at_design_width(win, maxed):
    """设计宽下最大化分支与还原分支同解（760），即两态在设计尺寸处连续。"""
    ui = win.Ui
    win.resize(DESIGN_WINDOW_W, 700)
    win._sync_page_layouts()
    assert ui.pushButton_tree_clear.x() == DESIGN_BUTTON_X


def test_restore_returns_to_restored_position(win, monkeypatch):
    """最大化 → 还原双向幂等：还原后必须逐像素回到还原态原位。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    ui = win.Ui
    win.resize(DESIGN_WINDOW_W, 700)
    win._sync_page_layouts()
    base_x = ui.pushButton_tree_clear.x()
    base_gap = _succ_gap(win)

    monkeypatch.setattr(mw_mod.MyMAinWindow, "isMaximized", lambda self: True)
    win.resize(1900, 1000)
    win._sync_page_layouts()
    assert ui.pushButton_tree_clear.x() != base_x

    monkeypatch.setattr(mw_mod.MyMAinWindow, "isMaximized", lambda self: False)
    win.resize(DESIGN_WINDOW_W, 700)
    win._sync_page_layouts()
    assert ui.pushButton_tree_clear.x() == base_x == DESIGN_BUTTON_X
    assert _succ_gap(win) == base_gap


def test_result_text_change_does_not_move_brush(win, maxed):
    """统计文字变化（成功/失败位数变化）不得影响刷子位置——间距只由几何决定。"""
    ui = win.Ui
    win.resize(1900, 1000)
    win._sync_page_layouts()
    x_before = ui.pushButton_tree_clear.x()
    gap_before = _succ_gap(win)

    ui.label_result.setText(" 刮削中：100 成功：80 失败：20")
    win._sync_page_layouts()
    assert ui.pushButton_tree_clear.x() == x_before, "统计文字变化不得让刷子漂移"
    assert _succ_gap(win) == gap_before


def test_non_maximized_still_uses_right_edge_formula(win):
    """非最大化态（含手动拉宽但不最大化）仍走历史贴右缘公式，行为零变化。"""
    ui = win.Ui
    for w in (1032, 1300, 1700):
        win.resize(w, 700)
        win._sync_page_layouts()
        assert ui.pushButton_tree_clear.x() == max(ui.page_main.width() - 20 - 40, 300)
