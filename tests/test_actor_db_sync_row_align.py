"""软件工具页「全量更新并入」别名分片行左缘对齐回归测试。

需求（最小化/还原态）：演员库维护组底部的「全量更新并入」复选框向右移动到与
封面补图组「覆盖已有图片」复选框严格上下对齐（绝对 x 相同）的位置，其右侧的
「起始行数」「单次限制」及提示词随整行同步右移；「覆盖已有图片」自身位置不变；
最大化态的页面布局/组件/控件/提示词一律不变。

事故背景：``_sync_actor_db_tool_layout`` 的最小化分支曾把该行右缘钉到封面补图
番号输入框右缘 552，再由六控件设计宽合计 601 反推左缘，得 ``start_x = -49``
—— 复选框被推到组框左缘之外，界面上被裁成「更新并入」。现改为由
``_actor_db_sync_row_left`` 直接取「覆盖已有图片」的组内局部 x（设计值 40）作左缘。

需求（最小化/还原态，末位提示标签）：「起始行数0+单次限制5000=默认更新数据表行数」
必须整串一行显示，宽度不够就向右拓展——即该标签宽度不再钉设计宽 211px，改按
``_actor_db_slice_hint_width`` 取「整串实测宽 + 余量」与设计宽的较大者；左缘仍紧接
末位 spin、行内其余五项逐像素不动。

实现见 ``main_window.MyMAinWindow._actor_db_sync_row_left``、
``_ACTOR_DB_SYNC_ROW_NAMES`` 与 ``_actor_db_slice_hint_width``。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None

# 分片行控件：按设计横排顺序（从左到右）
ROW_NAMES = [
    "checkBox_actor_db_alias_all",
    "label_actor_db_sync_offset",
    "spinBox_actor_db_sync_offset",
    "label_actor_db_sync_limit",
    "spinBox_actor_db_sync_limit",
    "label_actor_db_sync_slice_hint",
]
# 设计宽/高（来自 _ACTOR_DB_TOOL_DESIGN，最大化态的提示词宽度除外，见下）
# 末位提示标签的 211 只是宽度下限，实际宽度见 _expected_hint_width。
DESIGN_WIDTHS = [142, 56, 64, 56, 72, 211]
# 分片行 y：顶部同文案说明删除后窄态/宽态统一为设计值 336，不再下移。
ROW_Y = 336
NARROW_ROW_Y = 336
ROW_H = 28
# 「覆盖已有图片」的组内设计 x（_COVER_BACKFILL_OPTION_DESIGN，永不随窗宽移动）
OVERWRITE_DESIGN_X = 40
# 提示标签单行整串宽的额外余量（镜像 main_window._ACTOR_DB_SLICE_HINT_PAD）
HINT_PAD = 8


def _expected_hint_width(ui) -> int:
    """末位提示标签在最小化态的期望宽度：max(设计宽 211, 整串实测宽 + 余量)。"""
    hint = ui.label_actor_db_sync_slice_hint
    hint.ensurePolished()  # 字号来自样式表，未 polish 时字体度量不反映 12px
    need = hint.fontMetrics().horizontalAdvance(hint.text()) + HINT_PAD
    return max(DESIGN_WIDTHS[-1], need)


def _narrow_row_right(ui) -> int:
    """分片行在最小化态的组内右缘（前五项设计宽累加 + 末位标签按度量取宽）。"""
    return OVERWRITE_DESIGN_X + sum(DESIGN_WIDTHS[:-1]) + _expected_hint_width(ui)


def _doc_height(hint, width: int) -> float:
    """按给定宽度排版该标签整串文案后的文档高（QLabel 折行判据的权威口径）。

    QLabel.heightForWidth 在本控件上不可信（宽 211px 也只报 26px，见
    tests/test_actor_db_hint_height.py 的同一坑注），故改用 QTextDocument 量高：
    单行与两行的量高相差一个行高（实测 22px vs 36px），据此判定是否折行。
    """
    doc = QTextDocument()
    doc.setDefaultFont(hint.font())
    doc.setTextWidth(width)
    doc.setPlainText(hint.text())
    return doc.size().height()


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture(scope="module")
def win(app, tmp_path_factory):
    """构建真实主窗口并停在软件工具页（stackedWidget 索引 3）。

    切页是必需的：_sync_actor_db_tool_layout / _sync_cover_backfill_option_row 都以
    ``box.isVisibleTo(self)`` 跳过休眠页（见两方法开头注释）。
    """
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    orig_cwd = os.getcwd()
    tmp = str(tmp_path_factory.mktemp("actordbsyncrow"))
    os.chdir(tmp)
    orig = {}
    for name, fn in (
        ("run_startup_health_checks", lambda: None),
        ("show_netstatus", lambda *_a, **_k: None),
        ("check_version", lambda *_a, **_k: None),
        ("save_remain_list", lambda *_a, **_k: None),
        ("apply_site_priority_theme", lambda *_a, **_k: None),
    ):
        orig[name] = getattr(mw_mod, name)
        setattr(mw_mod, name, fn)
    orig_style = mw_mod.MyMAinWindow.set_style
    mw_mod.MyMAinWindow.set_style = lambda self: None
    orig_qtr = style_mod.resources.qtr
    style_mod.resources.qtr = lambda path: str(MAIN_PATH / "resources" / path)
    window = mw_mod.MyMAinWindow()
    for t in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        try:
            getattr(window, t).stop()
        except Exception:
            pass
    window.Ui.stackedWidget.setCurrentIndex(3)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()
    for name, fn in orig.items():
        setattr(mw_mod, name, fn)
    mw_mod.MyMAinWindow.set_style = orig_style
    style_mod.resources.qtr = orig_qtr
    os.chdir(orig_cwd)


def _resize(win, app, width: int, height: int = 800) -> None:
    win.showNormal()
    win.resize(width, height)
    win.show()
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _row(ui) -> list:
    return [getattr(ui, name) for name in ROW_NAMES]


def _host(ui):
    """两枚复选框的共同祖先（scrollArea_10 的内容区）：跨框测量经此中转。"""
    return ui.groupBox_actor_db_maintenance.parentWidget()


def _abs_x(win, widget) -> int:
    host = _host(win.Ui)
    return widget.mapTo(host, widget.rect().topLeft()).x()


def _assert_narrow_row(win) -> None:
    """最小化态：首枚左缘 == 覆盖已有图片绝对 x，整行零间隙顺排、y/h 一致、末位按度量加宽。"""
    ui = win.Ui
    row = _row(ui)
    overwrite = ui.checkBox_cover_backfill_overwrite
    hint_w = _expected_hint_width(ui)
    expect_widths = DESIGN_WIDTHS[:-1] + [hint_w]

    # ① 严格上下对齐：绝对 x 完全相等（这是本需求的唯一硬指标）
    assert _abs_x(win, row[0]) == _abs_x(win, overwrite), (
        f"{win.width()}x{win.height()}: 全量更新并入绝对 x {_abs_x(win, row[0])} "
        f"!= 覆盖已有图片绝对 x {_abs_x(win, overwrite)}"
    )
    # ③ 覆盖已有图片自身位置不变（组内恒为设计值 40，宽高照旧）
    assert overwrite.x() == OVERWRITE_DESIGN_X, f"覆盖已有图片 x 被改动: {overwrite.x()}"
    assert overwrite.width() == 161 and overwrite.height() == 20, "覆盖已有图片尺寸被改动"

    # ② 整行零间隙顺排：前五项取设计值，末位提示标签取「单行整串宽 + 余量」
    xs = [w.x() for w in row]
    ws = [w.width() for w in row]
    assert ws == expect_widths, f"分片行控件宽度被改动: {ws}（期望 {expect_widths}，末位按字体度量取宽）"
    assert xs[0] == OVERWRITE_DESIGN_X, f"分片行左缘应等于覆盖已有图片的 x: {xs[0]}"
    for i in range(1, len(row)):
        assert xs[i] == xs[i - 1] + ws[i - 1], f"{ROW_NAMES[i]} 未与左邻相接: {xs}（设计宽 {DESIGN_WIDTHS}）"
    assert xs[-1] + ws[-1] == _narrow_row_right(ui), f"分片行右缘应为 {_narrow_row_right(ui)}: {xs[-1] + ws[-1]}"

    # 纵向位置/高度统一，且整行不越出组框左缘（事故回归点：曾被推到 -49）
    assert all(w.y() == NARROW_ROW_Y for w in row), f"分片行 y 不统一: {[w.y() for w in row]}"
    assert all(w.height() == ROW_H for w in row), f"分片行高度不一致: {[w.height() for w in row]}"
    assert xs[0] >= 0, f"分片行左缘越出组框: {xs[0]}"


@pytest.mark.parametrize("width", [760, 900, 1080, 1400, 1920])
def test_alias_all_left_aligns_with_overwrite_in_normal_state(win, app, width):
    """最小化/还原态：全量更新并入与覆盖已有图片严格上下对齐，且各档窗宽一致。"""
    _resize(win, app, width)
    assert not win.isMaximized(), "本用例要求非最大化态"
    _assert_narrow_row(win)


def test_alias_row_moves_right_by_same_delta(win, app):
    """起始行数/单次限制/提示词随整行同步右移（相对首枚的偏移量 = 设计宽累加，一律不变）。"""
    _resize(win, app, 1080)
    row = _row(win.Ui)
    design_widths = [win._ACTOR_DB_TOOL_DESIGN[name][2] for name in ROW_NAMES]
    assert design_widths == DESIGN_WIDTHS, f"设计宽常量变了: {design_widths}"
    offsets = [0]
    for w in design_widths[:-1]:
        offsets.append(offsets[-1] + w)
    base_x = row[0].x()
    for widget, off in zip(row, offsets, strict=True):
        assert widget.x() == base_x + off, f"{widget.objectName()} 未随整行同步右移: {widget.x()} != {base_x + off}"
    # 前五项右缘不越组框右缘（末位提示标签按需求向右拓展，故不参与该断言）
    box = win.Ui.groupBox_actor_db_maintenance
    prefix_right = row[4].x() + row[4].width()
    assert prefix_right <= box.width(), f"分片行前五项右缘 {prefix_right} 越出组框宽 {box.width()}"


@pytest.mark.parametrize("width", [760, 1080, 1920])
def test_slice_hint_single_line_in_normal_state(win, app, width):
    """最小化态：提示词整串一行显示（宽度不够时向右拓展，不折行、不裁字）。"""
    _resize(win, app, width)
    hint = win.Ui.label_actor_db_sync_slice_hint
    hint.ensurePolished()
    assert hint.x() == OVERWRITE_DESIGN_X + sum(DESIGN_WIDTHS[:-1]), f"提示词左缘被改动: {hint.x()}"
    assert hint.width() == _expected_hint_width(win.Ui), (
        f"提示词宽度应为 max(211, 实测整串宽+{HINT_PAD}): {hint.width()}"
    )
    # 权威判据：按实际宽度排版的文档高等于不限宽时的单行高 → 未折行
    assert _doc_height(hint, hint.width()) == _doc_height(hint, 100000), (
        f"{width}px 窗宽下提示词折行了：单行高 {_doc_height(hint, 100000)}，实得 {_doc_height(hint, hint.width())}"
    )
    # 回归对照：设计宽 211px 确实排不下（这正是加宽的原因）
    assert _doc_height(hint, DESIGN_WIDTHS[-1]) > _doc_height(hint, 100000), "设计宽下已能单行，加宽逻辑失去依据"


def test_top_desc_removed_note_on_top(win, app):
    """顶部同文案说明已删除：控件不存在，提示语顶到组内 30，组框同步收窄。

    背景：演员库维护组顶部「来源TMDB需配置TMDB API KEY；…」与底部「补全别名」
    说明同文案，删除第一次出现（顶部），保留第二次（底部）；组内其余控件整体
    上移一行（22px），组框由 434 收窄到 412，单文件组顶边由 494 上移到 472。
    """
    ui = win.Ui
    _resize(win, app, 1080)
    box = ui.groupBox_actor_db_maintenance
    assert getattr(ui, "label_actor_db_desc", None) is None, "顶部说明控件应已删除"
    note = ui.label_actor_db_note
    # 提示语顶到组内 30，紧贴组标题下方
    assert (note.x(), note.y()) == (40, 30), f"提示语位置被改动: {(note.x(), note.y())}"
    assert note.y() + note.height() <= ui.pushButton_actor_db_translate.y(), (
        f"提示语盖住维护按钮: 提示语底边 {note.y() + note.height()}"
    )
    # 组内其余控件整体上移一行（抽查）：nfo 输入行、底部说明收进框内
    assert ui.lineEdit_actor_db_nfo_dir.y() == 222
    assert box.height() == 412, f"组框高度被改动: {box.height()}"
    bottom = ui.label_actor_db_sync_aliases_desc
    assert bottom.y() == 356
    assert bottom.y() + bottom.height() <= box.height(), (
        f"底部说明底边 {bottom.y() + bottom.height()} 越出组框高 {box.height()}"
    )
    # 底部「补全别名」说明保留且文案不变
    assert "Minnano" in bottom.text() and "全量更新" in bottom.text()
    # 单文件组同步上移，组间距保持设计值 20
    single = ui.groupBox_7
    assert single.y() == 472, f"单文件组顶边被改动: {single.y()}"
    assert single.y() - (box.y() + box.height()) == 20


def test_overwrite_row_other_options_still_follow_extra(win, app):
    """覆盖已有图片不动，另两枚仍按 extra 拉开（本次改动不得波及它们）。"""
    ui = win.Ui
    _resize(win, app, 1920)
    box = ui.groupBox_cover_backfill
    extra = max(box.width() - 701, 0)
    half = extra // 2
    assert ui.checkBox_cover_backfill_overwrite.x() == OVERWRITE_DESIGN_X
    assert ui.checkBox_cover_backfill_watermark.x() == 220 + half, "添加水印位置被改动"
    assert ui.checkBox_create_link.x() == 410 + extra, "软链接复选框位置被改动"


def test_maximized_state_unchanged(win, app, monkeypatch):
    """最大化态：分片行仍为设计几何（提示词按末位 spin 动态定位），布局不被本次改动影响。"""
    ui = win.Ui
    _resize(win, app, 1080)
    win.showMaximized()
    app.processEvents()
    if not win.isMaximized():
        # 离屏平台下 showMaximized 可能不生效：打桩 isMaximized 强制走最大化分支，
        # 并给足组框宽度（宽态下 extra>0，最大化分支才会展开加宽）
        win.showNormal()
        win.resize(1920, 1040)
        app.processEvents()
        monkeypatch.setattr(win, "isMaximized", lambda: True)
        win._sync_page_layouts()
        app.processEvents()

    row = _row(ui)
    # 最大化态：checkbox/label/spin 保持设计几何；hint 紧跟末位 spin + 10，宽 261
    assert [w.x() for w in row[:5]] == [40, 186, 246, 314, 374], (
        f"最大化态分片行前五项设计几何被改动: {[w.x() for w in row[:5]]}"
    )
    assert [w.width() for w in row[:5]] == DESIGN_WIDTHS[:5], "最大化态前五项宽度被改动"
    spin = row[4]
    hint = row[5]
    assert hint.x() == spin.x() + spin.width() + 10, f"最大化态提示词位置被改动: {hint.x()}"
    # 最大化态维持既有硬编码 261px（本次需求只针对最小化态的单行显示）
    assert hint.width() == 261, f"最大化态提示词宽度被改动: {hint.width()}"
    assert all(w.y() == ROW_Y for w in row), f"最大化态分片行 y 被改动: {[w.y() for w in row]}"
    assert ui.checkBox_cover_backfill_overwrite.x() == OVERWRITE_DESIGN_X
    # 最大化态顶部说明已删除、组框为收窄后设计值（本次改动两态统一）
    assert getattr(ui, "label_actor_db_desc", None) is None, "顶部说明控件应已删除"
    assert ui.groupBox_actor_db_maintenance.height() == 412, "最大化态组框高度被改动"

    # 还原后立即回到对齐态，无残留漂移
    win.showNormal()
    _resize(win, app, 1080)
    _assert_narrow_row(win)


def test_narrow_row_idempotent_across_width_roundtrip(win, app):
    """缩小-放大往返幂等：几何不漂移，对齐关系仍严格成立。"""
    ui = win.Ui
    _resize(win, app, 1080)
    before = [(w.x(), w.y(), w.width(), w.height()) for w in _row(ui)]
    _resize(win, app, 1920)
    _resize(win, app, 1080)
    after = [(w.x(), w.y(), w.width(), w.height()) for w in _row(ui)]
    assert before == after, f"往返后分片行几何漂移:\n{before}\n{after}"
    _assert_narrow_row(win)
