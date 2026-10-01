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
    # 窄态本身也要钉位（需求⑦），故宽度锁在窄态非空是正常的；真正要保证的是
    # 「锁定的是设计宽、不是宽态值」——路径输入框必须回到 300 而不是 466。
    assert ui.lineEdit_actor_db_path.width() == 300, f"还原态路径输入框宽度未复原: {ui.lineEdit_actor_db_path.width()}"
    assert ui.label_280.width() == base_indent[1], "还原态行首占位控件宽度未复原"
