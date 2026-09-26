"""窗口状态矩阵回归测试：边框模式 x 窗口尺寸 x 日志展开收起 x 页面切换 x 最大化内容跟随。

回归背景（议题 #68）：QStackedWidget 只会把当前可见页 resize 到自身尺寸，
休眠页永远停留在设计尺寸 820x692。修复前 `_sync_page_layouts` 以 page.width()
为基准计算内部几何，"先缩放窗口再切页"时休眠页全部按陈旧尺寸布局——
日志页上栏只剩 480*0.61≈292 高、按钮飘出页面、工具页右侧被裁。

另修复：show_hide_logs 硬编码 resize(790, 418/689) 覆盖同步结果；
日志页/net 页按钮未跟随页面宽度；下栏隐藏时上栏仍只占 61%。
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
    # Geometry tests do not need the full QSS/resource loading path.
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    # 窗口构造后立即停表：几何测试不依赖定时器回调，
    # 保留运行中的 QTimer 会让 processEvents 触发网络/日志等无关副作用。
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto(win, app, page_name):
    for i in range(win.Ui.stackedWidget.count()):
        if win.Ui.stackedWidget.widget(i).objectName() == page_name:
            win.Ui.stackedWidget.setCurrentIndex(i)
            app.processEvents()
            return win.Ui.stackedWidget.widget(i)
    raise AssertionError(f"page not found: {page_name}")


def test_dormant_pages_resize_with_window(win, app):
    """核心回归：缩放窗口后所有休眠页必须获得新尺寸，而非停留在设计尺寸。"""
    win.resize(1032, 737)
    app.processEvents()
    stacked = win.Ui.stackedWidget
    for i in range(stacked.count()):
        page = stacked.widget(i)
        assert page.width() == stacked.width(), f"{page.objectName()} 未跟随 stackedWidget 宽度"
        assert page.height() == stacked.height(), f"{page.objectName()} 未跟随 stackedWidget 高度"


def test_resize_first_then_switch_log_page_layout(win, app):
    """先缩放再切日志页（报告人操作序列）：上栏 61%、下栏 39%、按钮右缘锚定。"""
    win.resize(1032, 737)
    app.processEvents()
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main
    lower = win.Ui.textBrowser_log_main_2
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)
    assert lower.isVisibleTo(page)
    assert lower.height() == pytest.approx(page.height() - upper.height() - 1, abs=2)
    assert lower.y() == upper.height() + 1
    # 按钮右缘距页面右缘约 22px（设计 822-800），且不出界
    btn = win.Ui.pushButton_start_cap2
    assert btn.geometry().right() <= page.width()
    assert page.width() - btn.geometry().right() <= 30


def test_log_lower_hidden_upper_fills_page(win, app):
    """收起下栏后上栏应铺满整页（而非仍占 61%），展开后恢复分栏。"""
    win.resize(1200, 900)
    app.processEvents()
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main

    win.show_hide_logs(False)
    app.processEvents()
    assert win.Ui.textBrowser_log_main_2.isHidden()
    assert upper.height() == pytest.approx(page.height(), abs=2)

    win.show_hide_logs(True)
    app.processEvents()
    assert win.Ui.textBrowser_log_main_2.isVisibleTo(page)
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)


def test_nav_gap_uniform_when_entries_hidden(win, app, monkeypatch):
    """议题 #74：原生边框下开启隐藏入口后，剩余导航按钮间隙必须一致且等于 spacing。

    根因：导航 layout 的固定高度容器没有底部 Expanding spacer，隐藏入口后多余
    空间被摊进可见按钮间隙（实测 8→22px）。修复：垂直布局末尾加 Expanding spacer
    吸收多余空间。本测试锁定隐藏后的间隙与整体结构。
    """
    from mdcx.config.enums import Switch
    from mdcx.controllers.main_window import main_window as mw_mod

    old = list(mw_mod.manager.config.switch_on)
    monkeypatch.setattr(mw_mod.manager.config, "window_title", "show")  # 原生边框
    monkeypatch.setattr(mw_mod.manager.config, "switch_on", [*old, Switch.HIDE_ACTOR_NAV, Switch.HIDE_NFO_NAV])
    win.load_config()
    win._windows_auto_adjust()
    win.show()
    app.processEvents()

    layout = win.Ui.verticalLayout
    assert win.Ui.pushButton_emby_manager_nav.isHidden()
    assert win.Ui.pushButton_nfo_library.isHidden()

    nav_buttons = [
        win.Ui.pushButton_main,
        win.Ui.pushButton_log,
        win.Ui.pushButton_tool,
        win.Ui.pushButton_emby_manager_nav,
        win.Ui.pushButton_nfo_library,
        win.Ui.pushButton_setting,
        win.Ui.pushButton_net,
        win.Ui.pushButton_about,
    ]
    visible = [b for b in nav_buttons if not b.isHidden()]
    assert len(visible) == 6

    from itertools import pairwise

    gaps = [b.y() - (a.y() + a.height()) for a, b in pairwise(visible)]
    assert all(g == layout.spacing() for g in gaps), f"导航间隙不等于 spacing: {gaps}"


def test_maximize_button_present(win):
    """议题 #69: 最大化按钮恢复（#67 曾按报告人要求用 WindowMaximizeButtonHint 屏蔽）。

    #62/#66/#68 的最大化布局错乱根因已修复（见本文件其余用例），
    禁用按钮只是绕过症状且与拖拽边缘缩放能力自相矛盾，应恢复按钮。
    """
    from PyQt6.QtCore import Qt

    assert win.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint


def test_maximized_window_layout_sync(win, app):
    """最大化路径整体回归：showMaximized 后所有休眠页与内部组件跟随新窗口尺寸。"""
    win.showMaximized()
    app.processEvents()
    stacked = win.Ui.stackedWidget
    for i in range(stacked.count()):
        page = stacked.widget(i)
        assert page.width() == stacked.width(), f"{page.objectName()} 最大化后未跟随宽度"
        assert page.height() == stacked.height(), f"{page.objectName()} 最大化后未跟随高度"
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)
    assert win.Ui.pushButton_start_cap2.geometry().right() <= page.width()


def test_stats_label_moves_to_success_row_when_maximized(win, app, monkeypatch):
    """最大化时「刮削中/成功/失败」统计标签左对齐到结果树「成功」列上方。

    诉求：软件界面最大化后，统计标签不要停右对齐到结果树右上角（与结果树首行
    「成功」错位），而是左对齐到结果树左缘、贴到「成功」列正上方；纵向与还原/
    最小化一致（始终贴住顶部分隔线下方，整组不下沉）。非最大化时保持设计位置
    （右缘锚定），界面不做任何改动（双向幂等）。
    """
    ui = win.Ui
    # 非最大化：右缘锚定的设计位置（label_result y=70、结果树/清空按钮 y=110）
    monkeypatch.setattr(win, "isMaximized", lambda: False)
    win._sync_page_layouts()
    main_w = ui.page_main.width()
    assert ui.label_result.y() == 70
    assert ui.treeWidget_number.y() == 110
    assert ui.pushButton_tree_clear.y() == 110
    assert ui.label_result.x() == max(main_w - 211 - 9, 300)

    # 最大化：统计标签左对齐到结果树左缘「成功」列上方；纵向仍贴顶部、不下沉
    monkeypatch.setattr(win, "isMaximized", lambda: True)
    win._sync_page_layouts()
    assert ui.label_result.y() == 70
    assert ui.treeWidget_number.y() == 110
    assert ui.pushButton_tree_clear.y() == 110
    assert ui.label_result.x() == ui.treeWidget_number.x()  # 左对齐到结果树「成功」列
    # 统计标签底边与结果树顶边相接（「成功」是结果树首行）
    assert ui.label_result.y() + ui.label_result.height() == ui.treeWidget_number.y()

    # 还原：回到右缘锚定的设计位置，与 fresh 非最大化状态一致
    monkeypatch.setattr(win, "isMaximized", lambda: False)
    win._sync_page_layouts()
    assert ui.label_result.y() == 70
    assert ui.treeWidget_number.y() == 110
    assert ui.pushButton_tree_clear.y() == 110
    assert ui.label_result.x() == max(main_w - 211 - 9, 300)


def test_nav_buttons_hide_switch(win, app):
    """议题 #71: 设置-高级「隐藏入口」开关控制导航按钮显隐（保存后 load_config 即时生效）。"""
    from mdcx.config.enums import Switch
    from mdcx.config.manager import manager

    actor_btn = win.Ui.pushButton_emby_manager_nav
    nfo_btn = win.Ui.pushButton_nfo_library
    assert not actor_btn.isHidden()
    assert not nfo_btn.isHidden()

    old_switch_on = list(manager.config.switch_on)
    try:
        manager.config.switch_on = [*old_switch_on, Switch.HIDE_ACTOR_NAV, Switch.HIDE_NFO_NAV]
        win.load_config()
        app.processEvents()
        assert actor_btn.isHidden()
        assert nfo_btn.isHidden()
        # 设置页复选框同步回写勾选状态
        assert win.Ui.checkBox_hide_actor_nav.isChecked()
        assert win.Ui.checkBox_hide_nfo_nav.isChecked()

        # 取消开关后入口恢复显示
        manager.config.switch_on = old_switch_on
        win.load_config()
        app.processEvents()
        assert not actor_btn.isHidden()
        assert not nfo_btn.isHidden()
        assert not win.Ui.checkBox_hide_actor_nav.isChecked()
    finally:
        manager.config.switch_on = old_switch_on


def test_setting_tabs_scrollareas_follow_window(win, app):
    """设置页 12 个 tab 的 scrollArea 跟随窗口（#66 回归，含休眠 tab）。"""
    win.resize(1400, 950)
    app.processEvents()
    _goto(win, app, "page_setting")
    tab_widget = win.Ui.tabWidget
    for i in range(tab_widget.count()):
        tab_page = tab_widget.widget(i)
        assert tab_page.width() == tab_widget.width(), f"tab{i} 页未跟随 tabWidget"
    from mdcx.views.CustomClass import CustomScrollArea

    for i in range(tab_widget.count()):
        tab_page = tab_widget.widget(i)
        scroll = tab_page.findChild(CustomScrollArea)
        if scroll is not None and scroll.parentWidget() == tab_page:
            assert scroll.width() == pytest.approx(tab_widget.width() - 4, abs=2), f"tab{i} scrollArea 宽未同步"
            assert scroll.height() == pytest.approx(tab_widget.height() - 24, abs=2), f"tab{i} scrollArea 高未同步"


@pytest.mark.parametrize("border", ["show", "hide"])
def test_layout_correct_under_both_border_modes(win, app, border):
    """原生边框与隐藏边框两种外观下，日志页几何规则一致（报告人未开隐藏边框）。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    mw_mod.manager.config.window_title = border
    win._windows_auto_adjust()
    app.processEvents()
    win.resize(1032, 737)
    app.processEvents()
    page = _goto(win, app, "page_log")
    upper = win.Ui.textBrowser_log_main
    assert upper.height() == pytest.approx(page.height() * 0.61, abs=2)
    assert win.Ui.pushButton_start_cap2.geometry().right() <= page.width()
    mw_mod.manager.config.window_title = "show"
    win._windows_auto_adjust()
    app.processEvents()


def _size(obj):
    return (obj.width(), obj.height())


def test_save_load_config_keeps_minimized_main_window(win, app, monkeypatch):
    """议题 #82：主窗最小化时，后台触发的配置保存/加载不得还原主窗。

    根因：save_config/load_config 末尾无条件
    `setWindowState(去最小化 | WindowActive)` + `activateWindow()`——Windows 原生
    边框下会强制还原最小化主窗。用户场景：主窗最小化跑刮削/操作演员管理器期间，
    任意自动保存把主窗弹出。修复：仅在主窗可见且未最小化时才恢复激活。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    # dummy manager 无 save 桩——本测试只验证窗口状态行为，配置落盘打桩跳过
    monkeypatch.setattr(mw_mod.manager, "save", lambda *a, **k: None, raising=False)

    win.show()
    app.processEvents()
    win.showMinimized()
    app.processEvents()
    assert win.isMinimized()

    win.save_config()
    app.processEvents()
    assert win.isMinimized(), "save_config 不应还原最小化主窗"

    win.load_config()
    app.processEvents()
    assert win.isMinimized(), "load_config 不应还原最小化主窗"


def test_maximize_content_follow_all_pages(win, app):
    """横向放大复现：窗口从设计尺寸放大到 1920 宽（等价 Windows 原生最大化）。"""

    from mdcx.views.CustomClass import CustomScrollArea

    # 1. 正常显示（设计尺寸）
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    tool_scroll = win.Ui.page_tool.findChild(CustomScrollArea)
    setting_tab = win.Ui.tabWidget
    before_tool = _size(tool_scroll)
    before_setting = _size(setting_tab)
    before_main_page = _size(win.Ui.page_main)
    before_tree = _size(win.Ui.treeWidget_number)
    before_file_path = _size(win.Ui.label_file_path)

    # 2. 放大到 1920x1040（Windows 真机最大化等效）
    win.resize(1920, 1040)
    app.processEvents()

    print(f"window     : {win.width()}x{win.height()}")
    print(f"stacked    : {win.Ui.stackedWidget.width()}x{win.Ui.stackedWidget.height()}")
    print(f"page_main  : {before_main_page} -> {_size(win.Ui.page_main)}")
    print(f"tool_scroll: {before_tool} -> {_size(tool_scroll)}")
    print(f"setting_tab: {before_setting} -> {_size(setting_tab)}")
    print(f"main_tree  : {before_tree} -> {_size(win.Ui.treeWidget_number)}")
    print(f"file_path  : {before_file_path} -> {_size(win.Ui.label_file_path)}")

    # 页面本身跟随
    assert win.Ui.page_main.width() == win.Ui.stackedWidget.width(), "page_main 未跟随 stackedWidget"
    assert win.Ui.page_tool.width() == win.Ui.stackedWidget.width(), "page_tool 未跟随 stackedWidget"
    assert win.Ui.page_setting.width() == win.Ui.stackedWidget.width(), "page_setting 未跟随 stackedWidget"

    # 软件界面（初始可见页）：内部内容横向跟随
    assert win.Ui.treeWidget_number.geometry().right() == pytest.approx(win.Ui.page_main.width() - 18, abs=6), (
        f"软件界面结果树未锚定右缘: right={win.Ui.treeWidget_number.geometry().right()}"
    )
    assert win.Ui.label_file_path.width() == pytest.approx(win.Ui.page_main.width() - 34, abs=6), (
        f"软件界面文件路径标签未拉伸: {win.Ui.label_file_path.width()}"
    )
    # 议题 #173: 结果树宽随 cover_scale 拉伸贴向缩略图右缘, 最大化时左缘到缩略图右缘
    # 的 gap 应收窄(不再像固定 202 宽那样离缩略图 280px), 右缘仍贴页面右 18px。
    tree = win.Ui.treeWidget_number
    cover_scale = win.Ui.page_main.width() / 820
    thumb_right = int(580 * cover_scale)
    tree_gap_l = tree.x() - thumb_right
    assert tree_gap_l <= 80, f"结果树左缘到缩略图右缘 gap 未收窄: {tree_gap_l}px"
    # 工具/设置页为休眠页：容器几何即时跟随即可（content 拉伸在切页 show 时验证，
    # 见 test_switch_to_pages_after_maximize_content_visible）
    assert tool_scroll.width() == pytest.approx(win.Ui.page_tool.width() - 40, abs=4), (
        f"工具页 scrollArea 宽未跟随: {tool_scroll.width()} != {win.Ui.page_tool.width() - 40}"
    )
    assert setting_tab.width() == pytest.approx(win.Ui.page_setting.width() - 40, abs=4), (
        f"设置页 tabWidget 宽未跟随: {setting_tab.width()} != {win.Ui.page_setting.width() - 40}"
    )


def test_setting_config_bar_docked_to_bottom(win, app):
    """设置页底部配置操作浮框（当前配置/另存为/恢复默认/保存）跟随贴底 + 保存按钮右缘锚定."""

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    setting_page = _goto(win, app, "page_setting")
    page_h = setting_page.height()

    win.resize(1920, 1040)
    app.processEvents()
    page_h = setting_page.height()

    # 整组控件贴新底部（设计基线距底 692-630=62，允许 DPI 误差）
    for btn, name in (
        (win.Ui.pushButton_save_new_config, "另存为"),
        (win.Ui.pushButton_init_config, "恢复默认"),
        (win.Ui.pushButton_save_config, "保存"),
    ):
        dock = page_h - btn.y()
        assert 55 <= dock <= 75, f"{name} 未贴底: 距底 {dock}（页高 {page_h}）"

    # 保存按钮右缘锚定（设计右距 820-731=89）
    right_gap = setting_page.width() - (win.Ui.pushButton_save_config.x() + win.Ui.pushButton_save_config.width())
    assert 80 <= right_gap <= 100, f"保存按钮右缘未锚定: 右距 {right_gap}"

    # 背景 label 拉伸贴宽
    assert win.Ui.label_config.width() >= setting_page.width() - 30, (
        f"配置浮框背景未拉伸: {win.Ui.label_config.width()} / {setting_page.width()}"
    )


def test_setting_form_inputs_stretch_with_viewport(win, app):
    """设置页表单输入控件随视口拉宽（gridLayout 重排，修复"表单缩在左侧"）."""

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    _goto(win, app, "page_setting")
    # 切到刮削目录 tab（tab0），取其中行编辑框
    from PyQt6.QtWidgets import QLineEdit

    tab0 = win.Ui.tabWidget.widget(0)
    edits = tab0.findChildren(QLineEdit)
    assert edits, "刮削目录 tab 无输入框"
    before = max(e.width() for e in edits)

    win.resize(1920, 1040)
    app.processEvents()

    after = max(e.width() for e in edits)
    print(f"form edit width: {before} -> {after}")
    assert after > before + 100, f"表单输入框未随视口拉宽: {before} -> {after}"


def test_scroll_content_follow_viewport(win, app):
    """工具页 scrollArea 内部内容跟随视口宽（切页显示后验证，对齐用户观察路径）."""

    from mdcx.views.CustomClass import CustomScrollArea

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    tool_page = _goto(win, app, "page_tool")
    tool_scroll = tool_page.findChild(CustomScrollArea)
    content = tool_scroll.widget()
    before_content_w = content.width()

    win.resize(1920, 1040)
    app.processEvents()

    # 视口放大后（页面保持可见），widgetResizable 应把内容拉到视口宽
    after_content_w = content.width()
    print(f"before: viewport={tool_scroll.width()} content={before_content_w}")
    print(f"after : viewport={tool_scroll.width()} content={after_content_w}")
    assert after_content_w > before_content_w, (
        f"工具页 scrollArea 内容宽未跟随视口: {before_content_w} -> {after_content_w}"
    )

    # 宽幅 groupBox 跟随拉伸（sync_wide_children_width，设计基准从 setWidget 登记取）
    design_w = getattr(content, "_wide_children_design_width", 0)
    extra = tool_scroll.viewport().width() - design_w
    from PyQt6.QtWidgets import QGroupBox

    wide_groups = [g for g in content.findChildren(QGroupBox) if g.parentWidget() is content and g.width() > 400]
    print(f"groupBox widths: {[(g.objectName(), g.width()) for g in wide_groups[:4]]}")
    for g in wide_groups:
        assert g.width() >= 700 + extra - 4, f"宽幅容器 {g.objectName()} 未跟随拉伸: {g.width()} (extra={extra})"


def test_probe_main_tool_content(win, app):
    """软件界面/软件工具页内容随视口拉宽（与设置页同款自适应）。"""

    from PyQt6.QtWidgets import QLineEdit

    win.resize(1040, 760)
    win.show()
    app.processEvents()

    tool_page = _goto(win, app, "page_tool")
    before_edit = max((e.width() for e in tool_page.findChildren(QLineEdit)), default=0)
    before_outline = win.Ui.label_outline.width()
    before_series_x = win.Ui.label_series.x()

    win.resize(1920, 1040)
    app.processEvents()

    # 软件工具页：输入框跟随拉宽
    after_edit = max((e.width() for e in tool_page.findChildren(QLineEdit)), default=0)
    print(f"tool_lineEdit : {before_edit} -> {after_edit}")
    print(f"main_outline  : {before_outline} -> {win.Ui.label_outline.width()}")
    print(f"series_x      : {before_series_x} -> {win.Ui.label_series.x()}")
    assert after_edit > before_edit + 200, f"工具页输入框未随视口拉宽: {before_edit} -> {after_edit}"

    # 软件界面：#135 信息区保持设计左列（与「番号/标题/封面」对齐），按封面增高下移；
    # #141 下划线/值列按 ×scale 等比例加长，右列下划线延伸到缩略图右缘。
    cover_scale = win.Ui.page_main.width() / 820
    cover_bottom = int(160 + 220 * cover_scale)
    info_delta = cover_bottom - 380
    thumb_right = int(580 * cover_scale)
    tree_x = win.Ui.treeWidget_number.x()
    assert win.Ui.label_outline.x() == 70, "简介左缘应保持设计 x=70（与左上角对齐）"
    assert win.Ui.label_outline.x() + win.Ui.label_outline.width() == thumb_right, "简介下划线右缘应延伸到缩略图右缘"
    assert win.Ui.label_series.x() == int(350 * cover_scale), "右列应随 ×scale 右移"
    assert win.Ui.label_series.x() + win.Ui.label_series.width() == thumb_right, "右列下划线右缘应延伸到缩略图右缘"
    # 信息区首行下移到封面框下方（不被放大后的黑框盖住）
    assert win.Ui.label_outline.y() == pytest.approx(430 + info_delta, abs=2), "信息区未按封面增高下移"
    assert win.Ui.label_outline.y() >= cover_bottom, "信息区首行仍在封面框内（#135 未修复）"
    # 上区受右侧按钮限制的拉伸右界
    assert win.Ui.label_number.geometry().right() == pytest.approx(min(450, tree_x - 30), abs=4)

    # 幂等性：还原-再放大后，几何与直接放大结果一致（固定公式基准，无累积漂移）
    win.resize(1040, 760)
    app.processEvents()
    win.resize(1920, 1040)
    app.processEvents()
    # #135/#141 固定公式：左列 x 恒为设计值，右列 x 与下划线右缘由 ×scale 决定
    assert win.Ui.label_series.x() == int(350 * cover_scale), "右列 x 漂移"
    assert win.Ui.label_outline.x() == 70, "简介 x 漂移"
    assert win.Ui.label_outline.x() + win.Ui.label_outline.width() == thumb_right, "简介右缘漂移"
    assert win.Ui.label_outline.y() == pytest.approx(430 + info_delta, abs=2), "信息区 y 漂移"
    assert after_edit == max((e.width() for e in tool_page.findChildren(QLineEdit)), default=0), "工具页输入框宽漂移"


def test_runtime_row_follows_right_column_on_maximize(win, app):
    """议题 #82：最大化后「时长」行（右列 y=530）必须随右列平移。

    根因：_sync_page_layouts 下半区右列平移清单漏了 label_22（时长：标签,
    设计 x=310）与 label_runtime（时长值, 设计 x=350）——系列/发行平移后，
    时长行滞留原位，与左列日期行重叠错位。
    """
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    win.resize(1920, 1040)
    app.processEvents()

    # #141：右列随 ×scale 右移（label_22=310×scale，label_runtime=350×scale），
    # 时长行 y 与日期行（y=530）一致地下移。#154 撤销 #152 的行高增长：简介/标签
    # 恒定 40px，其下各行只随封面增高量 info_delta 下移，故 info_grow == info_delta。
    cover_scale = win.Ui.page_main.width() / 820
    info_delta = int(160 + 220 * cover_scale) - 380
    info_grow = info_delta
    assert win.Ui.label_22.x() == int(310 * cover_scale), f"时长标签 x 漂移: {win.Ui.label_22.x()}"
    assert win.Ui.label_runtime.x() == int(350 * cover_scale), f"时长值 x 漂移: {win.Ui.label_runtime.x()}"
    assert win.Ui.label_22.y() == pytest.approx(530 + info_grow, abs=2), (
        f"时长标签未随信息区下移: {win.Ui.label_22.y()} != {530 + info_grow}"
    )


def test_switch_to_pages_after_maximize_content_visible(win, app):
    """最大化后切到三个页面，内容尺寸正确（复现用户切页观察）."""

    win.resize(1040, 760)
    win.show()
    app.processEvents()
    win.resize(1920, 1040)
    app.processEvents()

    from mdcx.views.CustomClass import CustomScrollArea

    # 软件工具页
    tool_page = _goto(win, app, "page_tool")
    tool_scroll = tool_page.findChild(CustomScrollArea)
    assert tool_scroll.width() > 700, f"工具页内容未跟随: {tool_scroll.width()}"
    assert tool_scroll.width() == pytest.approx(tool_page.width() - 40, abs=4)
    tool_content = tool_scroll.widget()
    print(f"tool: viewport={tool_scroll.width()} content={tool_content.width()}")
    # 内容必须跟随视口拉宽（用户症状：内容停在 782/860 不放大）
    assert tool_content.width() >= tool_scroll.width() - 30, (
        f"工具页 scrollArea 内容未拉伸: content={tool_content.width()} viewport={tool_scroll.width()}"
    )

    # 软件设置页
    setting_page = _goto(win, app, "page_setting")
    assert win.Ui.tabWidget.width() > 700, f"设置页 tabWidget 未跟随: {win.Ui.tabWidget.width()}"
    assert win.Ui.tabWidget.width() == pytest.approx(setting_page.width() - 40, abs=4)
    # 当前 tab 的 scrollArea 内容同样必须拉伸
    current_tab = win.Ui.tabWidget.currentWidget()
    tab_scroll = current_tab.findChild(CustomScrollArea)
    if tab_scroll is not None and tab_scroll.parentWidget() == current_tab:
        tab_content = tab_scroll.widget()
        print(f"set: viewport={tab_scroll.width()} content={tab_content.width()}")
        assert tab_content.width() >= tab_scroll.width() - 30, (
            f"设置页内容未拉伸: content={tab_content.width()} viewport={tab_scroll.width()}"
        )


def test_nfo_lib_layout_probe(win, app):
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    page = _goto(win, app, "page_nfo_library")
    top = win.Ui.nfo_lib_top_bar
    content = win.Ui.nfo_lib_content
    print(
        f"before: page={page.width()}x{page.height()} top={top.height()} content={content.width()}x{content.height()}"
    )

    win.resize(1920, 1040)
    app.processEvents()
    print(
        f"after : page={page.width()}x{page.height()} top={top.height()} content={content.width()}x{content.height()}"
    )
    print(
        f"gap right={page.width() - (content.x() + content.width())} bottom={page.height() - (content.y() + content.height())}"
    )

    # 嵌套子布局激活验证：page → content → scrollArea → formLayout
    form_scroll = win.Ui.scrollArea_nfo_lib_form
    form_content = win.Ui.scrollAreaWidgetContents_nfo_lib
    form_layout = form_content.layout()
    print(f"form scroll viewport={form_scroll.viewport().width()} content={form_content.width()}")
    if form_layout is not None:
        print(f"form layout active={form_layout.isEnabled()} activated={form_layout.isEmpty()}")

    # 断言内容宽度跟随视口（消除右侧 194px 空白）
    assert form_content.width() >= form_scroll.viewport().width() - 20, (
        f"表单内容未跟随视口: content={form_content.width()} viewport={form_scroll.viewport().width()}"
    )

    # 保存按钮可见性：最大化后表单内容压缩简介/标签面积（议题 #78 用户建议），
    # 保存按钮必须落在滚动视口内、无需滚动即可见
    save_btn = win.Ui.pushButton_nfo_lib_save
    print(f"save btn: y={save_btn.y()} h={save_btn.height()} visible={save_btn.isVisible()}")
    print(f"form content height={form_content.height()} viewport height={form_scroll.viewport().height()}")
    # 简介/标签面积压缩（60px 固定，消除下拉栏）
    outline_h = win.Ui.plainTextEdit_nfo_lib_outline.height()
    tag_h = win.Ui.plainTextEdit_nfo_lib_tag.height()
    print(f"outline h={outline_h} tag h={tag_h}")
    assert outline_h == 60, f"简介未压到 60: {outline_h}"
    assert tag_h == 60, f"标签未压到 60: {tag_h}"
    # 保存按钮必须在视口内（无滚动可见），留 4px 安全边距应对平台差异
    save_bottom = save_btn.y() + save_btn.height()
    assert save_bottom <= form_scroll.viewport().height() - 4, (
        f"保存按钮仍被推视口: bottom={save_bottom} viewport={form_scroll.viewport().height()}"
    )
    # 内容总高不显著超过视口（缩列下拉栏消除——用户报告"下拉栏"现象）
    assert form_content.height() <= form_scroll.viewport().height() + 40, (
        f"表单总高超视口: content={form_content.height()} viewport={form_scroll.viewport().height()}"
    )


def test_nfo_lib_form_compact_and_no_clip_when_small(win, app):
    """议题 #117：小窗时输入框右缘不被裁、无垂直滚动条、保存按钮免滚动可见。

    用户截图（1032x737，Windows）：表单列内容宽顶在 QFormLayout 首选宽 301，
    垂直滚动条一出现就占掉 14px 视口宽 → 内容右缘被裁 9px，输入框左侧圆角正常、
    右侧被裁成平口；同时「保存当前 NFO」在视口外，必须下拉才见。
    修复三点：
    1. layout 驱动内容的宽度下限改用布局硬最小值——视口窄于首选宽时内容跟随视口；
    2. 该页内容底部余量收紧为 8px（默认 72 是给设置页底部浮框带避让用的，
       信息管理页没有浮框，白占一行多高度凭空顶出滚动条）；
    3. 视口仍放不下整表时，按缺口压缩简介/标签两个多行框（60 → 最低 40）。
    """
    form_scroll = win.Ui.scrollArea_nfo_lib_form
    form_content = win.Ui.scrollAreaWidgetContents_nfo_lib
    outline = win.Ui.plainTextEdit_nfo_lib_outline
    tag = win.Ui.plainTextEdit_nfo_lib_tag
    save_btn = win.Ui.pushButton_nfo_lib_save

    def probe():
        app.processEvents()
        viewport = form_scroll.viewport()
        return {
            "clip": form_content.width() - viewport.width(),
            "scroll": form_scroll.verticalScrollBar().maximum(),
            "outline_h": outline.height(),
            "tag_h": tag.height(),
            "save_hidden": save_btn.y() + save_btn.height() > viewport.height(),
        }

    # 常规小窗：整表放得下 → 保持设计高度 60（最大化布局不变），无滚动条
    win.resize(1032, 737)
    win.show()
    _goto(win, app, "page_nfo_library")
    at_small = probe()
    assert at_small["clip"] <= 0, f"输入框右缘被视口裁剪: {at_small['clip']}px"
    assert at_small["scroll"] == 0, f"小窗仍出现垂直滚动条: range={at_small['scroll']}"
    assert not at_small["save_hidden"], "保存按钮被推出视口"
    assert at_small["outline_h"] == 60 and at_small["tag_h"] == 60, "放得下时简介/标签应保持设计高"

    # 更矮的窗口：压缩简介/标签换取免滚动可见，且不得出现横向裁剪
    # 该高度在生产最小高（动态 ≥450）之下，属表单压缩用例，与最小尺寸策略解耦
    win.setMinimumSize(0, 0)
    win.resize(1032, 560)
    at_tiny = probe()
    assert at_tiny["clip"] <= 0, f"压缩后输入框右缘被裁剪: {at_tiny['clip']}px"
    assert at_tiny["scroll"] == 0, f"压缩后仍有垂直滚动条: range={at_tiny['scroll']}"
    assert not at_tiny["save_hidden"], "压缩后保存按钮仍被推出视口"
    assert at_tiny["outline_h"] < 60, f"视口放不下时简介未压缩: {at_tiny['outline_h']}"
    assert at_tiny["outline_h"] >= 40, f"压缩低于可读下限: {at_tiny['outline_h']}"
    assert at_tiny["outline_h"] == at_tiny["tag_h"], "简介/标签压缩幅度应一致"

    # 回到放大尺寸：必须自动恢复设计高（幂等，不依赖当前值）
    win.resize(1920, 1080)
    at_max = probe()
    assert at_max["outline_h"] == 60 and at_max["tag_h"] == 60, (
        f"最大化后简介/标签未恢复设计高: {at_max['outline_h']}/{at_max['tag_h']}"
    )
    assert at_max["clip"] <= 0, f"最大化后输入框右缘被裁剪: {at_max['clip']}px"


def test_scrollareas_restore_compact_after_maximize(win, app):
    """议题 #82：最大化→还原后，各页 scrollArea 内容几何必须回落紧凑基线。

    根因三层叠加：
    1. sync_wide_children_width 只增不减（extra<=0 直接 return），最大化拉宽的
       宽幅容器还原时不缩回；
    2. content.minimumWidth 从「拉宽后的」childrenRect 计算并锁死，widgetResizable
       受 minimumWidth 阻挡无法把内容缩回视口——设置/工具页内容右缘被裁剪；
    3. layout 驱动内容（NFO 表单 QFormLayout）的 minimumHeight 从膨胀
       childrenRect 计算：Expanding 行（简介/标签多行框）在超高容器中分得额外
       空间，childrenRect 抬高 → 最小高自锁（993 降不回紧凑 674），保存按钮
       被推出视口。
    修复：宽幅容器按「设计几何+extra」双向幂等伸缩；min_width 以设计宽为上界；
    layout 驱动内容的 min 尺寸改用 layout.sizeHint（紧凑排布，与容器拉伸无关）。
    """
    from mdcx.views.CustomClass import CustomScrollArea

    win.resize(1040, 760)
    win.show()
    app.processEvents()
    _goto(win, app, "page_nfo_library")

    # 最大化 → 还原
    win.resize(1920, 1040)
    app.processEvents()
    win.resize(1040, 760)
    app.processEvents()

    # 设置页当前 tab：内容宽度回落视口内，min 宽不再锁死在最大化值（1599）
    _goto(win, app, "page_setting")
    tab0 = win.Ui.tabWidget.widget(0)
    scroll = tab0.findChild(CustomScrollArea)
    assert scroll.widget().width() <= scroll.viewport().width() + 2, (
        f"设置页内容宽未回落: content={scroll.widget().width()} viewport={scroll.viewport().width()}"
    )
    assert scroll.widget().minimumWidth() <= 800, f"设置页内容 min 宽锁死: {scroll.widget().minimumWidth()}"

    # 工具页：同上（曾锁死 1603）
    _goto(win, app, "page_tool")
    tool_scroll = win.Ui.page_tool.findChild(CustomScrollArea)
    assert tool_scroll.widget().width() <= tool_scroll.viewport().width() + 2, (
        f"工具页内容宽未回落: content={tool_scroll.widget().width()} viewport={tool_scroll.viewport().width()}"
    )
    assert tool_scroll.widget().minimumWidth() <= 800, f"工具页内容 min 宽锁死: {tool_scroll.widget().minimumWidth()}"

    # NFO 表单：内容回落紧凑、保存按钮回到视口内（曾 y=946 > 视口 674）
    _goto(win, app, "page_nfo_library")
    app.processEvents()
    form_scroll = win.Ui.scrollArea_nfo_lib_form
    form_content = win.Ui.scrollAreaWidgetContents_nfo_lib
    assert form_content.height() <= 760, f"NFO 表单未回落紧凑: {form_content.height()}"
    save_btn = win.Ui.pushButton_nfo_lib_save
    assert save_btn.y() + save_btn.height() <= form_scroll.viewport().height() + 4, (
        f"NFO 保存按钮仍在视口外: bottom={save_btn.y() + save_btn.height()} viewport={form_scroll.viewport().height()}"
    )


def test_setting_all_tabs_wide_boxes_fill_viewport(win, app):
    """最大化后 12 个设置 tab 的全部宽幅顶层 groupBox 必须拉伸到位。

    回归背景：.ui 中 34 处 groupBox 带 maximumWidth=860 设计器遗留上限，
    sync_wide_children_width 的 setGeometry 被上限夹断——同一页面内部分
    groupBox 拉满（如刮削模式的"多线程刮削"）、部分停在 860（如"刮削模式"
    框），内容右侧大面积留白。刮削目录页无上限、拉伸正常（用户确认基准）。
    """
    from mdcx.views.CustomClass import CustomScrollArea

    _goto(win, app, "page_setting")
    win.resize(1920, 1170)
    win.show()
    app.processEvents()

    ui = win.Ui
    checked = 0
    for i in range(ui.tabWidget.count()):
        ui.tabWidget.setCurrentIndex(i)
        app.processEvents()
        page = ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea)
        content = area.widget()
        registry = getattr(content, "_wide_children_design", None)
        if not registry:
            continue
        design_w = getattr(content, "_wide_children_design_width", 0)
        extra = area.viewport().width() - design_w
        for entry in registry:
            box = entry.widget
            _, _, design_box_w, _ = entry.geometry
            expected = design_box_w + extra
            assert box.width() == expected, (
                f"tab{i}({ui.tabWidget.tabText(i)}) {box.objectName()} 拉伸被夹断: "
                f"w={box.width()} 期望={expected}（maximumWidth={box.maximumWidth()}）"
            )
            checked += 1
    assert checked >= 30, f"宽幅容器登记异常地少: {checked}"


def test_setting_config_bar_all_children_docked(win, app):
    """浮框组全部子件（含「当前配置:」label_241）必须位于底部浮框带内。

    回归背景：_sync_page_layouts 浮框段漏同步 label_241，最大化后它停在
    设计位置 y=629，与下移到页底的浮框带脱离、悬在滚动内容中部。
    """
    _goto(win, app, "page_setting")
    win.resize(1920, 1170)
    win.show()
    app.processEvents()

    ui = win.Ui
    bar = ui.label_config
    for name in (
        "label_241",
        "comboBox_change_config",
        "pushButton_save_new_config",
        "pushButton_init_config",
        "pushButton_save_config",
    ):
        w = getattr(ui, name)
        assert bar.y() <= w.y() < bar.y() + bar.height(), (
            f"{name} 脱离浮框带: y={w.y()} 带范围=[{bar.y()},{bar.y() + bar.height()})"
        )


def test_setting_content_clears_config_bar_when_scrolled(win, app):
    """滚动到底时设置页末行必须位于浮框带上方。

    浮框带（label_config）盖住滚动视口底部 intrusion px；内容最小高必须
    含 ≥ intrusion 的底部余量，否则最后一行文字从浮框后透出（用户截图）。
    layout 驱动内容（NFO 表单）此前 sizeHint 不加余量同样受影响。
    """
    from mdcx.views.CustomClass import CustomScrollArea

    _goto(win, app, "page_setting")
    win.resize(1920, 1170)
    win.show()
    app.processEvents()

    ui = win.Ui
    intrusion = (
        ui.tabWidget.widget(0)
        .findChild(CustomScrollArea)
        .mapTo(ui.page_setting, ui.tabWidget.widget(0).findChild(CustomScrollArea).viewport().rect().bottomLeft())
        .y()
        - ui.label_config.y()
    )
    margin = CustomScrollArea._CONTENT_BOTTOM_MARGIN
    assert margin > intrusion, f"内容底部余量 {margin} 不足以避开浮框侵入 {intrusion}"

    # layout 驱动页（NFO）：min 高 = sizeHint + 余量
    for i in range(ui.tabWidget.count()):
        page = ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea)
        content = area.widget()
        if content.layout() is None:
            continue
        ui.tabWidget.setCurrentIndex(i)
        app.processEvents()
        hint_h = content.layout().sizeHint().height()
        assert content.minimumHeight() == hint_h + margin, (
            f"tab{i}({ui.tabWidget.tabText(i)}) layout 内容 min 高缺底部余量: "
            f"{content.minimumHeight()} != {hint_h}+{margin}"
        )


def test_left_status_badges_follow_window_bottom(win, app):
    """议题 #86/#102：左侧状态区随窗口底边同步，并预留 40px 底距（#102 用户反馈贴底太靠下）。

    回归背景：label_show_version/label_local_number 固定在设计 y 坐标，
    窗口最大化后留在上半区，与侧栏贴底的「正常模式」字段分离，
    视觉上像状态条移位（用户图 3 红框标注「不正常应该下移」）。
    窗口 1920x1170 时 label_show_version 应移至 y≈929（1170-201-40），
    label_local_number 移至 y≈1109（1170-21-40）。
    """
    _goto(win, app, "page_main")
    win.resize(1920, 1170)
    win.show()
    app.processEvents()

    assert win.Ui.label_show_version.y() == 929, (
        f"label_show_version 未贴底预留 40px: y={win.Ui.label_show_version.y()}"
    )
    assert win.Ui.label_local_number.y() == 1109, (
        f"label_local_number 未贴底预留 40px: y={win.Ui.label_local_number.y()}"
    )


def test_left_status_badges_fully_visible_in_short_window(win, app):
    """矮窗口（<730）下左侧状态区不得被窗底裁掉。

    回归背景：贴底公式 max(height-241, 489) 的 489 下限只防"高于设计位置"，
    窗口高 <730 时 label 底边=690 超出窗口高度，底对齐文字的末行
    （config.json/MDCx 版本号）被父 widget 裁剪——用户反馈「config.json
    以下信息被截断」。修复后：label 底边必须 ≤ 窗口高度（完整落在窗口内）。
    公式守卫应在任意高度成立（含生产最小高之下），故先放开动态最小尺寸。
    """
    _goto(win, app, "page_main")
    win.setMinimumSize(0, 0)
    for h in (700, 680, 650, 550):
        win.resize(1089, h)
        win.show()
        app.processEvents()
        for label, label_h in (
            (win.Ui.label_show_version, 201),
            (win.Ui.label_local_number, 21),
        ):
            bottom = label.y() + label_h
            assert bottom <= win.height(), f"窗口高 {h} 时 {label.objectName()} 底边 {bottom} 超出窗口，末行被裁"


def test_adaptive_window_sizes_matrix():
    """_adaptive_window_sizes 纯函数：常见屏幕档位的 (min_w, min_h, def_w, def_h)。"""
    from mdcx.controllers.main_window.init import _adaptive_window_sizes

    # 1080p 无缩放（可用 1920x1040）：回到设计值，主页面内容完整
    assert _adaptive_window_sizes(1920, 1040) == (850, 650, 1030, 700)
    # 1080p 125% 缩放（逻辑 1536x864）：92ef2437 的原始诉求——不锁死 700，仍可缩到 648
    assert _adaptive_window_sizes(1536, 864) == (850, 648, 1030, 700)
    # 小屏（1024x600 可用）：默认/最小均按比例收，首启不占满
    assert _adaptive_window_sizes(1024, 600) == (614, 450, 921, 510)
    # 超小屏下限钳制：不得低于 400x300
    assert _adaptive_window_sizes(500, 350) == (400, 300, 450, 300)


def test_main_window_applies_adaptive_sizes(win, app):
    """集成：min 尺寸在构造时按屏应用；默认尺寸在首次 showEvent 按屏自适应。

    默认尺寸只允许 showEvent 应用——Init_Ui 阶段 resize 会崩 Windows 测试收尾
    （诊断 PR #185），此处同时锁定该时序：show 前不得已被自适应 resize 过。
    """
    from PyQt6.QtWidgets import QApplication

    from mdcx.controllers.main_window.init import _adaptive_window_sizes

    screen = QApplication.primaryScreen()
    assert screen is not None, "前置失败：offscreen 平台应有虚拟屏"
    avail = screen.availableGeometry()
    min_w, min_h, def_w, def_h = _adaptive_window_sizes(avail.width(), avail.height())
    assert win.minimumWidth() == min_w, f"最小宽未自适应: {win.minimumWidth()} != {min_w}"
    assert win.minimumHeight() == min_h, f"最小高未自适应: {win.minimumHeight()} != {min_h}"
    win.show()
    app.processEvents()
    assert (win.width(), win.height()) == (def_w, def_h), (
        f"首次显示未按屏自适应: {win.width()}x{win.height()} != {def_w}x{def_h}"
    )


# ============ 议题 #102：四项 UI 交互模拟验证 ============


def test_minimized_main_not_popped_on_app_activate(win, app):
    """议题 #102-①：主窗最小化后，应用激活事件（Emby 演员管理器任意操作/切任务
    让 app 重新激活）不得把主窗弹出前台。

    回归背景：eventFilter 的 ApplicationActivate 分支对隐藏/最小化主窗无条件
    show()，点 Emby 对话框即触发、主窗被拉出（用户截图「任何操作都弹主窗」）。
    修法：最小化时维持状态不动；仅非最小化的隐藏态保留 show()。

    模拟方式：eventFilter 挂载在 textBrowser_log_main 的 viewport 上
    （init.py:224-225），用 QApplication.sendEvent 向该 viewport 投递
    ApplicationActivate 事件，驱动真实守卫路径。
    """
    from PyQt6.QtCore import QEvent

    win.show()
    app.processEvents()

    # 最小化主窗（模拟用户最小化后去操作 Emby 管理器）
    win.showMinimized()
    app.processEvents()
    assert win.isMinimized(), "前置失败：主窗未最小化"

    viewport = win.Ui.textBrowser_log_main.viewport()
    activate = QEvent(QEvent.Type.ApplicationActivate)
    app.sendEvent(viewport, activate)
    app.processEvents()

    # 守卫生效：最小化状态维持，未被 showNormal/弹出。
    # 注：Qt 语义下 isVisible() 在最小化态恒为 True（含 minimized），不能据此判"被弹出"；
    # 正确判据是 isMinimized() 仍为 True（show() 会把它转成非最小化的可见态并弹出）。
    assert win.isMinimized(), "最小化主窗被 ApplicationActivate 弹出（状态脱离 minimized）"


def test_hidden_non_minimized_main_not_shown_on_app_activate(win, app):
    """议题 #132：主窗隐藏（托盘图标隐藏 / 关闭到托盘 / 最小化到托盘）后，应用激活
    事件（操作 Emby 演员管理器等工具会触发）不得把隐藏的主窗弹出前台。

    回归背景：议题 #102 曾保留「非最小化隐藏态」的 show()（当时认为隐藏态需要被
    恢复），但 #132 实测反馈：仅用托盘图标隐藏主窗后，对演员管理器做任何操作仍会
    把主窗弹出；要先最小化再隐藏才不弹。根因即此分支对非最小化隐藏态调用 show()。
    修复：隐藏是用户主动行为，恢复只由托盘图标/菜单触发，ApplicationActivate 不再
    自动 show()。
    """
    from PyQt6.QtCore import QEvent

    win.show()
    app.processEvents()
    win.hide()
    app.processEvents()
    assert not win.isVisible() and not win.isMinimized(), "前置失败：主窗应为非最小化隐藏态"

    viewport = win.Ui.textBrowser_log_main.viewport()
    app.sendEvent(viewport, QEvent(QEvent.Type.ApplicationActivate))
    app.processEvents()

    assert not win.isVisible(), "隐藏主窗被 ApplicationActivate 自动弹出（议题 #132）"


def test_tray_hidden_main_stays_hidden_after_manager_operation(win, app, monkeypatch):
    """议题 #132 主场景：托盘隐藏主窗后打开演员管理器并触发应用激活，主窗保持隐藏。

    ApplicationActivate 由操作演员管理器触发，等价于向主窗 eventFilter 投递该事件。
    """
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QSystemTrayIcon

    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window.tool_handlers import (
        pushButton_emby_actor_manager_clicked,
    )

    # tray_icon_click 仅在 Windows 走隐藏分支（IS_WINDOWS 门控），测试环境显式开启
    monkeypatch.setattr(mw_mod, "IS_WINDOWS", True)

    win.show()
    app.processEvents()

    # 用户点击托盘图标隐藏主窗（tray_icon_click 的 hide 路径）
    win.tray_icon_click(QSystemTrayIcon.ActivationReason.Trigger)
    app.processEvents()
    assert not win.isVisible(), "前置失败：托盘图标未隐藏主窗"

    # 打开演员管理器，并模拟其操作触发应用激活事件
    pushButton_emby_actor_manager_clicked(win)
    app.processEvents()
    viewport = win.Ui.textBrowser_log_main.viewport()
    app.sendEvent(viewport, QEvent(QEvent.Type.ApplicationActivate))
    app.processEvents()

    assert not win.isVisible(), "托盘隐藏后操作演员管理器把主窗弹出了（议题 #132）"


def test_tray_icon_click_restores_main_window_after_hide(win, app, monkeypatch):
    """议题 #132 配套：移除 ApplicationActivate 自动 show() 后，托盘图标点击仍能恢复主窗。

    防止修复过度——恢复显示必须继续由托盘交互负责。
    """
    from PyQt6.QtWidgets import QSystemTrayIcon

    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod, "IS_WINDOWS", True)

    win.show()
    app.processEvents()
    win.tray_icon_click(QSystemTrayIcon.ActivationReason.Trigger)
    app.processEvents()
    assert not win.isVisible(), "前置失败：托盘图标未隐藏主窗"

    # 再次点击托盘图标 → 恢复显示
    win.tray_icon_click(QSystemTrayIcon.ActivationReason.Trigger)
    app.processEvents()
    assert win.isVisible(), "托盘图标点击未恢复主窗显示"


def test_main_page_cover_scales_proportionally_when_maximized(win, app):
    """议题 #102-②：主界面封面区（poster/thumb 图片框 + 尺寸文字）最大化后
    按设计基准宽 820 横向等比放大，宽高与 x 同 scale、y 不变（纵向位置保留）。

    回归背景：绝对定位布局未把封面区纳入横向同步，最大化后 4 个 label 停留
    设计 220px 高、停在页面顶部不随窗口放大（用户标注「图片区域及图片等比放大」）。
    """
    _goto(win, app, "page_main")
    win.resize(1920, 1080)
    win.show()
    app.processEvents()

    ui = win.Ui
    # stackedWidget 可用宽 = width - 210 - 2 = 1708；scale = 1708/820
    stacked_w = ui.stackedWidget.width()
    scale = stacked_w / 820
    assert stacked_w == 1708, f"前置：最大化 stackedWidget 宽 {stacked_w} ≠ 1708"

    assert ui.label_poster.width() == int(156 * scale), f"封面框宽未按 scale 放大: {ui.label_poster.width()}"
    assert ui.label_poster.height() == int(220 * scale), f"封面框高未按 scale 放大: {ui.label_poster.height()}"
    assert ui.label_poster.x() == int(80 * scale), f"封面框 x 未按 scale 平移: {ui.label_poster.x()}"
    assert ui.label_poster.y() == 160, f"封面框 y 应保留设计 160: {ui.label_poster.y()}"

    assert ui.label_thumb.width() == int(328 * scale), f"缩略框宽未按 scale 放大: {ui.label_thumb.width()}"
    assert ui.label_thumb.height() == int(220 * scale), f"缩略框高未按 scale 放大: {ui.label_thumb.height()}"
    assert ui.label_thumb.x() == int(252 * scale), f"缩略框 x 未按 scale 平移: {ui.label_thumb.x()}"

    assert ui.label_poster_size.width() == int(411 * scale), f"封面尺寸文字宽未按 scale: {ui.label_poster_size.width()}"
    assert ui.label_thumb_size.width() == int(201 * scale), f"缩略尺寸文字宽未按 scale: {ui.label_thumb_size.width()}"


def test_nfo_lib_info_page_no_right_blank_when_maximized(win, app):
    """议题 #102-④：信息管理页（NFO 库）最大化后表单区右侧无残留空白。

    回归背景：该现象在 v2.0.9 用户截图中标注「这不正常」，实为议题 #78 描述的
    「右侧残留 ~194px 空白」+ #82 还原锁死——v2.1.0 已由 _sync_page_layouts
    逐页重排 + CustomScrollArea min 宽回落覆盖。本测试锁定当前代码无回归：
    表单内容宽必须跟随视口（右侧不留 194px 空白）。
    """
    _goto(win, app, "page_nfo_library")
    win.resize(1920, 1080)
    win.show()
    app.processEvents()

    form_scroll = win.Ui.scrollArea_nfo_lib_form
    form_content = win.Ui.scrollAreaWidgetContents_nfo_lib
    right_gap = form_scroll.viewport().width() - form_content.width()
    assert right_gap <= 20, f"信息管理页右侧仍残留空白 {right_gap}px（应 ≤20）"


def test_nfo_right_column_aligns_to_thirds_when_wide(win, app):
    """设置-NFO：宽窗口下右列左对齐到自定义分级/想看人数 thirds，窄态保持原样。

    用户截图（最大化）：影评人评分/导演/演员写入TMDB ID/标签被推到自定义分级/
    想看人数右侧两百多 px。根因：gridLayout_66 columnstretch=(1,0) 使 C1.x 以
    斜率 1 右移，而两行三项 HBox 以斜率 2/3 右移，宽视口下持续发散。
    _sync_nfo_right_column_align 自适应钳制 C1 列最小宽：发散态钉到 thirds，
    窄态（critic.x <= custom.x）保持清零不动。本测试故意不切 NFO 页，
    同步锁定休眠页同样生效；其它行（左列 x、y）不得移动。
    """
    ui = win.Ui
    score = ui.checkBox_nfo_score
    critic = ui.checkBox_nfo_criticrating
    director = ui.checkBox_nfo_director
    tmdb = ui.checkBox_nfo_actor_tmdbid
    tag = ui.checkBox_nfo_tag
    custom = ui.checkBox_nfo_customrating
    wanted = ui.checkBox_nfo_wanted

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(score), "checkBox_nfo_score") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    # 宽态（用户截图场景：最大化后打开 NFO 页）：右列四者与 thirds 严格上下对齐
    win.resize(1900, 1050)
    win.show()
    goto_nfo_tab()
    app.processEvents()
    assert critic.x() == custom.x() == wanted.x(), (
        f"宽态右列未对齐 thirds: critic={critic.x()} custom={custom.x()} wanted={wanted.x()}"
    )
    assert director.x() == custom.x(), f"导演未对齐: {director.x()} vs {custom.x()}"
    assert tmdb.x() == custom.x(), f"TMDB 未对齐: {tmdb.x()} vs {custom.x()}"
    assert tag.x() == custom.x(), f"标签未对齐: {tag.x()} vs {custom.x()}"
    assert ui.gridLayout_66.columnMinimumWidth(1) > 0, "宽态应设置 C1 列最小宽钳制"
    # 左列保持在右列左侧（其余不动）
    assert score.x() < critic.x(), "左列应保持在右列左侧"

    # 幂等：再同步一次位置不变
    win._sync_page_layouts()
    app.processEvents()
    assert critic.x() == custom.x() == wanted.x(), "二次同步后对齐漂移"

    # 窄态：钳制清零、自然位置原样保留
    win.resize(900, 700)
    goto_nfo_tab()
    app.processEvents()
    assert ui.gridLayout_66.columnMinimumWidth(1) == 0, "窄态 C1 列最小宽应清零"
    assert critic.x() <= custom.x(), f"窄态右列应保持自然位置: critic={critic.x()} custom={custom.x()}"


def test_nfo_title_plot_aligns_to_release_when_wide(win, app):
    """设置-NFO：原标题/简介对齐发行日期、原简介对齐上映日期，窄态宽态一致。

    用户截图（最大化）：原标题（originaltitle）应与发行日期（releasedate）
    上下对齐、简介（plot）与 releasedate 对齐、原简介（originalplot）与上映
    日期（premiered）对齐。根因：发行三项为 Minimum 策略、视口加宽时各自吞
    掉 extra/3，而原标题/简介行的 Fixed-150 前缀把后继项 x 冻结在窄态位置。
    _sync_nfo_title_plot_align 把三前缀恢复最小宽 150→重排→量自然位置，
    再按「当前宽+位移」设最小宽（g0=max(rd.x-ot.x,0)，g1=max(rd.x-plot.x,0)，
    g2=max(pr.x-opl.x-g1,0)，opl 永不超过 pr）；与视口宽窄无关，窄态宽态同一套。
    后用户要求最小化（窄态）同样对齐：三行是三个独立 HBox，加宽 135/136
    前缀只推本行后继项，137 行的 relasedate/premiered 纹丝不动；只碰列宽，
    行高不变故无上下移动。
    """
    ui = win.Ui
    st = ui.checkBox_nfo_sorttitle
    ot = ui.checkBox_nfo_originaltitle
    outline = ui.checkBox_nfo_outline
    plot = ui.checkBox_nfo_plot
    opl = ui.checkBox_nfo_originalplot
    rd = ui.checkBox_nfo_relasedate
    pr = ui.checkBox_nfo_premiered

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(ot), "checkBox_nfo_originaltitle") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    # 宽态（用户截图场景）：三者严格上下对齐，前缀被加宽钳制
    win.resize(1900, 1050)
    win.show()
    goto_nfo_tab()
    app.processEvents()
    assert ot.x() == rd.x(), f"宽态原标题未对齐发行日期: ot={ot.x()} rd={rd.x()}"
    assert plot.x() == rd.x(), f"宽态简介未对齐发行日期: plot={plot.x()} rd={rd.x()}"
    assert opl.x() == pr.x(), f"宽态原简介未对齐上映日期: opl={opl.x()} pr={pr.x()}"
    assert st.minimumWidth() > 150, "宽态 sorttitle 前缀应被加宽"
    assert outline.minimumWidth() > 150, "宽态 outline 前缀应被加宽"
    assert plot.minimumWidth() > 150, "宽态 plot 前缀应被加宽"

    # 幂等：再同步一次位置不变（含 y 稳定）
    win._sync_page_layouts()
    app.processEvents()
    assert ot.x() == rd.x() == plot.x(), "二次同步后对齐漂移"
    assert opl.x() == pr.x(), "二次同步后原简介对齐漂移"

    # 窄态（用户新需求，默认窗口尺寸）：几何允许时对齐，否则只保证不变量。
    # 注意测试字体的特殊性：set_style=None 下 sorttitle hint=192（>150），
    # 前缀缩不到 150 以下，ot 自然位 334 卡在 rd（322）右边 12px——两边都
    # 动不得（st 不能缩、rd 不能动），严格对齐在此字体下可证明无解，实现
    # 正确 no-op。生产字体（YaHei）下 st=150、ot=292<rd=321，对齐发生。
    # 此处不断言绝对等式，只断言字体无关的契约不变量。
    win.resize(1089, 1050)
    goto_nfo_tab()
    app.processEvents()
    rows = (ui.horizontalLayout_135, ui.horizontalLayout_136, ui.horizontalLayout_137)

    def check_narrow_invariants(tag):
        # 自然基线：前缀恢复最小宽 150→重排→量自然位置，记录位置
        for cb in (st, outline, plot):
            cb.setMinimumWidth(150)
        for row in rows:
            row.invalidate()
            row.activate()
        ui.gridLayout_40.activate()
        app.processEvents()
        nat = {cb: (cb.x(), cb.y()) for cb in (st, ot, outline, plot, opl, rd, pr)}
        # 全量同步后：后继项只许右移且 opl 永不超过 pr；参照与 y 逐像素不变
        win._sync_page_layouts()
        app.processEvents()
        assert ot.x() >= nat[ot][0] and plot.x() >= nat[plot][0], f"{tag}：后继项左移"
        assert nat[opl][0] <= opl.x() <= pr.x(), f"{tag}：原简介越界 opl={opl.x()} pr={pr.x()}"
        assert (rd.x(), rd.y()) == nat[rd], f"{tag}：发行日期移动"
        assert (pr.x(), pr.y()) == nat[pr], f"{tag}：上映日期移动"
        for cb in (st, ot, outline, plot, opl):
            assert cb.y() == nat[cb][1], f"{tag}：控件上下移动 {cb.objectName()}"
        # 幂等
        before = {cb: (cb.x(), cb.y()) for cb in (st, ot, outline, plot, opl, rd, pr)}
        win._sync_page_layouts()
        app.processEvents()
        after = {cb: (cb.x(), cb.y()) for cb in (st, ot, outline, plot, opl, rd, pr)}
        assert before == after, f"{tag}：二次同步漂移"

    check_narrow_invariants("窄态1089")

    # 过窄窗口（900x700）：布局更压缩，同样只断言不变量
    win.resize(900, 700)
    goto_nfo_tab()
    app.processEvents()
    check_narrow_invariants("过窄态900")


def test_nfo_resyncs_after_dormant_resize_on_page_back(win, app):
    """休眠 NFO 页 resize 后切回设置页必须补同步（用户截图：窄态 opl 落在 pr 左边）。

    根因：resize/changeEvent 进来的 _sync_page_layouts 会被各 sync 内 isVisibleTo
    早退跳过休眠 NFO；而切回设置页时 NFO 的 tab 索引没变，tabWidget.currentChanged
    不触发——此前 NFO 永远停留旧几何。修复：stackedWidget.currentChanged 同样排队
    级联后全量同步（_queue_nfo_post_cascade_sync，内层守卫保证休眠 no-op）。
    覆盖两条返回路径：
    A. 返回窄态（1000）：不断言严格对齐——桩配置+测试字体下冒号标定走另一分支
       （cal title=103/pad=5，lw10=(-10,625)），rd=301 卡在 ot 自然位 334 左边，
       d0 为负被钳，可证明无解（同 b23 窄态 hint-192 注释）；只断言钩子跑过
       （宽态残留前缀被清掉）+ 不变量（opl 不超 pr、二次同步幂等）。
    B. 返回宽态（1900）：严格对齐（宽态 d 全为正，任何字体/配置都可达）；无钩子
       时前缀停留窄态，ot≈318≠rd 必挂，保证测试对钩子失效敏感。
    """
    ui = win.Ui
    st = ui.checkBox_nfo_sorttitle
    ot = ui.checkBox_nfo_originaltitle
    outline = ui.checkBox_nfo_outline
    plot = ui.checkBox_nfo_plot
    opl = ui.checkBox_nfo_originalplot
    rd = ui.checkBox_nfo_relasedate
    pr = ui.checkBox_nfo_premiered
    keys = (st, ot, outline, plot, opl, rd, pr)

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(ot), "checkBox_nfo_originaltitle") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    def pump_until_stable(rounds=10):
        """抽干事件链直到坐标稳定（stacked 切回的级联比 tab 切换长，不固定拍数）。"""
        last = None
        for _ in range(rounds):
            app.processEvents()
            cur = tuple(cb.x() for cb in keys)
            if cur == last:
                return cur
            last = cur
        return last

    win.resize(1900, 1050)
    win.show()
    goto_nfo_tab()
    pump_until_stable()
    assert opl.x() == pr.x(), "前置条件：宽态原简介应对齐上映日期"

    # A. 休眠后返回窄态：钩子必须跑过（清掉宽态残留），但不断言严格对齐
    _goto(win, app, "page_log")
    app.processEvents()
    win.resize(1000, 760)
    app.processEvents()
    stale = tuple(cb.minimumWidth() for cb in (st, outline, plot))
    assert all(v > 400 for v in stale), "前置条件：休眠 resize 后宽态前缀应残留"
    _goto(win, app, "page_setting")  # NFO tab 索引不变，无 tab 钩子
    pump_until_stable()
    post = tuple(cb.minimumWidth() for cb in (st, outline, plot))
    assert all(p < s for p, s in zip(post, stale, strict=True)), f"切回后钩子未跑：前缀仍是宽态残留 {post} vs {stale}"
    assert opl.x() <= pr.x(), f"切回后原简介越界: opl={opl.x()} pr={pr.x()}"
    before = tuple((cb.x(), cb.y()) for cb in keys)
    win._sync_page_layouts()
    app.processEvents()
    assert before == tuple((cb.x(), cb.y()) for cb in keys), "二次同步漂移"

    # B. 休眠后返回宽态：必须严格收敛（无钩子时前缀停留窄态，ot≈318≠rd 必挂）
    _goto(win, app, "page_log")
    app.processEvents()
    win.resize(1900, 1050)
    app.processEvents()
    _goto(win, app, "page_setting")
    pump_until_stable()
    assert ot.x() == rd.x(), f"返回宽态后原标题未重对齐: ot={ot.x()} rd={rd.x()}"
    assert plot.x() == rd.x(), f"返回宽态后简介未重对齐: plot={plot.x()} rd={rd.x()}"
    assert opl.x() == pr.x(), f"返回宽态后原简介未重对齐: opl={opl.x()} pr={pr.x()}"
    assert st.minimumWidth() > 150, "返回宽态后 sorttitle 前缀应被加宽"


def test_nfo_colon_aligns_to_group_title(win, app):
    """设置-NFO「写入NFO的字段」组：11 个左标签整体左移，冒号向组标题冒号对齐。

    用户截图（最小化/最大化都要）：标题：/简介：/发行日期：/国家/分级：/
    年份/时长/想看：/评分：/演员/导演：/系列/标签：/风格/合集：/片商/发行商：/
    封面/背景/预告片：冒号缩进在右，要求整体左移、冒号与组标题
    「写入NFO的字段：」的冒号严格上下对齐，右侧控件跟随、间距不变。
    _sync_nfo_colon_align 像素标定 + layoutWidget_10 整体平移（右缘保持）+
    防裁字守卫。预算证明：不裁字 ⟺ 公共冒号 x ≥ 最宽标签字形宽；只要最宽
    标签宽于组标题冒号位置（如当前 11 字标签 vs 8 字标题），严格对齐就
    结构性无解，实现取免裁字最大位移（残差 = W_max - title_colon）。
    本测试不断言绝对像素，只断言字体无关的最优性：移到防裁字守卫允许
    的最左（自然位与守卫下界取 max）、无裁字、右缘保持、y 不动、窄宽同位、幂等。
    注：守卫生效在 advance 空间（字体度量），标定 pad 在 ink 空间（渲染墨点），
    两者有数 px 系统差，故不对齐残差断言绝对公式，只断言位移取到允许极值。
    """
    ui = win.Ui
    lw = ui.layoutWidget_10
    names = win._NFO_COLON_LABELS
    lbs = [getattr(ui, n) for n in names]
    ref = lbs[0]  # 标题：，col0 右对齐代表行

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(ref), "label_163") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    # 休眠页设计值（同步跳过，几何即设计值）
    design_x = lw.x()
    ref_y = ref.y()

    def check_state(tag):
        cal = win._nfo_colon_cal
        assert cal is not None, f"{tag}：冒号标定缓存为空"
        _, title_colon, row_pad = cal
        fm = ref.fontMetrics()
        adv = [fm.horizontalAdvance(lb.text()) for lb in lbs]
        # 11 标签同为 col0 右对齐代表：同 x 同宽，右缘共线
        for lb in lbs:
            assert lb.x() == ref.x() and lb.width() == ref.width(), f"{tag}：行标签右缘不共线"
        # 允许极值：自然位与守卫下界取 max（与实现同式，字体无关）
        fitting = [w for w in adv if w <= ref.width()]
        min_x = (max(fitting) - ref.width()) if fitting else -1000000
        natural_ref_right = design_x + ref.x() + ref.width() - row_pad
        expected_x = max(design_x + title_colon - natural_ref_right, min_x)
        assert lw.x() == expected_x, f"{tag}：位移未取极值 lw.x={lw.x()} 期望={expected_x}"
        # 无裁字（ink 空间：墨点左缘 = 矩形右缘 - advance + boundingRect.x，
        # 与标定同空间；horizontalAdvance 含 bearings，不能直接当墨宽用）
        rect_right = lw.x() + ref.x() + ref.width()
        for lb in lbs:
            a = fm.horizontalAdvance(lb.text())
            brx = fm.boundingRect(lb.text()).x()
            ink_left = rect_right - a + brx
            assert ink_left >= 0, f"{tag}：标签裁字 {lb.objectName()} ink_left={ink_left}"
        # 右缘保持不断言：实现中 right=x+w、new_w=right-new_x，算术构造保证，
        # 无测量参与、不可能坏；且任何真实窗口都会重排，休眠基线在各态皆无效。
        # y 与行不动
        assert ref.y() == ref_y, f"{tag}：行标签 y 移动"
        return lw.x()

    # 宽态（用户截图场景之一）
    win.resize(1900, 1050)
    win.show()
    goto_nfo_tab()
    app.processEvents()
    wide_x = check_state("宽态")
    # 位移方向：整体左移（或已对齐时不动），永不右移
    assert wide_x <= design_x, f"宽态容器右移: {wide_x} vs 设计 {design_x}"

    # 幂等：再同步一次位置不变
    win._sync_page_layouts()
    app.processEvents()
    assert lw.x() == wide_x, "二次同步后冒号对齐漂移"

    # 窄态：位移与宽态逐像素相同（只与字体有关，与视口无关）
    win.resize(900, 700)
    goto_nfo_tab()
    app.processEvents()
    narrow_x = check_state("窄态")
    assert narrow_x == wide_x, f"窄宽位移不一致: {narrow_x} vs {wide_x}"


def test_nfo_country_year_align_to_release_when_narrow(win, app):
    """设置-NFO：窄态下分级信息（mpaa）右移、时长（runtime）左移到发行日期列。

    用户截图（最小化）：mpaa 框偏左、runtime 框偏右；最大化天然对齐。
    根因：三行（h137 发行/h141 国家/h40 年份）皆左堆积无弹簧的 Minimum 行，
    同一起点 X0。有余量时三行均分天然对齐；容器窄到装不下 hint 总宽时
    Minimum 项被挤到 hint 以下、各行按各自文本乱挤（850 宽实测 rd=257、
    mpaa=252、runtime=268）。
    _sync_nfo_row_align 绝对钉死+有界迭代：country/year 的最小/最大宽
    全部钉到 rd.x - 前项.x - h137 实测间距（min=max 一次钉死，60px 地板），
    单遍后重排漂移再测再钉、最多 3 遍；mpaa.x 与 runtime.x 恒等于 rd.x；
    有余量时条件不触发，宽态零改动。只碰列宽，参照与 y 不动。
    """
    ui = win.Ui
    release = ui.checkBox_nfo_release
    country = ui.checkBox_nfo_country
    mpaa = ui.checkBox_nfo_mpaa
    year = ui.checkBox_nfo_year
    runtime = ui.checkBox_nfo_runtime
    rd = ui.checkBox_nfo_relasedate

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(rd), "checkBox_nfo_relasedate") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    rows = (ui.horizontalLayout_137, ui.horizontalLayout_141, ui.horizontalLayout_40)

    # 挤压态（700/750/850x700）：翻转方向全覆盖——750 宽 runtime 自然偏左、
    # 850 宽 settled 态 mpaa 反超；同步后三者严格 == rd.x，参照与 y 不动
    win.show()
    for w in (700, 750, 850):
        win.resize(w, 700)
        goto_nfo_tab()
        app.processEvents()
        # 自然基线：四约束复位→重排→记录位置
        country.setMinimumWidth(0)
        country.setMaximumWidth(16777215)
        year.setMinimumWidth(0)
        year.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        ui.gridLayout_40.activate()
        app.processEvents()
        nat = {cb: (cb.x(), cb.y()) for cb in (release, country, mpaa, year, runtime, rd)}
        # 全量同步：两者严格对齐 rd，参照/前项/y 不动
        win._sync_page_layouts()
        app.processEvents()
        assert mpaa.x() == rd.x(), f"{w}宽 mpaa 未对齐: mpaa={mpaa.x()} rd={rd.x()}"
        assert runtime.x() == rd.x(), f"{w}宽 runtime 未对齐: runtime={runtime.x()} rd={rd.x()}"
        assert (rd.x(), rd.y()) == nat[rd], f"{w}宽 参照发行日期移动"
        for cb in (release, country, year):
            assert (cb.x(), cb.y()) == nat[cb], f"{w}宽 前项移动 {cb.objectName()}"
        for cb in (mpaa, runtime):
            assert cb.y() == nat[cb][1], f"{w}宽 后项上下移动 {cb.objectName()}"
        # 幂等：再同步一次位置不变
        before = {cb: (cb.x(), cb.y()) for cb in (release, country, mpaa, year, runtime, rd)}
        win._sync_page_layouts()
        app.processEvents()
        after = {cb: (cb.x(), cb.y()) for cb in (release, country, mpaa, year, runtime, rd)}
        assert before == after, f"{w}宽 二次同步漂移"

    # 宽态（1900）：天然对齐，条件式无触发、约束零残留
    win.resize(1900, 1050)
    goto_nfo_tab()
    app.processEvents()
    assert mpaa.x() == rd.x() == runtime.x(), f"宽态三者应对齐: mpaa={mpaa.x()} rd={rd.x()} runtime={runtime.x()}"
    assert country.minimumWidth() == 0, "宽态 country 不应残留最小宽"
    assert country.maximumWidth() == 16777215, "宽态 country 不应残留最大宽"
    assert year.minimumWidth() == 0, "宽态 year 不应残留最小宽"
    assert year.maximumWidth() == 16777215, "宽态 year 不应残留最大宽"


def test_nfo_tail_align_to_premiered_when_narrow(win, app):
    """设置-NFO：窄态下自定义（customrating）、想看人数（votes）右移到首播日期列。

    用户需求（最小化）：custom 框、votes 框与 premiered（premiered）框严格
    上下对齐，premiered 不动；最大化天然对齐、行为不变；只能左右移动。
    根因：三行（h137 发行/h141 国家/h40 年份）皆左堆积无弹簧的 Minimum 行，
    同一起点 X0。有余量时三行均分天然对齐；800~900 宽挤压区第二项
    （mpaa/runtime）被挤得比 relasedate 窄（850 宽实测 mpaa.w=119、
    relasedate.w=133），末项 custom/votes 落在 premiered 左边
    （800 宽 custom 偏左 15、850 宽 custom 偏左 14/votes 偏左 2）。
    _sync_nfo_tail_align 条件对称钉死+有界迭代：只钉 mpaa/runtime 的
    最小/最大宽到 rd.width()（min=max 一次钉死，60px 地板），
    单遍后重排漂移再测再钉、最多 3 遍；custom.x 与 votes.x 恒等于 pr.x；
    有余量时条件不触发，宽态零改动。只碰列宽，参照与 y 不动。
    """
    ui = win.Ui
    country = ui.checkBox_nfo_country
    mpaa = ui.checkBox_nfo_mpaa
    custom = ui.checkBox_nfo_customrating
    year = ui.checkBox_nfo_year
    runtime = ui.checkBox_nfo_runtime
    votes = ui.checkBox_nfo_wanted
    rd = ui.checkBox_nfo_relasedate
    pr = ui.checkBox_nfo_premiered

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(rd), "checkBox_nfo_relasedate") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    rows = (ui.horizontalLayout_137, ui.horizontalLayout_141, ui.horizontalLayout_40)

    # 挤压态（800/850x700）：800 宽 custom 自然偏左 15、850 宽偏左 14/votes 偏左 2；
    # 同步后两者严格 == pr.x，参照/中项/y 不动
    win.show()
    for w in (800, 850):
        win.resize(w, 700)
        goto_nfo_tab()
        app.processEvents()
        # 自然基线：四约束复位→重排→记录位置
        country.setMinimumWidth(0)
        country.setMaximumWidth(16777215)
        year.setMinimumWidth(0)
        year.setMaximumWidth(16777215)
        mpaa.setMinimumWidth(0)
        mpaa.setMaximumWidth(16777215)
        runtime.setMinimumWidth(0)
        runtime.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        ui.gridLayout_40.activate()
        app.processEvents()
        nat = {cb: (cb.x(), cb.y()) for cb in (mpaa, custom, runtime, votes, rd, pr)}
        # 全量同步：两者严格对齐 pr，参照/中项/y 不动
        win._sync_page_layouts()
        app.processEvents()
        assert custom.x() == pr.x(), f"{w}宽 custom 未对齐: custom={custom.x()} pr={pr.x()}"
        assert votes.x() == pr.x(), f"{w}宽 votes 未对齐: votes={votes.x()} pr={pr.x()}"
        assert (pr.x(), pr.y()) == nat[pr], f"{w}宽 参照首播日期移动"
        assert (rd.x(), rd.y()) == nat[rd], f"{w}宽 参照发行日期移动"
        for cb in (mpaa, runtime):
            assert cb.y() == nat[cb][1], f"{w}宽 中项上下移动 {cb.objectName()}"
        for cb in (custom, votes):
            assert cb.y() == nat[cb][1], f"{w}宽 末项上下移动 {cb.objectName()}"
        # 幂等：再同步一次位置不变
        before = {cb: (cb.x(), cb.y()) for cb in (mpaa, custom, runtime, votes, rd, pr)}
        win._sync_page_layouts()
        app.processEvents()
        after = {cb: (cb.x(), cb.y()) for cb in (mpaa, custom, runtime, votes, rd, pr)}
        assert before == after, f"{w}宽 二次同步漂移"

    # 无操作检查（700/750/1900）：天然对齐，条件式无触发、约束零残留
    for w in (700, 750, 1900):
        win.resize(w, 700 if w < 1900 else 1050)
        goto_nfo_tab()
        app.processEvents()
        assert custom.x() == pr.x() == votes.x(), f"{w}宽三者应对齐"
        assert mpaa.minimumWidth() == 0, f"{w}宽 mpaa 不应残留最小宽"
        assert mpaa.maximumWidth() == 16777215, f"{w}宽 mpaa 不应残留最大宽"
        assert runtime.minimumWidth() == 0, f"{w}宽 runtime 不应残留最小宽"
        assert runtime.maximumWidth() == 16777215, f"{w}宽 runtime 不应残留最大宽"


def test_nfo_set_aligns_to_maker_publisher_when_wide(win, app):
    """设置-NFO：宽态下合集（演员字段）==片商、合集（系列字段）==发行商。

    用户需求（最大化）：actor_set 框与 maker（maker）框、set 框与
    publisher（publisher）框严格上下对齐；最小化布局不动；只能左右移动。
    根因（离屏 1900/1400/1089/1000 实测，测试字体）：h114 三分、h138
    四分，同一起点左堆积无弹簧，_sync_wide_children_width 加宽容器后两行
    按各自等分数 surplus，行为线性三分 vs 四分（d_aset≈W_cell/12、
    d_set≈W_cell/6）：1900 宽 d=+116/+232、1400 宽 d=+74/+149；
    1000/1089 自然 d=+41/+82、+46/+102，宽态门（extra=viewport-796>200）
    关闭保持不动。_sync_nfo_set_align 门内条件左移：genre 封顶钉
    actor_set.x==maker.x、actor_set 封顶钉 set.x==publisher.x，
    studio/maker/publisher 与 y 全不动。只碰列宽。
    """
    ui = win.Ui
    genre = ui.checkBox_nfo_genre
    actor_set = ui.checkBox_nfo_actor_set
    nfo_set = ui.checkBox_nfo_set
    studio = ui.checkBox_nfo_studio
    maker = ui.checkBox_nfo_maker
    publisher = ui.checkBox_nfo_publisher

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(maker), "checkBox_nfo_maker") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    rows = (ui.horizontalLayout_114, ui.horizontalLayout_138)

    # 门内（1900/1400x900）：自然错位，同步后两者严格==maker/publisher.x
    win.show()
    for w in (1900, 1400):
        win.resize(w, 900)
        goto_nfo_tab()
        app.processEvents()
        # 自然基线：两约束复位→重排→记录位置
        genre.setMinimumWidth(0)
        genre.setMaximumWidth(16777215)
        actor_set.setMinimumWidth(0)
        actor_set.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        ui.gridLayout_40.activate()
        app.processEvents()
        nat = {cb: (cb.x(), cb.y()) for cb in (genre, actor_set, nfo_set, studio, maker, publisher)}
        assert nat[actor_set][0] > nat[maker][0], f"{w}宽 门内自然应对错位"
        assert nat[nfo_set][0] > nat[publisher][0], f"{w}宽 门内自然应对错位"
        # 全量同步：两者严格对齐 maker/publisher，参照/y 不动
        win._sync_page_layouts()
        app.processEvents()
        assert actor_set.x() == maker.x(), f"{w}宽 actor_set 未对齐: aset={actor_set.x()} mk={maker.x()}"
        assert nfo_set.x() == publisher.x(), f"{w}宽 set 未对齐: set={nfo_set.x()} pb={publisher.x()}"
        for cb in (studio, maker, publisher):
            assert (cb.x(), cb.y()) == nat[cb], f"{w}宽 参照移动 {cb.objectName()}"
        for cb in (genre, actor_set, nfo_set):
            assert cb.y() == nat[cb][1], f"{w}宽 上下移动 {cb.objectName()}"
        # 幂等：再同步一次位置不变
        before = {cb: (cb.x(), cb.y()) for cb in (genre, actor_set, nfo_set, studio, maker, publisher)}
        win._sync_page_layouts()
        app.processEvents()
        after = {cb: (cb.x(), cb.y()) for cb in (genre, actor_set, nfo_set, studio, maker, publisher)}
        assert before == after, f"{w}宽 二次同步漂移"

    # 门外无操作（1000/1089）：自然漂移保留、约束零残留
    for w in (1000, 1089):
        win.resize(w, 700)
        goto_nfo_tab()
        app.processEvents()
        genre.setMinimumWidth(0)
        genre.setMaximumWidth(16777215)
        actor_set.setMinimumWidth(0)
        actor_set.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        ui.gridLayout_40.activate()
        app.processEvents()
        nat_aset_x = actor_set.x()
        nat_set_x = nfo_set.x()
        win._sync_page_layouts()
        app.processEvents()
        assert actor_set.x() == nat_aset_x, f"{w}宽 门外不应移动"
        assert nfo_set.x() == nat_set_x, f"{w}宽 门外不应移动"
        assert genre.minimumWidth() == 0, f"{w}宽 genre 不应残留最小宽"
        assert genre.maximumWidth() == 16777215, f"{w}宽 genre 不应残留最大宽"
        assert actor_set.minimumWidth() == 0, f"{w}宽 actor_set 不应残留最小宽"
        assert actor_set.maximumWidth() == 16777215, f"{w}宽 actor_set 不应残留最大宽"


def test_nfo_field_tips_stays_inside_group_box(win, app):
    """设置-NFO：窄态下字段说明按钮左移进组框，宽态保持 640 不动。

    用户截图：最小化时「字段说明」按钮（80 宽，设计 x=640..720）伸出
    「写入NFO的字段」组框（设计右缘 731，余量仅 11px）——宽幅同步按
    width=设计宽+extra 双向拉伸组框，extra<0 时组右缘左移而按钮不动。
    _sync_nfo_field_tips 做绝对 pin：按钮右缘>组右缘-11 才左移，
    只左移，y 不动，多拍收敛幂等。
    """
    ui = win.Ui
    btn = ui.pushButton_field_tips_nfo
    gb = ui.groupBox_81

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(btn), "pushButton_field_tips_nfo") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    win.show()
    # 窄态（1000x700）：自然应溢出，同步后按钮右缘≤组右缘-11，y 不动
    win.resize(1000, 700)
    goto_nfo_tab()
    app.processEvents()
    # goto 的 beats 已提前同步（btn.x()≈574 精确 pin 位），先复位到设计位再取自然基线
    btn.move(640, btn.y())
    app.processEvents()
    nat = (btn.x(), btn.y())
    gb_nat = (gb.x(), gb.width())
    assert nat[0] + btn.width() > gb_nat[0] + gb_nat[1] - 11, "1000宽 自然应溢出"
    win._sync_page_layouts()
    app.processEvents()
    assert btn.x() + btn.width() <= gb.x() + gb.width() - 11, (
        f"1000宽 按钮仍伸出: btn右={btn.x() + btn.width()} 组右-11={gb.x() + gb.width() - 11}"
    )
    assert btn.y() == nat[1], "1000宽 按钮上下移动"
    # 幂等：再同步一次位置不变
    before = (btn.x(), btn.y())
    win._sync_page_layouts()
    app.processEvents()
    assert (btn.x(), btn.y()) == before, "1000宽 二次同步漂移"
    # 宽态（1900x900）：x==640 逐像素不动
    win.resize(1900, 900)
    goto_nfo_tab()
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    assert btn.x() == 640, f"1900宽 按钮不应移动: x={btn.x()}"
