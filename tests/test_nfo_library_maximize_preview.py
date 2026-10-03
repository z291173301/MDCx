"""信息管理页（page_nfo_library）最大化布局 + 大图预览窗口回归测试。

背景（用户截图反馈）：

1. 最大化时表单 16 行之间凭空多出约一行宽的空白（QFormLayout 会把内容区
   富余高度平均分给所有「还能长高」的行，单行输入框 sizeHint 只有 22px，
   却分到 54px，于是发行日/年份之间出现一整行空白）；
2. 左键单击右侧预览图要弹出与主页面完全重合的大图窗口（带最小化/最大化/关闭按钮），
   ← / → 在同一个番号内切换封面与缩略图，↑ / ↓ 切换不同番号，Esc 关闭；
   图片下方提示用箭头图标表示按键，不写「左右键 / 上下键」这类文字；
3. 最大化时「筛选番号/演员/标题」输入框要按「选择目录」显示框宽度等比例加宽；
4. 顶栏顺序改为 目录显示框 → 选择目录按钮 → 共 N 个 → 筛选 → 刷新，
   目录框向左拓展、吃满按钮让出的空间；
5. 选择目录确定后（或刷新后）自动展示目录内第一个番号的信息；
6. 顶栏「选择目录」「刷新」按钮改用软件设置-高级页同款样式但宽高不变，
   「批量保存」「保存当前nfo文件」「裁剪封面」改用软件设置主页面保存按钮的蓝底，
   前两者宽度铺满所在边框，裁剪封面与批量保存同高。

最小化态必须逐像素不变（双向幂等），非最大化窗口只被拉伸（isMaximized 为假）
时也维持原样。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time
from pathlib import Path

import pytest
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFormLayout, QLabel

_app: QApplication | None = None

# 「简介/标签」两个多行框：最大化时它们吸收富余高度，故不参与行间隙比对
_FLEX_FIELDS = ("plainTextEdit_nfo_lib_outline", "plainTextEdit_nfo_lib_tag")


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


@pytest.fixture()
def library(win, app, tmp_path):
    """两个同目录 NFO，各带 poster / thumb 图，并已加载进列表。"""
    folder = tmp_path / "nfo_lib"
    folder.mkdir()
    for name in ("ABC-001", "ABC-002"):
        (folder / f"{name}.nfo").write_text("<movie></movie>", encoding="utf-8")
        for kind, size in (("poster", (300, 420)), ("thumb", (400, 225))):
            Image.new("RGB", size, (12, 34, 56)).save(folder / f"{name}-{kind}.jpg", quality=90)

    _goto_nfo_lib(win, app)
    win.Ui.lineEdit_nfo_lib_dir.setText(str(folder))
    win.pushButton_nfo_lib_refresh_clicked()
    app.processEvents()
    assert win.Ui.listWidget_nfo_lib.count() == 2
    return folder


def _goto_nfo_lib(win, app):
    """切到信息管理页。"""
    for i in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(i)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(i)
            app.processEvents()
            return page
    raise AssertionError("page_nfo_library not found")


def _set_maximized(win, app, maxed: bool) -> None:
    """摆出指定最大化态的几何。"""
    win.isMaximized = lambda: maxed
    win._sync_page_layouts()
    app.processEvents()


def _field_rows(ui):
    """表单每行的字段控件（跳过无字段的行）。"""
    layout = ui.formLayout_nfo_lib
    rows = []
    for row in range(layout.rowCount()):
        item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
        widget = item.widget() if item is not None else None
        if widget is not None:
            rows.append(widget)
    return rows


def _inter_row_gaps(ui) -> list[int]:
    """相邻两行之间多出来的空白高度（紧凑排布时应等于 verticalSpacing）。"""
    gaps = []
    previous = None
    for widget in _field_rows(ui):
        if widget.objectName() in _FLEX_FIELDS:
            previous = None
            continue
        if previous is not None:
            gaps.append(widget.geometry().y() - (previous.geometry().y() + previous.height()))
        previous = widget
    return gaps


def _snapshot(ui) -> list[tuple[str, int, int, int, int]]:
    """表单每行控件的几何 + 内容区高度上限，用于逐像素比对。"""
    layout = ui.formLayout_nfo_lib
    items = []
    for row in range(layout.rowCount()):
        for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
            item = layout.itemAt(row, role)
            widget = item.widget() if item is not None else None
            if widget is not None:
                items.append((widget.objectName(), *widget.geometry().getRect()))
    items.append(("__content_max_h__", 0, 0, 0, ui.scrollAreaWidgetContents_nfo_lib.maximumHeight()))
    return items


def _left_click(win, app, label) -> None:
    """在预览框上派发一次左键按下 + 释放（走主窗事件过滤器）。"""
    pos = QPointF(5.0, 5.0)
    for event_type, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
    ):
        event = QMouseEvent(
            event_type,
            pos,
            pos,
            Qt.MouseButton.LeftButton,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        win.eventFilter(label, event)
    app.processEvents()


# ============= 1. 最大化行间距 =============


def test_maximized_form_rows_have_no_blank_between_rows(win, app):
    """最大化后相邻行之间不得再出现约一行宽的空白（只保留设计的 verticalSpacing）。"""
    _goto_nfo_lib(win, app)
    win.resize(1920, 1080)
    app.processEvents()

    _set_maximized(win, app, True)
    gaps = _inter_row_gaps(win.Ui)
    assert gaps, "表单里没有可比对的相邻行"
    spacing = win.Ui.formLayout_nfo_lib.verticalSpacing()
    assert all(gap == spacing for gap in gaps), f"最大化后行间仍有空白: {gaps}（期望 {spacing}）"

    # 对照：非最大化时只拉伸窗口，维持原样（空白仍由布局摊开）
    _set_maximized(win, app, False)
    loose_gaps = _inter_row_gaps(win.Ui)
    assert max(loose_gaps) > spacing, f"非最大化态被误改了: {loose_gaps}"

    # 双向幂等：再切回最大化，行间隙与刚才一致
    _set_maximized(win, app, True)
    assert _inter_row_gaps(win.Ui) == gaps


def test_maximized_form_fits_scroll_viewport(win, app):
    """消除行间空白后，内容区不得比视口高（否则会冒出垂直滚动条）。"""
    _goto_nfo_lib(win, app)
    win.resize(1920, 1080)
    app.processEvents()
    _set_maximized(win, app, True)
    ui = win.Ui
    viewport_h = ui.scrollArea_nfo_lib_form.viewport().height()
    assert ui.scrollAreaWidgetContents_nfo_lib.height() <= viewport_h
    save_bottom = ui.pushButton_nfo_lib_save.geometry().y() + ui.pushButton_nfo_lib_save.height()
    assert save_bottom <= viewport_h, "「保存当前nfo文件」被推到视口外"
    # 富余高度由「简介/标签」吸收，两框应高于设计高 60
    assert ui.plainTextEdit_nfo_lib_outline.height() > 60
    assert ui.plainTextEdit_nfo_lib_tag.height() > 60


def test_minimized_layout_untouched_and_restores(win, app):
    """最小化态几何不得因最大化往返而改变（逐像素 + 简介/标签保持设计高）。"""
    _goto_nfo_lib(win, app)
    win.resize(1030, 700)
    app.processEvents()
    _set_maximized(win, app, False)
    ui = win.Ui
    assert ui.plainTextEdit_nfo_lib_outline.height() == 60
    assert ui.plainTextEdit_nfo_lib_tag.height() == 60
    baseline = _snapshot(ui)

    _set_maximized(win, app, True)
    assert _snapshot(ui) != baseline, "最大化态本应变化"

    _set_maximized(win, app, False)
    assert _snapshot(win.Ui) == baseline, "从最大化还原后最小化态几何漂移"


# ============= 2. 顶部栏：选择目录按钮移到「共 N 个」左侧，目录框向左拓展 =============


def test_top_bar_order_and_dir_box_expands_left(win, app):
    """顶栏顺序必须是 目录框 → 选择目录 → 共N个 → 筛选 → 刷新，且目录框吃满按钮腾出的空间。"""
    _goto_nfo_lib(win, app)
    ui = win.Ui
    win.resize(1030, 700)
    app.processEvents()

    layout = ui.nfo_lib_top_bar.layout()
    order = [layout.itemAt(i).widget().objectName() for i in range(layout.count())]
    assert order == [
        "lineEdit_nfo_lib_dir",
        "pushButton_nfo_lib_select_dir",
        "label_nfo_lib_count",
        "lineEdit_nfo_lib_filter",
        "pushButton_nfo_lib_refresh",
    ], f"顶栏控件顺序不对: {order}"

    box = ui.lineEdit_nfo_lib_dir
    button = ui.pushButton_nfo_lib_select_dir
    count = ui.label_nfo_lib_count
    spacing = layout.spacing()
    margins = layout.contentsMargins()
    # 目录框紧贴顶栏左边缘（按钮原来占的位置已归还给它）
    assert box.x() == margins.left(), f"目录框未向左拓展到边缘: x={box.x()}"
    assert box.x() + box.width() + spacing == button.x(), "目录框右边缘应紧贴选择目录按钮"
    assert button.x() + button.width() + spacing == count.x(), "选择目录按钮应紧邻「共 N 个」左侧"
    # 目录框必须比按钮宽得多，说明它吸收了富余宽度而不是固定在 sizeHint
    assert box.width() > button.width() * 2
    narrow_w = box.width()

    # 加宽窗口后目录框继续吃掉全部富余空间（最大化态同样成立）
    _set_maximized(win, app, True)
    win.resize(1920, 1080)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    assert box.x() == margins.left()
    assert box.width() > narrow_w, "拉宽窗口后目录框没有向左拓展"
    assert box.x() + box.width() + spacing == button.x()


# ============= 3. 筛选框等比例加宽 =============


def test_maximized_filter_box_scales_with_dir_box(win, app):
    """最大化时筛选框按目录框实测宽度等比例加宽，最小化态复位 180。"""
    _goto_nfo_lib(win, app)
    win.resize(1920, 1080)
    app.processEvents()
    ui = win.Ui

    _set_maximized(win, app, False)
    assert ui.lineEdit_nfo_lib_filter.maximumWidth() == win._NFO_LIB_FILTER_MAX_W

    _set_maximized(win, app, True)
    widened = ui.lineEdit_nfo_lib_filter.maximumWidth()
    assert widened > win._NFO_LIB_FILTER_MAX_W, "最大化后筛选框没有加宽"
    assert ui.lineEdit_nfo_lib_filter.width() > win._NFO_LIB_FILTER_MAX_W

    # 反复同步不得来回抖动（目录框宽度被自己的加宽结果影响会自反馈）
    for _ in range(4):
        win._sync_page_layouts()
        app.processEvents()
        assert ui.lineEdit_nfo_lib_filter.maximumWidth() == widened, "筛选框宽度在重复同步间抖动"

    # 换算依据是「筛选框按设计宽度复位时的目录框宽」
    ui.lineEdit_nfo_lib_filter.setMaximumWidth(win._NFO_LIB_FILTER_MAX_W)
    ui.nfo_lib_top_bar.layout().invalidate()
    ui.nfo_lib_top_bar.layout().activate()
    base = ui.lineEdit_nfo_lib_dir.width()
    assert base > 0
    expected = max(
        win._NFO_LIB_FILTER_MIN_W,
        min(int(base * win._NFO_LIB_FILTER_SCALE), win._NFO_LIB_FILTER_MAX_W_CAP),
    )
    assert widened == expected, f"筛选框宽度 {widened} 与目录框实测 {base} 不成比例（期望 {expected}）"

    _set_maximized(win, app, False)
    assert ui.lineEdit_nfo_lib_filter.maximumWidth() == win._NFO_LIB_FILTER_MAX_W


# ============= 4. 大图预览窗口 =============


def _key_cap_texts(window) -> list[str]:
    return [label.text() for label in window.findChildren(QLabel) if label.objectName() == "label_nfo_lib_preview_key"]


def _hint_texts(window) -> list[str]:
    return [
        label.text() for label in window.findChildren(QLabel) if label.objectName() == "label_nfo_lib_preview_hint_text"
    ]


def test_poster_preview_click_opens_window_covering_main(win, app, library):
    """左键单击海报预览 → 弹出与主页面完全重合（彻底覆盖）、带最小化/最大化按钮的大图窗口。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)

    window = getattr(win, "nfo_lib_preview_window", None)
    assert window is not None, "单击预览图没有弹出窗口"
    assert window.isVisible()
    assert window.geometry() == win.geometry(), "弹窗未与主页面完全重合"
    assert window.size() == win.size(), "窗口大小未与主页面一致"
    flags = window.windowFlags()
    assert flags & Qt.WindowType.WindowMaximizeButtonHint, "缺少最大化按钮"
    assert flags & Qt.WindowType.WindowMinimizeButtonHint, "缺少最小化按钮"
    assert not flags & Qt.WindowType.FramelessWindowHint, "应保留系统标题栏"
    assert window.current_path() == library / "ABC-001-poster.jpg"
    assert window.image_count() == 2, "同一番号的封面 + 缩略图应归为一组"
    assert window.nfo_count() == 2, "上下键要能切换两个番号"
    assert window.current_nfo_index() == 0
    assert "封面" in window.windowTitle()


def test_preview_window_follows_main_window_state(win, app, library):
    """主页面最大化时弹窗也最大化，主页面还原时弹窗回到普通窗口并重新盖住主页面。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _set_maximized(win, app, True)
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window
    assert window.isMaximized(), "主页面最大化时弹窗应一起最大化"

    _set_maximized(win, app, False)
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    app.processEvents()
    assert not window.isMaximized(), "主页面还原后弹窗应回到普通窗口"
    assert window.geometry() == win.geometry(), "还原后弹窗应再次完全盖住主页面"


def test_preview_window_minimized_when_main_minimized(win, app, library):
    """主页面最小化时弹窗也默认最小化。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    monkey = win.isMinimized
    win.isMinimized = lambda: True
    try:
        _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    finally:
        win.isMinimized = monkey
    assert win.nfo_lib_preview_window.isMinimized(), "主页面最小化时弹窗应一起最小化"


@pytest.mark.skipif(sys.platform != "win32", reason="任务栏 AppUserModelID 仅 Windows")
def test_preview_window_has_own_taskbar_app_id(win, app, library):
    """预览窗口必须有独立的任务栏 AppUserModelID，跟主窗口分成两个图标。

    主窗口右下角图标隐藏再显示后也不得合回一组：showEvent 每次显示都补齐。
    """
    from mdcx.views.nfo_preview_window import NfoPreviewWindow

    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window
    if app.platformName() != "windows":
        pytest.skip("任务栏 AppUserModelID 需要真实 Windows 窗口系统，离屏平台无 shell 可读回")
    assert window._read_taskbar_app_id() == "MDCx.NfoPreview"
    assert NfoPreviewWindow._read_app_id_for_widget(win) != "MDCx.NfoPreview"

    # 模拟托盘收起再放出主窗口：预览的独立 ID 必须还在，不得合回一组
    win.hide()
    app.processEvents()
    win.show()
    app.processEvents()
    assert window._read_taskbar_app_id() == "MDCx.NfoPreview"


def test_preview_window_repositions_after_main_window_moves(win, app, library):
    """主页面挪动 / 改尺寸后再次点图，弹窗要重新与主页面重合（默认居中覆盖）。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window

    win.resize(1280, 800)
    win.move(120, 90)
    app.processEvents()
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    app.processEvents()
    assert window.geometry() == win.geometry(), "弹窗没有跟随主页面重新居中"


def test_left_right_switch_images_inside_same_nfo(win, app, library):
    """← / → 只在同一个番号内切换封面与缩略图，不换番号、不动列表选中项。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window
    assert window.current_image_index() == 0 and window.current_nfo_index() == 0
    row_before = win.Ui.listWidget_nfo_lib.currentRow()

    QTest.keyClick(window, Qt.Key.Key_Right)
    app.processEvents()
    assert window.current_path() == library / "ABC-001-thumb.jpg", "→ 应切到同一番号的缩略图"
    assert window.current_nfo_index() == 0, "→ 不得换番号"
    assert win.Ui.listWidget_nfo_lib.currentRow() == row_before, "→ 不得改变列表选中项"

    QTest.keyClick(window, Qt.Key.Key_Left)
    app.processEvents()
    assert window.current_path() == library / "ABC-001-poster.jpg", "← 应切回同一番号的封面"


def test_up_down_switch_between_nfo_numbers(win, app, library):
    """↑ / ↓ 切换不同番号，并尽量保持同类型图片，同时联动列表选中项。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window

    QTest.keyClick(window, Qt.Key.Key_Down)
    app.processEvents()
    assert window.current_nfo_index() == 1, "↓ 应切到下一个番号"
    assert window.current_path() == library / "ABC-002-poster.jpg", "换番号后应仍是封面"
    assert win.Ui.listWidget_nfo_lib.currentItem().text() == "ABC-002", "列表选中项未跟随换番号"

    # 换成缩略图后再按 ↑，应回到上一个番号的缩略图
    QTest.keyClick(window, Qt.Key.Key_Right)
    app.processEvents()
    assert window.current_path() == library / "ABC-002-thumb.jpg"
    QTest.keyClick(window, Qt.Key.Key_Up)
    app.processEvents()
    assert window.current_nfo_index() == 0, "↑ 应切回上一个番号"
    assert window.current_path() == library / "ABC-001-thumb.jpg", "换番号后应保持缩略图"


def test_up_down_wraps_around(win, app, library):
    """↑ / ↓ 在番号清单首尾循环。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window

    QTest.keyClick(window, Qt.Key.Key_Up)
    app.processEvents()
    assert window.current_nfo_index() == 1, "首番号按 ↑ 应循环到末尾"
    QTest.keyClick(window, Qt.Key.Key_Down)
    app.processEvents()
    assert window.current_nfo_index() == 0, "末尾番号按 ↓ 应循环回首番号"


def test_esc_closes_preview_window(win, app, library):
    """Esc 关闭大图窗口。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window
    assert window.isVisible()

    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert not window.isVisible(), "Esc 未关闭窗口"


def test_hint_bar_uses_key_icons_not_text(win, app, library):
    """图片下方提示用箭头图标表示按键，不得出现「左右键 / 上下键」这类文字。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window

    assert _key_cap_texts(window) == ["←", "→", "↑", "↓", "Esc"], "键位提示应为图标而非文字"
    assert _hint_texts(window) == ["相同番号图片", "不同番号图片", "关闭"]
    all_text = " ".join(label.text() for label in window.findChildren(QLabel))
    assert "左右键" not in all_text and "上下键" not in all_text, "提示里不应出现按键名称文字"
    hint_top = window.info_label.mapTo(window, QPoint(0, 0)).y()
    image_bottom = window.image_label.mapTo(window, QPoint(0, window.image_label.height())).y()
    assert hint_top >= image_bottom, "提示行应在图片下方"


def test_thumb_preview_click_opens_thumb_first(win, app, library):
    """单击缩略图预览 → 优先打开该番号的缩略图。"""
    win._nfo_lib_current_path = library / "ABC-002.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_thumb_preview)

    window = win.nfo_lib_preview_window
    assert window.isVisible()
    assert window.image_count() == 2
    assert window.current_path() == library / "ABC-002-thumb.jpg"
    assert window.current_nfo_index() == 1
    assert "缩略图" in window.windowTitle()


def test_preview_click_without_nfo_selected_opens_nothing(win, app, library):
    """未选中 NFO 时单击预览图不弹窗，也不抛异常。"""
    win._nfo_lib_current_path = None
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    assert getattr(win, "nfo_lib_preview_window", None) is None


def test_preview_window_scales_image_to_window(win, app, library):
    """窗口放大后大图按新尺寸重绘（不会停留在原始 300x420）。"""
    win._nfo_lib_current_path = library / "ABC-001.nfo"
    _left_click(win, app, win.Ui.label_nfo_lib_poster_preview)
    window = win.nfo_lib_preview_window
    window.resize(1600, 1000)
    app.processEvents()
    pixmap = window.image_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert window.image_label.pixmap().width() > 300, "图片未随窗口放大重绘"
    assert window.image_label.size().width() >= pixmap.width() - 2


# ============= 5. 选择目录确定后默认展示第一个番号 =============


def _write_nfo(folder: Path, name: str, title: str) -> None:
    """写入一个可被 get_nfo_data 解析的 NFO（title 缺失会直接判定为损坏文件）。"""
    (folder / f"{name}.nfo").write_text(
        "<movie>"
        f"<title>{title}</title>"
        f"<num>{name}</num>"
        "<actor><name>演员甲</name></actor>"
        "<year>2024</year>"
        "<release>2024-03-15</release>"
        "<runtime>118</runtime>"
        "<plot>简介内容</plot>"
        "<tag>标签一,标签二</tag>"
        "</movie>",
        encoding="utf-8",
    )


def _wait_until(app, predicate, timeout: float = 10.0) -> bool:
    """轮询等待后台 NFO 解析回填表单。"""
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


def _make_library_folder(folder: Path, items) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, title in items:
        _write_nfo(folder, name, title)
        for kind, size in (("poster", (300, 420)), ("thumb", (400, 225))):
            Image.new("RGB", size, (12, 34, 56)).save(folder / f"{name}-{kind}.jpg", quality=90)


def test_select_dir_auto_shows_first_nfo(win, app, tmp_path):
    """选择目录确定后，右侧表单默认显示目录内第一个番号的信息。"""
    folder = tmp_path / "auto_first"
    # 故意让「第二个番号」的文件名字典序在前，验证取的是「列表第一项」
    _make_library_folder(folder, [("BBB-002", "第二个番号"), ("AAA-001", "第一个番号")])

    _goto_nfo_lib(win, app)
    win._get_select_folder_path = lambda _parent: str(folder)
    win.pushButton_nfo_lib_select_dir_clicked()
    app.processEvents()

    assert win.Ui.lineEdit_nfo_lib_dir.text() == str(folder)
    assert win.Ui.label_nfo_lib_count.text() == "共 2 个"
    assert win.Ui.listWidget_nfo_lib.count() == 2
    assert win.Ui.listWidget_nfo_lib.currentRow() == 0, "第一个番号未被自动选中"
    assert win.Ui.listWidget_nfo_lib.currentItem().text() == "AAA-001"
    assert win._nfo_lib_current_path == folder / "AAA-001.nfo"

    # 后台解析完成后表单与预览图都要跟着填上
    assert _wait_until(app, lambda: win.Ui.lineEdit_nfo_lib_title.text() == "第一个番号"), "表单未自动填充"
    assert win.Ui.lineEdit_nfo_lib_actor.text() == "演员甲"
    assert win.Ui.lineEdit_nfo_lib_release.text() == "2024-03-15"
    assert win.Ui.plainTextEdit_nfo_lib_outline.toPlainText() == "简介内容"
    assert not win.Ui.label_nfo_lib_poster_preview.pixmap().isNull(), "海报预览未自动填充"
    assert not win.Ui.label_nfo_lib_thumb_preview.pixmap().isNull(), "缩略图预览未自动填充"


def test_select_dir_keeps_no_selection_when_folder_empty(win, app, tmp_path):
    """目录里没有 NFO 时不产生选中项，只显示占位提示。"""
    folder = tmp_path / "empty_lib"
    folder.mkdir()

    _goto_nfo_lib(win, app)
    win._get_select_folder_path = lambda _parent: str(folder)
    win.pushButton_nfo_lib_select_dir_clicked()
    app.processEvents()

    assert win.Ui.listWidget_nfo_lib.count() == 1
    assert not win.Ui.listWidget_nfo_lib.selectedItems(), "空目录不应有选中项"
    assert "未找到" in win.Ui.listWidget_nfo_lib.item(0).text()


def test_refresh_also_shows_first_nfo(win, app, tmp_path):
    """刷新同样回到第一个番号，避免列表与右侧表单内容不一致。"""
    folder = tmp_path / "refresh_first"
    _make_library_folder(folder, [("AAA-001", "第一个番号"), ("BBB-002", "第二个番号")])

    _goto_nfo_lib(win, app)
    win.Ui.lineEdit_nfo_lib_dir.setText(str(folder))
    win.pushButton_nfo_lib_refresh_clicked()
    app.processEvents()
    assert _wait_until(app, lambda: win.Ui.lineEdit_nfo_lib_title.text() == "第一个番号")

    # 手动点第二个番号后刷新，应重新回到第一个
    win.Ui.listWidget_nfo_lib.setCurrentRow(1)
    app.processEvents()
    assert _wait_until(app, lambda: win.Ui.lineEdit_nfo_lib_title.text() == "第二个番号")
    win.Ui.listWidget_nfo_lib.clearSelection()
    win.pushButton_nfo_lib_refresh_clicked()
    app.processEvents()
    assert _wait_until(app, lambda: win.Ui.lineEdit_nfo_lib_title.text() == "第一个番号"), "刷新未回到第一个番号"
    assert win.Ui.listWidget_nfo_lib.currentRow() == 0


# ============= 6. 按钮样式：选择目录同高级页 / 两个保存按钮蓝底 =============
def _sheet_of(win, monkeypatch, apply) -> str:
    """跑一次样式应用，返回下发给 centralwidget 的整段 QSS。apply 接收 win。"""
    captured: list[str] = []
    original = win.Ui.centralwidget.setStyleSheet

    def recorder(sheet: str) -> None:
        captured.append(sheet)
        original(sheet)

    monkeypatch.setattr(win.Ui.centralwidget, "setStyleSheet", recorder)
    apply(win)
    return captured[-1] if captured else ""


def test_select_dir_button_uses_advanced_page_style(win, app):
    """信息管理「选择目录」的外观与高级页「选择目录」一致（明/暗两套）。"""
    from mdcx.controllers.main_window import style as style_mod

    _goto_nfo_lib(win, app)
    button = win.Ui.pushButton_nfo_lib_select_dir
    button.setStyleSheet("")

    style_mod.apply_nfo_lib_top_button_style(win, False)
    light = button.styleSheet()
    assert "QPushButton#pushButton_nfo_lib_select_dir" in light
    assert "QPushButton#pushButton_nfo_lib_refresh" in light, "刷新按钮未套用同款样式"
    for declaration in ("font-size:14px", "rgba(220, 220,220, 255)", "border-width:8px", "border-radius:20px"):
        assert declaration in light, f"浅色缺少 {declaration}"
    assert "QPushButton:hover#pushButton_nfo_lib_select_dir" in light
    assert "QPushButton:pressed#pushButton_nfo_lib_select_dir" in light
    # 选择器列表里每个都要带完整前缀，否则 :hover/:pressed 会退化成常态生效
    assert "QPushButton:hover#pushButton_nfo_lib_refresh" in light, "刷新按钮 hover 选择器缺少前缀"

    style_mod.apply_nfo_lib_top_button_style(win, True)
    dark = button.styleSheet()
    assert "rgba(220, 220,220, 50)" in dark, "暗色底色未生效"


def test_top_buttons_size_does_not_change(win, app):
    """套用样式不能改变顶栏「选择目录」「刷新」按钮的宽高，也不能挤动顶栏。"""
    from mdcx.controllers.main_window import style as style_mod

    _goto_nfo_lib(win, app)
    win.resize(1030, 700)
    win._sync_page_layouts()
    app.processEvents()

    ui = win.Ui
    bar = ui.nfo_lib_top_bar
    before = {
        "select_dir": ui.pushButton_nfo_lib_select_dir.size(),
        "refresh": ui.pushButton_nfo_lib_refresh.size(),
        "bar": bar.height(),
    }

    win.dark_mode = False
    style_mod.set_style(win)
    app.processEvents()
    assert ui.pushButton_nfo_lib_select_dir.size() == before["select_dir"]
    assert ui.pushButton_nfo_lib_refresh.size() == before["refresh"], "刷新按钮尺寸被改动"
    assert bar.height() == before["bar"]

    # 主题来回切换不能累积漂移
    win.dark_mode = True
    style_mod.set_dark_style(win)
    win.dark_mode = False
    style_mod.set_style(win)
    app.processEvents()
    assert ui.pushButton_nfo_lib_select_dir.size() == before["select_dir"]
    assert ui.pushButton_nfo_lib_refresh.size() == before["refresh"]
    assert bar.height() == before["bar"]


def test_top_buttons_look_alike(win, app):
    """「选择目录」与「刷新」渲染出的底色必须一致（防止 hover 规则退化成常态）。"""
    from mdcx.controllers.main_window import style as style_mod

    _goto_nfo_lib(win, app)
    win.resize(1030, 700)
    win._sync_page_layouts()
    app.processEvents()
    win.dark_mode = False
    style_mod.set_style(win)
    app.processEvents()

    ui = win.Ui
    select_img = ui.pushButton_nfo_lib_select_dir.grab().toImage()
    refresh_img = ui.pushButton_nfo_lib_refresh.grab().toImage()
    for y in (4, 8, 16, 24):
        assert select_img.pixelColor(4, y) == refresh_img.pixelColor(4, y), f"第 {y} 行底色不一致"


def test_save_buttons_fill_their_frame(win, app):
    """两个保存按钮宽度铺满所在边框（groupBox / 表单跨列区域）。"""
    _goto_nfo_lib(win, app)
    win.resize(1030, 700)
    win._sync_page_layouts()
    app.processEvents()

    ui = win.Ui
    batch = ui.pushButton_nfo_lib_batch_save
    assert batch.maximumWidth() >= batch.parentWidget().width(), "批量保存仍被宽度上限限制"
    assert batch.width() > batch.sizeHint().width(), "批量保存未铺满边框"

    save = ui.pushButton_nfo_lib_save
    assert save.maximumWidth() >= save.parentWidget().width(), "保存当前nfo文件仍被宽度上限限制"
    form = ui.formLayout_nfo_lib
    field = ui.lineEdit_nfo_lib_score
    # 跨列按钮与字段列共用同一宽度
    assert save.width() > field.width()
    assert save.width() <= form.contentsRect().width()


def test_crop_button_matches_batch_save_height(win, app):
    """「裁剪封面」与「批量保存」上下高度一致。"""
    _goto_nfo_lib(win, app)
    win.resize(1030, 700)
    win._sync_page_layouts()
    app.processEvents()

    batch = win.Ui.pushButton_nfo_lib_batch_save
    crop = win.Ui.pushButton_nfo_lib_crop
    assert crop.height() == batch.height(), f"裁剪封面高 {crop.height()} != 批量保存 {batch.height()}"


def test_crop_button_opens_cut_window(win, app, library):
    """点「裁剪封面」要真的弹出裁剪窗口（回归：曾把 Path 传成 str 导致静默异常）。"""
    ui = win.Ui
    ui.listWidget_nfo_lib.setCurrentRow(0)
    assert _wait_until(app, lambda: getattr(win, "_nfo_lib_current_path", None) is not None)

    win.pushButton_nfo_lib_crop_clicked()
    app.processEvents()
    assert win.cutwindow.isVisible(), "裁剪窗口没有弹出"
    assert win.cutwindow.show_image_path == library / "ABC-001-poster.jpg"


def test_crop_button_warns_when_no_selection(win, app, monkeypatch):
    """未选中 NFO 时点「裁剪封面」应给出提示，而不是静默失败。"""
    from mdcx.controllers.main_window import nfo_library as nfo_lib

    seen: list[str] = []

    def fake_warning(parent, title, text):
        seen.append(text)

    monkeypatch.setattr(nfo_lib.QMessageBox, "warning", staticmethod(fake_warning))
    monkeypatch.setattr(win, "_nfo_lib_current_path", None, raising=False)
    win.pushButton_nfo_lib_crop_clicked()
    assert seen, "未选中时没有给出提示"
    assert "NFO" in seen[0]
    """「裁剪封面」与「批量保存」上下高度一致。"""
    _goto_nfo_lib(win, app)
    win.resize(1030, 700)
    win._sync_page_layouts()
    app.processEvents()

    batch = win.Ui.pushButton_nfo_lib_batch_save
    crop = win.Ui.pushButton_nfo_lib_crop
    assert crop.height() == batch.height(), f"裁剪封面高 {crop.height()} != 批量保存 {batch.height()}"


def test_save_buttons_share_blue_save_style(win, app, monkeypatch):
    """「批量保存」「保存当前nfo文件」「裁剪封面」与软件设置主页面的保存按钮同款蓝底。"""
    from mdcx.controllers.main_window import style as style_mod

    selector = (
        "QPushButton#pushButton_save_config,#pushButton_nfo_lib_save,"
        "#pushButton_nfo_lib_batch_save,#pushButton_nfo_lib_crop{"
    )
    for dark in (False, True):
        win.dark_mode = dark
        apply = style_mod.set_dark_style if dark else style_mod.set_style
        sheet = _sheet_of(win, monkeypatch, apply)
        assert selector in sheet, f"{'暗色' if dark else '浅色'}样式表未包含两个保存按钮"
        block = sheet.split(selector, 1)[1].split("}", 1)[0]
        assert "color: white;" in block
        assert "background-color:#4C6EFF;" in block
