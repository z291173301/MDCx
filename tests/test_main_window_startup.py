"""启动冒烟测试：offscreen 下完整构造主窗口。

回归背景：v2.0.6 NFO 库页布局修复引入了 PyQt5 风格的
`QLayout.setStretchFactor(index, stretch)` 调用，PyQt6 严格重载下
启动即抛 TypeError 崩溃（Windows 打包版首发时暴露）。本测试
在 CI 双平台（Linux offscreen / Windows offscreen）完整执行主窗口
初始化链（setupUi → Init_Singal → Init_Ui → load_config → ...），
任何签名不兼容/属性缺失都会在此暴露，而不是留给用户运行时发现。
"""

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


def test_main_window_startup_no_crash(app, monkeypatch, tmp_path):
    """MyMAinWindow 完整初始化不抛异常（含 Init_Singal 全部信号/布局调用）。"""
    # 打桩启动链中与 GUI 无关的副作用：网络自检/版本检查/剩余任务保存
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)

    monkeypatch.chdir(tmp_path)  # load_config/get_success_list 会写当前目录

    win = mw_mod.MyMAinWindow()
    try:
        assert win.Ui is not None
        # NFO 库页三栏 stretch 已应用（回归点：setStretch 而非 setStretchFactor(int)）
        layout = win.Ui.nfo_lib_content_layout
        assert layout.itemAt(0) is not None
        assert layout.itemAt(1) is not None
        assert layout.itemAt(2) is not None
    finally:
        win.timer.stop()
        win.timer_scrape.stop()
        win.timer_update.stop()
        win.timer_remain_task.stop()
        win.close()
        win.deleteLater()
        app.processEvents()


def test_emby_actor_manager_dialog_startup_no_crash(app):
    """Emby 演员管理器对话框完整构造不抛异常。

    覆盖 _init_ui 全部 Qt 控件构造路径（QSplitter/表格/日志区等），
    配合主窗口冒烟测试，防止 PyQt6 签名不兼容类问题推迟到用户
    打开窗口时才暴露。
    """
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        assert dlg.windowTitle() == "Emby/Jellyfin 演员管理器"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_settings_dialog_startup_no_crash(app):
    """Emby 演员管理器设置对话框完整构造不抛异常。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorSettingsDialog

    dlg = EmbyActorSettingsDialog()
    try:
        assert dlg.windowTitle()
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_table_has_birthday_and_location_columns(app):
    """议题 #134/#136：新增出生日期/出生地列；详情/标签列按 3:1 分配且总宽铺满。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        table = dlg.table
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        assert headers == ["状态", "姓名", "头像", "简介", "详情", "出生日期", "出生地", "标签", "影片数"]

        # #136：详情:标签 = 3:1（标签约为原等分宽度的一半），各列总宽铺满视口
        dlg.resize(1600, 900)
        dlg.show()
        app.processEvents()
        dlg._apply_column_widths()
        app.processEvents()
        detail_w = table.columnWidth(4)
        tags_w = table.columnWidth(7)
        assert detail_w == pytest.approx(tags_w * 3, rel=0.15), f"详情/标签非 3:1: {detail_w}:{tags_w}"
        total = sum(table.columnWidth(i) for i in range(table.columnCount()))
        assert total == pytest.approx(table.viewport().width(), abs=4), "各列总宽未铺满视口"
        # 固定列宽度保持不变
        assert table.columnWidth(0) == 50
        assert table.columnWidth(1) == 160
        assert table.columnWidth(5) == 110
        assert table.columnWidth(6) == 140
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_populates_birthday_and_location(app):
    """议题 #134：出生日期取 Emby PremiereDate 前 10 位，出生地按逗号拼接。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        actor = ActorInfo(
            name="测试演员",
            actor_id="1",
            server_id="s",
            existing_premiere_date="1994-08-26T00:00:00.0000000Z",
            existing_production_locations=["日本", "东京都"],
        )
        dlg._actors = [actor]
        dlg._populate_table(dlg._actors)
        assert dlg.table.item(0, 5).text() == "1994-08-26"
        assert dlg.table.item(0, 6).text() == "日本, 东京都"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_blank_birthday_placeholder(app):
    """议题 #134：Emby 未设置生日时返回 0001-01-01，列表中按空值展示。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        actor = ActorInfo(
            name="无生日演员",
            actor_id="2",
            server_id="s",
            existing_premiere_date="0001-01-01T00:00:00.0000000Z",
        )
        dlg._actors = [actor]
        dlg._populate_table(dlg._actors)
        assert dlg.table.item(0, 5).text() == ""
        assert dlg.table.item(0, 6).text() == ""
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_emby_actor_manager_columns_fit_after_vertical_scrollbar(app):
    """议题 #160：纵向滚动条显隐后列宽应重算，不产生横向滚动条。"""
    from PyQt6.QtCore import Qt

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    try:
        dlg.resize(1600, 900)
        dlg.show()
        app.processEvents()
        table = dlg.table
        hbar = table.horizontalScrollBar()

        # 强制显示纵向滚动条（模拟演员数量多时的场景），视口变窄
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        app.processEvents()
        total_on = sum(table.columnWidth(i) for i in range(table.columnCount()))
        assert total_on == pytest.approx(table.viewport().width(), abs=4), "纵滚动条显示后列宽未铺满视口"
        assert hbar.maximum() == 0, f"纵滚动条显示后出现横向滚动条: {hbar.maximum()}"

        # 隐藏纵向滚动条，视口变宽，同样不应出现横向滚动条
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        app.processEvents()
        total_off = sum(table.columnWidth(i) for i in range(table.columnCount()))
        assert total_off == pytest.approx(table.viewport().width(), abs=4), "纵滚动条隐藏后列宽未铺满视口"
        assert hbar.maximum() == 0, f"纵滚动条隐藏后出现横向滚动条: {hbar.maximum()}"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()
