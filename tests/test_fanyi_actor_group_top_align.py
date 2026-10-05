"""翻译页「演员」组（groupBox_84）行首上移回归测试。

背景（用户截图）：演员组标题「演员」下方空着一整行，首行「演员语言」被整体
下推。要求「内容整体向上移动两行，移动完成后删掉下方多出来的空白空间」。

根因：`.ui` 里绝对定位容器 `layoutWidget_20` 声明高 418，而 `gridLayout_50` 各行
真实需要远小于它，Qt 会把多出来的竖向高度在「顶 / 行间 / 底」之间均分，于是行首
被顶下来一整行。控制器把这段行首留白显式收成常量 `_FANYI_ACTOR_TOP_PAD`（原 30）
并折进 `contentsMargins`，容器高钉成网格 sizeHint、组高 = 容器底 + 固定底留白，
其后各组按累计收缩量整体上移。留白归 0 后首行行顶回到 `layoutWidget_20` 的设计 y
（22），标题下方不再空整行，组高同步收 30（440 设计 → 实测 385），空出来的 30px
不会留成组底/组间空档。

本测试与 `test_fanyi_engine_group_spacing.py` 同款：刻意**不写死像素**（离屏平台
无字体，字号与真机不同），一律断言「关系」。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_fanyi(win, app):
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i) is ui.tab_6:
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("tab_6 not found")
    app.processEvents()


# 演员组及其后各组（绝对定位在 scrollAreaWidgetContents_fanyi 上）
_NAMES = (
    "groupBox_83",
    "groupBox_84",
    "groupBox_85",
    "groupBox_86",
    "groupBox_87",
    "groupBox_88",
    "groupBox_89",
)

# .ui 里 layoutWidget_20 在组内的设计 y（行首贴回这个位置的判据）
_DESIGN_LW_Y = 22


def _snapshot(win):
    ui = win.Ui
    return {n: getattr(ui, n).geometry().getRect() for n in _NAMES}


def _settle(win, app, rounds=8):
    """同步 → 处理事件 → 快照，多轮直到几何连续两轮不变（钉高/挪位会引发级联）。"""
    last = None
    for _ in range(rounds):
        win._sync_page_layouts()
        app.processEvents()
        cur = _snapshot(win)
        if cur == last:
            return cur
        last = cur
    return last


def _assert_tight(win):
    from mdcx.controllers.main_window.main_window import MyMAinWindow as MW

    ui = win.Ui
    grid = ui.gridLayout_50
    lw = ui.layoutWidget_20
    box = ui.groupBox_84
    first_row, story = ui.label_248, ui.label_249
    gap = grid.verticalSpacing()

    # 1) 行首留白归 0：首行「演员语言」行顶 = 容器设计 y（标题下方不再空整行）
    assert grid.contentsMargins().top() == MW._FANYI_ACTOR_TOP_PAD
    assert first_row.y() == grid.contentsMargins().top(), (first_row.y(), grid.contentsMargins().top())
    assert lw.y() == _DESIGN_LW_Y, lw.y()
    assert first_row.y() + lw.y() == _DESIGN_LW_Y, (first_row.y(), lw.y())

    # 2) 容器钉到网格自然高（不给 Qt 任何均分空间）
    assert lw.height() == grid.sizeHint().height(), (lw.height(), grid.sizeHint().height())

    # 3) 行与行之间只剩 verticalSpacing：用户圈出的整行空白不得回来
    assert ui.label_250.y() == first_row.y() + first_row.height() + gap
    assert story.y() == ui.label_250.y() + ui.label_250.height() + gap

    # 4) 长说明文字贴合到「真实绘制高 / heightForWidth 较大者」附近，且不裁字。
    #    上界用目标值本身（布局可能再收掉那 2px 抗锯齿余量），下界用绘制高（裁字）。
    painted = win._naming_label_painted_height(story)
    target = max(painted + 2, story.heightForWidth(story.width()))
    assert painted <= story.height() <= target, (painted, story.height(), target)

    # 5) 容器高度正好被各行占满：末行下方不许留死空白
    assert lw.height() == story.y() + story.height(), (lw.height(), story.y(), story.height())

    # 6) 组底留白 == 常量：组高完全由「容器设计 y + 网格自然高 + 常量」决定
    assert box.height() == lw.y() + lw.height() + MW._FANYI_BOX_BOT_PAD, box.height()

    # 7) 其后各组整体上移，但组间距保持设计值 20
    assert ui.groupBox_83.y() + ui.groupBox_83.height() + 20 == box.y()
    prev = box
    for name in _NAMES[2:]:
        cur = getattr(ui, name)
        assert cur.y() == prev.y() + prev.height() + 20, name
        prev = cur

    # 8) 宽幅登记表必须与当前几何一致，否则下一次宽幅同步会把收紧后的高度撑回去
    registry = getattr(ui.scrollAreaWidgetContents_fanyi, "_wide_children_design", None)
    entry = next(e for e in registry if e.widget is box)
    assert entry.geometry[3] == box.height(), (entry.geometry[3], box.height())
    inner = next(i for i in entry.inner if i.widget is lw)
    assert inner.geometry[3] == lw.height(), (inner.geometry[3], lw.height())


@pytest.mark.parametrize("width", [900, 1030, 1600])
def test_actor_group_content_moved_up_in_all_widths(win, app, width):
    """三档窗口宽度下都上移：无行首空白、组底留白常量、组间距不变、幂等。"""
    win.show()
    _goto_fanyi(win, app)
    win.resize(width, 760)
    app.processEvents()
    _settle(win, app)
    _assert_tight(win)

    before = _snapshot(win)
    win._sync_page_layouts()
    app.processEvents()
    assert _snapshot(win) == before, "重复同步后几何漂移（不幂等）"


def test_actor_group_constants_pinned(win):
    """间距常量钉死：改动常量时这条会红，避免间距被静默改掉。"""
    from mdcx.controllers.main_window.main_window import MyMAinWindow as MW

    # 行首留白必须为 0：留白即标题下方的整行空白（改前 30，首行行顶落在组内 52）
    assert MW._FANYI_ACTOR_TOP_PAD == 0, MW._FANYI_ACTOR_TOP_PAD
    assert MW._FANYI_BOX_BOT_PAD == 9, MW._FANYI_BOX_BOT_PAD
