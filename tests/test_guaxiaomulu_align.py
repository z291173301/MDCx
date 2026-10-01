"""设置-刮削目录页两处横向对齐的回归测试。

用户需求（三条锚点自身均保持不动）：
  ① 最大化/最小化时把「获取软链接指向的原文件的分辨率」左移到与「记录刮削成功的文件
     列表」严格上下对齐（两态都做，实测两态都是 -58px）。
  ② 最大化时把「刮削时自动清理」左移到与「记录刮削成功的文件列表」严格上下对齐。
  ③ 最小化时把「刮削时自动清理」右移到与「启用」严格上下对齐。

根因防线（任一回归都会让本文件失败）：
  - horizontalLayout_115 是 gridLayout_19 的子布局，两项都是 Minimum 策略且总需求
    恰好等于 col1 宽：对子控件 setGeometry 会被下次 layout 激活覆盖，只插间隔也不行
    （总需求一旦小于容器宽，Qt 把富余摊给其余 Minimum 项、目标弹回原位），只能靠
    「前导项收窄 + 钉宽」让位。
  - 钉宽必须**真解锁**（setMinimumWidth(0)+setMaximumWidth(QWIDGETSIZE_MAX)）后再量，
    否则拿上一遍的钉宽算 need_w，误差逐遍累积（_actor_info_width_locks 用
    setFixedWidth(saved) 永不真解锁就是这条坑）。
  - 前导项收窄有下限（150px）：低于此值会夹住「检查并清理失效的软链接」自己的文字
    （实测其 sizeHint 宽 101），窗口窄于约 960 时守卫生效、宁可不右移。
  - 「刮削时自动清理」是 groupBox_61 内绝对定位项，通用宽幅同步按 _DOCK_RIGHT 每遍
    钉回「设计x + extra」，故本方法必须排在 sync_wide_children_width() 之后。
  - 跨分支 mapTo（record 在 groupBox_32、目标在 groupBox_61）是未定义行为，必须经
    公共祖先 scrollAreaWidgetContents_guaxiaomulu 中转。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtCore import QPoint
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


def _goto_guaxiaomulu(win, app):
    """切到设置页的「刮削目录」tab（该 tab 的 objectName 是 tab2，不是 tab_2）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab2":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("刮削目录 tab2 not found")
    app.processEvents()


def _abs(ui, widget):
    """控件左缘映射到刮削目录页滚动内容的绝对 x。"""
    return widget.mapTo(ui.scrollAreaWidgetContents_guaxiaomulu, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _extra(win):
    return win._scroll_stretch_extra(win._guaxiaomulu_scroll)


# 需求②③ 的目标、需求① 的锚点与前导项
_AUTO_CLEAN = "checkBox_auto_clean"
_ENABLE = "checkBox_clean_file_ext"
_RECORD = "checkBox_record_success_file"
_DEFINITION = "checkBox_check_symlink_definition"
_LEAD = "checkBox_check_symlink"

# 必须逐项保持不动的参照控件
_REFS = (
    "checkBox_skip_success_file",
    "pushButton_view_success_file",
    "lineEdit_escape_size",
    "checkBox_no_escape_file",
    "checkBox_i_agree_clean",
    "checkBox_i_understand_clean",
    "pushButton_check_and_clean_files",
    "label_271",
    "label_199",
    "label_162",
)

_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1100, 800))
_NARROW_SIZES = ((1000, 700), (1030, 753))


def _snapshot(ui):
    snap = {
        name: (_abs(ui, getattr(ui, name)), getattr(ui, name).width())
        for name in (_REFS + (_AUTO_CLEAN, _RECORD, _DEFINITION, _LEAD))
    }
    for name in ("groupBox_32", "groupBox_61", "gridLayoutWidget_19", "gridLayoutWidget_34"):
        snap[name] = getattr(ui, name).geometry().getRect()
    snap["auto_clean_rect"] = getattr(ui, _AUTO_CLEAN).geometry().getRect()
    return snap


def _baseline_without(win, app, monkeypatch, take):
    """摘掉新方法重跑一遍同步，返回「只有通用逻辑」的几何基线（随后复位）。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    cls = mw_mod.MyMAinWindow
    original = cls._sync_guaxiaomulu_checkbox_align
    monkeypatch.setattr(cls, "_sync_guaxiaomulu_checkbox_align", lambda self, _scroll=None: None)
    try:
        win._sync_page_layouts()
        app.processEvents()
        base = take()
    finally:
        monkeypatch.setattr(cls, "_sync_guaxiaomulu_checkbox_align", original)
    win._sync_page_layouts()
    app.processEvents()
    return base


def test_symlink_row_aligns_to_record_in_both_states(win, app, monkeypatch):
    """需求①：宽窄两态「获取软链接指向的原文件的分辨率」都精确落在锚点列上。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomulu(win, app)

    for width, height in _NARROW_SIZES + _WIDE_SIZES:
        _resize(win, app, width, height)
        anchor = _abs(ui, ui.checkBox_record_success_file)
        got = _abs(ui, ui.checkBox_check_symlink_definition)
        assert got == anchor, (
            f"{width} 宽下「获取软链接指向的原文件的分辨率」未与「记录刮削成功的文件列表」对齐: x={got} 期望={anchor}"
        )
        # 前导项只让宽度、左缘纹丝不动（col1 起点随字体/缩放而变，故与基线比而非写死），
        # 且不低于它自己文字所需的下限。
        lead = ui.checkBox_check_symlink
        lead_left_before = _baseline_without(win, app, monkeypatch, lambda w=lead: _abs(ui, w))
        assert _abs(ui, lead) == lead_left_before, (
            f"{width} 宽下前导项「检查并清理失效的软链接」左缘被带偏: {lead_left_before} -> {_abs(ui, lead)}"
        )
        assert lead.width() >= win._GUAXIAOMULU_MIN_LEAD_W, (
            f"{width} 宽下前导项被压到 {lead.width()}px，会夹住自己的文字"
        )


def test_auto_clean_moves_by_state(win, app):
    """需求②③：宽态对「记录刮削成功的文件列表」列，窄态对「启用」列；只动 x。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomulu(win, app)

    for width, height in _WIDE_SIZES:
        _resize(win, app, width, height)
        assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"
        got = _abs(ui, ui.checkBox_auto_clean)
        anchor = _abs(ui, ui.checkBox_record_success_file)
        assert got == anchor, f"宽态「刮削时自动清理」未与锚点对齐: x={got} 期望={anchor}"

    for width, height in _NARROW_SIZES:
        _resize(win, app, width, height)
        assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"
        got = _abs(ui, ui.checkBox_auto_clean)
        enable = _abs(ui, ui.checkBox_clean_file_ext)
        assert got == enable, f"窄态「刮削时自动清理」未与「启用」对齐: x={got} 期望={enable}"

    # 只改 x：宽高与 y 恒为设计值（需求只说左右移动）
    rect = ui.checkBox_auto_clean.geometry().getRect()
    assert (rect[2], rect[3]) == (141, 41), f"「刮削时自动清理」宽高被改动: {rect}"


def test_align_touches_nothing_but_the_three_targets(win, app, monkeypatch):
    """与「摘掉新方法」的基线逐项比对：只有三个目标变化，其余全部逐像素不变。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomulu(win, app)

    for width, height in ((1030, 753), (1920, 1170)):
        _resize(win, app, width, height)
        new = _snapshot(ui)
        base = _baseline_without(win, app, monkeypatch, lambda: _snapshot(ui))
        changed = {k for k in new if base[k] != new[k]}
        expected = {_AUTO_CLEAN, _RECORD, _DEFINITION, _LEAD, "auto_clean_rect"}
        assert changed <= expected, f"{width} 宽下改动了预期外的控件: {sorted(changed - expected)}"
        # 锚点与全部参照控件必须与基线完全一致
        for name in _REFS + (_RECORD,):
            assert new[name] == base[name], f"{width} 宽下 {name} 被改动: {base[name]} -> {new[name]}"


def test_align_is_idempotent_and_round_trips(win, app):
    """幂等 + 窄↔宽往返自愈：重复同步与往返之后几何逐项复原。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomulu(win, app)

    _resize(win, app, 1030, 753)
    narrow = _snapshot(ui)
    _resize(win, app, 1030, 753)
    assert _snapshot(ui) == narrow, "窄态二次同步漂移"

    _resize(win, app, 1920, 1170)
    wide = _snapshot(ui)
    assert wide != narrow, "宽态未产生任何位移，钉位机制本身失效"
    _resize(win, app, 1920, 1170)
    assert _snapshot(ui) == wide, "宽态二次同步漂移"

    _resize(win, app, 1030, 753)
    assert _snapshot(ui) == narrow, "窄→宽→窄 往返未复原"
    _resize(win, app, 1920, 1170)
    assert _snapshot(ui) == wide, "窄→宽→窄→宽 往返未复原"


def test_narrow_guard_keeps_lead_text_intact(win, app):
    """窗口窄于约 960 时让位量不足 150px：保持解锁、不右移，且前导项不被压瘦。"""
    ui = win.Ui
    win.show()
    _goto_guaxiaomulu(win, app)

    _resize(win, app, 850, 650)
    anchor = _abs(ui, ui.checkBox_record_success_file)
    got = _abs(ui, ui.checkBox_check_symlink_definition)
    lead = ui.checkBox_check_symlink
    assert got != anchor, f"极窄窗口下让位量不足却仍移动了目标: {got} == {anchor}"
    assert lead.width() > win._GUAXIAOMULU_MIN_LEAD_W, f"前导项被压到 {lead.width()}px，会夹住文字"
    assert _abs(ui, ui.checkBox_auto_clean) == _abs(ui, ui.checkBox_clean_file_ext), (
        "极窄窗口下「刮削时自动清理」未与「启用」对齐（该需求与让位量无关，必须生效）"
    )
