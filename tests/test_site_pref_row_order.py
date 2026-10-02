"""软件设置-刮削网站「网站偏好」组：指定网站下拉框 / 提示按钮 / ⚠️ 警告 三者行序回归。

用户需求：「将指定网站下拉框及刮削不到？看这里！按钮与 ⚠️ 下载剧照、预告片…调换
位置，即下拉框及刮削不到？看这里！按钮在上方，⚠️…在下方」。

改前：指定网站下拉框（`comboBox_website_all`）在 gridLayout_28 第 4 行，⚠️ 警告
（`label_315`）在第 3 行，即警告压在下拉框上方、按钮又落在警告那行右侧。
改后：下拉框与按钮同处第 3 行（按钮垂直居中于下拉框），⚠️ 警告下移到第 4 行。

三处易错点，本文件逐条锁死：
1. **行序**：由 .ui 里的 grid row 决定，只能改 .ui 的行号并重编译 MDCx.py；
2. **按钮居中**：`pushButton_scrape_note` 是 groupBox_11 的**绝对定位**子控件
   （不在任何 layout 里），`.ui` 声明的 y 是死值、不随行高自适应。行序一换行
   位置就变，这个死值必须同步重标，否则按钮与下拉框错行（此处锁定 dy==0）。
   取证坑：离屏裸 `Ui_MDCx` 量到的行 y 与真实主窗口差 6px（真实窗口里
   `widget_field_priority_options` 行高被文字撑到 38 而非 34），**必须以真实
   主窗口读数为准**，否则居中差 6px。
3. **不与 ⚠️ 警告重叠**：按钮须完全位于警告行之上（y_overlap == 0）。

x 方向与下拉框的重叠是既有问题（`_sync_site_pref_combo_width` 把下拉框右缘钉到
「锁定类型」下拉框右缘，而按钮右缘锚组框右缘，两网格列数差 111px），不在本文件
断言范围内。
"""

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

UI_PATH = Path(__file__).resolve().parent.parent / "mdcx" / "views" / "MDCx.ui"

# 参与行序的三个控件
_COMBO = "comboBox_website_all"
_WARN = "label_315"
_BUTTON = "pushButton_scrape_note"

# 相对 gridLayout_28 的行号（.ui 里 <item row="N" column="1">）
_COMBO_ROW = 3
_WARN_ROW = 4

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
    # 注意：这里**刻意不**打桩 set_style / apply_site_priority_theme——本文件量的
    # 是行位置，而行高受 QSS 字体影响（真实主题下 widget_field_priority_options 行
    # 高 38、裸 UI 下 34），下拉框 y 随之差 6px（真实 138 / 打桩 144）。按钮的
    # 绝对定位 y 是按真实主题标定的，打桩后测出来的错位是假象。
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    # 构造后立即停表：几何测试不依赖定时器回调，保留运行中的 QTimer 会让
    # processEvents 触发网络/日志等无关副作用。
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_website_tab(win, app):
    """切到软件设置-刮削网站页（scrollArea_8 所在 tab）。"""
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).findChild(ui.scrollArea_8.__class__, "scrollArea_8") is not None:
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("刮削网站 tab (scrollArea_8) not found")
    for _ in range(4):
        app.processEvents()


def _rect_in_group(win, name):
    """控件相对 groupBox_11 的 (x, y, w, h)。"""
    gb = win.Ui.groupBox_11
    w = getattr(win.Ui, name)
    p = w.mapTo(gb, w.rect().topLeft())
    return p.x(), p.y(), w.width(), w.height()


def _y_overlap(a, b):
    """两矩形 (x, y, w, h) 的纵向重叠长度。"""
    return max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))


def test_site_pref_row_order_in_ui():
    """`.ui` 里下拉框在第 3 行、⚠️ 警告在第 4 行（行序本体）。

    直接解析 MDCx.ui 源码锁死行号——行序的唯一真相在 .ui，MDCx.py 是它的编译
    产物（由 tests/test_ui_structure.py::test_mdcx_py_in_sync_with_ui 保证同步）。
    """
    ui_src = UI_PATH.read_text(encoding="utf-8")

    def row_of(widget_name: str) -> int:
        idx = ui_src.index(f'name="{widget_name}"')
        head = ui_src.rindex("<item ", 0, idx)
        decl = ui_src[head : ui_src.index(">", head)]
        assert 'column="1"' in decl, f"{widget_name} 不在第 1 列：{decl}"
        return int(decl.split('row="')[1].split('"')[0])

    assert row_of(_COMBO) == _COMBO_ROW, "指定网站下拉框必须在第 3 行（⚠️ 警告之上）"
    assert row_of(_WARN) == _WARN_ROW, "⚠️ 警告必须下移到第 4 行（下拉框之下）"


@pytest.mark.parametrize("width", [800, 1000, 1400, 1920])
def test_scrape_note_button_centers_on_combo_above_warning(win, app, width):
    """按钮垂直居中于下拉框（dy==0），且完全不与下方的 ⚠️ 警告重叠。"""
    _goto_website_tab(win, app)
    win.resize(width, 900)
    win.show()
    for _ in range(4):  # 首次打开的几何要经 settle + 宽幅同步落定
        win._sync_page_layouts()
        app.processEvents()

    combo = _rect_in_group(win, _COMBO)
    warn = _rect_in_group(win, _WARN)
    button = _rect_in_group(win, _BUTTON)

    assert combo[1] < warn[1], f"下拉框 y={combo[1]} 应在 ⚠️ 警告 y={warn[1]} 之上"
    # 两者高度不同，用中心点比对（按钮高 26、下拉框高 30）
    dy = (button[1] + button[3] // 2) - (combo[1] + combo[3] // 2)
    assert dy == 0, f"{width} 宽下按钮与下拉框中心错位 {dy}px（combo={combo}, button={button}）"
    yov = _y_overlap(button, warn)
    assert yov == 0, f"{width} 宽下按钮与 ⚠️ 警告纵向重叠 {yov}px（button={button}, warn={warn}）"


def test_scrape_note_vertical_sync_heals_drift_and_keeps_x(win, app):
    """`_sync_scrape_note_vertical` 把被挪偏的按钮拉回居中，且不动 x。

    该按钮是绝对定位子控件，.ui 里的 y 只是初值；网格行高随字号/缩放变化，
    靠运行期重钉才不漂移。这里先人为把按钮挪偏，验证同步能自愈——
    这正是「只改 .ui 不加同步」的方案挡不住的场景。
    x 不动同样重要：按钮的右缘锚定由 CustomScrollArea 的 _DOCK_RIGHT 规则负责
    （CustomClass.py 的 _classify_inner），本控制器若顺手改 x 会与之打架。
    """
    _goto_website_tab(win, app)
    win.resize(1200, 900)
    win.show()
    for _ in range(4):
        win._sync_page_layouts()
        app.processEvents()

    button = win.Ui.pushButton_scrape_note
    combo = win.Ui.comboBox_website_all
    x_before = button.x()

    button.move(button.x(), combo.mapTo(button.parentWidget(), combo.rect().topLeft()).y() - 40)
    assert button.y() != _target_button_y(win), "前置条件失败：按钮未被挪偏"

    for _ in range(2):
        win._sync_page_layouts()
        app.processEvents()

    assert button.y() == _target_button_y(win), "同步后按钮未回到居中位"
    assert button.x() == x_before, f"同步不应改动按钮 x（{x_before} -> {button.x()}）"
    # 幂等：反复同步不产生漂移
    for _ in range(4):
        win._sync_page_layouts()
        app.processEvents()
    assert button.y() == _target_button_y(win), "反复同步后按钮 y 漂移"


def _target_button_y(win):
    """按下拉框实时几何算出的按钮目标 y（与 _sync_scrape_note_vertical 同算法）。"""
    button = win.Ui.pushButton_scrape_note
    combo = win.Ui.comboBox_website_all
    anchor = button.parentWidget()
    combo_y = combo.mapTo(anchor, combo.rect().topLeft()).y()
    return combo_y + (combo.height() - button.height()) // 2


def test_scrape_note_button_y_is_not_hardcoded_to_one_row():
    """`.ui` 里按钮的声明 y 必须与运行期算出的居中位一致（防止二者悄悄脱钩）。

    纵坐标在 .ui 与运行期各存一份（.ui 给初值、控制器每遍重钉）。若有人只改
    .ui 不看运行期（或反之），首帧就会出现错行。这里把两者钉在一起。
    """
    ui_src = UI_PATH.read_text(encoding="utf-8")
    # geometry <property> 紧跟在 name= 之后（.ui 里属性写在 widget 标签内部），
    # 必须从 marker 往后找，往前 rindex 会命中上一个控件的收尾属性。
    tail = ui_src[ui_src.index(f'name="{_BUTTON}"') :]
    geom = tail[: tail.index("</property>")]
    assert "<y>" in geom, f"未在 {_BUTTON} 的首个 property 里找到 <y>：{geom[:120]}"
    y = int(geom.split("<y>")[1].split("</y>")[0])
    # 真实默认字号下实测：下拉框 y=138、高 30，按钮高 26 → 138 + (30-26)//2 = 140
    assert y == 140, f".ui 声明的按钮 y={y} 与运行期居中位 140 不符（脱离运行期校准）"
