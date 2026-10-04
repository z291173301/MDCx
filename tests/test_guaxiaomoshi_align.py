"""设置-刮削模式页描述列对齐与单行显示的回归测试。

用户需求（2026-10-06，截图批注）：
  ① 刮削模式 5 行描述文字（正常/分离/视频/更新/读取模式的「执行：…」
     提示词）左缘，与「设置Javdb延时…」提示行左缘严格上下对齐——
     描述列曾无故右偏，本文件把对齐钉死。
  ② 5 行提示词必须是单行显示（wordWrap=false），以后不允许再变动位置——
     任何同步逻辑不得再搬动它们。

实现方式（见 init.py 刮削模式列钉死段）：
  - gridLayout_2（8 行模式组）与 gridLayout_15（Javdb 延时组）第 0 列
    stretch 钉 0、第 1 列钉 1，两网格第 0 列最小宽取各自全部行部件
    sizeHint 最大值再统一取大，保证两网格第 1 列左缘跨网格对齐。
  - 5 个描述 label 的 wordWrap 在 .ui 里直接改为 false（单行），并配同
    文案 tooltip 防极端 DPI 下被裁剪。
  - 一次性 init 钉死，不挂 _sync_page_layouts 钩子：通用宽幅同步只拉伸
    网格容器宽度，第 0 列最小宽不受影响，故同步前后位置恒定。

本文件 6 项（纯离线 + offscreen 窗口实测）：
  1. .ui 里 5 个 label 的 wordWrap 均为 false。
  2. MDCx.py 里 5 个 label 均为 setWordWrap(False)（与 .ui 同步）。
  3. 运行时 label_26 与 label_separate_mode 左缘精确对齐（映射到
     scrollAreaWidgetContents_guaxiaomoshi 下比对）。
  4. 两网格列 stretch 为 0/1，且 5 个 label 运行时 wordWrap 均为 False、
     tooltip 非空。
  5. 窄↔宽两态 + 重复同步，5 个 label 与 label_26 的左缘逐像素不变
     （以后不允许再变动位置）。
  6. 同列 4 个复选框（STRM 生成 / STRM 覆盖 / 元数据复用 / 视频模式删除）
     左缘严格一致，窄↔宽往返不变。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication

REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
PY_PATH = REPO / "mdcx" / "views" / "MDCx.py"

# gridLayout_2 第 1 列同列复选框：STRM 生成 / STRM 覆盖 / 元数据复用 / 视频模式删除。
# 四者同处第 1 列，左缘必须严格一致。
_MODE_CHECKBOXES = (
    "checkBox_separate_generate_strm",
    "checkBox_separate_overwrite_strm",
    "checkBox_separate_reuse_meta",
    "checkBox_sortmode_delpic",
)

# gridLayout_2 第 1 列 5 个描述 label：正常 / 分离 / 视频 / 更新 / 读取。
_DESC_LABELS = (
    "label_11",
    "label_separate_mode",
    "label_15",
    "label_36",
    "label_312",
)

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


def _goto_guaxiaomoshi(win, app):
    """切到设置页的「刮削模式」tab（objectName 是 tab1）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab1":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("刮削模式 tab1 not found")
    app.processEvents()


def _abs(ui, widget):
    """控件左缘映射到刮削模式页滚动内容的绝对 x。"""
    return widget.mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def test_desc_labels_single_line_in_ui():
    """需求②（静态）：.ui 里 5 个描述 label 的 wordWrap 必须为 false。"""
    tree = ET.parse(UI_PATH)
    missing = []
    for name in _DESC_LABELS:
        found = False
        for widget in tree.iter("widget"):
            if widget.get("name") == name:
                found = True
                for prop in widget.findall("property"):
                    if prop.get("name") == "wordWrap":
                        val = prop.find("bool").text == "true"
                        assert val is False, f".ui 里 {name} 的 wordWrap 又被改回 true（必须单行）"
                        break
                else:
                    raise AssertionError(f".ui 里 {name} 找不到 wordWrap 属性")
                break
        if not found:
            missing.append(name)
    assert not missing, f".ui 里找不到描述 label：{missing}"


def test_desc_labels_single_line_in_py():
    """需求②（同步）：MDCx.py 里 5 个 label 必须为 setWordWrap(False)。"""
    text = PY_PATH.read_text(encoding="utf-8")
    for name in _DESC_LABELS:
        assert f"self.{name}.setWordWrap(False)" in text, (
            f"MDCx.py 里 {name} 不是 setWordWrap(False)，请用 pyuic6 重生成"
        )


def test_desc_column_aligns_with_javdb_tip(win, app):
    """需求①：描述列左缘与 Javdb 延时提示行左缘严格上下对齐。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    _resize(win, app, 1030, 753)

    anchor = _abs(ui, ui.label_26)
    for name in _DESC_LABELS:
        got = _abs(ui, getattr(ui, name))
        assert got == anchor, f"{name} 未与 label_26 对齐: x={got} 期望={anchor}"


def test_grid_columns_pinned_and_tooltips(win, app):
    """列钉死 + 单行 + tooltip：两网格列 stretch 为 0/1，运行时单行且有提示。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    _resize(win, app, 1030, 753)

    for grid_name in ("gridLayout_2", "gridLayout_15"):
        grid = getattr(ui, grid_name)
        assert grid.columnStretch(0) == 0, f"{grid_name} 第 0 列 stretch 被改动"
        assert grid.columnStretch(1) == 1, f"{grid_name} 第 1 列 stretch 被改动"

    for name in _DESC_LABELS:
        label = getattr(ui, name)
        assert label.wordWrap() is False, f"运行时 {name} 的 wordWrap 不是 False"
        assert label.toolTip(), f"{name} 缺少 tooltip（极端 DPI 下文字会被裁剪）"


def test_desc_column_never_moves_again(win, app):
    """需求②（冻结）：窄↔宽两态 + 重复同步，描述列与锚点左缘逐像素不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def snapshot():
        return {name: _abs(ui, getattr(ui, name)) for name in _DESC_LABELS + ("label_26",)}

    _resize(win, app, 1030, 753)
    narrow = snapshot()
    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "窄态二次同步漂移（以后不允许再变动位置）"

    _resize(win, app, 1920, 1170)
    wide = snapshot()
    # 宽态下描述列左缘必须与窄态一致：只允许容器变宽，不允许列左移/右移
    assert wide == narrow, f"宽态描述列位置变动: {narrow} -> {wide}"
    _resize(win, app, 1920, 1170)
    assert snapshot() == wide, "宽态二次同步漂移"

    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "窄→宽→窄往返未复原"


def test_mode_checkboxes_left_aligned(win, app):
    """同列 3 复选框（生成/复用/删除）左缘严格一致，覆盖框同行居右，窄↔宽往返不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def snapshot():
        return {name: _abs(ui, getattr(ui, name)) for name in _MODE_CHECKBOXES}

    _resize(win, app, 1030, 753)
    narrow = snapshot()
    aligned = {
        k: narrow[k]
        for k in (
            "checkBox_separate_generate_strm",
            "checkBox_separate_reuse_meta",
            "checkBox_sortmode_delpic",
        )
    }
    assert len(set(aligned.values())) == 1, f"同列复选框左缘不一致: {narrow}"
    assert narrow["checkBox_separate_overwrite_strm"] > narrow["checkBox_separate_generate_strm"], (
        f"覆盖框应同行居右: {narrow}"
    )
    _resize(win, app, 1920, 1170)
    wide = snapshot()
    assert wide == narrow, f"宽态复选框位置变动: {narrow} -> {wide}"
    _resize(win, app, 1030, 753)
    assert snapshot() == narrow, "窄→宽→窄往返未复原"


def test_overwrite_meta_aligns_under_overwrite_strm(win, app):
    """覆盖元数据框与覆盖 STRM 框上下严格对齐、与复用框同行，窄↔宽往返不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)

    def pos(name):
        p = getattr(ui, name).mapTo(ui.scrollAreaWidgetContents_guaxiaomoshi, QPoint(0, 0))
        return (p.x(), p.y())

    _resize(win, app, 1030, 753)
    narrow_meta = pos("checkBox_separate_overwrite_meta")
    narrow_strm = pos("checkBox_separate_overwrite_strm")
    narrow_reuse = pos("checkBox_separate_reuse_meta")
    assert narrow_meta[0] == narrow_strm[0], f"覆盖元数据框未与覆盖 STRM 框对齐: {narrow_meta} vs {narrow_strm}"
    assert narrow_meta[1] == narrow_reuse[1], f"覆盖元数据框未与复用框同行: {narrow_meta} vs {narrow_reuse}"
    assert narrow_meta[1] > narrow_strm[1], "覆盖元数据框应在覆盖 STRM 框下方"
    _resize(win, app, 1920, 1170)
    wide_meta = pos("checkBox_separate_overwrite_meta")
    wide_strm = pos("checkBox_separate_overwrite_strm")
    assert wide_meta == narrow_meta, f"宽态覆盖元数据框位置变动: {narrow_meta} -> {wide_meta}"
    assert wide_meta[0] == wide_strm[0], "宽态两覆盖框不对齐"
    _resize(win, app, 1030, 753)
    assert pos("checkBox_separate_overwrite_meta") == narrow_meta, "窄→宽→窄往返未复原"


def test_reuse_overwrite_meta_mutually_exclusive(win, app):
    """复用/覆盖元数据互斥：勾选其一自动去勾另一，去勾不动作。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomoshi(win, app)
    _resize(win, app, 1030, 753)
    reuse = ui.checkBox_separate_reuse_meta
    overwrite = ui.checkBox_separate_overwrite_meta
    reuse.setChecked(False)
    overwrite.setChecked(False)
    app.processEvents()
    reuse.setChecked(True)
    app.processEvents()
    assert reuse.isChecked() and not overwrite.isChecked(), "勾选复用后覆盖应自动去勾"
    overwrite.setChecked(True)
    app.processEvents()
    assert overwrite.isChecked() and not reuse.isChecked(), "勾选覆盖后复用应自动去勾"
    overwrite.setChecked(False)
    app.processEvents()
    assert not overwrite.isChecked() and not reuse.isChecked(), "去勾不应影响另一方"
    reuse.setChecked(False)
    app.processEvents()
