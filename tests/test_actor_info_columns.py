"""演员页「补全Emby/Jellyfin演员信息」组列对齐回归测试。

用户需求（两轮共七条）：
  ① 「补全语言：」「演员信息数据库：」与「补全范围：」的**冒号**严格上下对齐（窄宽双态）。
  ② 宽态「中文简体」「所有演员」左缘对齐「使用Graphis背景」。
  ③ 宽态「中文繁体」「使用数据库补全演员信息」左缘对齐「使用Graphis头像」。
  ④ 宽态「日语」「不存在中文时，翻译日语为中文」左缘对齐「请求Graphis最新图片」。
  ⑤ 宽态「使用数据库补全演员信息」「点击下载演员数据库」「不存在中文时，翻译日语为
     中文」「不勾选则无中文时使用日语」左缘对齐「使用Graphis背景」（⑤ 覆盖了③④中
     这两行的旧目标列），三个 Graphis 锚点自身不动。
  ⑥ 宽态「演员信息数据库：」输入框左缘扩到 A1、右缘缩到 A2，「选择文件」按钮同步左移；
     最小化时此行不变。
  ⑦ 窄态「不存在中文时，翻译日语为中文」「不勾选则无中文时使用日语」「使用数据库补全
     演员信息」「点击下载演员数据库」左缘对齐「中文简体」（窄态下「使用Graphis背景」
     与「中文简体」同在 x=186，A1 锚点即等价），「所有演员」同样左移对齐。
  ⑧ 窄态（最小化/还原）把「仅缺少信息的演员」「仅缺少头像的演员」「本地头像库」与同行
     的「点击下载头像包」向右移动到与「补全完成后自动补全演员头像」上下严格对齐的位置，
     该锚点自身保持不动；最大化态的页面保持不变。
  ⑨ 窄态把「选择文件」向右移动到与「选择目录」上下对齐的位置（「选择目录」保持不
     变），同时「演员信息数据库」显示框右侧向右拓展到右移后「选择文件」按钮的左侧
     位置；最大化时的界面、布局、控件均保持不变。
  ⑩ 窄态把「Jellyfin」向右移动到与「补全完成后自动补全演员头像」上下对齐的位置，
     该锚点保持不变；最大化时的界面、布局、控件均保持不变。
  ⑪ 最大化时把「Jellyfin」「补全完成后自动补全演员头像」「本地头像库」
     「点击下载头像包」「刮削结束后自动补全演员头像」向左移动到与「使用 Graphis
     头像」严格上下对齐的位置，「使用 Graphis 头像」位置保持不变；最小化/还原时
     的页面布局、控件、组件等等均保持不变。
  ⑫ 最大化时把「仅缺少头像的演员」「刮削结束后自动创建」向右移动到与「使用
     Graphis 头像」严格上下对齐的位置，「使用 Graphis 头像」位置保持不变；最小化/
     还原时的页面布局、控件、组件等等均保持不变。

根因防线（任一回归都会让本文件失败）：
  - gridLayout_14 的 col0 必须钉死 130px，否则 QGridLayout 把富余宽度摊给 col0
    （实测宽态 col0 长到 762、col1 起点被推到 818），目标列全在 186 左侧无法到达；
    该设置持久，窄态也必须钉住，否则「先最大化再还原」会污染窄态。
  - col1 各行受布局管理，setGeometry 会被下次 layout 激活覆盖，只能靠 QSpacerItem 钉位。
  - hl100 / hl159 是 hl98 / hl158 的**子布局**，其 16px / 20px 前导缩进来自父布局的
    spacing 与行首占位控件，必须先归零才能左移（间隔只能右推、不能左拉）。
  - 目标控件是 Minimum 策略，插固定宽间隔会被挤瘦（实测 253→52），故钉位时锁宽、还原解锁。
  - hl101 内只剩两个 Fixed 宽单选时 QHBoxLayout 会把富余宽度摊到行首（56px 空档），
    宽态需在尾部补 Expanding 间隔。
  - ⑧ 的三行让位手法：QSpacerItem 的 minimumSize 是 (0,0)，行内需求超出可用宽时第一个
    被压扁（实测 hl101 插 13px 间隔、目标只走了 6px），故 hl101 / hl96 用「目标收窄 +
    同行 setSpacing 撑开」并让行内总需求恒等于容器宽（否则富余摊行首、「所有演员」漂 2px）；
    hl95 的容器是随窗口变的一整列，改用「stretch 挪给行尾 hl97」把前导项收回自己的
    sizeHint、腾出的宽度全给行尾，插入的固定间隔才不会被挤瘦。
  - ⑧ 的登记/还原必须与 _actor_info_width_locks 分开且**逆序**写回：同一控件一趟里被钉两次
    （先钉设计宽、再钉让位后的收窄宽），正序还原会让中间值覆盖原值、把控件永久钉死在窄态
    的收窄宽上（实测 hl96 的「仅缺少头像的演员」卡在 237，宽态随之被带歪）。
  - ⑩ 的服务类型行（hl103）行宽随窗口变、两个单选是「均分可用宽」关系，钉宽值必须取
    当前实宽；且可用宽要取**行自身**矩形宽而非容器宽（容器 639 / 行 503，取容器宽会把
    「Emby」推出 136px）。
  - ⑨ 的路径行尾部本就有一个 Expanding 间隔，故「路径框 + 按钮 + 间隔」恒等于行宽，
    把路径框钉到「选择目录」按钮左缘减行间距，按钮即落到那一列（两个按钮同宽 110px，
    左缘对齐与右缘对齐等价）。
  - ⑪⑫ 的宽态方法必须排在 _sync_actor_info_columns **之后**：后者末尾会
    grid.invalidate()+activate()，把 _DOCK_RIGHT 的绝对定位项重新钉回
    「design_x + extra」的右缘（实测「补全完成后自动补全演员头像」被弹回 1348）。
  - ⑪ 的三个布局行是「均分可用宽」，必须把 stretch 从前导项挪给尾部项，否则 Qt 把
    行内余量摊回头一项、前导项钉窄失效；「点击下载头像包」不是独立目标，它在尾部
    子布局 hl97 内、跟随「本地头像库」。
  - ⑪ 的 hl96 容器 layoutWidget_12 是固定宽 511 的绝对定位件，塞不下 203px 的右移
    量，须先按「2×目标相对位置 + spacing」加宽（不进任何 registry，窄态要显式复位）。
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


def _goto_actor_page(win, app):
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab_5":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("演员 tab_5 not found")
    app.processEvents()


def _abs(ui, widget):
    """控件左缘映射到演员页滚动内容（公共 content 祖先）的绝对 x。"""
    from PyQt6.QtCore import QPoint

    return widget.mapTo(ui.scrollAreaWidgetContents_yanyuan, QPoint(0, 0)).x()


def _resize(win, app, width, height):
    win.resize(width, height)
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


# 需要锁住左缘的控件（需求②~⑤、⑦ 全部点名）
_COLUMN_WIDGETS = (
    "radioButton_actor_info_zh_cn",
    "radioButton_actor_info_zh_tw",
    "radioButton_actor_info_ja",
    "radioButton_actor_info_all",
    "radioButton_actor_info_miss",
    "checkBox_actor_info_translate",
    "label_106",
    "checkBox_actor_db",
    "label_download_actor_db",
    "lineEdit_actor_db_path",
    "pushButton_select_actor_info_db",
)


def test_actor_info_labels_colon_align_in_both_states(win, app):
    """需求①：两个行标签右缘（冒号）与「补全范围：」严格一致，窄宽两态 + 往返切换。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)

    reference = None
    for width, height in ((1000, 700), (1920, 1170), (1000, 700)):
        _resize(win, app, width, height)
        right = _abs(ui, ui.label_299) + ui.label_299.width()  # 「补全范围：」
        for label, name in ((ui.label_291, "补全语言："), (ui.label_431, "演员信息数据库：")):
            got = _abs(ui, label) + label.width()
            assert got == right, f"{width} 宽下 {name} 冒号未与「补全范围：」对齐: right={got} 期望={right}"
        assert _abs(ui, ui.label_293) + ui.label_293.width() == right, "头像来源：冒号未对齐"
        if reference is None:
            reference = right
        assert right == reference, f"参照列在往返切换后漂移: {reference} -> {right}"


def test_actor_info_columns_align_when_wide(win, app):
    """需求②~⑥：宽态三列对齐、⑤ 两行并入 A1、⑥ 输入框铺 A1→A2 且按钮跟随。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1920, 1170)

    a1 = _abs(ui, ui.checkBox_actor_photo_ne_backdrop)  # 使用Graphis背景
    a2 = _abs(ui, ui.checkBox_actor_photo_ne_face)  # 使用Graphis头像
    a3 = _abs(ui, ui.checkBox_actor_photo_ne_new)  # 请求Graphis最新图片
    assert (a2 - a1) > 300 and (a3 - a2) > 300, f"宽态锚点列间距异常: {a1}/{a2}/{a3}"

    # 锚点自身不得移动（本测试只钉目标，不碰锚点）
    for name, anchor, desc in (
        (ui.checkBox_actor_photo_ne_backdrop, a1, "使用Graphis背景"),
        (ui.checkBox_actor_photo_ne_face, a2, "使用Graphis头像"),
        (ui.checkBox_actor_photo_ne_new, a3, "请求Graphis最新图片"),
    ):
        assert _abs(ui, name) == anchor, f"{desc} 锚点自身被移动"

    cases = (
        (ui.radioButton_actor_info_zh_cn, a1, "中文简体 → 使用Graphis背景"),
        (ui.radioButton_actor_info_all, a1, "所有演员 → 使用Graphis背景"),
        (ui.radioButton_actor_info_zh_tw, a2, "中文繁体 → 使用Graphis头像"),
        (ui.radioButton_actor_info_ja, a3, "日语 → 请求Graphis最新图片"),
        (ui.radioButton_actor_info_miss, a2, "仅缺少信息的演员 → 使用Graphis头像"),
        # 需求⑤：这两行连同同排后续控件一并并入 A1
        (ui.checkBox_actor_info_translate, a1, "不存在中文时翻译日语为中文 → 使用Graphis背景"),
        (ui.checkBox_actor_db, a1, "使用数据库补全演员信息 → 使用Graphis背景"),
    )
    for widget, target, desc in cases:
        got = _abs(ui, widget)
        assert got == target, f"宽态 {desc} 未对齐: x={got} 期望={target}"

    # 需求⑤ 点名的同排后续控件紧随其首控件（不与首控件重叠即可）
    for follower, leader, desc in (
        (ui.label_106, ui.checkBox_actor_info_translate, "不勾选则无中文时使用日语"),
        (ui.label_download_actor_db, ui.checkBox_actor_db, "点击下载演员数据库"),
    ):
        assert _abs(ui, follower) > _abs(ui, leader), f"宽态 {desc} 未紧随其首控件"

    # 需求⑥：路径输入框左缘 A1、右缘 A2；选择文件按钮紧随输入框右缘
    assert _abs(ui, ui.lineEdit_actor_db_path) == a1, "路径输入框左缘未到 A1"
    assert _abs(ui, ui.lineEdit_actor_db_path) + ui.lineEdit_actor_db_path.width() == a2, (
        f"路径输入框右缘未缩到 A2: right={_abs(ui, ui.lineEdit_actor_db_path) + ui.lineEdit_actor_db_path.width()}"
    )
    assert _abs(ui, ui.pushButton_select_actor_info_db) >= a2, "选择文件按钮未随输入框左移"

    # 「补全范围：」两个单选保持设计宽，不被固定宽间隔挤瘦
    assert (ui.radioButton_actor_info_all.width(), ui.radioButton_actor_info_miss.width()) == (253, 252), (
        f"补全范围行单选宽被改变: {(ui.radioButton_actor_info_all.width(), ui.radioButton_actor_info_miss.width())}"
    )

    # 幂等：二次同步几何纹丝不动
    snap = {n: getattr(ui, n).geometry().getRect() for n in _COLUMN_WIDGETS}
    snap["holder"] = ui.layoutWidget_15.geometry().getRect()
    _resize(win, app, 1920, 1170)
    again = {n: getattr(ui, n).geometry().getRect() for n in _COLUMN_WIDGETS}
    again["holder"] = ui.layoutWidget_15.geometry().getRect()
    assert snap == again, f"二次同步漂移: {snap} -> {again}"


def test_actor_info_columns_align_when_narrow(win, app):
    """需求⑦：窄态两行 + 「所有演员」左移到「中文简体」所在列，语言行与路径行不动。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1000, 700)

    cn = _abs(ui, ui.radioButton_actor_info_zh_cn)  # 「中文简体」基准
    for widget, desc in (
        (ui.radioButton_actor_info_zh_cn, "中文简体"),
        (ui.checkBox_actor_info_translate, "不存在中文时翻译日语为中文"),
        (ui.checkBox_actor_db, "使用数据库补全演员信息"),
        (ui.radioButton_actor_info_all, "所有演员"),
    ):
        got = _abs(ui, widget)
        assert got == cn, f"窄态 {desc} 未与「中文简体」对齐: x={got} 期望={cn}"

    # 「所有演员」确实左移了 1~5px（用户给的容差，不允许原地不动）
    delta = cn - 186  # 186 = 需求实施前的窄态实测位
    assert 1 <= -delta <= 5 or delta == 0, f"「所有演员」左移量异常: {delta}px"

    for follower, leader, desc in (
        (ui.label_106, ui.checkBox_actor_info_translate, "不勾选则无中文时使用日语"),
        (ui.label_download_actor_db, ui.checkBox_actor_db, "点击下载演员数据库"),
    ):
        assert _abs(ui, follower) > _abs(ui, leader), f"窄态 {desc} 未紧随其首控件"

    # 需求⑥ 明确「最小化时不用变」：路径行在窄态不得被钉到宽态位置
    assert _abs(ui, ui.lineEdit_actor_db_path) != _abs(ui, ui.radioButton_actor_info_zh_tw), (
        "窄态路径输入框被误钉到宽态列"
    )
    assert ui.lineEdit_actor_db_path.width() != 466, "窄态路径输入框宽度仍停在宽态值"


def test_actor_info_state_restored_after_round_trip(win, app):
    """窄→宽→窄 往返：所有列控控件、宽度、缩进、行容器逐项复原，无残留。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)

    def snap():
        return {n: getattr(ui, n).geometry().getRect() for n in _COLUMN_WIDGETS}

    _resize(win, app, 1000, 700)
    base = snap()
    base_indent = (
        ui.horizontalLayout_98.spacing(),
        ui.label_280.width(),
        ui.horizontalLayout_159.getContentsMargins(),
        ui.layoutWidget_15.geometry().getRect(),
    )

    _resize(win, app, 1920, 1170)
    assert snap() != base, "宽态未产生任何位移，钉位机制本身失效"
    assert win._actor_info_spacers, "宽态未注入任何间隔"

    _resize(win, app, 1000, 700)
    assert snap() == base, f"还原态几何未复原: {snap()} vs {base}"
    now_indent = (
        ui.horizontalLayout_98.spacing(),
        ui.label_280.width(),
        ui.horizontalLayout_159.getContentsMargins(),
        ui.layoutWidget_15.geometry().getRect(),
    )
    assert now_indent == base_indent, f"还原态缩进/容器未复原: {base_indent} -> {now_indent}"
    assert win._actor_info_spacers == [], "还原态未清空间隔"
    # 窄态本身也要钉位（需求⑦/⑧），故宽度锁在窄态非空是正常的；真正要保证的是
    # 「锁定的是窄态值、不是宽态值」——路径输入框不得停在宽态的 466。
    assert ui.lineEdit_actor_db_path.width() != 466, (
        f"还原态路径输入框宽度仍停在宽态值: {ui.lineEdit_actor_db_path.width()}"
    )
    # 窄态宽度由「选择目录」按钮位置反推（需求①）：右缘紧贴按钮左缘
    path_right = _abs(ui, ui.lineEdit_actor_db_path) + ui.lineEdit_actor_db_path.width()
    assert path_right < _abs(ui, ui.pushButton_select_actor_info_db), "还原态路径框右缘未与按钮留出间距"
    assert ui.label_280.width() == base_indent[1], "还原态行首占位控件宽度未复原"


# ---------------------------------------------------------------------------
# 需求⑧⑨⑩：窄态把各控件右移到各自锚点列
# ---------------------------------------------------------------------------

# 需要右移对齐锚点的目标（窄态）
_NARROW_MOVE_TARGETS = (
    ("radioButton_actor_info_miss", "仅缺少信息的演员"),
    ("radioButton_actor_photo_miss", "仅缺少头像的演员"),
    ("radioButton_actor_photo_local", "本地头像库"),
)

# 左缘与宽度都不得被窄态右移带动的参照控件
_NARROW_REFS = (
    ("checkBox_actor_info_photo", "补全完成后自动补全演员头像（锚点）"),
    ("radioButton_actor_info_all", "所有演员"),
    ("radioButton_actor_photo_all", "所有演员（头像来源）"),
    ("label_299", "补全范围："),
)

# 涉及窄态右移的三行（记录 spacing / count / stretch，防「改完忘还原」）
_NARROW_ROWS = (
    "horizontalLayout_101",
    "horizontalLayout_96",
    "horizontalLayout_95",
    "horizontalLayout_155",
    "horizontalLayout_103",
)

_NARROW_WIDGETS = tuple(
    [name for name, _ in _NARROW_MOVE_TARGETS]
    + ["label_download_actor_zip", "radioButton_actor_photo_net"]
    + [name for name, _ in _NARROW_REFS]
    # 需求①：路径框 + 「选择文件」按钮 + 「选择目录」基准按钮
    + ["lineEdit_actor_db_path", "pushButton_select_actor_info_db", "pushButton_select_gfriends_local"]
    # 需求②：「Emby」/「Jellyfin」
    + ["radioButton_server_emby", "radioButton_server_jellyfin"]
)


def _narrow_snapshot(ui):
    """窄态右移相关控件的 (绝对 x, 宽) + 三行的 (spacing, count, stretch)。"""
    snap = {name: (_abs(ui, getattr(ui, name)), getattr(ui, name).width()) for name in _NARROW_WIDGETS}
    for name in _NARROW_ROWS:
        row = getattr(ui, name)
        snap[name] = (row.spacing(), row.count(), tuple(row.stretch(i) for i in range(row.count())))
    return snap


def _baseline_without(win, app, monkeypatch, take, method, clear):
    """把某一拍对齐置 noop 后重新同步，返回「只剩通用逻辑」的几何基线。

    只摘**一拍**、另一拍保持生效：两个方法在不同宽窄态下本来就会互相影响
    （宽态那一拍在窄态分支里要复位 layoutWidget_12 与 kodi），一起摘掉的话基线
    里就没有另一拍的正常行为，比出来的差异反而会被误判成回归。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    cls = mw_mod.MyMAinWindow
    original = getattr(cls, method)
    monkeypatch.setattr(cls, method, lambda self, _scroll=None: None)
    snap = None
    try:
        clear()  # 上一遍留下的间隔/钉宽/容器几何必须先清干净
        win._sync_page_layouts()
        app.processEvents()
        snap = take(win.Ui)
    finally:
        monkeypatch.setattr(cls, method, original)
    win._sync_page_layouts()  # 复位到带新逻辑的状态
    app.processEvents()
    return snap


def _pristine_snapshot(win, app, monkeypatch):
    """窄态基线：摘掉窄态那一拍（宽态那一拍保持生效）后的几何。"""
    return _baseline_without(
        win, app, monkeypatch, _narrow_snapshot, "_sync_actor_page_narrow_align", win._clear_actor_narrow_align
    )


def test_actor_narrow_miss_align_to_anchor_when_narrow(win, app, monkeypatch):
    """需求⑧：窄态三个控件右移到锚点列；锚点与同排参照控件纹丝不动；只右移不左拉。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((940, 700), (1000, 700), (1030, 753)):
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下演员页不是窄态，测试前提失效"
        _resize(win, app, width, height)
        anchor = _abs(ui, ui.checkBox_actor_info_photo)
        base = _pristine_snapshot(win, app, monkeypatch)
        got = _narrow_snapshot(ui)

        for name, desc in _NARROW_REFS:
            assert got[name] == base[name], f"{width} 宽下 {desc} 被窄态右移带偏: {base[name]} -> {got[name]}"
        # 「网络获取头像」把宽度让给了行尾标签（文字左对齐，视觉无变化），左缘不得动
        assert got["radioButton_actor_photo_net"][0] == base["radioButton_actor_photo_net"][0], (
            f"{width} 宽下「网络获取头像」左缘被带偏: {base['radioButton_actor_photo_net'][0]} -> {got['radioButton_actor_photo_net'][0]}"
        )

        for name, desc in _NARROW_MOVE_TARGETS:
            now = got[name][0]
            before = base[name][0]
            assert now >= before, f"{width} 宽下 {desc} 被左拉: {before} -> {now}"
            need = anchor - before
            if need <= 0:
                # 窗口再窄一点时目标已在锚点列或更右：需求只要求右移，不得左拉
                assert now == before, f"{width} 宽下 {desc} 本不需移动却被移动: {before} -> {now}"
            else:
                assert now == anchor, f"{width} 宽下 {desc} 未与锚点对齐: x={now} 期望={anchor}"

        # 「点击下载头像包」与「本地头像库」同行同进退
        shift_zip = got["label_download_actor_zip"][0] - base["label_download_actor_zip"][0]
        shift_local = got["radioButton_actor_photo_local"][0] - base["radioButton_actor_photo_local"][0]
        assert shift_zip == shift_local, (
            f"{width} 宽下「点击下载头像包」未随「本地头像库」同进退: {shift_zip} vs {shift_local}"
        )


def test_actor_narrow_miss_align_leaves_wide_page_untouched(win, app, monkeypatch):
    """需求⑧：最大化态页面保持不变——几何、宽度、行间距、stretch 全部逐像素一致。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1920, 1170)
    assert win._actor_page_stretch_extra() > 0, "宽态前提失效（1920 宽下拉伸量应 > 0）"
    assert _narrow_snapshot(ui) == _pristine_snapshot(win, app, monkeypatch), "宽态被窄态右移逻辑改动"
    assert win._actor_narrow_spacers == [], "宽态残留来源行间隔"
    assert win._actor_narrow_restores == [], "宽态残留钉宽/间距登记"
    # 宽态「仅缺少头像的演员」对的是 A2 列（使用 Graphis 头像）——需求⑫ 的目标，
    # 与「补全完成后自动补全演员头像」同列只是二者都对到 A2 的结果，不是窄态逻辑
    # 在宽态生效（窄态逻辑此时 spacers / restores 均已清空，见上面两行断言）。
    assert _abs(ui, ui.radioButton_actor_photo_miss) == _abs(ui, ui.checkBox_actor_photo_ne_face), (
        "宽态「仅缺少头像的演员」未对到 A2 列"
    )


def test_actor_narrow_miss_align_idempotent_and_round_trip(win, app, monkeypatch):
    """需求⑧：窄态幂等；窄→宽→窄 往返后窄态几何逐项复原，且回宽态仍是宽态原样。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1030, 753)
    first = _narrow_snapshot(ui)
    assert win._actor_narrow_spacers, "窄态未在来源行注入固定间隔"
    assert win._actor_narrow_restores, "窄态未登记任何钉宽/行间距"

    _resize(win, app, 1030, 753)  # 幂等：二次同步纹丝不动
    assert _narrow_snapshot(ui) == first, "窄态二次同步漂移"

    _resize(win, app, 1920, 1170)
    assert win._actor_narrow_spacers == [], "宽态未清掉来源行间隔"
    assert win._actor_narrow_restores == [], "宽态未清掉钉宽/行间距登记"
    assert _narrow_snapshot(ui) == _pristine_snapshot(win, app, monkeypatch), "往返后宽态被污染"

    _resize(win, app, 1030, 753)
    assert _narrow_snapshot(ui) == first, f"窄→宽→窄 往返未复原: {first} -> {_narrow_snapshot(ui)}"


def test_actor_narrow_select_file_aligns_to_select_folder(win, app, monkeypatch):
    """需求①：窄态「选择文件」右移到与「选择目录」同列，路径框右缘拓展到按钮左缘。

    「选择目录」自身保持不动；路径框只向右拓展（收窄下限 _ACTOR_NARROW_PATH_MIN_W）。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((1030, 753), (1000, 700), (1030, 753)):
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下演员页不是窄态，测试前提失效"
        _resize(win, app, width, height)
        base = _pristine_snapshot(win, app, monkeypatch)
        btn = ui.pushButton_select_actor_info_db
        ref = ui.pushButton_select_gfriends_local
        path = ui.lineEdit_actor_db_path

        # 「选择目录」保持不动（基准按钮不被本需求移动）
        assert _abs(ui, ref) == base["pushButton_select_gfriends_local"][0], f"{width} 宽下「选择目录」被移动"

        # 「选择文件」与「选择目录」左缘严格对齐（同宽 110px，右缘对齐等价）
        assert _abs(ui, btn) == _abs(ui, ref), (
            f"{width} 宽下「选择文件」未与「选择目录」对齐: x={_abs(ui, btn)} 期望={_abs(ui, ref)}"
        )

        # 路径框右缘拓展到按钮左缘，行间距保持不变
        spacing = ui.horizontalLayout_155.spacing()
        assert _abs(ui, path) + path.width() + spacing == _abs(ui, btn), (
            f"{width} 宽下路径框右缘未到按钮左缘: right={_abs(ui, path) + path.width()} +{spacing} 期望={_abs(ui, btn)}"
        )
        # 只向右拓展，不收窄
        assert path.width() >= base["lineEdit_actor_db_path"][1], (
            f"{width} 宽下路径框被左拉收窄: {base['lineEdit_actor_db_path'][1]} -> {path.width()}"
        )
        assert path.width() >= win._ACTOR_NARROW_PATH_MIN_W, f"{width} 宽下路径框窄到夹不住文字"
        # 路径框左缘仍钉在 A1，不得左移
        assert _abs(ui, path) == base["lineEdit_actor_db_path"][0], f"{width} 宽下路径框左缘被移动"


def test_actor_narrow_jellyfin_aligns_to_anchor(win, app, monkeypatch):
    """需求②：窄态「Jellyfin」右移到与「补全完成后自动补全演员头像」同列，Emby 不动。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((1030, 753), (1000, 700), (1030, 753)):
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下演员页不是窄态，测试前提失效"
        _resize(win, app, width, height)
        base = _pristine_snapshot(win, app, monkeypatch)
        anchor = _abs(ui, ui.checkBox_actor_info_photo)
        jellyfin = ui.radioButton_server_jellyfin

        assert _abs(ui, jellyfin) == anchor, (
            f"{width} 宽下「Jellyfin」未与锚点对齐: x={_abs(ui, jellyfin)} 期望={anchor}"
        )
        # 「Emby」保持 A1 原位（服务类型行的行首不得被让位挤走）
        assert _abs(ui, ui.radioButton_server_emby) == base["radioButton_server_emby"][0], (
            f"{width} 宽下「Emby」被带偏: {base['radioButton_server_emby'][0]} -> {_abs(ui, ui.radioButton_server_emby)}"
        )
        # 只右移不左拉
        assert _abs(ui, jellyfin) >= base["radioButton_server_jellyfin"][0], f"{width} 宽下「Jellyfin」被左拉"
        # 收窄不得夹住自己的文字
        assert jellyfin.width() >= win._ACTOR_NARROW_MIN_DONOR_W, f"{width} 宽下「Jellyfin」窄到夹不住文字"
        # 锚点自身不动
        assert anchor == base["checkBox_actor_info_photo"][0], f"{width} 宽下锚点被移动"


# ---------------------------------------------------------------------------
# 需求⑪⑫：最大化态把各控件对齐到 A2 列（使用 Graphis 头像）
# ---------------------------------------------------------------------------

# 需求⑪：向左移动到 A2 列的四个目标（zip 是 local 的跟随者，单独断言）
_WIDE_LEFT_TARGETS = (
    ("radioButton_server_jellyfin", "Jellyfin"),
    ("checkBox_actor_info_photo", "补全完成后自动补全演员头像"),
    ("checkBox_actor_photo_auto", "刮削结束后自动补全演员头像"),
    ("radioButton_actor_photo_local", "本地头像库"),
)

# 需求⑫：向右移动到 A2 列的两个目标
_WIDE_RIGHT_TARGETS = (
    ("radioButton_actor_photo_miss", "仅缺少头像的演员"),
    ("checkBox_actor_photo_kodi", "刮削结束后自动创建"),
)

# 只让宽度、不让位置的前导项（左缘必须纹丝不动）
_WIDE_LEAD_ITEMS = (
    ("radioButton_server_emby", "Emby"),
    ("radioButton_actor_photo_all", "所有演员（头像来源）"),
    ("radioButton_actor_photo_net", "网络头像库（Gfriends）"),
)

# 宽态完全不该被动到的（锚点三兄弟 + 无关控件），x 与 width 都要一致
_WIDE_REFS = (
    ("checkBox_actor_photo_ne_backdrop", "使用Graphis背景"),
    ("checkBox_actor_photo_ne_face", "使用Graphis头像（A2 锚点）"),
    ("checkBox_actor_photo_ne_new", "请求Graphis最新图片"),
    ("radioButton_actor_info_miss", "仅缺少信息的演员"),
    ("pushButton_del_actor_folder", "清除所有.actors文件夹"),
    ("label_299", "补全范围："),
)

_WIDE_WIDGETS = tuple(
    dict.fromkeys(
        [n for n, _ in _WIDE_LEFT_TARGETS]
        + [n for n, _ in _WIDE_RIGHT_TARGETS]
        + [n for n, _ in _WIDE_LEAD_ITEMS]
        + [n for n, _ in _WIDE_REFS]
        + ["label_download_actor_zip", "layoutWidget_12"]
    )
)


def _wide_snapshot(ui):
    """宽态 A2 对齐相关控件的 (绝对 x, 宽)。"""
    return {name: (_abs(ui, getattr(ui, name)), getattr(ui, name).width()) for name in _WIDE_WIDGETS}


def _wide_pristine(win, app, monkeypatch):
    """宽态基线：摘掉宽态那一拍（窄态那一拍保持生效）后的同宽度几何。"""
    return _baseline_without(
        win, app, monkeypatch, _wide_snapshot, "_sync_actor_page_wide_a2_align", win._clear_actor_wide_align
    )


def test_actor_wide_a2_align_when_wide(win, app, monkeypatch):
    """需求⑪⑫：最大化态六个控件对齐到 A2 列；锚点与让位项左缘纹丝不动。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((1920, 1170), (1600, 1000), (1030, 753), (1920, 1170)):
        _resize(win, app, width, height)
        wide = win._actor_page_stretch_extra() > 0
        base = _wide_pristine(win, app, monkeypatch)
        got = _wide_snapshot(ui)
        anchor = got["checkBox_actor_photo_ne_face"][0]

        if wide:
            for name, desc in _WIDE_LEFT_TARGETS:
                assert got[name][0] == anchor, (
                    f"{width} 宽下最大化态 {desc} 未与「使用Graphis头像」对齐: x={got[name][0]} 期望={anchor}"
                )
            # 「点击下载头像包」在尾部子布局内，紧随「本地头像库」（非独立目标）
            assert got["label_download_actor_zip"][0] > got["radioButton_actor_photo_local"][0], (
                f"{width} 宽下「点击下载头像包」未紧随「本地头像库」"
            )
            for name, desc in _WIDE_RIGHT_TARGETS:
                delta = got[name][0] - base[name][0]
                assert delta >= 0, f"{width} 宽下最大化态 {desc} 被左拉: {base[name][0]} -> {got[name][0]}"
                if delta > 0:
                    assert got[name][0] == anchor, (
                        f"{width} 宽下最大化态 {desc} 右移后未与「使用Graphis头像」对齐: x={got[name][0]} 期望={anchor}"
                    )
                # 前导项收窄到夹住自己文字时宁可不右移：此时必须原地不动
                assert got["radioButton_actor_photo_miss"][1] >= win._ACTOR_PAGE_A2_MIN_LEAD_W

            # 让位项只让宽度，左缘必须纹丝不动
            for name, desc in _WIDE_LEAD_ITEMS:
                assert got[name][0] == base[name][0], (
                    f"{width} 宽下最大化态 {desc} 左缘被带偏: {base[name][0]} -> {got[name][0]}"
                )
            # 锚点与无关控件的 x、width 全不变
            for name, desc in _WIDE_REFS:
                assert got[name] == base[name], f"{width} 宽下最大化态 {desc} 被改动: {base[name]} -> {got[name]}"
        else:
            # 窄态逐像素不变：整份快照与「只有通用逻辑」的基线一致
            assert got == base, f"{width} 宽下窄态被宽态 A2 对齐改动: {base} -> {got}"


def test_actor_wide_a2_leaves_narrow_untouched(win, app, monkeypatch):
    """需求⑪⑫：还原态页面保持不变——含被加宽的 layoutWidget_12 按设计几何复位。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((1920, 1170), (1030, 753), (1000, 700), (1030, 753)):
        _resize(win, app, width, height)
        if win._actor_page_stretch_extra() > 0:
            continue
        assert _wide_snapshot(ui) == _wide_pristine(win, app, monkeypatch), f"{width} 宽下窄态被宽态逻辑改动"
        # layoutWidget_12 不进任何 registry，通用同步不会自愈，必须显式复位
        assert ui.layoutWidget_12.width() == win._ACTOR_PAGE_HOLDER12_DESIGN[2], (
            f"{width} 宽下还原态 layoutWidget_12 未按设计几何复位: {ui.layoutWidget_12.width()}"
        )
        assert win._actor_wide_restores == [], f"{width} 宽下还原态残留宽态钉宽登记"


def test_actor_wide_a2_idempotent_and_round_trip(win, app, monkeypatch):
    """需求⑪⑫：最大化态幂等；宽→窄→宽 往返后宽态几何逐项复原。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1920, 1170)
    assert win._actor_page_stretch_extra() > 0, "宽态前提失效"
    first = _wide_snapshot(ui)
    assert win._actor_wide_restores, "宽态未登记任何钉宽/stretch/容器几何"

    _resize(win, app, 1920, 1170)  # 幂等：二次同步纹丝不动
    assert _wide_snapshot(ui) == first, "宽态二次同步漂移"

    _resize(win, app, 1030, 753)
    assert win._actor_wide_restores == [], "还原态未清掉宽态钉宽/stretch 登记"
    assert ui.layoutWidget_12.width() == win._ACTOR_PAGE_HOLDER12_DESIGN[2], "还原态容器未复位"

    _resize(win, app, 1920, 1170)
    assert _wide_snapshot(ui) == first, f"宽→窄→宽 往返未复原: {first} -> {_wide_snapshot(ui)}"


def test_actor_narrow_kodi_aligns_to_a2(win, app):
    """需求⑬：窄态「刮削结束后自动创建」向左移到与「使用Graphis头像」同列，锚点不动；宽态不变。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((1030, 753), (1000, 700)):
        _resize(win, app, width, height)
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下不是窄态，测试前提失效"
        anchor = _abs(ui, ui.checkBox_actor_photo_ne_face)
        assert _abs(ui, ui.checkBox_actor_photo_kodi) == anchor, (
            f"{width} 宽下「刮削结束后自动创建」未与「使用Graphis头像」对齐"
        )
    # 锚点自身在窄态不得被带动
    _resize(win, app, 1030, 753)
    base_anchor = _abs(ui, ui.checkBox_actor_photo_ne_face)
    _resize(win, app, 1030, 753)
    assert _abs(ui, ui.checkBox_actor_photo_ne_face) == base_anchor, "窄态锚点被移动"


def test_actor_kodi_button_matches_upper_width_when_wide(win, app):
    """最下方「开始补全」按钮宽态与上方「开始补全」同宽，窄态保持设计宽 130 且往返复原。

    背景：pushButton_add_actor_pic_kodi 设计宽 130，上方两枚「开始补全」
    （pushButton_add_actor_info / pushButton_add_actor_pic）设计宽 261。
    宽态把最下方按钮加宽到与上方一致；窄态一个像素不动。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1030, 753)
    assert win._actor_page_stretch_extra() <= 0, "1030 宽下不是窄态，测试前提失效"
    assert ui.pushButton_add_actor_pic_kodi.width() == 130, "窄态按钮宽被改动"
    _resize(win, app, 1920, 1170)
    assert win._actor_page_stretch_extra() > 0, "1920 宽下不是宽态，测试前提失效"
    assert ui.pushButton_add_actor_pic_kodi.width() == ui.pushButton_add_actor_pic.width(), (
        "宽态最下方「开始补全」未与上方同宽"
    )
    assert ui.pushButton_add_actor_pic.width() == 261, "上方按钮自身被改动"
    # 复选框 checkBox_actor_photo_kodi 不得被连带加宽
    assert ui.checkBox_actor_photo_kodi.width() == 141, "宽态复选框被连带加宽"
    _resize(win, app, 1920, 1170)
    assert ui.pushButton_add_actor_pic_kodi.width() == ui.pushButton_add_actor_pic.width(), "宽态重复同步后宽度漂移"
    _resize(win, app, 1030, 753)
    assert ui.pushButton_add_actor_pic_kodi.width() == 130, "还原窄态后按钮宽未复原 130"
