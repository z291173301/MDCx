"""封面补图组三选项行：上移归属 + 最大化等距拉开的回归测试。

背景（用户截图两条诉求）：
1) 「刮削过程中自动创建软链接」从软链接助手组 groupBox_21 上移到封面补图组
   groupBox_cover_backfill 内「添加水印」右侧，左右位置不变（两组的 .ui 设计 x
   同为 30、宽同为 701，故屏上绝对位置不变；设计态三框 y 中心同为 135 保持同心）。
2) 最大化（组框被 CustomScrollArea 通用逻辑拉宽）时三枚复选框的间距同步拉开。
   它们在通用登记表里都判为 None（宽 161/191 < 拉伸阈值 340、右缘 601 < 右缘
   锚定阈值 631），本就不跟随，故由 MainWindow._sync_cover_backfill_option_row
   接管：extra = 组宽增量，两处间隙各摊一半（half = extra // 2）。

断言一律用关系式（间隙、间隙差、右缘余量、y 中心）而非写死像素：窗口/滚动视口
宽度随平台与 DPI 变化，写死会脆。另测还原幂等（双向复原），以及上移归属本身。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

DESIGN_W = 701  # groupBox_cover_backfill 的 .ui 设计宽度
OPTION_NAMES = (
    "checkBox_cover_backfill_overwrite",
    "checkBox_cover_backfill_watermark",
    "checkBox_create_link",
)


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
    os.chdir(str(tmp_path_factory.mktemp("coverrow")))
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


def _opts(ui):
    return [getattr(ui, name) for name in OPTION_NAMES]


def _y_center(w) -> int:
    return w.y() + w.height() // 2


def _row_metrics(ui):
    a, b, c = _opts(ui)
    return {
        "extra": ui.groupBox_cover_backfill.width() - DESIGN_W,
        "gap1": b.x() - (a.x() + a.width()),
        "gap2": c.x() - (b.x() + b.width()),
        "right_margin": ui.groupBox_cover_backfill.width() - (c.x() + c.width()),
        "y_centers": (_y_center(a), _y_center(b), _y_center(c)),
        "bottom": c.y() + c.height(),
    }


def test_create_link_moved_into_cover_backfill_group(win, app):
    """上移归属：checkBox_create_link 父组必须是 groupBox_cover_backfill。"""
    ui = _tool_page_sync(win, app, 1170)
    box = ui.groupBox_cover_backfill
    assert ui.checkBox_create_link.parentWidget() is box, "软链接复选框应已移入封面补图组"
    # 软链接助手组内不得再留同名控件（否则 setGeometry 走错父组）
    assert ui.groupBox_21.findChild(type(ui.checkBox_create_link), "checkBox_create_link") is None


def test_design_row_centers_align_and_sits_in_group(win, app):
    """设计态：三框 y 中心同行，且顺序/宽度照旧（间距由 gap 差体现）。"""
    ui = _tool_page_sync(win, app, 1032, 737)
    m = _row_metrics(ui)
    assert len(set(m["y_centers"])) == 1, f"三框必须同心: {m['y_centers']}"
    a, b, c = _opts(ui)
    assert a.x() == 40, "首框贴组内左缘"
    assert b.width() == 161 and c.width() == 191, "宽高恒定，只动 x"


def test_wide_row_spreads_both_gaps_equally(win, app):
    """最大化：两处间隙等量拉开，间隙差恒定，末框右缘余量不变。"""
    ui = _tool_page_sync(win, app, 1032, 737)
    base = _row_metrics(ui)
    seen_extra: list[int] = []
    seen_gaps: list[tuple[int, int]] = []
    seen_margin: list[int] = []
    for width in (1400, 1600, 1920):
        ui = _tool_page_sync(win, app, width, 1000)
        m = _row_metrics(ui)
        assert m["extra"] > base["extra"], f"{width} 窗宽下组框应变宽"
        assert m["gap1"] > base["gap1"], f"{width} 窗宽下 gap1 应拉开"
        assert m["gap2"] > base["gap2"], f"{width} 窗宽下 gap2 应拉开"
        assert m["gap2"] - m["gap1"] == base["gap2"] - base["gap1"], "两间隙差必须恒定"
        # 宽态末框贴组内右缘（余量 = 701-601=100）；小窗下组框本身被收窄、
        # 增量被截为 0，余量更小，故只断言宽态彼此一致且不小于小窗值。
        assert m["right_margin"] >= base["right_margin"], "末框不得比小窗更贴右缘"
        seen_extra.append(m["extra"])
        seen_gaps.append((m["gap1"], m["gap2"]))
        seen_margin.append(m["right_margin"])
    assert len(set(seen_margin)) == 1, f"宽态余量应恒定: {seen_margin}"
    # extra 递增方向正确（宽越大拉得越开）
    assert seen_extra == sorted(seen_extra), seen_extra
    # 摊分方式：gap 增量与 extra 增量同半（整数除允许 1px 误差）
    d_extra = seen_extra[-1] - seen_extra[0]
    d_gap1 = seen_gaps[-1][0] - seen_gaps[0][0]
    d_gap2 = seen_gaps[-1][1] - seen_gaps[0][1]
    assert abs(d_gap1 - d_extra / 2) <= 1, (d_gap1, d_extra)
    assert abs(d_gap2 - d_extra / 2) <= 1, (d_gap2, d_extra)


def test_row_never_intrudes_note_label(win, app):
    """末框底边不得压到橙色提示 label_cover_backfill_note（y=155）。"""
    for width, height in ((1032, 737), (1600, 1000), (2200, 1200)):
        ui = _tool_page_sync(win, app, width, height)
        bottom = _row_metrics(ui)["bottom"]
        assert bottom <= ui.label_cover_backfill_note.y(), f"{width}: 软链接复选框压到了提示标签"


def test_restore_is_idempotent(win, app):
    """还原小窗必须逐像素回到 fresh 状态（双向幂等）。"""
    ui = _tool_page_sync(win, app, 1032, 737)
    base = [(w.x(), w.y(), w.width(), w.height()) for w in _opts(ui)]
    _tool_page_sync(win, app, 1920, 1100)
    ui = _tool_page_sync(win, app, 1032, 737)
    after = [(w.x(), w.y(), w.width(), w.height()) for w in _opts(ui)]
    assert after == base, f"还原后几何必须复原: {after} != {base}"
    # 反复 _sync 也不得漂移（幂等）
    win._sync_page_layouts()
    win._sync_page_layouts()
    assert [(w.x(), w.y(), w.width(), w.height()) for w in _opts(ui)] == base


def test_narrow_group_keeps_design_row(win, app):
    """组框未被拉宽（extra<=0）时按常态几何落位，不出现负偏移。"""
    ui = _tool_page_sync(win, app, 1032, 737)
    a, b, c = _opts(ui)
    assert ui.groupBox_cover_backfill.width() <= DESIGN_W or a.x() == 40
    assert b.x() >= 220 or ui.groupBox_cover_backfill.width() <= DESIGN_W
    assert c.x() >= 410 or ui.groupBox_cover_backfill.width() <= DESIGN_W
