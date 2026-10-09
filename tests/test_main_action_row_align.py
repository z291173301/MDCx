"""软件界面「编辑 NFO/打开文件夹/播放/右键菜单」按钮组右缘对齐缩略图框回归测试.

需求（最小化/还原态）：四个按钮整体右移，使按钮组右缘与缩略图显示框右边界
严格上下对齐；缩略图框自身位置保持不变。最大化态的布局/控件/提示词一律不变。

实现见 ``_sync_page_layouts``：大小两态同一条规则
``align_right = max(缩略图实际右缘 x+w, 设计右缘 587)``，组内相对位置（4×40，间距 0）
保持不变；``max(..., 587)`` 保证极窄窗时只右移不左移，不会压住「标题：」值行。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


@pytest.fixture(scope="module")
def win(app, tmp_path_factory):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    orig_cwd = os.getcwd()
    tmp = str(tmp_path_factory.mktemp("mainactionrow"))
    os.chdir(tmp)
    orig = {}
    for name, fn in (
        ("run_startup_health_checks", lambda: None),
        ("show_netstatus", lambda: None),
        ("check_version", lambda: None),
        ("save_remain_list", lambda: None),
        ("apply_site_priority_theme", lambda _w: None),
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
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()
    for name, fn in orig.items():
        setattr(mw_mod, name, fn)
    mw_mod.MyMAinWindow.set_style = orig_style
    style_mod.resources.qtr = orig_qtr
    os.chdir(orig_cwd)


def _row(ui) -> list:
    """按左→右顺序返回按钮组四个按钮。"""
    return [
        ui.pushButton_open_nfo,
        ui.pushButton_open_folder,
        ui.pushButton_play,
        ui.pushButton_right_menu,
    ]


def _thumb_right(ui) -> int:
    """缩略图显示框右边界（与缩略图下尺寸文字共用同一缩放基准）。"""
    return ui.label_thumb.x() + ui.label_thumb.width()


def _assert_row_aligned(win, app) -> None:
    """按钮组右缘 == max(缩略图框右缘, 设计右缘 587)，且组内间距/纵向位置/不压标题行。"""
    ui = win.Ui
    right = _thumb_right(ui)
    row = _row(ui)
    group_right = row[-1].x() + row[-1].width()
    # 设计右缘 587 右侧（含等宽）时严格等于缩略图右缘；更窄时夹回设计位
    assert group_right == max(right, win._MAIN_ACTION_ROW_RIGHT), (
        f"{win.width()}x{win.height()}: 按钮组右缘 {group_right} != 期望 {max(right, win._MAIN_ACTION_ROW_RIGHT)}"
    )
    # 组内相对位置不变：设计态 427/467/507/547，每枚 40 宽、间距 0，整体右移
    for i, btn in enumerate(row):
        assert btn.x() == group_right - 40 * (len(row) - i), f"{btn.objectName()} 组内位置被改动: {btn.x()}"
        assert btn.width() == 40, f"{btn.objectName()} 宽度被改动: {btn.width()}"
        assert btn.y() == 110, f"{btn.objectName()} 纵向位置被改动: {btn.y()}"
    # 只右移不左移：右缘不得退到设计右缘 587 左侧
    assert group_right >= win._MAIN_ACTION_ROW_RIGHT, f"按钮组左移越界: {group_right}"
    # 不压住「标题：」值行（其右界由 _sync_page_layouts 限死 ≤417）
    title_right = ui.label_title.x() + ui.label_title.width()
    assert row[0].x() > title_right, f"编辑 NFO 按钮 {row[0].x()} 与标题值行右缘 {title_right} 重叠"
    # 按钮组右缘不得越进结果树左缘（仅严格对齐档要求；下限夹取档沿用设计位，
    # 与改动前一致，窄窗下与树的间距问题不在本次范围内）
    tree_left = ui.treeWidget_number.x()
    if right >= win._MAIN_ACTION_ROW_RIGHT:
        assert group_right <= tree_left, f"按钮组右缘 {group_right} 压到结果树左缘 {tree_left}"


@pytest.mark.parametrize("width", [1080, 1200, 1440, 1920])
def test_action_row_right_aligns_with_thumb_normal(win, app, width):
    """还原/最小化态：按钮组右缘严格对齐缩略图框右缘，缩略图框位置不变。"""
    ui = win.Ui
    win.resize(width, 800)
    win.show()
    app.processEvents()
    assert not win.isMaximized(), "本用例要求非最大化态"

    cover_scale = ui.page_main.width() / 820
    assert ui.label_thumb.x() == int(252 * cover_scale), "缩略图框 x 变了"
    assert ui.label_thumb.width() == int(328 * cover_scale), "缩略图框宽变了"
    assert ui.label_thumb.y() == 160, "缩略图框 y 变了"
    assert _thumb_right(ui) >= win._MAIN_ACTION_ROW_RIGHT, "该窗宽下应为严格对齐（无下限夹取）"

    _assert_row_aligned(win, app)
    assert _row(ui)[-1].x() + _row(ui)[-1].width() == _thumb_right(ui), "按钮组右缘未与缩略图右缘严格对齐"

    # 幂等：缩小-再放大回同一宽度，几何不漂移
    win.resize(1920, 1040)
    app.processEvents()
    win.resize(width, 800)
    app.processEvents()
    _assert_row_aligned(win, app)


@pytest.mark.parametrize("width", [900, 1040])
def test_action_row_never_moves_left_in_narrow_window(win, app, width):
    """极窄窗（缩略图右缘退到设计右缘 587 左侧）保持设计位，不左移、不越界。"""
    ui = win.Ui
    win.resize(width, 760)
    win.show()
    app.processEvents()

    row = _row(ui)
    assert [b.x() for b in row] == [427, 467, 507, 547], f"窄窗按钮组未保持设计位: {[b.x() for b in row]}"
    assert _thumb_right(ui) < win._MAIN_ACTION_ROW_RIGHT, "该窗宽应触发下限夹取"
    # 「显示封面」勾选框沿用设计坐标 490（仅最大化态右对齐缩略图右缘）
    assert ui.checkBox_cover.x() == 490, f"窄窗勾选框位置被改动: {ui.checkBox_cover.x()}"


def test_action_row_maximized_state_unchanged(win, app):
    """最大化态：仍是「右缘对齐缩略图右缘 + 勾选框同样对齐」，布局其余不动。"""
    ui = win.Ui
    win.showNormal()
    win.resize(1040, 760)
    win.show()
    app.processEvents()

    win.showMaximized()
    app.processEvents()
    if win.isMaximized() and ui.page_main.width() > 820:
        # 真最大化：按钮组与「显示封面」勾选框都右对齐缩略图右缘
        _assert_row_aligned(win, app)
        assert ui.checkBox_cover.x() + ui.checkBox_cover.width() == _thumb_right(ui), (
            f"最大化态显示封面勾选框右缘未对齐缩略图右缘: "
            f"{ui.checkBox_cover.x() + ui.checkBox_cover.width()} != {_thumb_right(ui)}"
        )
    else:
        # offscreen 真最大化会给出退化尺寸（如 584 宽），改用等效放大尺寸走同一条规则
        win.showNormal()
        win.resize(1920, 1040)
        app.processEvents()
        _assert_row_aligned(win, app)

    # 还原后立即回到对齐态（两态同规则），无残留漂移
    win.showNormal()
    win.resize(1080, 760)
    app.processEvents()
    _assert_row_aligned(win, app)
    assert _row(ui)[-1].x() + _row(ui)[-1].width() == _thumb_right(ui), "还原态按钮组右缘未严格对齐"
