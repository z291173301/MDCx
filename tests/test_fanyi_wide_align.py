"""软件设置-翻译页：宽态（最大化）四个目标对到锚点列，窄态保持不变。

用户需求（宽态）：「显示翻译来源」「使用演员映射表翻译演员」向左移动到与
「中文繁体」上下严格对齐（中文繁体不动）；「日语+中文」向右移动到与「中文繁体」
严格上下对齐，「关闭」向右移动到与「日语」严格上下对齐（中文繁体、日语不动）。
窄态（最小化）：翻译页布局、控件、组件、提示词等均保持不变。

实现位置：`MyMAinWindow._sync_fanyi_trans_align`（`mdcx/controllers/main_window/
main_window.py`）。此前该方法只处理窄态（四个目标只允许左移、宽态直接 return）；
本次补上宽态分支：四个目标按锚点 content-x 精确对齐（方向不限）。

宽态独有的两个坑，本文件逐条锁死：
1. 「双语显示」行的 frame_5（设计 661）与 layoutWidget_24（设计 521）是绝对定位、
   通用宽幅同步不拉宽——不先加宽就 move() 会把单选框钉到父容器之外被裁掉。
   加宽公式：frame = 组宽 − 2×20，lw24 = frame 宽 − 140。
2. 加宽后 HBox 会把多余宽度均分到三个单选身上（实测会被拉到 460 宽），故三个单选
   在宽态钉为自然宽（sizeHint），「中文+日语」保持自然大小不动；窄态交还设计值
   （frame 661 / lw24 521 / 单选 min 0 + max 16777215）。

fixture 照抄 tests/test_window_state_matrix.py 的 win（打桩启动副作用 + 停表 +
chdir），但刻意不打桩 set_style——行列几何受 QSS 字体影响，必须按真实主题量。
"""

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_PAIRS = (
    ("radioButton_outline_zh_tw", "checkBox_show_translate_from"),
    ("radioButton_outline_zh_tw", "radioButton_trans_show_jp_zh"),
    ("radioButton_outline_jp", "radioButton_trans_show_one"),
    ("radioButton_actor_zh_tw", "checkBox_actor_translate"),
)

_BILINGUAL_RADIOS = (
    "radioButton_trans_show_zh_jp",
    "radioButton_trans_show_jp_zh",
    "radioButton_trans_show_one",
)

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
    # 注意：刻意不打桩 set_style / apply_site_priority_theme——本文件量的是列位置，
    # 列宽受 QSS 字体影响，必须按真实主题测（打桩后是另一套假几何）。
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


def _goto_fanyi_tab(win, app):
    """切到软件设置-翻译页（scrollArea_11 所在 tab）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).findChild(ui.scrollArea_11.__class__, "scrollArea_11") is not None:
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("翻译 tab (scrollArea_11) not found")
    for _ in range(4):
        app.processEvents()


def _content_x(win, name):
    """控件在翻译页 content 里的绝对 x（跨分支比对必须经 content 中转）。"""
    w = getattr(win.Ui, name)
    return w.mapTo(win.Ui.scrollArea_11.widget(), w.rect().topLeft()).x()


def _settle(win, app, width):
    win.resize(width, 900)
    win.show()
    for _ in range(6):  # 首次打开的几何要经 settle + 宽幅同步落定
        win._sync_page_layouts()
        app.processEvents()


@pytest.mark.parametrize("width", [1400, 1920])
def test_fanyi_wide_targets_align_to_anchors(win, app, width):
    """宽态四个目标的 content-x 与各自锚点完全相等（严格上下对齐）。"""
    _goto_fanyi_tab(win, app)
    _settle(win, app, width)
    for anchor_name, target_name in _PAIRS:
        ax, tx = _content_x(win, anchor_name), _content_x(win, target_name)
        assert tx == ax, f"{width} 宽下 {target_name} x={tx} 未对齐锚点 {anchor_name} x={ax}"


def test_fanyi_wide_bilingual_row_widened(win, app):
    """宽态双语显示行容器按公式加宽（否则单选框会被父容器裁掉）。"""
    _goto_fanyi_tab(win, app)
    _settle(win, app, 1920)
    ui = win.Ui
    assert ui.frame_5.width() == ui.groupBox_83.width() - 40
    assert ui.layoutWidget_24.width() == ui.frame_5.width() - 140


def test_fanyi_wide_zh_jp_stays_natural_left(win, app):
    """宽态「中文+日语」保持自然大小顶左排列（不被 HBox 拉宽、不被本控制器移动）。"""
    _goto_fanyi_tab(win, app)
    _settle(win, app, 1920)
    zh_jp = win.Ui.radioButton_trans_show_zh_jp
    assert zh_jp.x() == 0, f"中文+日语应顶左排列，实际 x={zh_jp.x()}"
    assert zh_jp.width() == zh_jp.sizeHint().width(), "中文+日语应保持自然宽"


def test_fanyi_wide_sync_idempotent(win, app):
    """宽态反复同步不漂移（目标、容器、钉宽全部定格）。"""
    _goto_fanyi_tab(win, app)
    _settle(win, app, 1920)

    def snap():
        ui = win.Ui
        return (
            tuple(_content_x(win, n) for pair in _PAIRS for n in pair),
            ui.frame_5.width(),
            ui.layoutWidget_24.width(),
            tuple((getattr(ui, n).minimumWidth(), getattr(ui, n).maximumWidth()) for n in _BILINGUAL_RADIOS),
        )

    before = snap()
    for _ in range(4):
        win._sync_page_layouts()
        app.processEvents()
    assert snap() == before, "宽态反复同步后几何漂移"


def test_fanyi_narrow_restore_after_wide(win, app):
    """先最大化再最小化：容器与单选约束交还设计值，四组仍对齐（窄态保持不变）。"""
    _goto_fanyi_tab(win, app)
    _settle(win, app, 1920)
    _settle(win, app, 1000)
    ui = win.Ui
    assert ui.frame_5.width() == 661, "窄态 frame_5 应回到设计宽 661"
    assert ui.layoutWidget_24.width() == 521, "窄态 layoutWidget_24 应回到设计宽 521"
    for name in _BILINGUAL_RADIOS:
        radio = getattr(ui, name)
        assert (radio.minimumWidth(), radio.maximumWidth()) == (0, 16777215), f"窄态 {name} 应解除钉宽"
    for anchor_name, target_name in _PAIRS:
        ax, tx = _content_x(win, anchor_name), _content_x(win, target_name)
        assert tx == ax, f"窄态 {target_name} x={tx} 未对齐锚点 {anchor_name} x={ax}"
