"""最大化整行对齐回归：演员表不多不少 20 整行，运行日志不多不少 10 整行。

背景：收紧边距 + splitter 4:1 后，最大化时表格显示 21.5 行（末行半截），
日志只剩约 7 行。现 `_fit_visible_rows` 在最大化时把高度差均摊到 20 行行高上
（±1~2px），余数垫在日志底部视口边距里，两处都不出现半行。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


def test_row_fit_constants_are_20_and_10():
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    assert EmbyActorManagerDialog.TABLE_VISIBLE_ROWS == 20
    assert EmbyActorManagerDialog.LOG_VISIBLE_LINES == 10


def test_plan_row_fit_is_pixel_exact():
    """方案自洽：表格视口 == 20*行高，日志视口+垫底 == 10*行高+垫底，两侧之和 == 可用高。"""
    from mdcx.tools.emby_actor_manager_ui import _plan_row_fit

    # 模拟 1080p 最大化：可用 850，表格固定开销 60，日志固定开销 50，基准行高 30，日志行高 21
    row_h, list_h, log_h, pad = _plan_row_fit(
        avail=850, table_fixed=60, log_fixed=50, base_row_h=30, line_h=21, min_row_h=20
    )
    assert list_h + log_h == 850
    assert list_h - 60 == 20 * row_h  # 表格无半行
    assert log_h - 50 - pad == 10 * 21  # 日志 10 整行
    assert 0 <= pad < 20  # 余数只垫在日志底部
    assert abs(row_h - 30) <= 6  # 行高微调不影响阅读


def test_plan_row_fit_falls_back_on_tiny_screen():
    """极小屏行高越界时保持基准行高、不断言崩溃，表格仍取整行。"""
    from mdcx.tools.emby_actor_manager_ui import _plan_row_fit

    row_h, list_h, log_h, pad = _plan_row_fit(
        avail=200, table_fixed=60, log_fixed=50, base_row_h=30, line_h=21, min_row_h=20
    )
    assert row_h == 30
    assert list_h + log_h == 200
    assert pad == 0


def test_maximized_fit_gives_full_rows_only(app):
    """集成：表格不多不少 20 整行，日志 10 整行且底部无空白垫。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    actors = [ActorInfo(name=f"演员{i:02d}", actor_id=str(i), server_id="s") for i in range(30)]
    for a in actors:
        a.existing_overview = "简介"
        a.has_overview = True
        a.has_image = True
    dlg._actors = actors
    dlg._fitting_rows = True  # 冻结自动对齐，手动控制测量点
    dlg.show()
    app.processEvents()
    dlg._populate_table(actors)
    app.processEvents()
    try:
        # 先算出刚好装下 20 行 + 10 行的对话框高度，验证主路径精确性
        dlg.resize(1600, 1100)
        app.processEvents()
        t = dlg.table
        log = dlg.log_text
        header_h = t.horizontalHeader().height()
        table_fixed = (dlg._list_widget.height() - t.height()) + header_h + (
            t.height() - header_h - t.viewport().height()
        )
        log_fixed = (dlg._log_widget.height() - log.height()) + (log.height() - log.viewport().height())
        line_h = log.fontMetrics().lineSpacing()
        doc_top = int(log.document().documentMargin())
        base_r = t.verticalHeader().defaultSectionSize()
        need_splitter = (
            table_fixed + 20 * base_r + log_fixed + doc_top + 10 * line_h + dlg._splitter.handleWidth()
        )
        dlg.resize(1600, 1100 + (need_splitter - dlg._splitter.height()))
        app.processEvents()
        dlg._fitting_rows = False
        dlg._fit_visible_rows()
        app.processEvents()
        row_h = t.rowHeight(0)
        assert row_h > 0
        assert t.viewport().height() == 20 * row_h  # 不多不少 20 整行，无半行
        assert log.viewport().height() == 10 * line_h + doc_top  # 10 整行，末行不被盖
        assert log.viewportMargins().bottom() == 0  # 无空白垫
        assert dlg._conn_grid.contentsMargins().top() == 4  # 无富余，连接组保持基准
        assert log.minimumHeight() >= 10 * line_h
        # 长日志行随后冒出横向滚动条：Show 事件重对后 10 行不被盖、表格仍是 20 整行
        for i in range(12):
            log.appendPlainText(f"[{i:02d}] " + "长日志行_" * 120)
        for _ in range(4):
            app.processEvents()
        dlg._fit_visible_rows()  # 事件级联后直接再对一次，结果确定
        app.processEvents()
        assert t.viewport().height() == 20 * t.rowHeight(0)
        assert log.viewport().height() == 10 * line_h + int(log.document().documentMargin())
    finally:
        dlg.close()
        app.processEvents()


def test_surplus_goes_to_rows_and_connection(app):
    """富余按整数瓜分：表格行长高 + 连接组边距，日志不定空白垫。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    actors = [ActorInfo(name=f"演员{i:02d}", actor_id=str(i), server_id="s") for i in range(30)]
    for a in actors:
        a.existing_overview = "简介"
        a.has_overview = True
        a.has_image = True
    dlg._actors = actors
    dlg._fitting_rows = True  # 冻结自动对齐，手动控制测量点
    dlg.show()
    app.processEvents()
    dlg._populate_table(actors)
    app.processEvents()
    try:
        dlg.resize(1600, 1100)
        app.processEvents()
        t = dlg.table
        log = dlg.log_text
        header_h = t.horizontalHeader().height()
        table_fixed = (dlg._list_widget.height() - t.height()) + header_h + (
            t.height() - header_h - t.viewport().height()
        )
        log_fixed = (dlg._log_widget.height() - log.height()) + (log.height() - log.viewport().height())
        line_h = log.fontMetrics().lineSpacing()
        doc_top = int(log.document().documentMargin())
        base_r = t.verticalHeader().defaultSectionSize()
        need_splitter = (
            table_fixed + 20 * base_r + log_fixed + doc_top + 10 * line_h + dlg._splitter.handleWidth()
        )
        # 多给 85px：行高 +4（80px），连接组 +5（上 2 下 3），日志垫 0
        dlg.resize(1600, 1100 + (need_splitter - dlg._splitter.height()) + 85)
        app.processEvents()
        dlg._fitting_rows = False
        dlg._fit_visible_rows()
        app.processEvents()
        assert t.rowHeight(0) == base_r + 4
        assert t.viewport().height() == 20 * (base_r + 4)
        margins = dlg._conn_grid.contentsMargins()
        assert margins.top() == 4 + 2
        assert margins.bottom() == 4 + 3
        assert log.viewport().height() == 10 * line_h + doc_top
        assert log.viewportMargins().bottom() == 0
    finally:
        dlg.close()
        app.processEvents()


def test_short_window_fit_is_noop(app):
    """小窗实在塞不下 20 行 + 10 行时不干预（行高/分隔条不动，连接组恢复基准）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    actors = []
    dlg._fitting_rows = True  # 冻结自动对齐，手动控制测量点
    dlg.show()
    app.processEvents()
    try:
        dlg.resize(1200, 700)
        app.processEvents()
        dlg._fitting_rows = False
        t = dlg.table
        before = t.verticalHeader().defaultSectionSize()
        sizes_before = dlg._splitter.sizes()
        dlg._fit_visible_rows()
        app.processEvents()
        assert t.verticalHeader().defaultSectionSize() == before
        assert dlg._splitter.sizes() == sizes_before
        m = dlg._conn_grid.contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == (6, 4, 6, 4)
    finally:
        dlg.close()
        app.processEvents()
