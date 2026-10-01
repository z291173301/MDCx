"""设置-命名页画质行与水印页水印设置组横向对齐的回归测试。

用户需求（锚点自身均保持不动）：
  ① 最大化时把「使用路径中包含的画质信息」向右移动到与下方「视频文件名」严格上下
     对齐的位置，「不获取分辨率」同步向右移动，「视频文件名」位置保持不变；
     最小化时界面、控件、组件等等均保持不变。
  ② 最大化时把「添加水印的图片」「水印大小」「水印类型」「水印位置」向左移动到与
     「首个水印位置：」严格上下对齐的位置（注意是对齐冒号），「首个水印位置：」的
     位置保持不变，右侧的复选框、提示词、组件等同步向左移动；最小化时界面、控件、
     组件等等均保持不变。

根因防线（任一回归都会让本文件失败）：
  - 需求① 的 horizontalLayout_112 三项 Minimum/Minimum/Fixed、总需求恰好等于容器宽
    （471 = 197 + 196 + 66 + 2×6）：对子控件 setGeometry 会被下次 layout 激活覆盖，
    只插间隔也不行（总需求一旦小于容器宽，Qt 把富余摊给其余 Minimum 项、目标弹回
    原位），只能「容器加宽 need + 目标前插 need - spacing 宽的固定间隔」，使行内总
    需求恒等于容器宽。
  - layoutWidget_26 是 frame_6 内绝对定位的容器：只恢复 min/max 收不回宽度（widget
    保持当前宽），必须先真解锁（setMinimumWidth(0)+setMaximumWidth(QWIDGETSIZE_MAX)）
    再按记录值把宽度写回去，否则加宽量逐遍累积（实测 holder 471→559 越垒越高）。
  - 需求② 的 gridLayout_24 col1 行内多为 Maximum 策略（capped 在 sizeHint）或 Fixed
    宽：无处吸收富余时多出的宽度会溢回 col0，光钉 col0/stretch 拉不动；必须在 col1
    四行尾部补 Expanding 间隔让 col1 无界吸收，富余才全进 col1、col0 恒 130。
  - 判态一律用几何拉伸量 _scroll_stretch_extra() 而非 isMaximized()。
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


def _goto_tab(win, app, name):
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == name:
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError(f"{name} not found")
    app.processEvents()


def _abs_naming(ui, widget):
    return widget.mapTo(ui.scrollAreaWidgetContents_mingming, QPoint(0, 0)).x()


def _abs_wm(ui, widget):
    return widget.mapTo(ui.scrollAreaWidgetContents_shuiyin, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 900), (1100, 800))
_NARROW_SIZES = ((1000, 700), (1030, 753))

# 命名页：目标、锚点、参照
_NAMING_TARGET = "radioButton_videosize_path"
_NAMING_FOLLOWER = "radioButton_videosize_none"
_NAMING_LEAD = "radioButton_videosize_video"
_NAMING_ANCHOR = "checkBox_filename_4k"
_NAMING_REFS = (
    "radioButton_videosize_video",
    "checkBox_filename_4k",
    "checkBox_foldername_4k",
    "label_357",
    "label_332",
)
_NAMING_BOXES = ("groupBox_65", "groupBox_67", "frame_6", "layoutWidget_26")

# 水印页：四行左标签、锚点、右侧随动项
_WM_LABELS = ("label_128", "label_139", "label_135", "label_127")
_WM_ANCHOR = "label_126"
_WM_FOLLOWERS = (
    "checkBox_poster_mark",
    "checkBox_thumb_mark",
    "checkBox_fanart_mark",
    "horizontalSlider_mark_size",
    "lcdNumber_mark_size",
    "checkBox_sub",
    "checkBox_censored",
    "checkBox_umr",
    "checkBox_leak",
    "checkBox_uncensored",
    "checkBox_hd",
    "radioButton_not_fixed_position",
    "radioButton_fixed_corner",
    "radioButton_fixed_position",
    "label_130",
    "label_140",
    "label_138",
    "label_141",
)
_WM_REFS = (
    "label_126",
    "groupBox_31",
    "groupBox_36",
    "groupBox_39",
    "groupBox_42",
    "gridLayoutWidget_24",
    "gridLayoutWidget_30",
)


def _naming_snapshot(ui):
    snap = {
        name: (_abs_naming(ui, getattr(ui, name)), getattr(ui, name).width())
        for name in (_NAMING_TARGET, _NAMING_FOLLOWER) + _NAMING_REFS
    }
    for name in _NAMING_BOXES:
        snap[name] = getattr(ui, name).geometry().getRect()
    snap["hl112"] = (ui.horizontalLayout_112.spacing(), ui.horizontalLayout_112.count())
    return snap


def _wm_snapshot(ui):
    snap = {
        name: (_abs_wm(ui, getattr(ui, name)), getattr(ui, name).width())
        for name in _WM_LABELS + (_WM_ANCHOR,) + _WM_FOLLOWERS
    }
    for name in _WM_REFS:
        snap[name] = getattr(ui, name).geometry().getRect()
    return snap


def _baseline_without(win, app, monkeypatch, take, method, clear):
    """摘掉指定方法（先清掉它的残留）重跑同步，返回「只有通用逻辑」的基线，随后复位。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    cls = mw_mod.MyMAinWindow
    original = getattr(cls, method)
    monkeypatch.setattr(cls, method, lambda self, _scroll=None: None)
    try:
        clear()
        win._sync_page_layouts()
        app.processEvents()
        base = take()
    finally:
        monkeypatch.setattr(cls, method, original)
    win._sync_page_layouts()
    app.processEvents()
    return base


def _assert_ref_eq(new, base, width, name):
    """参照断言：宽度必须精确相等；x 允许 ±1px（不同字体/DPI 下布局引擎的 qreal
    舍入 phantom，子像素级不可见；真正的回归都是 10px 以上）。"""
    assert new[1] == base[1], f"{width} 宽下 {name} 宽度被改动: {base} -> {new}"
    assert abs(new[0] - base[0]) <= 1, f"{width} 宽下 {name} 左缘被带偏: {base} -> {new}"


def _naming_baseline(win, app, monkeypatch, take):
    return _baseline_without(win, app, monkeypatch, take, "_sync_naming_definition_align", win._clear_naming_defn_align)


def _wm_baseline(win, app, monkeypatch, take):
    return _baseline_without(
        win, app, monkeypatch, take, "_sync_watermark_colon_align", win._clear_watermark_colon_align
    )


def test_naming_path_aligns_to_filename_when_wide(win, app, monkeypatch):
    """需求①：宽态「使用路径中包含的画质信息」精确落在「视频文件名」列上。"""
    ui = win.Ui
    win.show()
    _goto_tab(win, app, "tab_3")
    for width, height in _WIDE_SIZES:
        _resize(win, app, width, height)
        assert win._scroll_stretch_extra(ui.scrollArea_7) > 0, f"{width} 宽下应处于宽态"
        anchor = _abs_naming(ui, ui.checkBox_filename_4k)
        got = _abs_naming(ui, ui.radioButton_videosize_path)
        assert got == anchor, f"{width} 宽下未对齐: x={got} 期望={anchor}"
        # 「不获取分辨率」同步向右移动（相对基线右移，且移动量与目标一致）
        base = _naming_baseline(win, app, monkeypatch, lambda: _naming_snapshot(ui))
        new = _naming_snapshot(ui)
        shift_target = new[_NAMING_TARGET][0] - base[_NAMING_TARGET][0]
        assert shift_target > 0, f"{width} 宽下目标未右移"
        shift_follower = new[_NAMING_FOLLOWER][0] - base[_NAMING_FOLLOWER][0]
        # 开环跟随：none 的位置由「path 右缘 + 行间距」决定，没有回读修正，
        # 不同字体/DPI 下有 ±5px 以内的舍入差（实测 65 vs 62）；关键是它确实同步右移。
        assert shift_follower > 0, f"{width} 宽下「不获取分辨率」未同步右移"
        assert abs(shift_follower - shift_target) <= 5, (
            f"{width} 宽下「不获取分辨率」移动量与目标差太多: {shift_follower} vs {shift_target}"
        )
        # 前导项与锚点纹丝不动（±1px 子像素舍入容差，见 _assert_ref_eq）
        for name in _NAMING_REFS:
            _assert_ref_eq(new[name], base[name], width, name)


def test_naming_leaves_narrow_untouched(win, app, monkeypatch):
    """新需求：窄态三复选框左移到 path 列，path/宽态容器不动，最大化布局不变。

    最小化时视频文件名（上下两个）+空格向左移动到与「使用路径中包含的画质信息」
    上下严格对齐，锚点位置保持不变；最大化时的页面布局控件提示等均保持不变
    （宽态分支另测，这里只锁定窄态）。
    """
    ui = win.Ui
    win.show()
    _goto_tab(win, app, "tab_3")
    for width, height in _NARROW_SIZES:
        _resize(win, app, width, height)
        assert win._scroll_stretch_extra(ui.scrollArea_7) <= 0, f"{width} 宽下应处于窄态"
        anchor = _abs_naming(ui, ui.radioButton_videosize_path)
        for name in ("checkBox_filename_mosaic", "checkBox_cd_part_space", "checkBox_filename_4k"):
            got = _abs_naming(ui, getattr(ui, name))
            assert got == anchor, f"{width} 宽下 {name} 未对齐到 path 列: x={got} 期望={anchor}"
        # 锚点 path 自身不动（与摘掉方法后的基线一致）
        base = _naming_baseline(win, app, monkeypatch, lambda: _naming_snapshot(ui))
        new = _naming_snapshot(ui)
        assert new[_NAMING_TARGET] == base[_NAMING_TARGET], (
            f"{width} 宽下锚点被带偏: {base[_NAMING_TARGET]} -> {new[_NAMING_TARGET]}"
        )
    assert win._naming_defn_spacers == [], "窄态残留画质行间隔"
    assert win._naming_defn_restores == [], "窄态残留容器加宽登记"
    assert win._naming_narrow_restores != [], "窄态三复选框未登记左移"


def test_naming_idempotent_and_round_trip(win, app):
    """需求①：幂等 + 窄↔宽往返自愈。"""
    ui = win.Ui
    win.show()
    _goto_tab(win, app, "tab_3")
    _resize(win, app, 1030, 753)
    narrow = _naming_snapshot(ui)
    _resize(win, app, 1030, 753)
    assert _naming_snapshot(ui) == narrow, "窄态二次同步漂移"
    _resize(win, app, 1920, 1170)
    wide = _naming_snapshot(ui)
    assert wide != narrow, "宽态未产生任何位移，钉位机制本身失效"
    assert wide[(_NAMING_TARGET)][0] == wide[(_NAMING_ANCHOR)][0], "宽态目标未落在锚点列"
    _resize(win, app, 1920, 1170)
    assert _naming_snapshot(ui) == wide, "宽态二次同步漂移"
    _resize(win, app, 1030, 753)
    assert _naming_snapshot(ui) == narrow, "窄→宽→窄往返未复原"


def test_watermark_labels_align_to_first_position_when_wide(win, app, monkeypatch):
    """需求②：宽态四行左标签冒号与「首个水印位置：」冒号严格对齐，右侧同步左移。"""
    ui = win.Ui
    win.show()
    _goto_tab(win, app, "tab4")
    moved = dict.fromkeys(_WM_FOLLOWERS, False)
    for width, height in _WIDE_SIZES:
        _resize(win, app, width, height)
        assert win._scroll_stretch_extra(ui.scrollArea_4) > 0, f"{width} 宽下应处于宽态"
        anchor_right = _abs_wm(ui, ui.label_126) + ui.label_126.width()
        for name in _WM_LABELS:
            right = _abs_wm(ui, getattr(ui, name)) + getattr(ui, name).width()
            assert right == anchor_right, f"{width} 宽下 {name} 冒号未对齐: right={right} 期望={anchor_right}"
        # 右侧复选框/滑杆/提示词同步向左移动（相对基线左移）。宽度不断言相等：
        # 基线里 col1 的富余由 Minimum 项自己吃掉（checkbox 会被拉宽），本方法用尾部
        # Expanding 间隔吸收后它们回到 hint 宽——这是修复的应有之义，需求只要求位置左移。
        base = _wm_baseline(win, app, monkeypatch, lambda: _wm_snapshot(ui))
        new = _wm_snapshot(ui)
        for name in _WM_FOLLOWERS:
            assert new[name][0] <= base[name][0], f"{width} 宽下 {name} 反而右移: {base[name]} -> {new[name]}"
            if new[name][0] < base[name][0]:
                moved[name] = True
        # 锚点与组框容器纹丝不动
        for name in _WM_REFS:
            assert new[name] == base[name], f"{width} 宽下 {name} 被改动: {base[name]} -> {new[name]}"
    assert all(moved.values()), (
        f"宽态下没有 follower 真正左移过，对齐机制可能根本没生效: {sorted(k for k, v in moved.items() if not v)}"
    )


def test_watermark_leaves_narrow_untouched(win, app, monkeypatch):
    """需求②：窄态与基线逐项一致，最小化逐像素不变。"""
    ui = win.Ui
    win.show()
    _goto_tab(win, app, "tab4")
    for width, height in _NARROW_SIZES:
        _resize(win, app, width, height)
        assert win._scroll_stretch_extra(ui.scrollArea_4) <= 0, f"{width} 宽下应处于窄态"
        assert _wm_snapshot(ui) == _wm_baseline(win, app, monkeypatch, lambda: _wm_snapshot(ui)), (
            f"{width} 宽下窄态被改动"
        )


def test_watermark_idempotent_and_round_trip(win, app):
    """需求②：幂等 + 窄↔宽往返自愈。"""
    ui = win.Ui
    win.show()
    _goto_tab(win, app, "tab4")
    _resize(win, app, 1030, 753)
    narrow = _wm_snapshot(ui)
    _resize(win, app, 1030, 753)
    assert _wm_snapshot(ui) == narrow, "窄态二次同步漂移"
    _resize(win, app, 1920, 1170)
    wide = _wm_snapshot(ui)
    assert wide != narrow, "宽态未产生任何位移，钉位机制本身失效"
    _resize(win, app, 1920, 1170)
    assert _wm_snapshot(ui) == wide, "宽态二次同步漂移"
    _resize(win, app, 1030, 753)
    assert _wm_snapshot(ui) == narrow, "窄→宽→窄往返未复原"
