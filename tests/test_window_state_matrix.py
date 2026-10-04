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


def test_left_background_follows_sidebar_height(win, app):
    """左侧背景条随侧栏同高：最大化后下方不得露出与上部不同的底色。

    根因：left_backgroud_widget 是 widget_setting 的子项、设计高仅 700，
    resizeEvent 只同步了父项高度，背景条滞留 700，窗口拉高后底部露出父项
    底色、与各页配色断层。修复后两者同高。
    """
    ui = win.Ui
    win.show()
    app.processEvents()
    for width, height in ((1030, 753), (1920, 1170), (1030, 753)):
        win.resize(width, height)
        app.processEvents()
        assert ui.widget_setting.height() == height, "侧栏未跟随窗口高"
        assert ui.left_backgroud_widget.height() == ui.widget_setting.height(), (
            f"{width}x{height} 下背景条高 {ui.left_backgroud_widget.height()} 与侧栏 {ui.widget_setting.height()} 断层"
        )


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
    右侧被裁成平口；同时「保存当前nfo文件」在视口外，必须下拉才见。
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


def test_fanyi_group_width_stable_across_resize_cycles(win, app):
    """翻译页简介/演员组宽度在反复缩放窗口后必须恒为「设计宽 + extra」。

    回归背景：`_sync_fanyi_group_spacing` 把「宽幅同步已拉伸后的当前宽」
    （`intro.width()` / `actor.width()`）写回 `_wide_children_design` 的设计宽度，
    下一轮宽幅同步再加一次 extra → 每轮缩放宽度无界增长（离屏实测每次窗口
    缩放 +1216px，几轮后两个组框飞出窗口右缘）。设计宽度只能取登记值——
    它是 `_register_design_geometry` 在 setupUi 时刻采集的唯一真值。
    """
    _goto(win, app, "page_setting")
    ui = win.Ui
    fanyi_tab = next(i for i in range(ui.tabWidget.count()) if ui.tabWidget.widget(i) is ui.tab_6)
    ui.tabWidget.setCurrentIndex(fanyi_tab)
    win.resize(1400, 900)
    win.show()
    app.processEvents()

    scroll = ui.scrollArea_11
    content = scroll.widget()
    design_w = getattr(content, "_wide_children_design_width", 0)
    for _ in range(3):
        for width in (1920, 1400):
            win.resize(width, 900)
            app.processEvents()
            extra = scroll.viewport().width() - design_w
            for name in ("groupBox_83", "groupBox_84"):
                box = getattr(ui, name)
                entry_w = next(e.geometry[2] for e in content._wide_children_design if e.widget is box)
                assert box.width() == entry_w + extra, (
                    f"{name} 宽幅同步被污染: 窗宽={width} w={box.width()} "
                    f"期望={entry_w + extra}（登记设计宽={entry_w} extra={extra}）"
                )
                assert box.width() <= scroll.viewport().width(), (
                    f"{name} 宽度已溢出视口: w={box.width()} viewport={scroll.viewport().width()}"
                )


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
    不变量是「底边贴底并预留 40px」，而不是矩形顶 y 的具体数值——顶 y 依赖
    label_show_version 的矩形高（底对齐文字块 + _DOCK_TEXT_GAP 推导的矩形高），
    随文案行数变化，改设计高就会变，故只断言底边。
    """
    _goto(win, app, "page_main")
    win.resize(1920, 1170)
    win.show()
    app.processEvents()

    status = win.Ui.label_show_version
    pad = win._DOCK_STATUS_BOTTOM_PAD
    assert status.y() + status.height() == 1170 - pad, (
        f"label_show_version 底边应贴底预留 {pad}px: "
        f"y={status.y()} height={status.height()} → 底={status.y() + status.height()}"
    )
    assert win.Ui.label_local_number.y() == 1109, (
        f"label_local_number 未贴底预留 40px: y={win.Ui.label_local_number.y()}"
    )


def test_left_status_badges_fully_visible_in_short_window(win, app):
    """矮窗口（<730）下左侧状态区不得被窗底裁掉，也不得压到导航按钮上。

    回归背景：贴底公式 max(height-241, 489) 的 489 下限只防"高于设计位置"，
    窗口高 <730 时 label 底边=690 超出窗口高度，底对齐文字的末行
    （config.json/MDCx 版本号）被父 widget 裁剪——用户反馈「config.json
    以下信息被截断」。修复后：label 底边必须 ≤ 窗口高度（完整落在窗口内）。
    议题 #181：同一公式只兜底边不兜顶边，窗口更矮时状态区会顶进导航按钮区
    （用户 175% 界面缩放截图：状态文字压在「检测网络/使用说明」上）。
    修复后两种边界都要满足，且状态区高度按剩余空间自适应（不再恒为 201）。
    公式守卫应在任意高度成立（含生产最小高之下），故先放开动态最小尺寸。
    """
    _goto(win, app, "page_main")
    win.setMinimumSize(0, 0)
    for h in (700, 680, 650, 550, 504, 450, 306):
        win.resize(1089, h)
        win.show()
        app.processEvents()
        nav_bottom = win.Ui.widget_buttons.y() + win.Ui.widget_buttons.height()
        for label in (win.Ui.label_show_version, win.Ui.label_local_number):
            if label.isHidden():
                continue
            bottom = label.y() + label.height()
            assert bottom <= win.height(), f"窗口高 {h} 时 {label.objectName()} 底边 {bottom} 超出窗口，末行被裁"
            if label is win.Ui.label_show_version:
                assert label.y() >= nav_bottom, (
                    f"窗口高 {h} 时状态区顶边 {label.y()} 压进导航区（导航底 {nav_bottom}），文字与按钮叠字"
                )


def test_left_dock_adapts_to_large_ui_scale(win, app):
    """议题 #181：界面缩放很大（用户 175% 反馈）时导航坞必须压缩，不得与状态区叠字。

    根因：侧栏是绝对定位几何——导航固定占 50..440（8 个 40px 按钮 + 8px 间距），
    状态区 label_show_version 高 201 且贴底。1920x1080@175% 的可用逻辑分辨率只有
    1097x594，默认窗口高 ~500 < 730，贴底公式把状态区顶到 y≈303，压在最后两个
    导航按钮上（截图：正常模式/actor.json 与 检测网络/使用说明 叠在一起）。
    本测试锁定：①任意高度下导航区与状态区不相交；②状态区至少留 72（4 行 13px 文字）；
    ③窗口拉高后逐值复原设计几何（双向幂等，军规③）；④隐藏导航项后按可见数排布。
    """
    _goto(win, app, "page_main")
    win.setMinimumSize(0, 0)
    ui = win.Ui
    status = ui.label_show_version

    def nav_bottom() -> int:
        return ui.widget_buttons.y() + ui.widget_buttons.height()

    def visible_nav() -> list:
        return list(win._dock_nav_buttons())

    # ① 175%（默认窗口 741x504）与 250%（450x306）下不重叠、状态区不小于 72
    for w, h in ((741, 504), (450, 306), (1089, 620)):
        win.resize(w, h)
        win.show()
        app.processEvents()
        if status.isHidden():  # 极矮窗口：状态区让位给导航（叠字比裁切更糟）
            continue
        assert status.height() >= win._DOCK_STATUS_H_MIN, (
            f"{w}x{h}: 状态区高 {status.height()} < {win._DOCK_STATUS_H_MIN}"
        )
        assert status.y() >= nav_bottom(), f"{w}x{h}: 状态区顶边 {status.y()} 压进导航区（导航底 {nav_bottom()}）"
        assert status.y() + status.height() <= win.height(), f"{w}x{h}: 状态区底边超出窗口"
        for btn in visible_nav():
            assert btn.height() >= win._DOCK_NAV_BTN_H_MIN, f"{w}x{h}: 导航按钮被压到 {btn.height()}"
            assert btn.height() <= win._DOCK_NAV_BTN_H, f"{w}x{h}: 导航按钮被拉高到 {btn.height()}"

    # ③ 窗口拉高后逐值复原设计几何（1920x1170：状态区贴底、导航用设计高/间距）
    # 设计值一律从 _DOCK_* 常量推导：改一次设计不必再改这里的硬编码
    win.resize(1920, 1170)
    app.processEvents()
    nav_top = ui.widget_buttons.y()
    btn_h, spacing = win._DOCK_NAV_BTN_H, win._DOCK_NAV_SPACING
    # 状态区是「底对齐锚定」：底边恒贴底留 40px，矩形高按文案行数推导（收款码块
    # 从下方顶上来时只会把矩形压矮，不会移动底边），故断言底边而非顶 y/固定高
    assert status.y() + status.height() == 1170 - win._DOCK_STATUS_BOTTOM_PAD, (
        f"设计态状态区底边未贴底留 {win._DOCK_STATUS_BOTTOM_PAD}px: "
        f"y={status.y()} height={status.height()}"
    )
    assert status.height() >= win._DOCK_STATUS_H_MIN, (
        f"设计态状态区高 {status.height()} < {win._DOCK_STATUS_H_MIN}"
    )
    assert ui.widget_buttons.height() == win._DOCK_NAV_H
    assert ui.verticalLayout.spacing() == spacing
    btns = visible_nav()
    for index, btn in enumerate(btns):
        assert btn.height() == btn_h and btn.maximumHeight() == btn_h
        assert btn.y() == index * (btn_h + spacing), (
            f"设计态第 {index} 个导航按钮 y={btn.y()}，期望 {index * (btn_h + spacing)}"
        )
    assert btns[-1].y() + btns[-1].height() <= nav_top + win._DOCK_NAV_H, "设计态按钮越出导航容器"
    assert ui.label_local_number.y() == 1109

    # ④ 隐藏「演员管理/信息管理」两项（配置项）后按可见数量排布，仍不重叠
    ui.pushButton_emby_manager_nav.setVisible(False)
    ui.pushButton_nfo_library.setVisible(False)
    win.resize(741, 504)
    app.processEvents()
    btns = visible_nav()
    assert len(btns) == 6
    step = btn_h + spacing
    assert [b.y() for b in btns] == [i * step for i in range(6)], "隐藏导航项后间距未按设计重排"
    assert status.y() >= nav_bottom()


def test_donate_block_is_centered_and_keeps_text_gap_at_any_height(win, app):
    """收款码块在任意窗口高度下：边长恒定且居中 + 「[赞助作者]→状态文字」间距恒定。

    回归背景：① 二维码块原先顶对齐在导航区下方，多余空间全落下方，而状态文字是
    底对齐（rect 越高文字越靠下），两边叠加导致最大化后「[赞助作者]」与
    「正常模式·字段优先」的间距从 17px 暴涨到 331px（用户反馈截图），
    改为底部锚定后两者都应与窗口高度无关；② 二维码边长上限先后在「侧栏宽（满宽不留
    白）」、「恒定 176」、「恒定 168」与「恒定 180」之间来回改过，两档不一致被用户指出
    （最大化时直接顶到左右边界；176 时最大化留白 17px 而还原窗口 21px，差 4px）。
    180 是收窄三处缝隙（_DONATE_LINK_GAP 6→2、_DONATE_PAD 6→2、_DONATE_TEXT_GAP 17→10）
    换来的，默认窗口下的高度预算：
        avail = 198 − max(TEXT_GAP, PAD + STATUS_H_MIN − text_h) − LINK_GAP − PAD
              （198 = status_bottom 690 − text_h 60 − LINK_H 22 − nav_bottom 410）
              = 198 − max(10, 72+2−60) − 2 − 2 = 198 − 14 − 2 − 2 = 180
    _DONATE_QR_SIZE 必须等于这个 avail，否则两态留白会不一致（见 main_window 常量注释）。
    """
    _goto(win, app, "page_main")
    win.setMinimumSize(0, 0)
    ui = win.Ui
    qr, link, status = ui.label_donate_qr, ui.label_donate_link, ui.label_show_version
    side_w = ui.widget_setting.width()
    gaps: dict[int, int] = {}
    pads: dict[int, tuple[int, int]] = {}

    for height in (693, 700, 737, 900, 1080, 1200):
        win.resize(1032, height)
        win.show()
        app.processEvents()
        assert not qr.isHidden() and not link.isHidden(), f"{height}: 收款码块被隐藏"
        # 水平居中，左右留白相等（奇数边长时差 1px 属正常取整）
        pad_l, pad_r = qr.x(), side_w - qr.x() - qr.width()
        pads[height] = (pad_l, pad_r)
        assert abs(pad_l - pad_r) <= 1, f"{height}: 二维码左右留白不等 {pad_l}/{pad_r}"
        # 边长恒为 _DONATE_QR_SIZE（不随窗口高度变大），只有太矮放不下才等比缩小
        assert qr.width() <= win._DONATE_QR_SIZE, (
            f"{height}: 二维码 {qr.width()} 超过设计边长 {win._DONATE_QR_SIZE}"
        )
        if height >= 700:  # 默认窗口高度（693 客户区/700 外框）以上应正好等于设计边长
            assert qr.width() == win._DONATE_QR_SIZE, (
                f"{height}: 二维码 {qr.width()} != 设计边长 {win._DONATE_QR_SIZE}"
            )
            assert pad_l == (side_w - win._DONATE_QR_SIZE) // 2, f"{height}: 左右留白 {pad_l}"
        # 「[赞助作者]」底边到状态文字首行的间距。文字在矩形内底对齐，故文字顶 =
        # 矩形底 − 文字块高（_dock_status_text_h 按字体度量算，不用写死）
        link_bottom = link.y() + link.height()
        text_top = status.y() + status.height() - win._dock_status_text_h()
        gaps[height] = text_top - link_bottom
        # 三者仍不重叠
        for a, b in ((qr, link), (link, status), (qr, status)):
            assert a.geometry().intersects(b.geometry()) is False, (
                f"{height}: {a.objectName()} 与 {b.objectName()} 矩形相交"
            )

    # 间距不小于设计下限，且**与窗口高度无关**（这才是用户反馈的回归点）
    assert min(gaps.values()) >= win._DONATE_TEXT_GAP, f"间距 {gaps} 小于 {_DONATE_TEXT_GAP}"
    assert len(set(gaps.values())) == 1, f"间距随窗口高度变化：{gaps}"
    # 同理，左右留白也必须与窗口高度无关：边长上限一旦大于默认窗口下的实测边长，
    # 最大化时二维码就会涨到上限、留白变小（176 时最大化 17px vs 还原 21px，差 4px）
    assert len(set(pads.values())) == 1, f"左右留白随窗口高度变化：{pads}"


def test_adaptive_window_sizes_matrix():
    """_adaptive_window_sizes 纯函数：常见屏幕档位的 (min_w, min_h, def_w, def_h)。"""
    from mdcx.controllers.main_window.init import _adaptive_window_sizes

    # 1080p 无缩放（可用 1920x1040）：回到设计值，主页面内容完整
    assert _adaptive_window_sizes(1920, 1040) == (850, 650, 1030, 700)
    # 1080p 125% 缩放（逻辑 1536x864）：92ef2437 的原始诉求——不锁死 700，仍可缩到 648
    assert _adaptive_window_sizes(1536, 864) == (850, 648, 1030, 700)
    # 小屏（1024x600 可用）：宽高各自独立收窄，不占满屏幕
    assert _adaptive_window_sizes(1024, 600) == (614, 450, 921, 510)
    # 超小屏下限钳制：不得低于 400x300（此时最小尺寸兜底）
    assert _adaptive_window_sizes(500, 350) == (400, 300, 450, 300)


def test_adaptive_window_sizes_never_exceed_available_area():
    """任意分辨率 / 任意界面缩放：默认尺寸不超出屏幕可用区，且不低于最小尺寸。

    默认尺寸公式是历史行为（宽高各自独立收缩，80% 缩放下必须仍是 1030×700），
    界面缩放档位超屏由设置页「高分屏缩放」下拉隐藏该档位来防，此处只保证
    窗口本身完整落在屏幕内。
    """
    from mdcx.controllers.main_window.init import _adaptive_window_sizes

    # 覆盖 4K/1080p/720p/竖屏与「界面缩放很大（可用逻辑区被压缩）」的典型档位
    for avail_w, avail_h in (
        (3840, 2000),
        (2560, 1400),
        (1920, 1040),
        (1536, 864),
        (1280, 1024),
        (1280, 720),
        (1024, 600),
        (960, 540),
        (1097, 594),  # 1080p @ 175% 缩放
        (960, 520),  # 1080p @ 200% 缩放
        (640, 360),  # 1080p @ 300% 缩放
        (800, 600),
        (500, 350),
    ):
        min_w, min_h, def_w, def_h = _adaptive_window_sizes(avail_w, avail_h)
        assert def_w <= avail_w and def_h <= avail_h, f"默认尺寸 {def_w}x{def_h} 超出屏幕可用区 {avail_w}x{avail_h}"
        assert def_w >= min_w and def_h >= min_h, f"默认尺寸 {def_w}x{def_h} 低于最小尺寸 {min_w}x{min_h}"


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
    # 首次显示必须同时居中（任何分辨率/缩放率下都应在可用区正中央）
    frame = win.frameGeometry()
    assert abs(frame.center().x() - avail.center().x()) <= 1 and abs(frame.center().y() - avail.center().y()) <= 1, (
        f"首次显示未居中: frame={frame} avail={avail}"
    )


def test_main_window_recenter_after_manual_move(win, app):
    """_center_on_screen 与用户手动摆放无关：任意位置调用都能拉回可用区正中。"""
    from PyQt6.QtWidgets import QApplication

    screen = QApplication.primaryScreen()
    assert screen is not None, "前置失败：offscreen 平台应有虚拟屏"
    avail = screen.availableGeometry()
    win.show()
    app.processEvents()
    win.move(avail.x() + 7, avail.y() + 13)
    win._center_on_screen()
    frame = win.frameGeometry()
    # 奇数像素余量无法整除，±1px 属整数取整的正常误差
    assert abs(frame.center().x() - avail.center().x()) <= 1 and abs(frame.center().y() - avail.center().y()) <= 1, (
        f"重新居中失败: frame={frame} avail={avail}"
    )
    # 窗口比可用区还大时（超小屏）至少保证左上角留在屏内，标题栏不会跑到屏外
    win.resize(avail.width() + 400, avail.height() + 300)
    win._center_on_screen()
    assert win.frameGeometry().topLeft() == avail.topLeft(), "超尺寸时应贴可用区左上角"


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
    # 宽态钉宽（目标列对齐接管前缀：值约 340，不再是标题控制器的旧大前缀），
    # 休眠 resize 不得改动，记下来当比对基准。
    wide_mins = tuple(cb.minimumWidth() for cb in (st, outline, plot))

    # A. 休眠后返回窄态：钩子必须跑过（清掉宽态残留），但不断言严格对齐
    _goto(win, app, "page_log")
    app.processEvents()
    win.resize(1000, 760)
    app.processEvents()
    stale = tuple(cb.minimumWidth() for cb in (st, outline, plot))
    assert stale == wide_mins, f"前置条件：休眠 resize 后宽态前缀应原样残留 {stale} vs {wide_mins}"
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

    # 宽态（1900）：mpaa/runtime 仍与 rd 同列（目标列控制器把整列搬到演员列，
    # 相对关系不变）；country/year 的钉宽改由目标列控制器写入（min=max 到演员列），
    # 故旧“零残留”断言改为新契约断言。
    win.resize(1900, 1050)
    goto_nfo_tab()
    app.processEvents()
    assert mpaa.x() == rd.x() == runtime.x(), f"宽态三者应对齐: mpaa={mpaa.x()} rd={rd.x()} runtime={runtime.x()}"
    gap141 = ui.horizontalLayout_141.spacing()
    gap40 = ui.horizontalLayout_40.spacing()
    assert country.minimumWidth() == country.maximumWidth() == ui.checkBox_tag_actor.x() - country.x() - gap141, (
        f"宽态 country 未钉到演员列: min={country.minimumWidth()} max={country.maximumWidth()}"
    )
    assert year.minimumWidth() == year.maximumWidth() == ui.checkBox_tag_actor.x() - year.x() - gap40, (
        f"宽态 year 未钉到演员列: min={year.minimumWidth()} max={year.maximumWidth()}"
    )


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

    # 无操作检查（700/750）：天然对齐，条件式无触发、约束零残留
    for w in (700, 750):
        win.resize(w, 700)
        goto_nfo_tab()
        app.processEvents()
        assert custom.x() == pr.x() == votes.x(), f"{w}宽三者应对齐"
        assert mpaa.minimumWidth() == 0, f"{w}宽 mpaa 不应残留最小宽"
        assert mpaa.maximumWidth() == 16777215, f"{w}宽 mpaa 不应残留最大宽"
        assert runtime.minimumWidth() == 0, f"{w}宽 runtime 不应残留最小宽"
        assert runtime.maximumWidth() == 16777215, f"{w}宽 runtime 不应残留最大宽"

    # 宽态（1900）：custom/votes 仍与 pr 同列（目标列控制器把整列搬到分级列）；
    # mpaa/runtime 的钉宽改由目标列控制器写入（min=max 到分级列），旧“零残留”
    # 断言改为新契约断言。
    win.resize(1900, 1050)
    goto_nfo_tab()
    app.processEvents()
    assert custom.x() == pr.x() == votes.x(), "1900宽三者应对齐"
    gap141 = ui.horizontalLayout_141.spacing()
    gap40 = ui.horizontalLayout_40.spacing()
    assert (
        mpaa.minimumWidth()
        == mpaa.maximumWidth()
        == ui.checkBox_tag_definition.x() - ui.checkBox_tag_actor.x() - gap141
    ), f"1900宽 mpaa 未钉到分级列: min={mpaa.minimumWidth()} max={mpaa.maximumWidth()}"
    assert (
        runtime.minimumWidth()
        == runtime.maximumWidth()
        == ui.checkBox_tag_definition.x() - ui.checkBox_tag_actor.x() - gap40
    ), f"1900宽 runtime 未钉到分级列: min={runtime.minimumWidth()} max={runtime.maximumWidth()}"


def test_nfo_targets_align_to_tag_columns_when_wide(win, app, monkeypatch):
    """设置-NFO：宽态下目标两列左移到演员/剧集列与分级/片商列，锚点不动，窄态逐像素不变。

    A 组（原标题/剧情/发行日期/分级/时长，五 HBox 行第 2 项）== 演员 == 剧集；
    B 组（简介/首映/自定义评分/投票 + 影评/导演/TMDB/标签）== 分级 == 片商。
    _sync_nfo_target_column_align：首项/第 2 项钉宽 + 两项行尾间隔 + C1 列最小宽；
    窄态复位并重跑右列/标题/行/尾控制器（逐像素无残留）。
    """
    ui = win.Ui
    group_a = (
        ui.checkBox_nfo_originaltitle,
        ui.checkBox_nfo_plot,
        ui.checkBox_nfo_relasedate,
        ui.checkBox_nfo_mpaa,
        ui.checkBox_nfo_runtime,
    )
    group_b = (
        ui.checkBox_nfo_originalplot,
        ui.checkBox_nfo_premiered,
        ui.checkBox_nfo_customrating,
        ui.checkBox_nfo_wanted,
        ui.checkBox_nfo_criticrating,
        ui.checkBox_nfo_director,
        ui.checkBox_nfo_actor_tmdbid,
        ui.checkBox_nfo_tag,
    )
    firsts = (
        ui.checkBox_nfo_sorttitle,
        ui.checkBox_nfo_outline,
        ui.checkBox_nfo_release,
        ui.checkBox_nfo_country,
        ui.checkBox_nfo_year,
    )
    anchors_a = (ui.checkBox_tag_actor, ui.checkBox_tag_series)
    anchors_b = (ui.checkBox_tag_definition, ui.checkBox_tag_studio)
    watched = (
        group_a
        + group_b
        + firsts
        + anchors_a
        + anchors_b
        + (
            ui.checkBox_nfo_score,
            ui.checkBox_nfo_actor,
            ui.checkBox_nfo_all_actor,
            ui.checkBox_nfo_series,
        )
    )

    def goto_nfo_tab():
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(ui.checkBox_nfo_score), "checkBox_nfo_score") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    def snap():
        d = {cb.objectName(): (cb.x(), cb.y(), cb.width()) for cb in watched}
        d["C1min"] = ui.gridLayout_66.columnMinimumWidth(1)
        return d

    def baseline():
        from mdcx.controllers.main_window import main_window as mw_mod

        cls = mw_mod.MyMAinWindow
        orig = cls._sync_nfo_target_column_align
        monkeypatch.setattr(cls, "_sync_nfo_target_column_align", lambda self: None)
        try:
            win._sync_page_layouts()
            app.processEvents()
            base = snap()
        finally:
            monkeypatch.setattr(cls, "_sync_nfo_target_column_align", orig)
        win._sync_page_layouts()
        app.processEvents()
        return base

    win.show()
    for w, h in ((1900, 1050), (1920, 1170)):
        win.resize(w, h)
        goto_nfo_tab()
        app.processEvents()
        assert ui.checkBox_tag_actor.x() == ui.checkBox_tag_series.x(), "锚 A 两列本来就没对齐"
        assert ui.checkBox_tag_definition.x() == ui.checkBox_tag_studio.x(), "锚 B 两列本来就没对齐"
        for cb in group_a:
            assert cb.x() == ui.checkBox_tag_actor.x(), f"宽态 {cb.objectName()} 未到演员列"
        for cb in group_b:
            assert cb.x() == ui.checkBox_tag_definition.x(), f"宽态 {cb.objectName()} 未到分级列"
        # 锚点 x 与所有人 y 不动（对照摘掉本方法后的基线）
        new = snap()
        base = baseline()
        for cb in anchors_a + anchors_b:
            assert new[cb.objectName()][0] == base[cb.objectName()][0], f"宽态锚点移动 {cb.objectName()}"
        for cb in watched:
            assert new[cb.objectName()][1] == base[cb.objectName()][1], f"宽态上下移动 {cb.objectName()}"
        # 机制残留：两项行尾间隔恰一枚、C1 列最小宽已钳制
        assert len(win._nfo_target_col_tails) == 1, "宽态两项行尾间隔缺失"
        assert ui.gridLayout_66.columnMinimumWidth(1) > 0, "宽态 C1 未钳制"
        # 幂等：再同步一次位置不变
        win._sync_page_layouts()
        app.processEvents()
        assert snap() == new, "宽态二次同步漂移"

    # 窄态：与摘掉本方法后的基线逐像素一致、无尾间隔残留
    for w, h in ((1030, 753), (900, 700)):
        win.resize(w, h)
        goto_nfo_tab()
        app.processEvents()
        assert snap() == baseline(), f"{w}宽窄态被改动"
    assert win._nfo_target_col_tails == [], "窄态残留尾间隔"


def test_nfo_debug_tmp(win, app):
    import mdcx.controllers.main_window.main_window as mw_mod

    calls = []
    orig = mw_mod.MyMAinWindow._sync_nfo_target_column_align

    def wrap(self):
        calls.append((ui.checkBox_tag_actor.x(), ui.checkBox_tag_definition.x()))
        r = orig(self)
        calls.append(("pinned", ui.checkBox_nfo_sorttitle.width(), ui.checkBox_tag_actor.x()))
        return r

    mw_mod.MyMAinWindow._sync_nfo_target_column_align = wrap
    try:
        ui = win.Ui
        win.show()
        win.resize(1900, 1050)
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(ui.checkBox_nfo_score), "checkBox_nfo_score") is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()
        print("calls:", calls)
        st, ot = ui.checkBox_nfo_sorttitle, ui.checkBox_nfo_originaltitle
        print(f"final: st=({st.x()},{st.width()}) ot=({ot.x()},{ot.width()}) actor={ui.checkBox_tag_actor.x()}")
    finally:
        mw_mod.MyMAinWindow._sync_nfo_target_column_align = orig


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


def test_nfo_groupbox_resyncs_after_stale_stretch(win, app):
    """设置-NFO：组框右缘看齐水印/演员组（左缘 x=30 不动）。

    用户截图：NFO 组框左右边界宽度大于水印/演员组，要求只把 NFO 右边界
    向左收到一样宽，水印/演员不做任何修改，面板内控件位置不变。
    结论（清理式）：设计宽回到 701（= 水印/演员），差值 diff=Δvp 裸奔；
    动态控制器已删除（它与 wide-sync 同构，设计 701 时纯冗余，且曾因
    tab_7(837)/内部 stacked(833) 框 confusion 用错边距 65 overshoot 到 742）。
    自然 wide-sync（组宽=701+extra）在两视口相等时两组天然等宽。
    本测试故障注入（改窄 64px）后断言收敛到诚实公式 701+(视口-设计宽)
    （全实测值，无魔法数），并跨页黑盒锁死两组严格等宽
    （1089/1900；700 挤压地板舍入允许 ±3）。
    """
    ui = win.Ui
    gb81 = ui.groupBox_81
    gb31 = ui.groupBox_31

    def goto_tab_by_box(box, name):
        _goto(win, app, "page_setting")
        for i in range(ui.tabWidget.count()):
            if ui.tabWidget.widget(i).findChild(type(box), name) is not None:
                ui.tabWidget.setCurrentIndex(i)
                break
        app.processEvents()

    win.show()
    for w in (700, 1089, 1900):
        win.resize(w, 900)
        goto_tab_by_box(gb81, "groupBox_81")
        app.processEvents()
        before = (gb81.x(), gb81.y(), gb81.height())
        # 故障注入：模拟 stale stretch（改窄 64px），与时序无关。
        # 自然 wide-sync（+trailing 重跑）把它收敛回诚实公式，全实测值。
        # 收敛环：跨 beats 重跑至收敛（至多 3 轮），首轮即收敛时直接退出。
        gb81.resize(gb81.width() - 64, gb81.height())
        app.processEvents()
        sc13 = ui.scrollArea_13
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
            vp = sc13.viewport().width()
            dw = sc13.widget()._wide_children_design_width
            if gb81.width() == max(701 + (vp - dw), 701 // 2):
                break
        vp = sc13.viewport().width()
        dw = sc13.widget()._wide_children_design_width
        assert gb81.width() == max(701 + (vp - dw), 701 // 2), (
            f"{w}宽 组框未收敛到诚实公式: 组宽={gb81.width()} 诚实值={max(701 + (vp - dw), 701 // 2)}(vp={vp},dw={dw})"
        )
        assert (gb81.x(), gb81.y(), gb81.height()) == before, f"{w}宽 组位移或变形"
        # 跨页黑盒锁死用户诉求：切水印页实测兄弟组宽（全实测值，无魔法数）。
        # NFO 页休眠后组宽冻结（控制器守卫跳过），读到的正是收敛终态。
        goto_tab_by_box(gb31, "groupBox_31")
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
        if w >= 1089:
            assert gb81.width() == gb31.width(), f"{w}宽 两组不等宽: nfo={gb81.width()} 水印={gb31.width()}"
        else:
            assert abs(gb81.width() - gb31.width()) <= 3, f"{w}宽 两组差超3px: nfo={gb81.width()} 水印={gb31.width()}"


def test_nfo_field_tips_no_jump_on_first_open(win, app):
    """首开 NFO 字段说明按钮不得跳动：冷窗 + 900 窄宽 + 零外部 beats，一次落定。

    用户报障：初次打开设置-NFO 的瞬间按钮从右边跳到左边，再次打开正常。
    根因：tab 切换只走双拍 beats（直接读 stale 几何会钉错 thirds），paint
    跑在 beats 之前；首开第一拍常读到中间态视口（滚动条闪烁），trailing
    定格偏窄组框，pin 误判溢出左移 → 可见跳动；第二拍落定后复位，
    之后各次几何已稳、beats 全 no-op。
    回归断言：冷窗 resize(900) → show → 切设置页 → 裸切 NFO tab
    （零外部 processEvents，同步 settle 必须在 direct 钩子里一次落定，
    paint 之前），按钮即终态；随后全量+beats 幂等、无位移。
    全实测值：期望 pin 位按诚实公式 701+(视口-设计宽) 现场算（900 宽下
    溢出确定，stale 组 701 下按钮停 640 必挂），不硬编码。
    """
    ui = win.Ui
    btn = ui.pushButton_field_tips_nfo
    gb = ui.groupBox_81
    sc = ui.scrollArea_13
    win.resize(900, 700)
    win.show()
    _goto(win, app, "page_setting")
    y0 = btn.y()
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).findChild(type(btn), "pushButton_field_tips_nfo") is not None:
            ui.tabWidget.setCurrentIndex(i)
            break
    # 零外部 beats：到此 direct settle 已跑完（内部泵收敛），按钮须已是终态
    vp = sc.viewport().width()
    dw = sc.widget()._wide_children_design_width
    honest_gb = max(701 + (vp - dw), 701 // 2)
    assert gb.width() == honest_gb, f"首开组框未落定: {gb.width()} != {honest_gb}(vp={vp},dw={dw})"
    limit = gb.x() + gb.width() - 11
    expect_x = 640 if 640 + btn.width() <= limit else limit - btn.width()
    assert btn.x() == expect_x, f"首开按钮未一次落定: btn.x={btn.x()} 期望={expect_x}(limit={limit})"
    assert btn.x() + btn.width() <= limit, "首开按钮溢出组框"
    assert btn.y() == y0, "按钮上下移动了"
    # 幂等：后续全量+beats 纹丝不动（首遍即终态，无跳动可跳）
    snap = (btn.x(), btn.y())
    for _ in range(3):
        win._sync_page_layouts()
        app.processEvents()
    assert (btn.x(), btn.y()) == snap, f"非幂等: {snap} -> {(btn.x(), btn.y())}"


def test_settings_scrollbars_uniform_width_across_tabs(win, app):
    """设置页各页签竖向滚动条厚度必须逐像素一致（分数缩放不等宽修复回归）。

    用户实测四条：100% 缩放各页一致；80% 缩放启动后先点开过的页正常、没点
    过的更窄；等 30~60 秒或最大化再还原后全齐；且每次异常页都不同。
    根因：QScrollBar 厚度指标要控件被 polish、且滚动区被真正布局过才有，
    而 QStackedWidget 只布局当前页——未点开的页签滚动条从未被布局（离屏
    实测其 width() 报 Qt 默认 100x30 的长度 100），分数缩放（样式 16px
    ×0.8=12.8）下两种厚度取整到不同设备像素，于是"谁被打开谁先变齐"。
    修复见 main_window._sync_settings_scrollbar_widths。
    回归做法：先逐个点开所有页签（复刻生产"已布局"状态，厚度应统一落在
    合理区间），再把两页改窄模拟未布局/未抛光页，调用控制器后各页必须被
    统一到最宽者；组框几何原样恢复（视口随厚度复原，不留持久位移），
    二次调用幂等。
    """
    from mdcx.views.CustomClass import CustomScrollArea

    ui = win.Ui
    win.resize(1089, 700)
    win.show()
    _goto(win, app, "page_setting")

    found = []
    for i in range(ui.tabWidget.count()):
        page = ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea)
        if area is not None:
            found.append((page.objectName(), area.verticalScrollBar()))
    assert len(found) >= 10, f"页签滚动区数量异常: {len(found)}"

    # 逐个点开：QStackedWidget 只布局当前页，点开过才有真实厚度
    for i in range(ui.tabWidget.count()):
        ui.tabWidget.setCurrentIndex(i)
        app.processEvents()
    widths = {name: bar.width() for name, bar in found}
    assert len(set(widths.values())) == 1, f"点开后各页厚度仍不一致: {widths}"
    target = next(iter(widths.values()))
    assert 8 <= target <= 48, f"点开后厚度不在合理区间（未布局?）: {target}"
    gb = ui.groupBox_81
    before = (gb.x(), gb.y(), gb.width(), gb.height())

    # 故障注入：两页改窄 4px，模拟未布局（80% 下走另一种取整厚度）状态
    for _name, bar in found[:2]:
        bar.setFixedWidth(max(8, target - 4))
    assert any(bar.width() != target for _name, bar in found), "故障注入未生效"

    win._sync_settings_scrollbar_widths()
    app.processEvents()
    fixed = {name: bar.width() for name, bar in found}
    assert len(set(fixed.values())) == 1, f"各页滚动条仍不等宽: {fixed}"
    assert next(iter(fixed.values())) == target, f"未统一到最宽者: {fixed}(target={target})"
    after = (gb.x(), gb.y(), gb.width(), gb.height())
    assert after == before, f"组框几何漂移: {before} -> {after}"
    win._sync_settings_scrollbar_widths()
    app.processEvents()
    assert {name: bar.width() for name, bar in found} == fixed, "非幂等"


def test_settings_scrollbars_use_declared_thickness_not_stale_geometry(win, app):
    """滚动条厚度取 QSS 声明值，不被"未布局页"的陈旧几何拉低（随机页签变窄回归）。

    用户现象：首开某页签滚动条是宽的，切到别的页签再回来就变窄，且每次落在
    随机页签、永不恢复；80% 分数缩放下最明显落在字幕/水印/演员/网络/高级五页。
    根因（离屏整窗 + 逐像素 grab 实测）：QSS 权威厚度
    `QScrollBar:vertical{width:16px}` 落在 sizeHint 上，而 width() 只是控件当前
    几何——未被 polish / 未被布局的页签停在平台默认 PM_ScrollBarExtent（实测 12）。
    控制器若读 width() 再取 min，一次坏读数就把 12 页一齐 setFixedWidth(12)
    钉死（min=max 覆盖 QSS），此后永远回不到 16。修前 11 页里 10 页 grab() 出
    12px，修后全部 16px。

    回归做法：给 page_setting 挂真实滚动条 QSS，复刻生产"厚度声明 16 / 几何停在
    平台默认"的混合态 → 调控制器 → 12 页必须全部回到声明厚度，且逐条钉成
    min=max=target（不留"几何恰好已等于 target 就放过"的口子，那是随机页签的
    残余）；再切走切回（用户操作序列）复跑，仍须稳定不降级。附带锁住"取最宽者"：
    注入的窄几何不得成为基准。
    """
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.views.CustomClass import CustomScrollArea

    ui = win.Ui
    win.resize(1089, 700)
    win.show()
    _goto(win, app, "page_setting")
    # 只补滚动条 QSS：本用例只关心厚度声明，几何测试不需要整窗样式
    ui.page_setting.setStyleSheet(style_mod.build_scrollbar_style(False))
    app.processEvents()
    app.processEvents()

    bars = []
    for i in range(ui.tabWidget.count()):
        page = ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea)
        if area is not None:
            bars.append(area.verticalScrollBar())
    assert len(bars) >= 10, f"页签滚动区数量异常: {len(bars)}"

    declared = {bar.sizeHint().width() for bar in bars}
    assert len(declared) == 1, f"QSS 声明厚度应逐页一致: {declared}"
    target = next(iter(declared))
    assert 8 <= target <= 48, f"声明厚度不在合理区间: {target}"

    # 故障注入：几页几何被压到"未布局"的陈旧值（QSS 声明仍是 target）
    stale = max(8, target - 2)
    for bar in bars[:3]:
        bar.setFixedWidth(stale)
    app.processEvents()
    assert any(bar.width() == stale for bar in bars), "故障注入未生效"
    assert all(bar.sizeHint().width() == target for bar in bars), "sizeHint 不应受几何影响"

    win._sync_settings_scrollbar_widths()
    app.processEvents()
    fixed = {bar.width() for bar in bars}
    assert fixed == {target}, f"未统一回 QSS 声明厚度: {fixed}(target={target},stale={stale})"
    # 逐条封死：所有页签都必须 min=max=target。只看 width() 会漏掉「几何恰好已经
    # 等于 target 而被放过」的那条——它没钉住，后续任意一次 polish/布局都能把它
    # 打回平台默认厚度，正是「随机落在某个页签」的残余。
    unpinned = [
        (i, bar.minimumWidth(), bar.maximumWidth())
        for i, bar in enumerate(bars)
        if bar.minimumWidth() != target or bar.maximumWidth() != target
    ]
    assert not unpinned, f"有页签未被钉死(仍只靠 QSS 撑着): {unpinned}"

    # 用户操作序列：切走再切回，复跑不得降级（旧实现此处已被钉死）
    ui.tabWidget.setCurrentIndex(0)
    app.processEvents()
    app.processEvents()
    win._sync_settings_scrollbar_widths()
    app.processEvents()
    ui.tabWidget.setCurrentIndex(4)
    app.processEvents()
    app.processEvents()
    win._sync_settings_scrollbar_widths()
    app.processEvents()
    assert {bar.width() for bar in bars} == {target}, "切页往返后厚度降级（旧 bug 复现）"
    unpinned = [
        (i, bar.minimumWidth(), bar.maximumWidth())
        for i, bar in enumerate(bars)
        if bar.minimumWidth() != target or bar.maximumWidth() != target
    ]
    assert not unpinned, f"切页往返后有页签掉出钉死态: {unpinned}"


def test_scroll_area_pins_scrollbar_thickness_on_show_without_timer(win, app):
    """滚动区自身在 show 时钉死厚度**并重新抛光**，不改绘制就等于没修（回归）。

    用户现象（两轮复测都复现）："异常页签"每次都换一批——先是字幕/水印/演员/
    网络/高级，修复后变成下载/刮削网站/刮削模式，我一直以为随机。真正的根因
    （按整窗合成图逐像素实测，不是看控件属性）：**Qt 在 polish 时把滚动条
    groove/handle 的子控件矩形缓存下来；`setFixedWidth` 只改几何、不让那份缓存
    失效，于是控件 `width()` 已经是 16、实际画出来的槽却还是抛光时的平台默认
    12px**。属性全对、画面是错的，所以前两轮"改几何"的修法在屏幕上毫无变化。
    为什么落在随机页签：一条条看起来宽，只是碰巧被别的事件（换肤、焦点、祖先
    样式表变动）顺带重新抛光过；最大化让整棵树重抛光，所以"看着好了"。

    本用例锁住下沉到控件的修法，且**完全不碰控制器、不依赖事件循环排序**：
    给滚动区挂真实滚动条 QSS → 注入"几何 16 / 绘制停在 12"的真实故障态
    （`setFixedWidth(窄值)` + `unpolish` + `polish`，即复刻陈旧缓存）→ 让该
    滚动区重新 show（触发 `showEvent` 的 `repolish=True`）→ 断言几何、约束
    （min=max）与绘制宽度都回到声明厚度；另锁幂等（resizeEvent 那条路径不得
    自激成 resize 回环）与"荒唐 sizeHint 不被采纳"。
    """
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.views.CustomClass import CustomScrollArea

    declared_px = 16
    # 压矮窗口让 12 页都真实溢出，滚动条才可见、绘制宽度才量得到
    # （本用例不逐个切页签，规避 NFO 页在矮窗下的既有崩溃）
    win.resize(1089, 420)
    win.show()
    _goto(win, app, "page_setting")

    areas = []
    for i in range(win.Ui.tabWidget.count()):
        page = win.Ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea) if page is not None else None
        if area is not None:
            area.setStyleSheet(style_mod.build_scrollbar_style(False))
            areas.append(area)
    assert len(areas) >= 10, f"页签滚动区数量异常: {len(areas)}"
    app.processEvents()
    app.processEvents()

    declared = {a.verticalScrollBar().sizeHint().width() for a in areas}
    assert declared == {declared_px}, f"QSS 声明厚度应为 {declared_px}: {declared}"

    stale = max(8, declared_px - 4)
    for area in areas:
        area.verticalScrollBar().setFixedWidth(stale)
    app.processEvents()
    assert any(a.verticalScrollBar().width() == stale for a in areas), "故障注入未生效"

    # 只调控件自身的方法：不经过控制器、不排定时器
    for area in areas:
        area.sync_scrollbar_thickness()
    app.processEvents()
    for i, area in enumerate(areas):
        bar = area.verticalScrollBar()
        assert bar.width() == declared_px, f"滚动区{i} 未回到声明厚度: {bar.width()}"
        assert bar.minimumWidth() == declared_px and bar.maximumWidth() == declared_px, (
            f"滚动区{i} 未钉死: min={bar.minimumWidth()} max={bar.maximumWidth()}"
        )

    # 幂等：已钉死时重复调用不得改动（否则 resizeEvent 里会自激成回环）
    before = [(a.verticalScrollBar().width(), a.verticalScrollBar().minimumWidth()) for a in areas]
    for area in areas:
        area.sync_scrollbar_thickness()
    app.processEvents()
    after = [(a.verticalScrollBar().width(), a.verticalScrollBar().minimumWidth()) for a in areas]
    assert after == before, f"重复调用非幂等: {before} -> {after}"

    # 关键：光改几何不够，必须重新抛光，否则 Qt 仍按抛光时的旧 groove 宽度绘制。
    # 注入"几何 16 / 绘制停在 12"的真实故障态（这正是用户看到的随机窄态），
    # 再走 showEvent 那条带 repolish 的路径，绘制宽度必须回到声明值。
    # 非当前页签的滚动区 isVisible() 为 False，量不到绘制，故逐页切换实测；
    # 跳过 NFO 页（tabWidget 下标 8），它在矮窗下会让本进程直接崩（既有崩溃）。
    def painted_width(bar):
        """量实际绘制的槽宽；离屏未真正绘制时返回 None（此时量不到，交给几何断言）。"""
        img = bar.grab().toImage()
        y = img.height() // 2
        row = [img.pixelColor(x, y) for x in range(img.width())]
        cols = [i for i, c in enumerate(row) if c != row[0]]
        if len({c.name() for c in row}) < 2:
            return None  # 整行同色 = 没画出来（grab 拿到的是空 backing store）
        return max(cols) - min(cols) + 1

    checked = 0
    for i in range(win.Ui.tabWidget.count()):
        if i == 8:
            continue
        win.Ui.tabWidget.setCurrentIndex(i)
        app.processEvents()
        app.processEvents()
        page = win.Ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea) if page is not None else None
        if area is None:
            continue
        bar = area.verticalScrollBar()
        assert bar.isVisible(), f"页签{i} 滚动条不可见，无法量绘制宽度"
        w_now = painted_width(bar)
        assert w_now in (None, declared_px), f"页签{i} 修法下应绘制 {declared_px}px，实际 {w_now}"
        # 复刻故障：退回平台默认厚度并重新抛光（= 陈旧缓存被刷新成窄值）
        bar.setFixedWidth(stale)
        bar.style().unpolish(bar)
        bar.style().polish(bar)
        app.processEvents()
        area.show()  # 触发 showEvent → repolish=True
        app.processEvents()
        app.processEvents()
        assert bar.width() == declared_px, f"页签{i} 几何未回到声明厚度: {bar.width()}"
        assert bar.minimumWidth() == declared_px and bar.maximumWidth() == declared_px, (
            f"页签{i} 未重新钉死: min={bar.minimumWidth()} max={bar.maximumWidth()}"
        )
        w_after = painted_width(bar)
        assert w_after in (None, declared_px), f"页签{i} 绘制宽度未回到声明厚度: {w_after}"
        checked += 1
    assert checked >= 10, f"实测页签数异常: {checked}"


def test_zimu_rows_align_to_filename_when_wide(win, app):
    """设置-字幕：最大化时两处左移到与「视频文件名」严格上下对齐，最小化复原。

    用户需求（最大化态）：「新添加字幕的视频在结束后重新刮削」复选框左移到
    与「视频文件名」左缘上下对齐（视频文件名自身保持不变）；「点击下载字幕包」
    左移到视频文件名下方（左缘同样对齐）；最小化时页面、布局、控件保持不变。
    根因：复选框被通用宽幅同步判为 _DOCK_RIGHT（右缘 661 ≥ 组宽 701*0.9），
    最大化时右移到右缘；下载行是横向均分布局，链接位置随列宽漂移。
    本测试锁定：宽态两处左缘 == 活测量的文件名左缘、参照与链接 y 不动、
    复选框行/绿色说明钉回设计 y、组框底部上收贴内容、组间距保持设计值、
    二次同步幂等；窄态复选框/链接/前导钉宽/行列数/组高/行 y 与基线逐值一致。
    """
    from PyQt6.QtCore import QPoint

    from mdcx.views.CustomClass import CustomScrollArea

    ui = win.Ui
    _goto(win, app, "page_setting")
    for i in range(ui.tabWidget.count()):
        page = ui.tabWidget.widget(i)
        area = page.findChild(CustomScrollArea)
        if (
            area is not None
            and area.widget() is not None
            and area.widget().objectName() == "scrollAreaWidgetContents_zimu"
        ):
            ui.tabWidget.setCurrentIndex(i)
            break
    app.processEvents()
    win.show()

    rs = ui.checkBox_sub_rescrape
    link = ui.label_download_sub_zip
    lead = ui.label_102
    lay = ui.horizontalLayout_10

    win.resize(1000, 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    base = {
        "rs": rs.geometry().getRect(),
        "link": link.geometry().getRect(),
        "link_align": link.alignment(),
        "lead_mm": (lead.minimumWidth(), lead.maximumWidth()),
        "count": lay.count(),
        "box": ui.groupBox_45.geometry().getRect(),
        "fn": ui.checkBox_filename.geometry().getRect(),
        "rows": [ui.gridLayout_27.cellRect(r, 1).height() for r in range(4)],
        "lay": lay.geometry().getRect(),
    }
    assert lay.count() == 2, f"窄态下载行列数异常: {lay.count()}"

    win.resize(1920, 1170)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    content = ui.scrollArea_9.widget()
    fn_cx = ui.checkBox_filename.mapTo(content, QPoint(0, 0)).x()
    box = ui.groupBox_45
    grid27 = ui.gridLayoutWidget_27
    assert rs.x() == fn_cx - box.x(), f"复选框未对齐文件名: rs.x={rs.x()} 期望={fn_cx - box.x()}"
    # 纵向均匀铺排：上方网格 4 行各增 unit，长按钮/复选框行/绿色说明跟进，
    # 下半部分相对位置保持紧凑（复选框行与绿色说明只比设计间隙多 unit//3）。
    zimu_scroll = getattr(win, "_zimu_scroll", None)
    assert zimu_scroll is not None
    filler = zimu_scroll.viewport().height() - (310 + 425) - zimu_scroll.content_bottom_margin()
    assert filler > 0, f"宽态无填充可验: filler={filler}"
    unit = filler // 8
    gap = unit // 3
    grid = ui.gridLayout_27
    base_rows = base["rows"]
    for r in range(4):
        assert grid.rowMinimumHeight(r) == base_rows[r] + unit, f"网格行{r}铺排异常: min={grid.rowMinimumHeight(r)}"
    assert grid27.height() == 186 + 4 * unit, f"网格容器未按铺排增高: h={grid27.height()}"
    assert ui.pushButton_add_sub_for_all_video.y() == 220 + 5 * unit, "长按钮未按铺排下移"
    assert (rs.y(), rs.width(), rs.height()) == (272 + 5 * unit + gap, 236, 30), (
        f"复选框行铺排异常: {rs.geometry().getRect()}"
    )
    assert ui.checkBox_sub_add_chs.y() == 272 + 5 * unit + gap, "同行复选框未同步铺排"
    # 绿色说明上提删掉下方多余底垫（与实现 _zimu_wide_rows 同式），
    # 组框按绿色说明底部贴合（只留 12px），且不越过复选框行。
    _checks_y = 272 + 5 * unit + gap
    _spread_teal = 309 + 5 * unit + 2 * gap
    _pad_full = 425 + filler - (_spread_teal + ui.label_125.height())
    _room = max(0, _spread_teal - (_checks_y + 38))
    _up = min(max(0, _pad_full - 12), _room)
    _teal_y = _spread_teal - _up
    _box_h = min(425 + filler, _teal_y + ui.label_125.height() + 12)
    assert ui.label_125.y() == _teal_y, f"绿色说明未上提: y={ui.label_125.y()} 期望={_teal_y}"
    assert ui.label_125.y() >= _checks_y + 38, "绿色说明越过复选框行"
    assert box.height() == _box_h, f"组框底边未同步上收: h={box.height()} 期望={_box_h}"
    assert box.height() - (ui.label_125.y() + ui.label_125.height()) == 12, "组框底垫未收至 12px"
    assert link.x() == fn_cx - box.x() - grid27.x(), (
        f"下载链接未对齐文件名: link.x={link.x()} 期望={fn_cx - box.x() - grid27.x()}"
    )
    # 链接行被第 0 行铺排顶下 unit，叠加行内垂直居中多下沉 unit//2；
    # 用行布局几何推导期望（DPI 鲁棒），链接自身高度不变。
    lay_geom = lay.geometry().getRect()
    assert lay_geom[1] == base["lay"][1] + unit, f"下载行未跟随铺排: y={lay_geom[1]}"
    assert link.y() == lay_geom[1] + (lay_geom[3] - link.height()) // 2, (
        f"下载链接行内居中异常: {link.geometry().getRect()}"
    )
    assert link.height() == base["link"][3], f"下载链接高度变化: {link.geometry().getRect()}"
    from PyQt6.QtCore import Qt as _Qt

    assert link.alignment() == (_Qt.AlignmentFlag.AlignLeft | _Qt.AlignmentFlag.AlignVCenter), (
        f"下载链接文字未左对齐: {link.alignment()}"
    )
    # 组间距保持设计值：y=310；组框底边已按绿色说明贴合上收（见上）。
    assert box.y() == 310, f"组间距被放大: y={box.y()}"
    assert zimu_scroll.verticalScrollBar().maximum() == 0, "宽态出现垂直滚动条"
    assert ui.checkBox_filename.y() == base["fn"][1], "视频文件名 y 移动"
    assert ui.checkBox_filename.height() == base["fn"][3], "视频文件名高变化"
    assert lead.minimumWidth() == lead.maximumWidth() == lead.sizeHint().width(), "前导说明未钉回自然宽"

    before = {
        "rs": rs.geometry().getRect(),
        "link": link.geometry().getRect(),
        "lead_mm": (lead.minimumWidth(), lead.maximumWidth()),
        "fn": ui.checkBox_filename.geometry().getRect(),
        "box": box.geometry().getRect(),
        "chs_y": ui.checkBox_sub_add_chs.y(),
        "teal_y": ui.label_125.y(),
        "btn_y": ui.pushButton_add_sub_for_all_video.y(),
        "grid_h": grid27.height(),
        "row_mins": [grid.rowMinimumHeight(r) for r in range(4)],
    }
    win._sync_page_layouts()
    app.processEvents()
    after = {
        "rs": rs.geometry().getRect(),
        "link": link.geometry().getRect(),
        "lead_mm": (lead.minimumWidth(), lead.maximumWidth()),
        "fn": ui.checkBox_filename.geometry().getRect(),
        "box": box.geometry().getRect(),
        "chs_y": ui.checkBox_sub_add_chs.y(),
        "teal_y": ui.label_125.y(),
        "btn_y": ui.pushButton_add_sub_for_all_video.y(),
        "grid_h": grid27.height(),
        "row_mins": [grid.rowMinimumHeight(r) for r in range(4)],
    }
    assert before == after, f"二次同步漂移: {before} -> {after}"

    win.resize(1000, 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    assert rs.geometry().getRect() == base["rs"], f"窄态复选框未复原: {rs.geometry().getRect()} vs {base['rs']}"
    assert ui.checkBox_sub_add_chs.geometry().getRect() == (162, 272, 169, 30), "窄态同行复选框 y 未复原"
    assert ui.label_125.y() == 309, "窄态绿色说明 y 未复原"
    assert ui.pushButton_add_sub_for_all_video.y() == 220, "窄态长按钮 y 未复原"
    assert ui.gridLayoutWidget_27.height() == 186, "窄态网格容器高未复原"
    assert [ui.gridLayout_27.rowMinimumHeight(r) for r in range(4)] == [0, 0, 0, 0], "窄态网格行最小高残留"
    assert link.geometry().getRect() == base["link"], f"窄态链接未复原: {link.geometry().getRect()} vs {base['link']}"
    assert lay.geometry().getRect() == base["lay"], "窄态下载行几何未复原"
    assert link.alignment() == base["link_align"], "窄态链接对齐残留"
    assert (lead.minimumWidth(), lead.maximumWidth()) == base["lead_mm"], "窄态前导钉宽残留"
    assert lay.count() == base["count"], f"窄态间隔未拆除: count={lay.count()}"
    assert ui.groupBox_45.geometry().getRect() == base["box"], "窄态组框 y/高未复原"


def _goto_naming_tab(win, app):
    """切到软件设置-命名页（三个命名规则组所在 tab）。"""
    ui = win.Ui
    _goto(win, app, "page_setting")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab_3":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("命名 tab_3 not found")
    app.processEvents()


@pytest.mark.parametrize("width", [1000, 1920])
def test_naming_filename_checkboxes_column_align(win, app, width):
    """命名页三处「视频文件名/空格」同列 + 「.小数点」与「不获取分辨率」同列。

    用户需求：马赛克命名规则的「视频文件名」右移到与画质命名规则「视频文件名」
    上下严格对齐；分隔符行的「 空格」同样右移对齐；最小化时把「.小数点」向左移动、
    最大化时向右移动到与「不获取分辨率」上下严格对齐（「不获取分辨率」保持不动）；
    窄态与宽态都必须生效。

    三个组都是命名滚动区内容的直接子控件、设计 x 同为 30 且宽态只加宽不改 x，
    故用「映射到滚动区内容的绝对 x」比对才是用户肉眼看到的对齐基准。
    根因防线：小数点右缘 560+110+1=671 ≥ 组宽 720*0.9=648，会被通用宽幅
    同步判为 _DOCK_RIGHT 在宽态额外右移 extra——故它必须留在
    CustomScrollArea._MANUAL_WIDGET_NAMES 里不被登记（宽态 1920 下若被登记，
    会先被推到 671+extra 再被本方法拉回，对齐值不变但多一次跳动；窄态则直接
    按登记位参与计算，量到的 none 仍是终态故结论不变，但为稳妥起见保持不登记）。
    注：此前「小数点与空格保持 140 设计间距、等距右随」的约定已被新需求取代——
    窄态下该约定本来也从未成立（空格被左移 47 而小数点纹丝不动，point-space 实测
    187 ≠ 140，正是本用例 [1000] 之前挂掉的原因）。
    """
    from PyQt6.QtCore import QPoint

    ui = win.Ui
    win.show()
    _goto_naming_tab(win, app)
    win.resize(width, 1170 if width > 1200 else 700)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()

    content = ui.scrollAreaWidgetContents_mingming
    mosaic = ui.checkBox_filename_mosaic
    hd = ui.checkBox_filename_4k
    space = ui.checkBox_cd_part_space
    point = ui.checkBox_cd_part_point
    underline = ui.checkBox_cd_part_underline
    none = ui.radioButton_videosize_none

    abs_x = lambda w: w.mapTo(content, QPoint(0, 0)).x()  # noqa: E731
    base_x = abs_x(hd)
    for label, w in (("马赛克视频文件名", mosaic), ("分隔符空格", space)):
        assert abs_x(w) == base_x, f"{width} 宽下 {label} 未与画质视频文件名同列: {abs_x(w)} vs {base_x}"
    # 「.小数点」两态都与「不获取分辨率」严格上下对齐（锚点不动，只动小数点；
    # 本方法从不写锚点几何，下面的复位快照会连带锁定锚点不被第二遍同步搬动）
    assert abs_x(point) == abs_x(none), f"{width} 宽下小数点未与不获取分辨率同列: {abs_x(point)} vs {abs_x(none)}"
    # 「_ 下划线」保持设计原位（局部 x=160），不受任何对齐改动（窄态 path 列本身
    # 随字体度量浮动：conftest 桩掉字体时 path/space/none 同步左移 15，190-388=-198；
    # 故不断言与 space 的相对值，只断言下划线自己纹丝不动）
    assert underline.x() == 160, f"{width} 宽下下划线被改动: x={underline.x()}"

    # 锚点「不获取分辨率」同样纳入复位快照：第二遍同步不得搬动它（需求：锚点保持不动）
    snap = {
        n: getattr(ui, n).geometry().getRect()
        for n in (
            "checkBox_filename_mosaic",
            "checkBox_filename_4k",
            "checkBox_cd_part_underline",
            "checkBox_cd_part_space",
            "checkBox_cd_part_point",
            "radioButton_videosize_none",
        )
    }
    win._sync_page_layouts()
    app.processEvents()
    after = {
        n: getattr(ui, n).geometry().getRect()
        for n in (
            "checkBox_filename_mosaic",
            "checkBox_filename_4k",
            "checkBox_cd_part_underline",
            "checkBox_cd_part_space",
            "checkBox_cd_part_point",
            "radioButton_videosize_none",
        )
    }
    assert snap == after, f"二次同步漂移: {snap} -> {after}"


def _goto_website_tab(win, app):
    """切到软件设置-刮削网站页（两个待对齐下拉框所在 tab，即 scrollArea_8 那一页）。"""
    ui = win.Ui
    _goto(win, app, "page_setting")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).findChild(ui.scrollArea_8.__class__, "scrollArea_8") is not None:
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("刮削网站 tab (scrollArea_8) not found")
    app.processEvents()


def _site_pref_rights(win):
    """「指定网站」「锁定类型」两个下拉框在公共祖先 content 里的右缘（+1 右开区间）。"""
    content = win.Ui.scrollArea_8.widget()
    out = []
    for name in ("comboBox_website_all", "comboBox_fixed_scraping_type"):
        widget = getattr(win.Ui, name)
        out.append(widget.mapTo(content, widget.rect().bottomRight()).x() + 1)
    return out


@pytest.mark.parametrize("width", [1030, 1920])
def test_site_pref_combo_right_aligns_to_fixed_type(win, app, width):
    """刮削网站页「指定网站」下拉框右缘收缩到「锁定类型」下拉框右缘（窄宽两态）。

    用户需求：「软件设置-刮削网站-指定网站下拉框右侧收缩到锁定类型右侧的位置」。
    根因：两个下拉框分属不同组框的不同网格（gridLayout_28 只有 2 列，
    gridLayout_36 有 4 列——多出「编辑网站」「网站优先」两个按钮列），列宽天然
    差 111px，「指定网站」下拉框因此比「锁定类型」多出 111px 右缘（窄态
    689 vs 578、宽态 1579 vs 1468，实测两态差值恒等）。
    _sync_site_pref_combo_width 按参考框实时右缘换算宽度上限并 setMaximumWidth
    钉住（不能用 move()，网格会覆盖绝对坐标），故窄宽两态都应收敛到差值 0。
    """
    ui = win.Ui
    _goto_website_tab(win, app)
    win.resize(width, 700 if width == 1030 else 1080)
    win.show()
    app.processEvents()
    for _ in range(3):  # 首次打开的几何要经 settle + 宽幅同步落定，多泵几轮事件
        win._sync_page_layouts()
        app.processEvents()

    combo_right, ref_right = _site_pref_rights(win)
    assert combo_right == ref_right, f"{width} 宽下指定网站右缘 {combo_right} 未对齐锁定类型 {ref_right}"
    # 宽度上限应恰为「参考右缘 - 本框左缘」；且只钉上限、不钉下限
    combo = ui.comboBox_website_all
    content = ui.scrollArea_8.widget()
    combo_x = combo.mapTo(content, combo.rect().topLeft()).x()
    assert combo.maximumWidth() == ref_right - combo_x, "宽度上限与目标宽度不符"
    assert combo.minimumWidth() == 0, "只应限制上限，不应钉死下限"
    # 参考框自身不得被本控制器改动（它是基准）
    ref = ui.comboBox_fixed_scraping_type
    assert (ref.minimumWidth(), ref.maximumWidth()) == (0, 16777215), "参考框被写入宽度约束"

    snap = _site_pref_rights(win)
    win._sync_page_layouts()
    app.processEvents()
    assert _site_pref_rights(win) == snap, f"{width} 宽下二次同步漂移: {snap} -> {_site_pref_rights(win)}"


def test_site_pref_combo_ignored_until_tab_opened(win, app):
    """从未打开过的刮削网站页签：不得据未布局的假读数把宽度钉死。

    取证坑：未布局页签里两个下拉框都停在 Qt 默认 100px 宽（实测 combo right=180、
    ref right=150，差 30），若不加可见性早退就会按这组假读数把 maximumWidth
    钉成 70，页签首次打开时宽度再也张不开。故休眠时整段早退、不碰约束。
    """
    ui = win.Ui
    combo = ui.comboBox_website_all
    design_max = combo.maximumWidth()  # .ui 声明的 maximumSize 宽（16000）
    # 切到设置页但停在别的 tab（不切刮削网站），制造「该 tab 从未打开」的状态
    _goto(win, app, "page_setting")
    ui.tabWidget.setCurrentIndex(0)
    win.resize(1030, 700)
    win.show()  # isVisibleTo 需要窗口真显示，否则休眠/可见判定不成立
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()
    assert not ui.scrollArea_8.isVisibleTo(win), "前置条件失败：刮削网站 tab 仍可见"
    assert combo.maximumWidth() == design_max, "休眠时不应写入宽度上限"

    # 切进该 tab 后应立刻对齐（currentChanged 的 settle/beats 会补跑全量同步）
    _goto_website_tab(win, app)
    for _ in range(3):
        win._sync_page_layouts()
        app.processEvents()
    combo_right, ref_right = _site_pref_rights(win)
    assert combo_right == ref_right, f"首次打开未对齐: 指定网站 {combo_right} vs 锁定类型 {ref_right}"
