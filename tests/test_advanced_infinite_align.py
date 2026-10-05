"""设置-高级页保留任务行：「无限次刮削」与「停止刮削时」严格上下对齐（宽窄两态）。

需求（用户截图红框）：
  最小化时「无限次刮削」向右移到与「停止刮削时」上下对齐；
  最大化时「无限次刮削」向左移到与「停止刮削时」上下对齐；
  「停止刮削时」自身位置保持不变。

实现：_sync_advanced_page_align 内在弹窗确认行落定后，钉死前导项
「记住未完成的刮削任务」，使末位「无限次刮削」落到「停止刮削时」实测 x。
只断言「精确落在锚点左缘」，不断言移动方向（离屏无 CJK 字体，方向不可比）。

可行性门控（与「隐藏菜单栏图标」行同款手法）：落点落在前导项文本自然宽
之内时硬钉会裁字，此时整行放弃、保持设计态原样。窄态与全最大化下放得下，
必须精确对齐；1100/1366 中间带在离屏度量下放不下，走延后分支断言。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
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


def _goto_advanced(win, app):
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab5":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("高级 tab5 not found")
    app.processEvents()


def _abs(ui, widget) -> int:
    return widget.mapTo(ui.scrollAreaWidgetContents_gaoji, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _remain_row(ui):
    """保留任务行的实测可行性（与实现同式）：钉宽放得下才算可行。"""
    host = ui.gridLayoutWidget_20
    content = ui.scrollAreaWidgetContents_gaoji
    host_x = host.mapTo(content, QPoint(0, 0)).x()
    row5_x = _abs(ui, ui.checkBox_remain_task) - host_x
    want = _abs(ui, ui.checkBox_show_dialog_stop_scrape) - host_x
    lay = ui.horizontalLayout_89
    col_w = host.width() - row5_x
    pin = want - row5_x - lay.spacing()
    feasible = (
        want > row5_x
        and pin >= ui.checkBox_remain_task.sizeHint().width()
        and col_w - pin - lay.spacing() >= ui.checkBox_infinite_scrape.sizeHint().width()
    )
    return {"pin": pin, "feasible": feasible}


_WIDE_SIZES = ((1920, 1170), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


@pytest.mark.parametrize("width,height", _WIDE_SIZES + _NARROW_SIZES)
def test_infinite_aligns_to_stop_or_defers(win, app, width, height):
    """放得下就必须精确对齐；放不下就整行放弃（不钉宽、不裁字）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    row = _remain_row(ui)
    got = _abs(ui, ui.checkBox_infinite_scrape)
    want = _abs(ui, ui.checkBox_show_dialog_stop_scrape)
    remain = ui.checkBox_remain_task
    infinite = ui.checkBox_infinite_scrape

    if row["feasible"]:
        assert got == want, f"{width} 宽下放得下（pin={row['pin']}）却未对齐: x={got} 期望={want}"
    else:
        # 放弃态：落点在前导项文本自然宽之内，硬钉必然裁字，故保持自然位
        # （末项停在竖线右侧）；钉宽必须处于解除态，下次放得下时才能重新钉上。
        assert got > want, f"{width} 宽下放不下（pin={row['pin']}）本应整行放弃，却对到了 x={got}（可能裁字）"
        assert remain.minimumWidth() == 0 and remain.maximumWidth() == 16777215, (
            f"{width} 宽下放弃态里前导项钉宽未解除: min={remain.minimumWidth()} max={remain.maximumWidth()}"
        )

    # 两种情形下两项都不许被压到裁字；「停止刮削时」自身一律不动。
    assert remain.width() >= remain.sizeHint().width(), (
        f"{width} 宽下「记住未完成的刮削任务」被压到 {remain.width()}px（sizeHint {remain.sizeHint().width()}），会裁字"
    )
    assert infinite.width() >= infinite.sizeHint().width(), (
        f"{width} 宽下「无限次刮削」被压到 {infinite.width()}px（sizeHint {infinite.sizeHint().width()}），会裁字"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_stop_stays_on_spec_line_in_wide(win, app, width, height):
    """宽态「停止刮削时」仍精确落在既有竖线（显示字段来源信息）上，本需求未搬动它。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert win._scroll_stretch_extra(win._adv_scroll) > 0
    got = _abs(ui, ui.checkBox_show_dialog_stop_scrape)
    anchor = _abs(ui, ui.checkBox_show_from_log)
    assert got == anchor, f"{width} 宽下「停止刮削时」被搬动: x={got} 既有竖线={anchor}"


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_stop_stays_on_spec_line_in_narrow(win, app, width, height):
    """窄态「停止刮削时」仍精确落在既有竖线（显示字段内容信息）上，本需求未搬动它。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert win._scroll_stretch_extra(win._adv_scroll) <= 0
    got = _abs(ui, ui.checkBox_show_dialog_stop_scrape)
    anchor = _abs(ui, ui.checkBox_show_data_log)
    assert got == anchor, f"{width} 宽下「停止刮削时」被搬动: x={got} 既有竖线={anchor}"
