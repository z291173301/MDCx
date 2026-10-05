"""软链接助手「一键创建软链接」按钮宽度对齐「开始移动」的回归测试。

背景（用户截图诉求）：一键创建软链接右侧边界扩展到开始移动右侧边界，最大化时
左右边界同步放大。

实现方式刻意走 CustomScrollArea 的通用拉伸登记表，而不是再加一处定制 setGeometry：
两个按钮同设计几何（groupBox_21 与 groupBox_6 同 x=30、同宽 701；按钮 x=140、
宽 351、右缘 491），按 _classify_inner 的「宽 ≥ 内半宽 340.5 → _STRETCH」规则
双双登记为拉伸，于是 sync_wide_children_width 用同一条 extra = 视口宽 - 设计宽
把两者等量铺开——左右边界在任何窗宽下都恒等，最大化时同步放大，缩小双向幂等复原。
这也是本测试要守住的隐式契约：一旦有人把该按钮改窄到阈值以下、或误加进
CustomScrollArea._MANUAL_WIDGET_NAMES，它会悄悄停止跟随而与「开始移动」错开。

断言一律用关系式（两按钮左右边界相等、宽度随组宽增量、边界不越组内缘），
只有设计态宽度 351 这一个写死值——它就是本次改动的设计意图本身。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

DESIGN_GROUP_W = 701  # groupBox_21 / groupBox_6 的 .ui 设计宽度
DESIGN_BTN_W = 351  # pushButton_creat_symlink / pushButton_move_mp4 的 .ui 设计宽度
DESIGN_BTN_X = 140
BTN_NAMES = ("pushButton_creat_symlink", "pushButton_move_mp4")


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture(scope="module")
def win(app, tmp_path_factory):
    from PyQt6.QtCore import QTimer

    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    orig_cwd = os.getcwd()
    os.chdir(str(tmp_path_factory.mktemp("symlinkbtn")))
    orig = {}
    for name, fn in (
        ("run_startup_health_checks", lambda: None),
        ("show_netstatus", lambda: None),
        ("check_version", lambda: None),
        ("save_remain_list", lambda: None),
        ("apply_site_priority_theme", lambda _w: None),
    ):
        orig[name] = getattr(mw_mod, name)
        setattr(mw_mod, name, fn)
    orig_style = mw_mod.MyMAinWindow.set_style
    mw_mod.MyMAinWindow.set_style = lambda self: None
    orig_qtr = style_mod.resources.qtr
    style_mod.resources.qtr = lambda path: str(MAIN_PATH / "resources" / path)
    window = mw_mod.MyMAinWindow()
    for timer in window.findChildren(QTimer):
        timer.stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()
    for name, fn in orig.items():
        setattr(mw_mod, name, fn)
    mw_mod.MyMAinWindow.set_style = orig_style
    style_mod.resources.qtr = orig_qtr
    os.chdir(orig_cwd)


def _tool_page_sync(win, app, width: int, height: int = 900):
    """切到软件工具页、按给定窗宽拉窗并跑一次 _sync_page_layouts。"""
    ui = win.Ui
    win.resize(width, height)
    win.show()
    app.processEvents()
    ui.stackedWidget.setCurrentWidget(ui.page_tool)
    app.processEvents()
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    return ui


def _pair(ui):
    """返回 (软链接按钮, 开始移动按钮, 各自父组)。"""
    return (
        ui.pushButton_creat_symlink,
        ui.pushButton_move_mp4,
        ui.groupBox_21,
        ui.groupBox_6,
    )


def _registry_design(ui, name: str):
    """从通用拉伸登记表取某控件的「设计几何 + 分类」，登记发生在 setupUi 时刻。"""
    from mdcx.views.CustomClass import CustomScrollArea

    scroll = ui.page_tool.findChild(CustomScrollArea)
    assert scroll is not None, "工具页滚动区未找到"
    content = scroll.widget()
    for entry in getattr(content, "_wide_children_design", []):
        for item in entry.inner:
            if item.widget.objectName() == name:
                return item.kind, item.geometry
    return None, None


def test_design_geometry_matches_move_button(win, app):
    """设计态：两按钮 x/宽/右缘完全一致（本次改动把 241 扩到 351 即对齐 491）。"""
    kind, geom = _registry_design(win.Ui, "pushButton_creat_symlink")
    assert kind == "stretch", f"软链接按钮须登记为拉伸，实际 {kind}"
    move_kind, move_geom = _registry_design(win.Ui, "pushButton_move_mp4")
    assert move_kind == "stretch", f"开始移动须登记为拉伸，实际 {move_kind}"
    # y/高各组独立，只比 x 与宽（即左右边界）
    assert (geom[0], geom[2]) == (move_geom[0], move_geom[2]), f"两按钮设计 x/宽应一致：{geom} != {move_geom}"
    assert geom[3] == move_geom[3] == 40, f"行高应一致：{geom[3]} != {move_geom[3]}"
    x, _y, w, _h = geom
    assert (x, w) == (DESIGN_BTN_X, DESIGN_BTN_W), geom
    assert x + w == 491, "右缘须落在 491（= 开始移动右缘）"


def test_both_buttons_registered_in_wide_sync(win, app):
    """两个按钮都必须进登记表，否则宽态不会同步放大。"""
    for name in BTN_NAMES:
        kind, geom = _registry_design(win.Ui, name)
        assert kind is not None and geom is not None, f"{name} 未登记进宽幅同步"
        # 守住隐式阈值：宽 ≥ (组宽-20)/2 才判 _STRETCH，跌破即失去同步
        assert geom[2] >= (DESIGN_GROUP_W - 20) / 2, f"{name} 宽度跌破拉伸阈值：{geom}"


def test_left_and_right_edges_identical_at_any_width(win, app):
    """任意窗宽下两按钮左边界、右边界都相等，且左右边界同步放大。"""
    seen: list[tuple[int, int, int, int]] = []
    for width in (1032, 1170, 1400, 1600, 1920, 2200):
        ui = _tool_page_sync(win, app, width, 1000)
        link, move, box_link, box_move = _pair(ui)
        assert link.x() == move.x(), f"{width}: 左边界应相等 {link.x()} != {move.x()}"
        assert link.x() + link.width() == move.x() + move.width(), f"{width}: 右边界应相等"
        assert box_link.width() == box_move.width(), f"{width}: 两组设计宽相同，实时宽也应相同"
        # 两按钮右缘都不得越出各自父组内缘
        for btn, box in ((link, box_link), (move, box_move)):
            assert btn.x() + btn.width() <= box.width(), f"{width}: {btn.objectName()} 越出组内缘"
        seen.append((link.x(), link.width(), link.x() + link.width(), box_link.width()))
    # 窗宽递增 → 组变宽 → 右边界单调右移；左边界恒定在设计列（不左移）
    assert [s[0] for s in seen] == [DESIGN_BTN_X] * len(seen), seen
    rights = [s[2] for s in seen]
    assert rights == sorted(rights), rights
    # 同步放大：右边界增量 == 组宽增量（宽全给右缘）
    assert rights[-1] - rights[0] == seen[-1][3] - seen[0][3], seen


def test_wide_state_widens_beyond_design(win, app):
    """最大化：按钮明显宽于设计值，且宽度随组宽等量增长。"""
    ui = _tool_page_sync(win, app, 1920, 1100)
    link, _move, box_link, _box_move = _pair(ui)
    extra = box_link.width() - DESIGN_GROUP_W
    assert extra > 0, "1920 窗宽下软链接组应变宽"
    assert link.width() == DESIGN_BTN_W + extra, (link.width(), extra)


def test_narrow_state_keeps_left_edge_and_no_negative_shift(win, app):
    """组框被收窄时左边界不左移，宽度按公式下限收而不塌陷。"""
    ui = _tool_page_sync(win, app, 1032, 737)
    link, move, box_link, _box_move = _pair(ui)
    assert box_link.width() < DESIGN_GROUP_W, "小窗下组框应变窄"
    assert link.x() == move.x() == DESIGN_BTN_X, "左边界不得左移"
    assert link.width() >= DESIGN_BTN_W // 2, link.width()
    assert link.x() + link.width() == move.x() + move.width()


def test_restore_is_idempotent(win, app):
    """还原小窗必须逐像素回到 fresh 状态；反复 _sync 也不漂移。"""
    ui = _tool_page_sync(win, app, 1170, 900)
    base = [(w.x(), w.y(), w.width(), w.height()) for w in (ui.pushButton_creat_symlink, ui.pushButton_move_mp4)]
    _tool_page_sync(win, app, 1920, 1100)
    ui = _tool_page_sync(win, app, 1170, 900)
    after = [(w.x(), w.y(), w.width(), w.height()) for w in (ui.pushButton_creat_symlink, ui.pushButton_move_mp4)]
    assert after == base, f"还原后几何必须复原：{after} != {base}"
    win._sync_page_layouts()
    win._sync_page_layouts()
    assert [
        (w.x(), w.y(), w.width(), w.height()) for w in (ui.pushButton_creat_symlink, ui.pushButton_move_mp4)
    ] == base
