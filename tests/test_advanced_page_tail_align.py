"""设置-高级页下半三处右移对齐的回归测试（仅最大化态生效）。

用户需求（三个锚点自身均保持不动，最小化态整页逐像素不变，含提示词与控件提示）：
  ① 「保存日志」「检查更新」两行的「关」右移到与「隐藏NFO库管理」严格上下对齐；
  ② 「隐藏窗口」行的「点最小化按钮」右移到与「显示字段来源信息」严格上下对齐；
  ③ 同一行最右侧的「无」右移到与「显示字段内容信息」严格上下对齐。

根因防线（任一回归都会让本文件失败）：
  - 三处手法不同，勿互相套用。①所在行容器是顶层组框的**直接子项**、被通用
    宽幅同步判成 _STRETCH 每遍拉宽并重排行内布局，两个单选均分余量
    （宽态实测 742/741），钉死前导项「开」才能把「关」的左缘钉在锚点上。
  - ②③所在行容器 layoutWidget_17 **完全不参与拉伸**（它是 frame_3 的子控件，
    而通用同步只登记顶层组框的直接子项），四个尺寸下恒为 551x32、三个单选按
    551 均分（180/179/180）。两个锚点在另一个组框里随该组一起拉伸，行内位置
    与锚点之间没有任何联动，只能钉死前两项 + 按落点加宽容器。
  - 容器加宽的下界必须是 lw.sizeHint()（168 = 三项 hint 之和 + 两间隔），**不是**
    设计宽 551：n 随拉伸量增长，刚过「宽态线」那一段 want_w 只有 400 出头
    （1100 宽实测 457 < 551），拿 551 卡门会让那段窗宽全部漏排。
  - 判态用几何拉伸量 _scroll_stretch_extra() > 0 而非 isMaximized()：窗口管理器
    最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False，用户会看到
    「先在原位、再跳到对齐位」。窄态下「关」反而在锚点右侧约 80px，所以判态
    判错方向会把「向右移动」实现成左移。
  - 跨分支 mapTo（锚点在 groupBox_12 内、目标在 groupBox_17/_4 与 frame_3）必须
    经公共祖先 scrollAreaWidgetContents_gaoji 中转。
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


def _goto_advanced(win, app):
    """切到设置页的「高级」tab（该 tab 的 objectName 是 tab5，不是 tab_5）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab5":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("高级 tab5 not found")
    app.processEvents()


def _abs(ui, widget) -> int:
    """控件左缘映射到高级页滚动内容的绝对 x（跨分支必须经 content 中转）。"""
    return widget.mapTo(ui.scrollAreaWidgetContents_gaoji, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


def _extra(win) -> int:
    return win._scroll_stretch_extra(win._adv_scroll)


# 本文件覆盖高级页两组竖线需求：
#   第一组（v2.1.9「右移」）：两个「关」→「隐藏NFO库管理」、「点最小化按钮」→
#     「显示字段来源信息」、「无」→「显示字段内容信息」
#   第二组（v2.1.9「左移」）：刮削结束后自动退出软件 / 停止刮削时 /
#     隐藏菜单栏图标（Mac）/ 暗黑模式 / 隐藏NFO库管理 / 两枚「关」
#     → 「显示字段来源信息」
# 第二组把竖线整体换成了 checkBox_show_from_log，两组在宽态下**同时成立**：
# 两枚「关」先随「隐藏NFO库管理」左移，再被第一组的 tail_align 拉回它右侧。
_LEFT_TARGETS = (
    ("checkBox_auto_exit", "checkBox_show_from_log"),
    ("checkBox_show_dialog_stop_scrape", "checkBox_show_from_log"),
    ("checkBox_dark_mode", "checkBox_show_from_log"),
    ("checkBox_hide_nfo_nav", "checkBox_show_from_log"),
    ("radioButton_log_off", "checkBox_show_from_log"),
    ("radioButton_update_off", "checkBox_show_from_log"),
)

# 「隐藏菜单栏图标（Mac）」单列，不在 _LEFT_TARGETS 里做钉死像素的断言，原因见
# _dock_row 的说明：它所在行是「Fixed 前缀 + 间隔 + 末项」结构，前缀宽度等于两个
# 控件的 sizeHint 之和，而 sizeHint 是**字体度量**的函数；离屏测试环境里的字体度量
# 既不真实也不稳定（tests/conftest.py 把 get_fonts 桩掉 -> QFontDatabase.families()
# 为 0，"Sans Serif" 解析不到任何字族；而 resources/fonts/ 里只有 Consolas 与
# Segoe UI Emoji、**没有任何 CJK 字体**，真跑 get_fonts 时 CJK 全部落到 .notdef，
# 横向 advance 只剩 91px）。两个环境给出的前缀宽度差约 1.5 倍，于是「这一行放不放
# 得下」的结论在测试环境里与生产不一致——钉死像素等于在断言一个假度量。
# 故改为按实测可行性分别断言（test_menu_icon_row_aligns_or_defers），其对回归仍
# 有判别力：放得下却没对齐、或放不下却硬对齐（必然裁字/压住前缀）都会红。
_EXTRA_NAMES = ("checkBox_hide_menu_icon",)

# (目标, 锚点)：第一组右移三处 + 第二组两枚「关」
_TARGETS = (
    ("radioButton_log_off", "checkBox_hide_nfo_nav"),
    ("radioButton_update_off", "checkBox_hide_nfo_nav"),
    ("radioButton_hide_mini", "checkBox_show_from_log"),
    ("radioButton_hide_none", "checkBox_show_data_log"),
)

# 宽态下**整块几何**都不许动的参照：三个锚点、其余行内控件、容器、组框。
_REFS = (
    "checkBox_show_web_log",
    "checkBox_show_from_log",
    "checkBox_show_data_log",
    "frame_3",
    "layoutWidget_3",
    "horizontalLayoutWidget_11",
    "horizontalLayoutWidget_7",
    "groupBox_3",
    "groupBox_4",
    "groupBox_12",
    "groupBox_17",
)

# 宽态下**只许改宽度、不许改左缘**的中间量：它们正是需求生效的搬运工与容器，
# 量到宽度差异恰恰是对齐生效的证据，拿整块几何去卡会误报。
#   checkBox_auto_start      阶段一被钉死的前导项，「刮削结束后自动退出软件」靠它落到竖线
#   checkBox_hide_actor_nav  第 12 行被钉的前导项，「隐藏NFO库管理」靠它落到竖线
#   radioButton_log_on / radioButton_update_on
#                           第一组两行的前导项「开」，两枚「关」靠它们落到「隐藏NFO库管理」
#   radioButton_hide_close   「隐藏窗口」行被钉的前导项，「点最小化按钮」「无」靠它排下去
#   layoutWidget5            「界面外观行」容器，宽态按落点收窄/加宽（frame 无布局，用 setGeometry）
#   layoutWidget_17          「隐藏窗口」行容器，宽态按落点加宽（frame_3 无布局，用 setGeometry）
_REFS_X_ONLY = (
    "checkBox_auto_start",
    "checkBox_hide_actor_nav",
    "radioButton_log_on",
    "radioButton_update_on",
    "radioButton_hide_close",
    "layoutWidget5",
    "layoutWidget_17",
)

# 宽态下必然随需求一起动的从动项（末位吸收余量/紧贴右邻），只作窄态与往返比对。
_FOLLOWERS = ("label_nav_hide_hint",)

# 全部落在宽态（_scroll_stretch_extra() > 0）；1100 特意保留——它是最贴近
# 刚过宽态线的那一档，正是 want_w < 551 曾被误判为「放不下」的那一档。
_WIDE_SIZES = ((1920, 1170), (1600, 1000), (1366, 850), (1100, 800))
_NARROW_SIZES = ((1030, 753), (1000, 700))


def _snapshot(ui):
    names = (
        _REFS
        + _REFS_X_ONLY
        + _FOLLOWERS
        + tuple(n for n, _ in _TARGETS)
        + tuple(n for n, _ in _LEFT_TARGETS)
        + _EXTRA_NAMES
    )
    return {name: (_abs(ui, getattr(ui, name)), getattr(ui, name).width()) for name in dict.fromkeys(names)}


def _statics(ui):
    """提示词 / 控件提示 / 尺寸提示：需求要求一个都不许动。"""
    names = ("radioButton_hide_close",) + tuple(t for t, _ in _TARGETS) + tuple(a for _, a in _TARGETS)
    names += tuple(t for t, _ in _LEFT_TARGETS) + _EXTRA_NAMES
    return {
        name: (
            getattr(ui, name).text(),
            getattr(ui, name).toolTip(),
            getattr(ui, name).sizeHint().width(),
        )
        for name in dict.fromkeys(names)
    }


def _without_feature(win, app, monkeypatch, width, height):
    """造一份「只有通用宽幅逻辑」的基线快照：另起一个窗口，两个对齐控制器全程摘掉。

    不能在同一个窗口上摘掉方法再跑一次同步——摘掉后就没人解除上一轮留下的钉宽
    （setFixedWidth 落在控件自身的 min/max 上，跨调用留存），量到的「基线」会带着
    新竖线，比对就成了自己比自己（本文件第一版正是栽在这里：base 与 now 全等）。

    第二组改的是 _sync_advanced_page_align 本体（不是独立方法），故两个都得摘。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    originals = {
        "_sync_advanced_page_align": mw_mod.MyMAinWindow._sync_advanced_page_align,
        "_sync_advanced_page_tail_align": mw_mod.MyMAinWindow._sync_advanced_page_tail_align,
    }
    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_align", lambda self, *a, **k: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "_sync_advanced_page_tail_align", lambda self: None)
    probe = None
    try:
        probe = mw_mod.MyMAinWindow()
        for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
            getattr(probe, timer_name).stop()
        probe.show()
        _goto_advanced(probe, app)
        _resize(probe, app, width, height)
        return _snapshot(probe.Ui), _statics(probe.Ui)
    finally:
        if probe is not None:
            probe.close()
            probe.deleteLater()
            app.processEvents()
        for name, fn in originals.items():
            monkeypatch.setattr(mw_mod.MyMAinWindow, name, fn)


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_tail_aligns_to_anchors_in_wide(win, app, width, height):
    """需求①②③：宽态下四个目标分别精确落在三个锚点的左缘上。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    for target, anchor in _TARGETS:
        got = _abs(ui, getattr(ui, target))
        want = _abs(ui, getattr(ui, anchor))
        assert got == want, f"{width} 宽下「{target}」未与「{anchor}」严格上下对齐: x={got} 期望={want}"


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_left_targets_land_on_from_log_in_wide(win, app, width, height):
    """第二组：宽态下六项一律精确落在「显示字段来源信息」的左缘上。

    第七项「隐藏菜单栏图标（Mac）」不在此列，它由 test_menu_icon_row_aligns_or_defers
    按实测可行性单独断言（理由见 _EXTRA_NAMES）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    want = _abs(ui, ui.checkBox_show_from_log)
    for target, anchor in _LEFT_TARGETS:
        assert anchor == "checkBox_show_from_log"
        got = _abs(ui, getattr(ui, target))
        assert got == want, f"{width} 宽下「{target}」未与「显示字段来源信息」严格上下对齐: x={got} 期望={want}"


def _dock_row(ui):
    """隐藏图标行（horizontalLayout_dock）的实测可行性。

    与 _sync_advanced_page_align 里那一段同式：前缀 = 两个 Fixed 文本项的 sizeHint
    之和 + 两个间隔，能插入的间隔 gap = 新竖线 - 行左缘 - 前缀；放得下的条件是
    gap >= 0 且让出 gap 后剩余宽度仍够末项的 sizeHint（sizeHint 就是不裁字下限）。
    量到的竖线用「刮削结束后自动退出软件」代理——阶段一钉完之后它恰在新锚点上。
    """
    lay = ui.horizontalLayout_dock
    host = ui.gridLayoutWidget_20
    content = ui.scrollAreaWidgetContents_gaoji
    host_x = host.mapTo(content, QPoint(0, 0)).x()
    row_x = _abs(ui, ui.checkBox_hide_dock_icon) - host_x
    col_w = host.width() - row_x
    anchor = _abs(ui, ui.checkBox_auto_exit) - host_x
    prefix = ui.checkBox_hide_dock_icon.sizeHint().width() + ui.label_42.sizeHint().width() + 2 * lay.spacing()
    gap = anchor - row_x - prefix
    return {
        "gap": gap,
        "prefix": prefix,
        "feasible": gap >= 0 and col_w - gap - prefix >= ui.checkBox_hide_menu_icon.sizeHint().width(),
    }


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_menu_icon_row_aligns_or_defers(win, app, monkeypatch, width, height):
    """「隐藏菜单栏图标（Mac）」：放得下就必须精确对齐，放不下就整行放弃。

    放弃态的语义与本页其余各行一致：间隔归 0、不裁字、Fixed 前缀两项一律不动，
    于是末项停在竖线**右侧**（前缀本身就压过竖线，物理上够不到）。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) > 0, f"{width} 宽下应处于宽态（拉伸量 > 0）"

    row = _dock_row(ui)
    menu = ui.checkBox_hide_menu_icon
    dock = ui.checkBox_hide_dock_icon
    anchor_x = _abs(ui, ui.checkBox_show_from_log)
    menu_x = _abs(ui, menu)
    prefix_before = (_abs(ui, dock), _abs(ui, ui.label_42))

    if row["feasible"]:
        assert menu_x == anchor_x, f"{width} 宽下前缀放得下（gap={row['gap']}）却未对齐: x={menu_x} 期望={anchor_x}"
    else:
        assert menu_x > anchor_x, (
            f"{width} 宽下前缀放不下（gap={row['gap']}）本应整行放弃，却对到了 x={menu_x}（可能裁字）"
        )
        assert _abs(ui, ui.label_42) + ui.label_42.width() <= menu_x, (
            f"{width} 宽下放弃态里「隐藏菜单栏图标」压住了 Fixed 前缀: 前缀右缘"
            f"{_abs(ui, ui.label_42) + ui.label_42.width()} > 目标左缘 {menu_x}"
        )

    # 两种情形下 Fixed 前缀两项都不许动、末项都不许被压到裁字
    win._sync_page_layouts()
    app.processEvents()
    assert (_abs(ui, dock), _abs(ui, ui.label_42)) == prefix_before, (
        f"{width} 宽下 Fixed 前缀两项被本需求带偏: {prefix_before} -> {(_abs(ui, dock), _abs(ui, ui.label_42))}"
    )
    assert menu.width() >= menu.sizeHint().width(), (
        f"{width} 宽下「隐藏菜单栏图标」被压到 {menu.width()}px（sizeHint {menu.sizeHint().width()}），会裁字"
    )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_new_line_is_left_of_the_old_one_in_wide(win, app, monkeypatch, width, height):
    """第二组的方向是「向左」：新竖线必须严格落在旧竖线左侧。

    旧竖线 = 只有通用宽幅逻辑时「刮削结束后自动退出软件」的自然位（`_without_feature`
    另起窗口量得），旧代码正是拿它当基准。断言「新竖线 < 旧竖线」而不是逐项与通用
    逻辑比大小——后者依赖字体度量：本文件所用离屏环境里「显示字段来源信息」与旧基准
    的左右关系并不总与生产一致（例如 1920 宽下暗黑模式由 428 被移到 589，看着是右移，
    但那是因为通用逻辑把「界面外观行」摊到了另一处，真实生产度量下是左移）。
    真正与环境无关的是「新竖线在旧竖线左边」，它对每一档都成立。
    """
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    old_line = base["checkBox_auto_exit"][0]
    win._sync_page_layouts()
    app.processEvents()

    new_line = _abs(ui, ui.checkBox_show_from_log)
    assert new_line < old_line, f"{width} 宽下新竖线未在旧竖线左侧: 新={new_line} 旧={old_line}"
    for target, _ in _LEFT_TARGETS:
        assert _abs(ui, getattr(ui, target)) <= old_line, (
            f"{width} 宽下「{target}」落到了旧竖线右侧: x={_abs(ui, getattr(ui, target))} 旧竖线={old_line}"
        )


@pytest.mark.parametrize("width,height", _WIDE_SIZES)
def test_wide_never_moves_anchors_and_never_clips(win, app, monkeypatch, width, height):
    """锚点自身逐项不动；且「无」不许被压到裁字（宽度 >= 自身 sizeHint）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)

    base, _ = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    for name in _REFS:
        assert _snapshot(ui)[name] == base[name], (
            f"{width} 宽下参照控件「{name}」被本需求带偏: {base[name]} -> {_snapshot(ui)[name]}"
        )
    for name in _REFS_X_ONLY:
        assert _snapshot(ui)[name][0] == base[name][0], (
            f"{width} 宽下搬运工/容器「{name}」左缘被本需求带偏: {base[name]} -> {_snapshot(ui)[name]}"
        )

    for name in ("radioButton_hide_close",) + tuple(t for t, _ in _TARGETS):
        box = getattr(ui, name)
        assert box.width() >= box.sizeHint().width(), (
            f"{width} 宽下「{name}」被压到 {box.width()}px（sizeHint {box.sizeHint().width()}），会裁字"
        )

    # 「无」的右缘不得越出 frame_3（frame 无布局，越界子控件会被父控件裁掉）
    lw = ui.layoutWidget_17
    none = ui.radioButton_hide_none
    assert _abs(ui, none) + none.width() <= _abs(ui, ui.frame_3) + ui.frame_3.width(), (
        f"{width} 宽下「无」越出 frame_3 右缘"
    )
    assert lw.width() >= lw.sizeHint().width(), (
        f"{width} 宽下 layoutWidget_17={lw.width()} 窄于布局最小 {lw.sizeHint().width()}"
    )


@pytest.mark.parametrize("width,height", _NARROW_SIZES)
def test_narrow_state_untouched(win, app, monkeypatch, width, height):
    """最小化态：往返后与「只有通用逻辑」的窄态基线逐像素一致（两控制器零介入）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)
    _resize(win, app, width, height)
    assert _extra(win) <= 0, f"{width} 宽下应处于窄态（拉伸量 <= 0）"

    base, base_statics = _without_feature(win, app, monkeypatch, width, height)
    win._sync_page_layouts()
    app.processEvents()

    # 窄态下五个左移目标必须正好停在「只有通用逻辑」时的位置——第二组改的
    # _sync_advanced_page_align 在窄态须完全退让（它换了基准线，很容易漏）
    for target, _ in _LEFT_TARGETS:
        assert _abs(ui, getattr(ui, target)) == base[target][0], (
            f"窄态 {width} 宽下「{target}」被本需求带偏: 基线={base[target][0]} 实际={_abs(ui, getattr(ui, target))}"
        )

    # 最大化再还原回来，窄态必须与上面那份基线逐像素相同
    _resize(win, app, 1920, 1170)
    assert _extra(win) > 0, "往返中途应处于宽态"
    _resize(win, app, width, height)

    for name in _snapshot(ui):
        assert _snapshot(ui)[name] == base[name], (
            f"往返后窄态「{name}」与通用逻辑基线不同: 基线={base[name]} 实际={_snapshot(ui)[name]}"
        )
    assert _statics(ui) == base_statics, "往返后窄态的提示词/控件提示被改动"

    # 窄态下钉宽必须已解除、容器回到设计宽 551
    assert ui.layoutWidget_17.width() == win._ADV_HIDE_LW_W, (
        f"窄态 layoutWidget_17 宽 {ui.layoutWidget_17.width()} != 设计宽 {win._ADV_HIDE_LW_W}"
    )
    # 只列「窄态本就不该钉」的：第 6/8/9 行（退出软件时 / 菜单栏图标 / 暗黑模式）
    # 是两态生效，不在此列；第 12 行与第一组三处、以及本次新增的阶段一前导项
    # checkBox_auto_start 都只在宽态钉，窄态必须解除。
    for name in (
        "radioButton_hide_close",
        "radioButton_hide_mini",
        "radioButton_log_on",
        "radioButton_update_on",
        "checkBox_auto_start",
        "checkBox_hide_actor_nav",
        "checkBox_hide_nfo_nav",
    ):
        box = getattr(ui, name)
        assert box.minimumWidth() == 0 and box.maximumWidth() == 16777215, f"窄态「{name}」的钉宽未解除"


def test_round_trip_is_stable(win, app):
    """最大化↔最小化往返 3 轮：窄态快照、宽态对齐结果都不许漂移。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    _resize(win, app, 1030, 753)
    narrow = _snapshot(ui)
    statics = _statics(ui)
    _resize(win, app, 1920, 1170)
    all_pairs = _TARGETS + _LEFT_TARGETS
    wide = {target: _abs(ui, getattr(ui, target)) - _abs(ui, getattr(ui, anchor)) for target, anchor in all_pairs}

    for _ in range(3):
        _resize(win, app, 1030, 753)
        assert _snapshot(ui) == narrow, "往返后窄态几何漂移"
        assert _statics(ui) == statics, "往返后提示词/控件提示漂移"
        _resize(win, app, 1920, 1170)
        now = {target: _abs(ui, getattr(ui, target)) - _abs(ui, getattr(ui, anchor)) for target, anchor in all_pairs}
        assert now == wide, f"往返后宽态对齐偏移漂移: {wide} -> {now}"


def test_repeated_sync_is_idempotent(win, app):
    """重复调用全量同步不应再改动任何几何（钉宽已封死成终态）。"""
    ui = win.Ui
    win.show()
    _goto_advanced(win, app)

    for width, height in _WIDE_SIZES:
        _resize(win, app, width, height)
        before = _snapshot(ui)
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
            assert _snapshot(ui) == before, f"{width} 宽下重复同步仍在改几何: {before} -> {_snapshot(ui)}"
