"""刮削缓存组「刷新统计」右缘与「清空全部缓存」上下严格对齐的回归测试。

背景（用户截图诉求）：软件工具-刮削缓存管理中把「刷新统计」按钮向左移动，使
其右侧边界与下方「清空全部缓存」的右侧边界上下严格对齐，「清空全部缓存」位置不动。

实现方式刻意复用 CustomScrollArea 的通用右缘锚定登记表，而不是再加一处定制
setGeometry：两个按钮同设计右缘（刷新 550+131=681，清空 540+141=681），按
_classify_inner 的「宽 < 内半宽 340.5 且 右缘+1 ≥ 组宽×0.9 = 630.9 → _DOCK_RIGHT」
规则双双登记为右缘锚定，于是 sync_wide_children_width 用同一条
extra = 视口宽 - 设计宽 - content_right_trim() 把两者等量平移——右缘在任何窗宽下
都恒等，最大化时同步放大，缩小双向幂等复原。

本测试要守住的隐式契约：一旦有人把任一按钮的右缘挪离 681、或把宽度改到 340.5
以上（会被误判成 _STRETCH 而改成拉宽、从而与「清空全部缓存」分道扬镳），或者
误加进 CustomScrollArea._MANUAL_WIDGET_NAMES，两者都会悄悄错开。

断言一律用关系式（两按钮右缘相等、宽度不随窗宽变化、右缘不越组内缘），只有设计
态右缘 681 这一个写死值——它就是本次改动的设计意图本身。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

DESIGN_GROUP_W = 701  # groupBox_scrape_cache 的 .ui 设计宽度
DESIGN_RIGHT = 681  # 刷新 550+131 = 清空 540+141
DOCK_THRESHOLD = DESIGN_GROUP_W * 0.9  # 630.9，右缘锚定判定阈值
BTN_NAMES = ("pushButton_scrape_cache_refresh", "pushButton_scrape_cache_clear")


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
    os.chdir(str(tmp_path_factory.mktemp("scrapealign")))
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
    """返回 (刷新统计, 清空全部缓存, 缓存组框)。"""
    return (
        ui.pushButton_scrape_cache_refresh,
        ui.pushButton_scrape_cache_clear,
        ui.groupBox_scrape_cache,
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


def _group_design(ui, name: str):
    """取某个顶层宽幅 groupBox 的登记设计几何 (x, y, w, h)。"""
    from mdcx.views.CustomClass import CustomScrollArea

    content = ui.page_tool.findChild(CustomScrollArea).widget()
    for entry in getattr(content, "_wide_children_design", []):
        if entry.widget.objectName() == name:
            return entry.geometry
    return None


def test_design_right_edges_identical(win, app):
    """设计态（登记表里的 .ui 设计几何）：两按钮右缘都等于 681。

    这里刻意读登记的设计几何而不是实时 geometry——实时值受当前窗宽的 extra 影响，
    而设计几何才是本次改动要守住的意图本身（刷新统计左移到 550、右缘 681）。
    """
    refresh_geom = _registry_design(win.Ui, "pushButton_scrape_cache_refresh")[1]
    clear_geom = _registry_design(win.Ui, "pushButton_scrape_cache_clear")[1]
    assert refresh_geom == (550, 28, 131, 26), refresh_geom
    # 「清空全部缓存」位置保持不变
    assert clear_geom == (540, 300, 141, 28), clear_geom
    assert refresh_geom[0] + refresh_geom[2] == clear_geom[0] + clear_geom[2] == DESIGN_RIGHT
    # 两者同属刮削缓存组，设计宽 701
    assert _group_design(win.Ui, "groupBox_scrape_cache")[2] == DESIGN_GROUP_W
    refresh, clear, box = _pair(win.Ui)
    assert refresh.parentWidget() is box and clear.parentWidget() is box


def test_both_buttons_dock_right(win, app):
    """两个按钮都必须登记为右缘锚定，否则宽态不会同步平移。"""
    for name in BTN_NAMES:
        kind, geom = _registry_design(win.Ui, name)
        assert kind == "dock_right", f"{name} 须登记为右缘锚定，实际 {kind}"
        # 守住两条隐式阈值：过宽会被误判成 _STRETCH（改成拉宽而错开），
        # 右缘退到 630.9 以下会失去锚定（宽态不再跟随）。
        assert geom[2] < (DESIGN_GROUP_W - 20) * 0.5, f"{name} 过宽会误判为拉伸：{geom}"
        assert geom[0] + geom[2] >= DOCK_THRESHOLD, f"{name} 右缘跌破锚定阈值：{geom}"


def test_right_edges_identical_at_any_width(win, app):
    """任意窗宽下两按钮右边界相等，且随窗宽同步放大。"""
    seen: list[tuple[int, int, int]] = []
    for width in (1032, 1170, 1400, 1600, 1920, 2200):
        ui = _tool_page_sync(win, app, width, 1000)
        refresh, clear, box = _pair(ui)
        assert refresh.x() + refresh.width() == clear.x() + clear.width(), f"{width}: 右边界应严格对齐"
        assert box.width() == DESIGN_GROUP_W + (refresh.x() + refresh.width() - DESIGN_RIGHT), width
        # 右缘锚定是纯平移，宽度不得被改动
        assert (refresh.width(), clear.width()) == (131, 141), width
        # 右缘不得越出组框内缘
        assert refresh.x() + refresh.width() <= box.width(), f"{width}: 刷新统计越出组内缘"
        assert clear.x() + clear.width() <= box.width(), f"{width}: 清空全部缓存越出组内缘"
        seen.append((refresh.x() + refresh.width(), box.width(), width))
    rights = [s[0] for s in seen]
    # 窗宽递增 → 组变宽 → 右缘单调右移，且位移量 == 组宽增量
    assert rights == sorted(rights), rights
    assert rights[-1] - rights[0] == seen[-1][1] - seen[0][1], seen
    assert rights[0] < DESIGN_RIGHT, "1032 小窗下组框应收窄，右缘应内移"


def test_wide_state_shifts_beyond_design(win, app):
    """最大化：右缘明显内移出设计列，且位移量 == 组宽增量。"""
    ui = _tool_page_sync(win, app, 1920, 1100)
    refresh, clear, box = _pair(ui)
    extra = box.width() - DESIGN_GROUP_W
    assert extra > 0, "1920 窗宽下缓存组应变宽"
    right = refresh.x() + refresh.width()
    assert right == clear.x() + clear.width() == DESIGN_RIGHT + extra, (right, extra)


def test_narrow_state_no_overflow(win, app):
    """组框被收窄时右缘随之内移，不塌陷也不越界。"""
    ui = _tool_page_sync(win, app, 1032, 737)
    refresh, clear, box = _pair(ui)
    assert box.width() < DESIGN_GROUP_W, "小窗下组框应变窄"
    right = refresh.x() + refresh.width()
    assert right == clear.x() + clear.width() == DESIGN_RIGHT + box.width() - DESIGN_GROUP_W, right
    assert right <= box.width(), right
    assert (refresh.width(), clear.width()) == (131, 141)


def test_restore_is_idempotent(win, app):
    """还原小窗必须逐像素回到 fresh 状态；反复 _sync 也不漂移。"""
    ui = _tool_page_sync(win, app, 1170, 900)
    base = [
        (w.x(), w.y(), w.width(), w.height())
        for w in (ui.pushButton_scrape_cache_refresh, ui.pushButton_scrape_cache_clear)
    ]
    _tool_page_sync(win, app, 1920, 1100)
    ui = _tool_page_sync(win, app, 1170, 900)
    after = [
        (w.x(), w.y(), w.width(), w.height())
        for w in (ui.pushButton_scrape_cache_refresh, ui.pushButton_scrape_cache_clear)
    ]
    assert after == base, f"还原后几何必须复原：{after} != {base}"
    win._sync_page_layouts()
    win._sync_page_layouts()
    assert [
        (w.x(), w.y(), w.width(), w.height())
        for w in (ui.pushButton_scrape_cache_refresh, ui.pushButton_scrape_cache_clear)
    ] == base
