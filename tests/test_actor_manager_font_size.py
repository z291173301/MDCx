"""演员管理器整体字号放大一号回归。

需求: 演员管理器（主窗 + 设置 / 数据源测试 / 演员详情 / 选择媒体库 等子窗口）字体
全部大一号; 例外只有左上角窗口标题「Emby/Jellyfin演员管理器」与设置窗口标题
「Emby/Jellyfin 演员设置」——两者都由系统窗口框绘制, QSS 天然不覆盖, 无需额外排除代码
(下方 test_window_titles_unchanged 把这两条标题文案钉住, 防止有人改用「换标题」绕开)。

实现要点（改动任一条都会让本文件失败）:
① 字号由 QSS `QWidget { font-size: Npt }` 统一下发, 不用 setFont: 样式表沿 QObject
   父子链级联, 独立顶层子对话框一并生效; 而 setFont 只对子控件生效, 子窗口仍是应用默认字号。
② 两处灰色提示文字（使用说明 / 双击行可编辑）不得再写死 font-size: 控件自身样式表优先级
   高于对话框样式表, 写死 12px 会把放大后的字号盖回去。
③ QWidget 规则只带 font-size, 不带 font-weight: 分组框标题的加粗必须保留。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


def _expected_pt() -> float:
    from mdcx.tools.emby_actor_manager_ui import _ui_font_pt

    return float(_ui_font_pt().removesuffix("pt"))


@pytest.fixture
def dlg(app):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dialog = EmbyActorManagerDialog()
    dialog.resize(1500, 900)
    dialog.show()
    app.processEvents()
    try:
        yield dialog
    finally:
        dialog.close()
        app.processEvents()


def test_ui_font_pt_is_base_plus_one():
    """字号基准取应用默认字号 +1 号（缺省 9pt 时得 10pt），不是写死的绝对值。"""
    from mdcx.tools.emby_actor_manager_ui import _ui_font_pt

    base = QApplication.font().pointSizeF()
    assert _ui_font_pt().endswith("pt"), "须返回带 pt 单位的 QSS 字号"
    if base > 0:  # 应用若用像素字号, 基准走 96dpi 折算, 不在此断言
        assert float(_ui_font_pt().removesuffix("pt")) == pytest.approx(base + 1)


def test_manager_widgets_all_use_bumped_font(dlg, app):
    """主窗内各类控件（按钮/下拉/表格/日志/状态栏/统计标签）字号统一 +1 号。"""
    expected = _expected_pt()
    widgets = {
        "连接按钮": dlg.btn_connect,
        "数据源测试按钮": dlg.btn_test_source,
        "清空缓存文件夹按钮": dlg.btn_clear_cache,
        "设置按钮": dlg.btn_settings,
        "开始全部更新同步按钮": dlg.btn_sync,
        "获取模式下拉": dlg.cmb_fetch_mode,
        "计数方式下拉": dlg.cmb_count_mode,
        "筛选下拉": dlg.cmb_filter,
        "搜索框": dlg.txt_search,
        "服务器地址输入框": dlg.txt_url,
        "演员表格": dlg.table,
        "运行日志": dlg.log_text,
        "状态栏": dlg.status_bar,
        "统计标签": dlg.lbl_total,
    }
    for name, widget in widgets.items():
        assert widget.font().pointSizeF() == pytest.approx(expected), f"{name} 字号未跟随放大"


def test_hint_labels_follow_bumped_font(dlg):
    """灰色提示文字不得写死 font-size, 否则会盖回放大前的字号。"""
    expected = _expected_pt()
    hints = [
        lbl for lbl in dlg.findChildren(QLabel) if lbl.text().startswith("使用说明") or lbl.text() == "双击行可编辑"
    ]
    assert len(hints) == 2, "应找到「使用说明」与「双击行可编辑」两处提示"
    for lbl in hints:
        assert "font-size" not in lbl.styleSheet(), f"提示文字写死了字号: {lbl.styleSheet()!r}"
        assert lbl.font().pointSizeF() == pytest.approx(expected)


def test_groupbox_titles_stay_bold(dlg):
    """QWidget 规则只带 font-size, 分组框标题的加粗不得被抹掉。"""
    from PyQt6.QtWidgets import QGroupBox

    expected = _expected_pt()
    groups = dlg.findChildren(QGroupBox)
    assert groups, "管理器内应有分组框"
    for group in groups:
        assert group.font().bold(), f"分组框 [{group.title()}] 标题失去加粗"
        assert group.font().pointSizeF() == pytest.approx(expected)


def test_stylesheet_declares_widget_font_size_rule(dlg):
    """字号必须由样式表下发（setFont 到不了独立顶层子窗口），且不改动应用默认字体。"""
    from mdcx.tools.emby_actor_manager_ui import _ui_font_pt

    assert f"QWidget {{ font-size: {_ui_font_pt()}; }}" in dlg.styleSheet(), (
        "样式表须含 QWidget 字号规则, 否则子对话框拿不到放大字号"
    )


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(lambda d: _settings_dialog(d), id="settings"),
        pytest.param(lambda d: _source_test_dialog(d), id="source_test"),
        pytest.param(lambda d: _detail_dialog(d), id="actor_detail"),
        pytest.param(lambda d: _library_dialog(d), id="library_select"),
    ],
)
def test_child_dialogs_inherit_bumped_font(dlg, factory, app):
    """子对话框（设置/数据源测试/演员详情/选择媒体库）由样式表级联继承放大字号。"""
    expected = _expected_pt()
    sub = factory(dlg)
    sub.show()
    app.processEvents()
    try:
        labels = [lbl for lbl in sub.findChildren(QLabel) if lbl.text()]
        assert labels, "子对话框内应有可见文字"
        for lbl in labels:
            assert lbl.font().pointSizeF() == pytest.approx(expected), f"[{lbl.text()[:12]}] 未继承放大字号"
    finally:
        sub.close()
        app.processEvents()


def _settings_dialog(parent):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorSettingsDialog

    return EmbyActorSettingsDialog(parent)


def _source_test_dialog(parent):
    from mdcx.tools.emby_actor_manager_ui import ActorSourceTestDialog

    return ActorSourceTestDialog(parent)


def _detail_dialog(parent):
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import ActorDetailDialog

    # has_image=False: 跳过现有头像下载, 测试不触网
    return ActorDetailDialog(ActorInfo(name="测试演员", actor_id="1", server_id="s"), parent)


def _library_dialog(parent):
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    libraries = [
        {"Name": "电影", "CollectionType": "movies", "Id": "1"},
        {"Name": "剧集", "CollectionType": "tvshows", "Id": "2"},
    ]
    return LibrarySelectDialog(libraries, parent)


def test_window_titles_unchanged(dlg):
    """两处窗口标题（系统窗口框绘制, 不随 QSS 放大）文案保持原样。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorSettingsDialog

    assert dlg.windowTitle() == "Emby/Jellyfin演员管理器"
    assert EmbyActorSettingsDialog(dlg).windowTitle() == "Emby/Jellyfin 演员设置"
