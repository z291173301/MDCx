"""翻译页「翻译引擎」组（groupBox_trans）行距收紧回归测试。

背景（用户截图）：「DeepLX URL」与提示词 `label_baidu_hint` 之间空着一整行，
提示词被垂直居中，其下「百度 APP / 百度密钥」两行被整体下推。用户要求「提示词
向上移动一行，百度 APP、百度密钥同步向上移动一行」。

根因：`.ui` 里绝对定位容器 `layoutWidget_2` 声明高 280，而 `gridLayout_32` 各行
真实需要远小于它（真机 + 主题字体实测自然高 218），网格末尾又没有 Expanding
间隔，富余全被「独占一行、垂直策略 Preferred、heightForWidth 有效」的
`label_baidu_hint` 吃掉（真机实测行高 62 / 文字墨迹 15）。修法两半（见
`MyMAinWindow._sync_fanyi_group_spacing` 第 0 步）：`.ui` 末尾补垂直 Expanding
间隔 + 运行期把两行说明文字按墨迹高度贴合、容器高钉成网格 sizeHint、其后组按
累计收缩量上移。

本测试刻意**不写死像素**：离屏平台无字体，字号与真机不同，故一律断言「关系」
——行高 == 纯宽度函数算出的墨迹高、行与行之间只剩 verticalSpacing、组底留白
== 常量、组间距保持设计值、宽幅登记表与当前几何一致、幂等。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QLayoutItem, QSpacerItem

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


_NAMES = (
    "groupBox_trans",
    "groupBox_llm",
    "groupBox_82",
    "groupBox_83",
    "groupBox_84",
    "groupBox_85",
    "groupBox_86",
    "groupBox_87",
    "groupBox_88",
    "groupBox_89",
    "layoutWidget_2",
    "label_164",
    "label_baidu_hint",
    "lineEdit_deeplx_url",
    "lineEdit_baidu_appid",
    "lineEdit_baidu_key",
)


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
    grid = ui.gridLayout_32
    lw = ui.layoutWidget_2
    box = ui.groupBox_trans
    note, hint = ui.label_164, ui.label_baidu_hint
    deeplx = ui.lineEdit_deeplx_url
    appid, bkey = ui.lineEdit_baidu_appid, ui.lineEdit_baidu_key
    gap = grid.verticalSpacing()

    # 1) 容器钉到网格自然高（不给 Qt 任何均分空间）
    assert lw.height() == grid.sizeHint().height(), (lw.height(), grid.sizeHint().height())

    # 2) 两行说明文字按「当前宽度的墨迹高」贴合，且不裁字
    assert note.height() == win._label_ink_height_for_width(note), note.height()
    assert hint.height() == win._label_ink_height_for_width(hint), hint.height()
    assert win._measure_painted_height(hint) <= hint.height()
    assert win._measure_painted_height(note) <= note.height()

    # 3) 行与行之间只剩 verticalSpacing：用户圈出的那整行空白不得回来
    assert hint.y() == deeplx.y() + deeplx.height() + gap, (hint.y(), deeplx.y())
    assert appid.y() == hint.y() + hint.height() + gap, (appid.y(), hint.y())
    assert bkey.y() == appid.y() + appid.height() + gap, (bkey.y(), appid.y())

    # 4) 组底留白 == 常量（不把空白挪到组底变成新的大片留白）
    assert box.height() == lw.y() + lw.height() + MW._FANYI_TRANS_BOT_PAD, box.height()
    assert box.height() < 320, box.height()  # 设计值 320，确实收紧了

    # 5) 其后各组整体上移，但组间距保持设计值（翻译引擎组下方 14、其余 20）
    assert ui.groupBox_llm.y() == box.y() + box.height() + 14
    prev = ui.groupBox_llm
    for name in _NAMES[2:9]:
        cur = getattr(ui, name)
        assert cur.y() == prev.y() + prev.height() + 20, name
        prev = cur

    # 6) 宽幅登记表必须与当前几何一致，否则下一次宽幅同步会把收紧后的高度撑回去
    registry = getattr(ui.scrollAreaWidgetContents_fanyi, "_wide_children_design", None)
    entry = next(e for e in registry if e.widget is box)
    assert entry.geometry[3] == box.height(), (entry.geometry[3], box.height())
    inner = next(i for i in entry.inner if i.widget is lw)
    assert inner.geometry[3] == lw.height(), (inner.geometry[3], lw.height())


@pytest.mark.parametrize("width", [900, 1030, 1600])
def test_engine_group_tight_in_all_widths(win, app, width):
    """三档窗口宽度下都收紧：无空白行、组底留白常量、组间距不变、幂等。"""
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


def test_engine_group_constants_pinned(win):
    """间距常量钉死：改动常量时这条会红，避免间距被静默改掉。"""
    from mdcx.controllers.main_window.main_window import MyMAinWindow as MW

    assert MW._FANYI_TRANS_BOT_PAD == 10
    assert MW._FANYI_TRANS_FOLLOW_GROUPS == ("groupBox_llm", "groupBox_82")
    # 组内网格末尾必须有 Expanding 间隔（.ui 的 verticalSpacer_trans_grid）：
    # 没有它，任何残余富余都会再次被独占一行的提示词标签吃掉
    ui = win.Ui
    item = ui.gridLayout_32.itemAtPosition(7, 0)
    assert isinstance(item, QLayoutItem) and isinstance(item.spacerItem(), QSpacerItem)
    spacer = item.spacerItem()
    assert spacer.sizePolicy().verticalPolicy() == spacer.sizePolicy().Policy.Expanding


def test_engine_group_baidu_rows_moved_up(win, app):
    """百度 APP / 百度密钥两行必须跟着提示词一起上移（用户原始诉求）。

    判据取「百度两行底 与 组框内框底 的距离」：设计值下留白只有 10px，
    提示词行吃掉 62px 富余时该距离会涨到 60px 以上。
    """
    win.show()
    _goto_fanyi(win, app)
    win.resize(1030, 760)
    app.processEvents()
    _settle(win, app)
    ui = win.Ui
    box = ui.groupBox_trans
    lw = ui.layoutWidget_2
    key_bottom = lw.y() + ui.lineEdit_baidu_key.y() + ui.lineEdit_baidu_key.height()
    bottom_pad = box.height() - key_bottom
    assert bottom_pad <= 30, bottom_pad
