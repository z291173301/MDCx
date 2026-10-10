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
    """集成：最大化下表格视口是行高的整数倍（无半行），日志不少于 10 行高度。"""
    from mdcx.tools.emby_actor_manager import ActorInfo
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    actors = [ActorInfo(name=f"演员{i:02d}", actor_id=str(i), server_id="s") for i in range(30)]
    for a in actors:
        a.existing_overview = "简介"
        a.has_overview = True
        a.has_image = True
    dlg._actors = actors
    dlg.show()
    app.processEvents()
    dlg._populate_table(actors)
    app.processEvents()
    try:
        # 离屏伪装最大化：先算出刚好装下 20 行 + 10 行的对话框高度，验证主路径精确性
        dlg.isMaximized = lambda: True  # type: ignore[method-assign]
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
        base_r = t.verticalHeader().defaultSectionSize()
        need_splitter = table_fixed + 20 * base_r + log_fixed + 10 * line_h + dlg._splitter.handleWidth()
        dlg.resize(1600, 1100 + (need_splitter - dlg._splitter.height()))
        app.processEvents()
        dlg._fit_visible_rows()
        app.processEvents()
        row_h = t.rowHeight(0)
        assert row_h > 0
        assert t.viewport().height() == 20 * row_h  # 不多不少 20 整行，无半行
        assert log.viewport().height() == 10 * line_h  # 不多不少 10 整行
        assert log.minimumHeight() >= 10 * line_h
    finally:
        dlg.close()
        app.processEvents()


def test_short_window_fit_is_noop(app):
    """小窗实在塞不下 20 行 + 10 行时不干预（行高/分隔条都不动）。"""
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dlg = EmbyActorManagerDialog()
    dlg.resize(1200, 700)
    dlg.show()
    app.processEvents()
    try:
        before = dlg.table.verticalHeader().defaultSectionSize()
        sizes_before = dlg._splitter.sizes()
        dlg._fit_visible_rows()
        app.processEvents()
        assert dlg.table.verticalHeader().defaultSectionSize() == before
        assert dlg._splitter.sizes() == sizes_before
    finally:
        dlg.close()
        app.processEvents()
