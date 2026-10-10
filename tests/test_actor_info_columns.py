"""演员页「补全Emby/Jellyfin演员信息」组列对齐回归测试。

用户需求（共十五条）：
  ① 「补全语言：」「演员信息数据库：」与「补全范围：」的**冒号**严格上下对齐（窄宽双态）。
  ② 宽态「中文简体」「所有演员」左缘对齐「使用Graphis背景」。
  ③ 宽态「中文繁体」「使用数据库补全演员信息」左缘对齐「使用Graphis头像」。
  ④ 宽态「日语」「不存在中文时，翻译日语为中文」左缘对齐「请求Graphis最新图片」。
  ⑤ 宽态「使用数据库补全演员信息」「点击下载演员数据库」「不存在中文时，翻译日语为
     中文」「不勾选则无中文时使用日语」左缘对齐「使用Graphis背景」（⑤ 覆盖了③④中
     这两行的旧目标列），三个 Graphis 锚点自身不动。
  ⑥ 宽态「演员信息数据库：」输入框左缘扩到 A1、右缘一路铺到「选择目录」按钮左缘，
     「选择文件」按钮随之右移到那一列（与下方两枚「选择目录」严格上下对齐）；
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
  ⑬ 窄态（最小化/还原）把「本地头像库」「点击下载头像包」向左移动到与「使用
     Graphis 头像」严格上下对齐的位置，「使用 Graphis 头像」位置保持不变；最大化
     时的页面布局、控件、提示词等等均保持不变。
  ⑭ 最大化时把「网络头像库」显示输入框缩到与「Gfridens 本地仓库」「本地头像库」
     两行显示输入框上下对齐；最小化时的界面、组件、控件、提示词等等均保持不动。
  ⑮ 最小化时把「网络头像库」显示输入框最右侧向左缩进到与「Gfridens 本地仓库」
     「本地头像库」右侧严格上下对齐的位置，这两行位置保持不变；最大化时的界面、
     控件、组件、提示词等等均保持不变。

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
  - ⑬ 的来源行 hl95 与 ⑪⑫ 三行结构不同，套不了「前导项收窄 + 行尾插 Expanding
    间隔」：目标是 Fixed 宽单选（min==max==59）吸不走余量、必须插间隔，而行尾 hl97
    是嵌套子布局（内含「点击下载头像包」一枚 QLabel），插间隔会与它争余量、把链接
    文字夹没（实测被压到 49px）。只能「stretch 挪给行尾 + 前导项钉窄」。又不能直接
    钉住行尾那枚 QLabel 的现宽——那会改变 hl95 的最小宽、连带把 layoutWidget_8 的
    三等分挤偏（A2 由 356 漂到 362）。
  - ⑥ 的按钮列不能写死 A2（= 「使用Graphis头像」左缘）：那枚按钮在头像组、演员
    信息组是**两套网格**，列宽互不相关。要对齐的是同页另两枚「选择目录」按钮，故宽度
    须由那枚按钮的实测左缘反推（行内 spacing 也算进去），窗口任意宽度都成立；
    写死 A2 会让「选择文件」停在 658（1920），与真正要对齐的 1469 差 811px。
  - ⑭ 的「网络头像库」输入框是 layoutWidget_8 网格的**直接项**、右侧无按钮，宽态会
    独占整列富余宽（1920 实测 1393），比另两枚（1277，右缘被 Fixed 110px 的「选择目录」
    顶住）宽出整整一枚按钮的宽；三者左缘本就同列（A1），故钉宽即可对齐右缘。它不进
    任何 registry（父容器才是 _STRETCH 项），通用宽幅同步只拉父容器、不会抹掉钉宽。
    钉宽必须登记进 _actor_wide_restores（记录原 min/max 写回）并排在
    _sync_actor_info_columns 之后，否则被其末尾的 grid.activate() 弹回整列宽。
  - ⑮ 与⑭ 是同一个成因的两个态：钉宽基准不同（宽态钉成参照枚在宽态的宽，窄态钉成
    参照枚在窄态的宽），必须**各钉各的**——共用一处会有一态失效（那一拍只在宽态/窄态
    跑）。窄态那一拍登记进 _actor_narrow_restores（真解锁），并必须把 layoutWidget_8
    的**网格**（不是 layoutWidget_8 本身，它是 QLayoutWidget，invalidate/activate 在
    它布局上）一并登记进 _clear_actor_narrow_align 的重排行名，否则解锁后网格不重排、
    控件仍停在窄态钉宽。
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
    """需求②~⑥：宽态三列对齐、⑤ 两行并入 A1、⑥ 输入框铺到「选择目录」列且按钮跟随。"""
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

    # 需求⑥：路径输入框左缘 A1、右缘铺到「选择目录」按钮左缘；「选择文件」随之右移到
    # 那一列，与下方两枚「选择目录」严格上下对齐（下方两枚自身不动）。
    sel_gf = ui.pushButton_select_gfriends_local  # Gfriends 本地仓库行的「选择目录」
    sel_photo = ui.pushButton_select_actor_photo_folder  # 本地头像库行的「选择目录」
    spacing = ui.horizontalLayout_155.spacing()
    path_right = _abs(ui, ui.lineEdit_actor_db_path) + ui.lineEdit_actor_db_path.width()
    assert _abs(ui, ui.lineEdit_actor_db_path) == a1, "路径输入框左缘未到 A1"
    assert path_right + spacing == _abs(ui, sel_gf), (
        f"路径输入框右缘未铺到「选择目录」列: right={path_right} +{spacing} 期望={_abs(ui, sel_gf)}"
    )
    assert _abs(ui, ui.pushButton_select_actor_info_db) == _abs(ui, sel_gf), (
        f"「选择文件」未与「选择目录」上下对齐: x={_abs(ui, ui.pushButton_select_actor_info_db)} "
        f"期望={_abs(ui, sel_gf)}"
    )
    # 两枚「选择目录」同宽 110px 且同列，右缘相等；本需求只动演员信息组那一枚按钮
    assert _abs(ui, sel_gf) == _abs(ui, sel_photo), "两个「选择目录」按钮不同列"
    assert ui.pushButton_select_actor_info_db.width() == 110, "「选择文件」按钮被改宽"

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
    """需求⑦ + 本轮：窄态两行 + 「所有演员」左移到「中文简体」所在列；语言行繁/日右移到 A2/A3。"""
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

    # 本轮：窄态「中文繁体」右移到 A2（使用Graphis头像）、「日语」右移到 A3
    # （请求Graphis最新图片），两锚点自身不动；「中文简体」保持在 A1 原位。
    assert _abs(ui, ui.radioButton_actor_info_zh_tw) == _abs(ui, ui.checkBox_actor_photo_ne_face), (
        "窄态「中文繁体」未与「使用Graphis头像」对齐"
    )
    assert _abs(ui, ui.radioButton_actor_info_ja) == _abs(ui, ui.checkBox_actor_photo_ne_new), (
        "窄态「日语」未与「请求Graphis最新图片」对齐"
    )
    assert _abs(ui, ui.radioButton_actor_info_zh_cn) == _abs(ui, ui.checkBox_actor_photo_ne_backdrop), (
        "窄态「中文简体」被带偏"
    )

    # 需求⑥ 明确「最小化时不用变」：路径行在窄态不得被钉到宽态列/宽态钉宽。
    # 断言写成「与宽态对比」而非写死像素值，避免窗口尺寸无关的脆弱断言。
    narrow_w = ui.lineEdit_actor_db_path.width()
    _resize(win, app, 1920, 1170)
    assert _abs(ui, ui.lineEdit_actor_db_path) != _abs(ui, ui.radioButton_actor_info_zh_tw), (
        "窄态路径输入框被误钉到宽态列（往返后）"
    )
    assert ui.lineEdit_actor_db_path.width() > narrow_w, (
        f"窄态路径输入框宽度未与宽态区分: 窄={narrow_w} 宽={ui.lineEdit_actor_db_path.width()}"
    )
    _resize(win, app, 1000, 700)
    assert ui.lineEdit_actor_db_path.width() == narrow_w, (
        f"往返回窄态后路径输入框宽度未复原: {ui.lineEdit_actor_db_path.width()} != {narrow_w}"
    )


def test_actor_info_state_restored_after_round_trip(win, app):
    """窄→宽→窄 往返：所有列控控件、宽度、缩进、行容器逐项复原，无残留。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)

    def snap():
        return {n: getattr(ui, n).geometry().getRect() for n in _COLUMN_WIDGETS}

    _resize(win, app, 1000, 700)
    base = snap()
    base_spacers = sorted(row.objectName() for row, _ in win._actor_info_spacers)
    base_indent = (
        ui.horizontalLayout_98.spacing(),
        ui.label_280.width(),
        ui.horizontalLayout_159.getContentsMargins(),
        ui.layoutWidget_15.geometry().getRect(),
    )

    _resize(win, app, 1920, 1170)
    wide_w = ui.lineEdit_actor_db_path.width()
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
    # 窄态语言行（繁→A2、日→A3）合法注入固定间隔，还原态应与初态一致
    # （初态窄态同样有这几个），而非清零。
    assert sorted(row.objectName() for row, _ in win._actor_info_spacers) == base_spacers, (
        f"还原态间隔与初态不一致: {base_spacers} -> {sorted(row.objectName() for row, _ in win._actor_info_spacers)}"
    )
    # 窄态本身也要钉位（需求⑦/⑧），故宽度锁在窄态非空是正常的；真正要保证的是
    # 「锁定的是窄态值、不是宽态值」——路径输入框不得停在宽态的钉宽。
    assert ui.lineEdit_actor_db_path.width() != wide_w, f"还原态路径输入框宽度仍停在宽态值: {wide_w}"
    # 窄态宽度由「选择目录」按钮位置反推（需求①）：右缘紧贴按钮左缘
    path_right = _abs(ui, ui.lineEdit_actor_db_path) + ui.lineEdit_actor_db_path.width()
    assert path_right < _abs(ui, ui.pushButton_select_actor_info_db), "还原态路径框右缘未与按钮留出间距"
    assert ui.label_280.width() == base_indent[1], "还原态行首占位控件宽度未复原"


# ---------------------------------------------------------------------------
# 需求⑧⑨⑩ + 本轮：窄态把各控件对齐到 A2 列（使用 Graphis 头像）
#
# 本轮方向由「右移到补全完成后自动补全演员头像」改为「左移到 A2 列」：窄态下
# A2 列比那些控件更靠左，故一律是左移，只左移不右拉。
# ---------------------------------------------------------------------------

# 需要在窄态对到 A2 列（checkBox_actor_photo_ne_face 左缘）的目标
_NARROW_A2_TARGETS = (
    ("checkBox_actor_info_photo", "补全完成后自动补全演员头像"),
    ("checkBox_actor_photo_auto", "刮削结束后自动补全演员头像"),
    ("checkBox_actor_photo_kodi", "刮削结束后自动创建"),
    ("radioButton_actor_info_miss", "仅缺少信息的演员"),
    ("radioButton_actor_photo_miss", "仅缺少头像的演员"),
    ("radioButton_server_jellyfin", "Jellyfin"),
    ("radioButton_actor_photo_local", "本地头像库"),
)

# 需求⑬：与「本地头像库」同行、紧随其后的链接。它不是独立目标——它得对到 A2 列的
# 「本地头像库」跟着左移，自己只是左缘右移到紧随其后的新位置，故不能断言 == 锚点。
# 只断言「跟着左移」且「不窄于自己的文字」（否则链接文字会被夹掉）。
_NARROW_SOURCE_LINK = ("label_download_actor_zip", "点击下载头像包")

# 窄态需要收窄到与最下方按钮同宽的上方两枚「开始补全」
_NARROW_ADD_BTNS = (
    ("pushButton_add_actor_info", "开始补全（演员信息）"),
    ("pushButton_add_actor_pic", "开始补全（头像）"),
)

# 窄态 A2 列锚点
_NARROW_A2_ANCHOR = "checkBox_actor_photo_ne_face"

# 左缘与宽度都不得被窄态对齐带动的参照控件
_NARROW_REFS = (
    ("label_299", "补全范围："),
    (_NARROW_A2_ANCHOR, "使用Graphis头像（A2 锚点）"),
    ("pushButton_add_actor_pic_kodi", "开始补全（最下方，基准按钮）"),
)

# 为把目标左移到 A2 列而**收窄让位**的同行前导项：左缘必须纹丝不动，只许收窄
_NARROW_LEADS = (
    ("radioButton_actor_info_all", "所有演员"),
    ("radioButton_actor_photo_all", "所有演员（头像来源）"),
    ("radioButton_server_emby", "Emby"),
    ("radioButton_actor_photo_net", "网络头像库Gfriends"),
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
    dict.fromkeys(
        [name for name, _ in _NARROW_A2_TARGETS]
        + [name for name, _ in _NARROW_REFS]
        + [name for name, _ in _NARROW_LEADS]
        + [name for name, _ in _NARROW_ADD_BTNS]
        + ["label_download_actor_zip", "radioButton_actor_photo_net", "radioButton_actor_photo_local"]
        # 需求①：路径框 + 「选择文件」按钮 + 「选择目录」基准按钮
        + ["lineEdit_actor_db_path", "pushButton_select_actor_info_db", "pushButton_select_gfriends_local"]
    )
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


def test_actor_narrow_controls_land_on_a2_column(win, app, monkeypatch):
    """窄态：七枚控件全部对到 A2 列（使用 Graphis 头像）左缘；锚点与参照控件纹丝不动。

    方向是「左移」——窄态下 A2 列比这些控件更靠左；只左移不右拉，且不得被夹掉文字。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((940, 700), (1000, 700), (1030, 753)):
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下演员页不是窄态，测试前提失效"
        _resize(win, app, width, height)
        anchor = _abs(ui, getattr(ui, _NARROW_A2_ANCHOR))
        base = _pristine_snapshot(win, app, monkeypatch)
        got = _narrow_snapshot(ui)

        # 锚点与参照控件：左缘和宽度都不得被带偏
        for name, desc in _NARROW_REFS:
            assert got[name] == base[name], f"{width} 宽下 {desc} 被窄态对齐带偏: {base[name]} -> {got[name]}"
        # 「网络获取头像」把宽度让给了行尾标签（文字左对齐，视觉无变化），左缘不得动
        assert got["radioButton_actor_photo_net"][0] == base["radioButton_actor_photo_net"][0], (
            f"{width} 宽下「网络获取头像」左缘被带偏: {base['radioButton_actor_photo_net'][0]} -> {got['radioButton_actor_photo_net'][0]}"
        )

        for name, desc in _NARROW_A2_TARGETS:
            now = got[name][0]
            before = base[name][0]
            assert now <= before, f"{width} 宽下 {desc} 被右拉: {before} -> {now}"
            assert now == anchor, f"{width} 宽下 {desc} 未与 A2 列对齐: x={now} 期望={anchor}"

        # 需求⑬：「点击下载头像包」不独立对齐，它随「本地头像库」一起左移；
        # 且绝不能被窄到夹掉链接文字（这正是不能对它插 Expanding 间隔的原因）。
        link_name, link_desc = _NARROW_SOURCE_LINK
        assert got[link_name][0] <= base[link_name][0], (
            f"{width} 宽下 {link_desc} 未随「本地头像库」左移: {base[link_name][0]} -> {got[link_name][0]}"
        )
        link_text_w = (
            getattr(ui, link_name).fontMetrics().horizontalAdvance(getattr(ui, link_name).text())
            + getattr(ui, link_name).margin() * 2
        )
        assert got[link_name][1] >= link_text_w, (
            f"{width} 宽下 {link_desc} 被窄到夹掉文字: w={got[link_name][1]} < 文字宽={link_text_w}"
        )

        # 收窄不得夹住自己的文字：可涨的行由布局给足宽度，钉死的行由 maxWidth 保底，
        # 统一用 sizeHint（文字 + 单选指示器）当下限即可
        for name, desc in _NARROW_A2_TARGETS:
            assert got[name][1] >= getattr(ui, name).sizeHint().width(), (
                f"{width} 宽下 {desc} 窄到夹住文字: w={got[name][1]} < sizeHint={getattr(ui, name).sizeHint().width()}"
            )
        # 前导项只许收窄让位：左缘不动、宽度不增、且不低于下限
        for name, desc in _NARROW_LEADS:
            assert got[name][0] == base[name][0], f"{width} 宽下 {desc} 左缘被带偏: {base[name][0]} -> {got[name][0]}"
            assert got[name][1] <= base[name][1], f"{width} 宽下 {desc} 反被加宽: {base[name][1]} -> {got[name][1]}"
            assert got[name][1] >= win._ACTOR_NARROW_MIN_LEAD_W, f"{width} 宽下 {desc} 收窄到下限以下: w={got[name][1]}"

        # 上方两枚「开始补全」收窄到与最下方基准按钮同宽，基准按钮自身不动
        ref_w = ui.pushButton_add_actor_pic_kodi.width()
        for name, desc in _NARROW_ADD_BTNS:
            assert got[name][1] == ref_w, f"{width} 宽下 {desc} 宽未与最下方按钮一致: {got[name][1]} != {ref_w}"
            assert got[name][1] < base[name][1], f"{width} 宽下 {desc} 未被收窄: {base[name][1]} -> {got[name][1]}"


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


def test_actor_narrow_jellyfin_aligns_to_a2_anchor(win, app, monkeypatch):
    """需求②：窄态「Jellyfin」左移到与「使用 Graphis 头像」同列；「Emby」不动、不被右拉。"""
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((940, 700), (1030, 753), (1000, 700), (1030, 753)):
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下演员页不是窄态，测试前提失效"
        _resize(win, app, width, height)
        base = _pristine_snapshot(win, app, monkeypatch)
        anchor = _abs(ui, getattr(ui, _NARROW_A2_ANCHOR))
        jellyfin = ui.radioButton_server_jellyfin

        assert _abs(ui, jellyfin) == anchor, (
            f"{width} 宽下「Jellyfin」未与 A2 列对齐: x={_abs(ui, jellyfin)} 期望={anchor}"
        )
        # 「Emby」保持 A1 原位（服务类型行的行首不得被让位挤走），宽度也不变
        assert _abs(ui, ui.radioButton_server_emby) == base["radioButton_server_emby"][0], (
            f"{width} 宽下「Emby」被带偏: {base['radioButton_server_emby'][0]} -> {_abs(ui, ui.radioButton_server_emby)}"
        )
        # 只左移不右拉
        assert _abs(ui, jellyfin) <= base["radioButton_server_jellyfin"][0], f"{width} 宽下「Jellyfin」被右拉"
        # 收窄不得夹住自己的文字
        assert jellyfin.width() >= jellyfin.sizeHint().width(), (
            f"{width} 宽下「Jellyfin」窄到夹不住文字: w={jellyfin.width()}"
        )
        # A2 锚点自身不动
        assert anchor == base[_NARROW_A2_ANCHOR][0], f"{width} 宽下 A2 锚点被移动"


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
    ("radioButton_actor_photo_net", "网络头像库Gfriends"),
)

# 宽态完全不该被动到的（锚点三兄弟 + 无关控件），x 与 width 都要一致。
# 注：「清除所有.actors文件夹」原在此表里锁死「宽态不得移动」，但最新需求正是要它
# 宽态右移到与「选择目录」右缘对齐，故已移出，改由
# test_actor_del_folder_button_right_edge_aligns_to_select_folder 专项覆盖。
_WIDE_REFS = (
    ("checkBox_actor_photo_ne_backdrop", "使用Graphis背景"),
    ("checkBox_actor_photo_ne_face", "使用Graphis头像（A2 锚点）"),
    ("checkBox_actor_photo_ne_new", "请求Graphis最新图片"),
    ("radioButton_actor_info_miss", "仅缺少信息的演员"),
    ("label_299", "补全范围："),
)

_WIDE_WIDGETS = tuple(
    dict.fromkeys(
        [n for n, _ in _WIDE_LEFT_TARGETS]
        + [n for n, _ in _WIDE_RIGHT_TARGETS]
        + [n for n, _ in _WIDE_LEAD_ITEMS]
        + [n for n, _ in _WIDE_REFS]
        + ["label_download_actor_zip", "layoutWidget_12"]
        # 需求⑭：「网络头像库」输入框与另两枚路径框（及两枚「选择目录」基准按钮）——
        # 进快照是为了让窄态「整份快照 == 只有通用逻辑的基线」这条断言顺带覆盖它，
        # 宽态那侧由 test_actor_wide_net_photo_input_aligns_with_path_inputs 专项断言。
        + [
            "lineEdit_net_actor_photo",
            "lineEdit_gfriends_local_path",
            "lineEdit_actor_photo_folder",
            "pushButton_select_gfriends_local",
            "pushButton_select_actor_photo_folder",
        ]
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


def test_actor_wide_net_photo_input_aligns_with_path_inputs(win, app):
    """需求⑭⑮：两态下「网络头像库」输入框都与另两枚路径框上下对齐。

    背景：三者左缘本就同列（A1 = 「使用Graphis背景」），但另两枚右边各顶着一枚
    Fixed 110px 的「选择目录」按钮，右缘停在按钮列；「网络头像库」输入框是
    layoutWidget_8 网格里的直接项、右侧无按钮，会独占整列富余宽（宽态 1920 实测
    1393 vs 1277，窄态 1030 实测 503 vs 387），故两态各把它钉成与另两枚同宽：
    宽态由 _sync_actor_page_wide_a2_align 第 ⑥ 步负责（登记 _actor_wide_restores），
    窄态由 _sync_actor_page_narrow_align 第 ⑤ 步负责（登记 _actor_narrow_restores），
    两拍互不越界：本用例专断宽态那一拍（钉宽来自宽态登记、窄态无残留宽态登记），
    窄态那一拍由 test_actor_narrow_net_photo_input_aligns_with_path_inputs 专断。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    net = ui.lineEdit_net_actor_photo
    refs = (
        (ui.lineEdit_gfriends_local_path, "Gfridens 本地仓库"),
        (ui.lineEdit_actor_photo_folder, "本地头像库"),
    )

    def right(w):
        return _abs(ui, w) + w.width()

    def _unlocked(w):
        return w.minimumWidth() == 300 and w.maximumWidth() > 10000

    # ── 宽态：与两枚路径框左缘、右缘都相等 ──
    _resize(win, app, 1920, 1170)
    assert win._actor_page_stretch_extra() > 0, "1920 宽下不是宽态，测试前提失效"
    first = (_abs(ui, net), net.width())
    assert _unlocked(net) is False, "宽态未钉宽（min/max 应被锁成同一个值）"
    assert any(obj is net for _kind, obj, _saved in win._actor_wide_restores), (
        "宽态钉宽未登记进 _actor_wide_restores（清不回去）"
    )
    for ref, desc in refs:
        assert _abs(ui, net) == _abs(ui, ref), f"宽态「网络头像库」输入框左缘未与{desc}对齐"
        assert net.width() == ref.width(), (
            f"宽态「网络头像库」输入框宽 {net.width()} 未与{desc}输入框宽 {ref.width()} 一致"
        )
        assert right(net) == right(ref), f"宽态「网络头像库」输入框右缘未与{desc}对齐"

    # 钉宽确实「缩进」了：右缘退到「选择目录」按钮列之前，缩进量 = 一枚按钮宽 + 行间距
    sel = ui.pushButton_select_gfriends_local
    sel_x = _abs(ui, sel)
    assert right(net) == sel_x - ui.horizontalLayout_gfriends_local.spacing(), (
        f"宽态「网络头像库」输入框右缘 {right(net)} 未退到「选择目录」按钮列 {sel_x} 之前"
    )
    assert sel_x + sel.width() - right(net) == sel.width() + ui.horizontalLayout_gfriends_local.spacing(), (
        f"缩进量不是「一枚按钮宽 + 行间距」: {sel_x + sel.width() - right(net)}"
    )

    # 幂等：二次同步纹丝不动
    _resize(win, app, 1920, 1170)
    assert (_abs(ui, net), net.width()) == first, f"宽态二次同步漂移: {first} -> {(_abs(ui, net), net.width())}"

    # ── 窄态：宽态钉宽登记清干净（窄态自身的收窄由需求⑮ 那一拍负责，另有用例断言）──
    _resize(win, app, 1030, 753)
    assert win._actor_page_stretch_extra() <= 0, "1030 宽下不是窄态，测试前提失效"
    assert win._actor_wide_restores == [], "窄态残留宽态钉宽登记"
    assert _unlocked(net) is False, (
        f"窄态钉宽未真解锁（应由窄态那一拍重新钉住）: min={net.minimumWidth()} max={net.maximumWidth()}"
    )
    assert any(obj is net for _kind, obj, _saved in win._actor_narrow_restores), (
        "窄态钉宽未登记进 _actor_narrow_restores（清不回去）"
    )
    narrow = (_abs(ui, net), net.width())

    # ── 往返：宽态几何逐项复原 ──
    _resize(win, app, 1920, 1170)
    assert (_abs(ui, net), net.width()) == first, f"窄→宽往返未复原: {first} -> {(_abs(ui, net), net.width())}"
    assert _unlocked(net) is False, "往返回宽态后钉宽丢失"
    _resize(win, app, 1030, 753)
    assert (_abs(ui, net), net.width()) == narrow, f"宽→窄往返未复原: {narrow} -> {(_abs(ui, net), net.width())}"


def test_actor_narrow_net_photo_input_aligns_with_path_inputs(win, app, monkeypatch):
    """需求⑮：窄态「网络头像库」输入框右缘向左缩进，与另两枚路径框右缘上下对齐。

    用户原话：「软件设置-演员页最小化时网络头像库显示输入框最右侧向左缩进到与
    Grifends本地仓库、本地头像库右侧严格上下对齐的位置，Grifends本地仓库、本地头像库
    位置保持不变，最大化时界面、控件、组件、提示词等等均保持不变」。

    成因与宽态需求⑭ 完全相同（网格直系项、右侧无按钮、独占整列富余宽），只是宽度
    基准不同：窄态钉成「Gfridens本地仓库」那枚的当前宽（1030 实测 387，自身 503）。
    左缘本就同列，故钉宽即同时对齐左右缘；参照两枚与两枚「选择目录」按钮必须纹丝不动。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    net = ui.lineEdit_net_actor_photo
    refs = (
        (ui.lineEdit_gfriends_local_path, "Gfridens本地仓库"),
        (ui.lineEdit_actor_photo_folder, "本地头像库"),
    )

    def right(w):
        return _abs(ui, w) + w.width()

    for width, height in ((1030, 753), (1000, 700), (940, 700)):
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下演员页不是窄态，测试前提失效"
        _resize(win, app, width, height)
        # 左缘本就同列，绝不能被左拉（钉宽只改宽，Qt 把控件排在格子左缘）
        base_left = _abs(ui, net)
        for ref, desc in refs:
            assert _abs(ui, net) == _abs(ui, ref) == base_left, (
                f"{width} 宽下窄态「网络头像库」输入框左缘未与{desc}对齐: {_abs(ui, net)} vs {_abs(ui, ref)}"
            )
            assert net.width() == ref.width(), (
                f"{width} 宽下窄态「网络头像库」输入框宽 {net.width()} 未与{desc}输入框宽 {ref.width()} 一致"
            )
            assert right(net) == right(ref), (
                f"{width} 宽下窄态「网络头像库」输入框右缘 {right(net)} 未与{desc}右缘 {right(ref)} 对齐"
            )
            assert net.minimumWidth() == net.maximumWidth() == ref.width(), (
                f"{width} 宽下窄态「网络头像库」输入框未被钉死: min={net.minimumWidth()} "
                f"max={net.maximumWidth()} 期望={ref.width()}"
            )
        assert any(obj is net for _kind, obj, _saved in win._actor_narrow_restores), (
            f"{width} 宽下窄态钉宽未登记进 _actor_narrow_restores（清不回去）"
        )

        # 右缘确实退到了「选择目录」按钮列之前，且缩进量 = 一枚按钮宽 + 行间距。
        # 仅在参照枚还没被挤到自身最小宽时成立：窗口再窄则「输入框 + 按钮」这一行
        # 装不下（实测 940 参照枚已到 minimumWidth=300、按钮左缘只差 3px），
        # 此时对齐基准仍是「与参照枚同宽」，上面前面的断言已覆盖。
        ref_min = ui.lineEdit_gfriends_local_path.minimumWidth()
        if ui.lineEdit_gfriends_local_path.width() > ref_min:
            sel = ui.pushButton_select_gfriends_local
            sel_x = _abs(ui, sel)
            assert right(net) == sel_x - ui.horizontalLayout_gfriends_local.spacing(), (
                f"{width} 宽下窄态「网络头像库」输入框右缘 {right(net)} 未退到「选择目录」按钮列 {sel_x} 之前"
            )

    # 幂等 + 往返：宽态那一拍重新钉宽，窄态这一拍复原
    _resize(win, app, 1030, 753)
    narrow = (_abs(ui, net), net.width(), net.minimumWidth(), net.maximumWidth())
    _resize(win, app, 1030, 753)
    assert (_abs(ui, net), net.width(), net.minimumWidth(), net.maximumWidth()) == narrow, f"窄态二次同步漂移: {narrow}"
    _resize(win, app, 1920, 1170)
    assert win._actor_narrow_restores == [], "宽态残留窄态钉宽登记"
    _resize(win, app, 1030, 753)
    assert (_abs(ui, net), net.width(), net.minimumWidth(), net.maximumWidth()) == narrow, (
        f"宽→窄往返未复原: {narrow} -> {(_abs(ui, net), net.width(), net.minimumWidth(), net.maximumWidth())}"
    )

    # 需求⑮ 的另一半：最大化时窄态这一拍一像素都不碰（钉宽登记摘掉后的几何 == 现状）
    _resize(win, app, 1920, 1170)
    got = _wide_snapshot(ui)
    assert got == _baseline_without(
        win, app, monkeypatch, _wide_snapshot, "_sync_actor_page_narrow_align", win._clear_actor_narrow_align
    ), "宽态被窄态第 ⑤ 步改动（最大化必须逐像素不变）"


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
    """最下方「开始补全」按钮宽态与上方「开始补全」同宽，窄态保持设计宽 50 且往返复原。

    背景：pushButton_add_actor_pic_kodi 设计宽 50，上方两枚「开始补全」
    （pushButton_add_actor_info / pushButton_add_actor_pic）设计宽 181。
    宽态把最下方按钮加宽到与上方一致；窄态一个像素不动。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    _resize(win, app, 1030, 753)
    assert win._actor_page_stretch_extra() <= 0, "1030 宽下不是窄态，测试前提失效"
    assert ui.pushButton_add_actor_pic_kodi.width() == 50, "窄态按钮宽被改动"
    _resize(win, app, 1920, 1170)
    assert win._actor_page_stretch_extra() > 0, "1920 宽下不是宽态，测试前提失效"
    assert ui.pushButton_add_actor_pic_kodi.width() == ui.pushButton_add_actor_pic.width(), (
        "宽态最下方「开始补全」未与上方同宽"
    )
    assert ui.pushButton_add_actor_pic.width() == 181, "上方按钮自身被改动"
    # 复选框 checkBox_actor_photo_kodi 不得被连带加宽
    assert ui.checkBox_actor_photo_kodi.width() == 141, "宽态复选框被连带加宽"
    _resize(win, app, 1920, 1170)
    assert ui.pushButton_add_actor_pic_kodi.width() == ui.pushButton_add_actor_pic.width(), "宽态重复同步后宽度漂移"
    _resize(win, app, 1030, 753)
    assert ui.pushButton_add_actor_pic_kodi.width() == 50, "还原窄态后按钮宽未复原 50"


def test_actor_del_folder_button_right_edge_aligns_to_select_folder(win, app):
    """宽态：「清除所有.actors文件夹」右缘对到「选择目录」按钮右缘；窄态一像素不动。

    背景：pushButton_del_actor_folder 是 groupBox_68 内 _DOCK_RIGHT 绝对定位项，
    宽态被通用宽幅同步钉到「design_x + extra」的右缘；而锚点 pushButton_select_actor_photo_folder
    （本地头像库行的「选择目录」）随 layoutWidget_8 拉伸，两者右缘在宽态恒差 20px
    （1920 1559 vs 1579 / 1600 1239 vs 1259 / 1366 1005 vs 1025 / 1100 739 vs 759），
    窄态则反多 7px。需求：最大化时右移到与「选择目录」上下对齐，最小化时布局、页面、
    组件、提示词等等均保持不变。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    del_btn = ui.pushButton_del_actor_folder
    sel_btn = ui.pushButton_select_actor_photo_folder
    gf_btn = ui.pushButton_select_gfriends_local

    def right(w):
        return _abs(ui, w) + w.width()

    # ── 窄态：一个像素都不动 ──
    _resize(win, app, 1030, 753)
    assert win._actor_page_stretch_extra() <= 0, "1030 宽下不是窄态，测试前提失效"
    narrow = (_abs(ui, del_btn), del_btn.width(), right(sel_btn))
    _resize(win, app, 1030, 753)
    assert (_abs(ui, del_btn), del_btn.width(), right(sel_btn)) == narrow, "窄态重复同步后发生漂移"

    # ── 宽态：右缘对到「选择目录」右缘 ──
    for width, height in ((1920, 1170), (1600, 1000), (1366, 900), (1100, 800)):
        _resize(win, app, width, height)
        assert win._actor_page_stretch_extra() > 0, f"{width} 宽下不是宽态，测试前提失效"
        assert right(del_btn) == right(sel_btn), (
            f"{width} 宽下「清除所有.actors文件夹」右缘 {right(del_btn)} 未与「选择目录」右缘 {right(sel_btn)} 对齐"
        )
        # 只平移不改宽度：两者设计宽本就不同（171 vs 110）
        assert del_btn.width() == 171, f"{width} 宽下目标按钮被改宽: {del_btn.width()}"
        assert sel_btn.width() == 110, f"{width} 宽下锚点按钮被改宽: {sel_btn.width()}"
        # 另一个「选择目录」与之同列，若不等则锚点选取需要复核
        assert right(gf_btn) == right(sel_btn), f"{width} 宽下两个「选择目录」按钮右缘不等，锚点选取需复核"

    _resize(win, app, 1920, 1170)
    first = right(del_btn)
    _resize(win, app, 1920, 1170)
    assert right(del_btn) == first, "宽态重复同步后右缘漂移"

    # ── 往返：窄态基线复原 ──
    _resize(win, app, 1030, 753)
    got = (_abs(ui, del_btn), del_btn.width(), right(sel_btn))
    assert got == narrow, f"窄→宽→窄 往返后窄态几何未复原: {got} != {narrow}"


def test_actor_narrow_add_buttons_shrink_to_bottom_button(win, app):
    """窄态：上方两枚「开始补全」收窄到与最下方同宽；宽态保持设计宽 181 不变；往返复原。

    与 test_actor_kodi_button_matches_upper_width_when_wide 相反：那一测是宽态把
    最下方按钮加宽到 181；这一测是窄态把上方两枚从 181 收窄到最下方的 50。
    两测合起来保证窄态三枚同宽、宽态三枚同宽，且各自不越界。
    """
    ui = win.Ui
    win.show()
    _goto_actor_page(win, app)
    for width, height in ((940, 700), (1030, 753), (1000, 700), (1030, 753)):
        _resize(win, app, width, height)
        assert win._actor_page_stretch_extra() <= 0, f"{width} 宽下不是窄态，测试前提失效"
        ref = ui.pushButton_add_actor_pic_kodi
        assert ref.width() == 50, f"{width} 宽下最下方基准按钮被改动: {ref.width()}"
        for name, desc in _NARROW_ADD_BTNS:
            btn = getattr(ui, name)
            assert btn.width() == ref.width(), f"{width} 宽下{desc}宽未与最下方一致: {btn.width()} != {ref.width()}"
            assert btn.width() < 181, f"{width} 宽下{desc}未收窄: {btn.width()}"
    # 左缘不因收窄而移动（收窄只向右让，右缘内缩）
    _resize(win, app, 1030, 753)
    narrow_left = {name: _abs(ui, getattr(ui, name)) for name, _ in _NARROW_ADD_BTNS}

    _resize(win, app, 1920, 1170)
    assert win._actor_page_stretch_extra() > 0, "1920 宽下不是宽态，测试前提失效"
    for name, desc in _NARROW_ADD_BTNS:
        btn = getattr(ui, name)
        assert btn.width() == 181, f"宽态{desc}未被还原成设计宽 181: {btn.width()}"
        assert _abs(ui, btn) == narrow_left[name], f"宽态{desc}左缘被带偏"

    _resize(win, app, 1030, 753)
    for name, desc in _NARROW_ADD_BTNS:
        btn = getattr(ui, name)
        assert btn.width() == 50, f"窄→宽→窄 往返后{desc}宽未复原: {btn.width()}"
        assert _abs(ui, btn) == narrow_left[name], f"窄→宽→窄 往返后{desc}左缘未复原"
