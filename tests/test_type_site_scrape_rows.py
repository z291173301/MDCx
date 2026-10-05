"""软件设置-刮削网站「类型刮削网站」组（groupBox_80 / gridLayout_36）行距回归。

用户需求两条：

1. 「收紧国产番号、动漫番号、MyWifes、锁定类型之间的上下间距使得更紧凑，将文字
   说明之间的间距由当前改成一行汉字的高度」；
2. 「有码番号、无码番号、素人番号、FC2 番号、欧美番号、国产番号下方的绿色文字说明
   向上移动一行，文字下方的控件、组件等同步向上移动一行」。

改前实测（真实主窗口 1014 宽，主题字体下一行说明文字高 17px）：`.ui` 里
`layoutWidget_6` 声明高 930，而 `gridLayout_36` 的自然高只有 618，多出的 312px 余量
被 QGridLayout 摊到每一行，于是「输入框 → 说明文字」被撑到 24px（需求 2 的
「上移一行」= 减 17px）；`label_318` / `label_323` 上还挂着 84px 的硬最小高，把三段
说明下方的块间间隙顶到 51px（需求 1 要的「一行汉字高度」= 17px）。

改后方案（全部落在 .ui，MDCx.py 由 pyuic6 重编译，测试
`test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 保证二者同步）：

* `gridLayout_36` 显式 `verticalSpacing = 7`，单行说明行行高=文字高，故「输入框 →
  说明」「说明 → 下一组控件」两侧都精确为 7px（改前 24px，正好上移一行）；
* 三段会换行的说明（`label_232` / `label_318` / `label_323`）所在行锚死为 34px
  （两行文字的高度：主题字体下一行 17px）：三者都加 `maximumSize` 高度 34，
  `label_318` / `label_323` 去掉 84px 硬最小高，行高由同行的 `label_316` /
  `label_322`（最小高 30）兜底——余量因此全部留在 `layoutWidget_6` 底部，不会再摊到
  行里制造死白；
* 国产说明 / 动漫里番 / MyWifes / 锁定类型 四个块之间各插一行固定 9px 的
  QSpacerItem，块间总间隙 = 7 + 9 = 16px ≈ 一行汉字高度（改前 51px）；
* `layoutWidget_6` 高 930→558、`groupBox_80` 高 970→628，分隔线 `y` 1289→976、
  后续组 `groupBox_35` y 1340→1027，content 高 2470→2157（底部留白仍 130）。

本文件锁死：19 行的行号表、verticalSpacing、三个 spacer 的高度与 Fixed 策略、
说明标签不再有 84px 硬最小高、声明几何，以及真实主窗口在各窗口宽度下量到的间隙。

已知取舍：窗口窄于约 980 时三段换行说明需要三行（51px），而行高被钉在 34px，会截掉
第三行——这是为了让默认宽度下的紧凑布局稳定；同样地，窗口很宽时三段说明只有一行，
34px 的行高会在文字下方留下约 19px 死白，块间视觉间隙相应变大。宽态的死白已由
运行期收敛处理（见文末「宽态单行收敛」一节）。
"""

import re
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

UI_PATH = Path(__file__).resolve().parent.parent / "mdcx" / "views" / "MDCx.ui"

# 目标组：`scrollAreaWidgetContents_guaxiaowangzhan` 里的 groupBox_80「类型刮削网站」
_GRID = "gridLayout_36"
_GROUP = "groupBox_80"
_INNER = "layoutWidget_6"
_CONTENT = "scrollAreaWidgetContents_guaxiaowangzhan"
_NEXT_GROUP = "groupBox_35"  # 紧随其后的「字段刮削网站」，用来验证没有互相压叠

_SPACING = 7  # gridLayout_36 的 verticalSpacing
_BLOCK_SPACER_H = 9  # 三个块间 QSpacerItem 的固定高
_DESC_ROW_H = 34  # 三段换行说明所在行的锚死高度（两行文字）

# 期望间隙：行高=文字高时上下两侧都精确为 verticalSpacing；块间再加 9px spacer
_GAP_TIGHT = _SPACING
_GAP_BLOCK = _SPACING + _BLOCK_SPACER_H
_TOL = 2  # 字体渲染取整容差
# 块间要放宽：换行说明行的行高取 `max(sizeHint)`，而 wordWrap QLabel 的 sizeHint 是文字
# 包围盒高（可带小数），同一段文字在 339 / 341px 宽下包围盒高会差 1~2px，行高随之抖动
_TOL_BLOCK = 4

# gridLayout_36 的完整行号表：(行号, 该行的 (控件名 -> 列号))
_ROW_TABLE = {
    0: {"label_153": 0, "lineEdit_website_youma": 1},
    1: {"label_154": 1},
    2: {"label_151": 0, "lineEdit_website_wuma": 1},
    3: {"label_155": 1},
    4: {"label_152": 0, "lineEdit_website_suren": 1},
    5: {"label_156": 1},
    6: {"label_148": 0, "lineEdit_website_fc2": 1},
    7: {"label_157": 1},
    8: {"label_149": 0, "lineEdit_website_oumei": 1},
    9: {"label_158": 1},
    10: {"label_217": 0, "lineEdit_website_guochan": 1},
    11: {"label_232": 1},
    12: {"verticalSpacer_guochan_gap": 0},
    13: {"label_316": 0, "label_318": 1},
    14: {"verticalSpacer_dongman_gap": 0},
    15: {"label_322": 0, "label_323": 1},
    16: {"verticalSpacer_mywifes_gap": 0},
    17: {"label_fixed_scraping_type": 0, "comboBox_fixed_scraping_type": 1},
    18: {"label_fixed_scraping_type_desc": 1},
}

# (上方控件, 说明标签)：需求 2 —— 说明文字紧贴上方输入框
_DESC_UNDER_CONTROL = [
    ("lineEdit_website_youma", "label_154"),
    ("lineEdit_website_wuma", "label_155"),
    ("lineEdit_website_suren", "label_156"),
    ("lineEdit_website_fc2", "label_157"),
    ("lineEdit_website_oumei", "label_158"),
    ("lineEdit_website_guochan", "label_232"),
]
# 需求 1 —— 块与块之间（说明文字 ↔ 下一块首个控件）＝ 一行汉字高度
_DESC_TO_NEXT_BLOCK = [
    ("label_232", "label_316"),
    ("label_318", "label_322"),
    ("label_323", "comboBox_fixed_scraping_type"),
]
# 说明文字下方的控件同步上移（说明底 → 下一控件顶）
_DESC_TO_NEXT_CONTROL = [
    ("label_154", "lineEdit_website_wuma"),
    ("label_155", "lineEdit_website_suren"),
    ("label_156", "lineEdit_website_fc2"),
    ("label_157", "lineEdit_website_oumei"),
    ("label_158", "lineEdit_website_guochan"),
    ("comboBox_fixed_scraping_type", "label_fixed_scraping_type_desc"),
]
# 动漫里番 / MyWifes 两块是「块标签 + 说明」同行（列 0 / 列 1），顶边必须基本齐平
_LABEL_TO_OWN_DESC = [
    ("label_316", "label_318"),
    ("label_322", "label_323"),
]

_WIDE_WIDTHS = [1400, 1014, 860]
_APP_FONT_LINE = 17  # 主题字体下一行说明文字的高度

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
    """离屏真实主窗口（几何断言必须以真实窗口读数为准，见 test_site_pref_row_order.py）。"""
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
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


# --------------------------------------------------------------------------- #
# 静态断言：.ui 是行号 / 间距 / 几何的唯一真相，MDCx.py 由 pyuic6 生成
# --------------------------------------------------------------------------- #
def _ui_src() -> str:
    return UI_PATH.read_text(encoding="utf-8")


def _grid_block(ui_src: str) -> str:
    """gridLayout_36 的 <layout> ... </layout> 原文。"""
    idx = ui_src.index(f'name="{_GRID}"')
    start = ui_src.rindex("<layout ", 0, idx)
    return ui_src[start : ui_src.index("</layout>", idx)]


def _item_decl(ui_src: str, widget_name: str) -> str:
    """widget 在网格里的 <item row=.. column=.. colspan=..> 声明行。"""
    idx = ui_src.index(f'name="{widget_name}"')
    head = ui_src.rindex("<item ", 0, idx)
    return ui_src[head : ui_src.index(">", head)]


def _widget_block(ui_src: str, widget_name: str) -> str:
    """widget 自身的 <widget ...> ... </widget> 原文（不含网格 item 声明）。"""
    idx = ui_src.index(f'name="{widget_name}"')
    start = ui_src.rindex("<widget ", 0, idx)
    return ui_src[start : ui_src.index("</widget>", idx)]


def _widget_head(ui_src: str, widget_name: str) -> str:
    """widget 自身的 <widget ...> 到第一个子控件/子布局之前（只含自身 property）。"""
    block = _widget_block(ui_src, widget_name)
    head = block
    for stop in ("<widget class=", "<layout "):
        # 从开标签之后开始找，避免把自身开标签当成子控件
        pos = head.find(stop, len("<widget "))
        if pos != -1:
            head = head[:pos]
    return head


def _geometry_of(ui_src: str, widget_name: str) -> tuple[int, int, int, int]:
    """.ui 里声明的 geometry (x, y, w, h)。"""
    idx = ui_src.index(f'name="{widget_name}"')
    tail = ui_src[idx : idx + 4000]
    # geometry 必须是该控件自己的首个 property，不能越过下一个子控件标签
    for stop in ("<layout ", "<widget class=", "<spacer "):
        pos = tail.find(stop)
        if pos != -1:
            tail = tail[:pos]
    assert '<property name="geometry">' in tail, f"{widget_name} 未声明 geometry"
    geom = tail[: tail.index("</property>")]
    return tuple(int(re.search(f"<{k}>(\\d+)</{k}>", geom).group(1)) for k in ("x", "y", "width", "height"))


def test_grid_row_table_in_ui():
    """19 行行号表锁死：6 组「输入框 + 绿色说明」+ 3 个块间 spacer + 动漫/MyWifes/锁定类型。"""
    ui_src = _ui_src()
    block = _grid_block(ui_src)

    for row, members in _ROW_TABLE.items():
        for name, column in members.items():
            decl = _item_decl(block, name)
            got_row = int(decl.split('row="')[1].split('"')[0])
            got_col = int(decl.split('column="')[1].split('"')[0])
            assert (got_row, got_col) == (
                row,
                column,
            ), f"{name} 应在 gridLayout_36 第 {row} 行第 {column} 列，实为 {got_row}/{got_col}"

    # 行数不得悄悄增加（多一行就多一份 verticalSpacing，整组又会松回去）
    rows = {int(m) for m in re.findall(r'<item row="(\d+)"', block)}
    assert rows == set(range(19)), f"gridLayout_36 的行号集合应为 0..18，实为 {sorted(rows)}"


def test_grid_vertical_spacing_in_ui():
    """verticalSpacing 显式为 7（行高=文字高的单行说明行据此得到 7px 间隙 = 上移一行）。"""
    block = _grid_block(_ui_src())
    spacing = block[block.index('<property name="verticalSpacing">') :]
    spacing = spacing[: spacing.index("</property>")]
    assert f"<number>{_SPACING}</number>" in spacing, f"gridLayout_36 的 verticalSpacing 应为 {_SPACING}：{spacing}"
    # 纵向间距必须显式写死：默认值（6）既不是目标值、也不随行数收敛
    assert '<property name="verticalSpacing">' in block


def test_block_gap_spacers_in_ui():
    """三个块间 spacer：Fixed 策略 + 固定高 9（块间总间隙 = 7 + 9 = 16px ≈ 一行汉字）。"""
    block = _grid_block(_ui_src())
    for name in ("verticalSpacer_guochan_gap", "verticalSpacer_dongman_gap", "verticalSpacer_mywifes_gap"):
        idx = block.index(f'name="{name}"')
        spacer = block[idx - len("<spacer ") : block.index("</spacer>", idx)]
        assert "<enum>QSizePolicy::Fixed</enum>" in spacer, f"{name} 必须 Fixed（否则会被余量撑开）：{spacer}"
        assert '<property name="orientation">' in spacer and "Qt::Vertical" in spacer, f"{name} 必须纵向"
        height = int(re.search(r"<height>(\d+)</height>", spacer).group(1))
        assert height == _BLOCK_SPACER_H, f"{name} 的固定高应为 {_BLOCK_SPACER_H}，实为 {height}"
        # 必须横跨整行 4 列，否则 spacer 只占首列、列宽变化时会挤到别的列上
        assert 'colspan="4"' in _item_decl(block, name), f"{name} 未横跨 4 列"


def test_wrapped_desc_labels_anchored_at_desc_row_height():
    """三段换行说明不再挂 84px 硬最小高（那是原来 51px 死白的根因），行高锚在 34px。"""
    ui_src = _ui_src()
    for name in ("label_318", "label_323"):
        head = _widget_head(ui_src, name)
        assert 'name="minimumSize"' not in head or "84" not in head, f"{name} 不应再保留 84px 硬最小高：{head}"

    # 三段说明都用 maximumSize 把所在行钉在两行文字（34px）
    for name in ("label_232", "label_318", "label_323"):
        block = _widget_block(ui_src, name)
        assert 'name="maximumSize"' in block, f"{name} 应用 maximumSize 锚死行高"
        max_size = block[block.index('name="maximumSize"') :]
        max_size = max_size[: max_size.index("</property>")]
        assert f"<height>{_DESC_ROW_H}</height>" in max_size, (
            f"{name} 的 maximumSize 高度应为 {_DESC_ROW_H}：{max_size}"
        )
    assert "Qt::AlignTop" in _widget_block(ui_src, "label_232"), "label_232 必须 AlignTop，否则文字不会紧贴输入框下方"

    # 行高由同行的块标签兜底（最小高 30，允许被 34 的说明撑高）
    for name in ("label_316", "label_322"):
        head = _widget_head(ui_src, name)
        assert "<height>30</height>" in head, f"{name} 的最小高应为 30（决定说明行高）：{head}"


def test_declared_geometry_is_compacted_and_followers_shifted():
    """声明几何收敛：组内 558/628，后续兄弟上移 360px，content 收窄到 2157。"""
    ui_src = _ui_src()
    assert _geometry_of(ui_src, _INNER) == (20, 30, 661, 558), "layoutWidget_6 应为 661x558（= 各行自然高之和 + 间距）"
    assert _geometry_of(ui_src, _GROUP) == (30, 290, 701, 628), "groupBox_80 应为 701x628"

    group_bottom = 290 + 628
    _nx, next_y, _nw, next_h = _geometry_of(ui_src, _NEXT_GROUP)
    assert next_y == 1027, f"groupBox_35 应整体上移到 y=1027（改前 1340），实为 {next_y}"
    assert next_y >= group_bottom, f"groupBox_35(y={next_y}) 与 groupBox_80(底={group_bottom}) 重叠"

    content_x, content_y, content_w, content_h = _geometry_of(ui_src, _CONTENT)
    assert (content_x, content_y, content_w) == (0, 0, 860)
    assert content_h == 2157, "content 高应收窄到 2157（底部留白与改前一致）"
    assert content_h >= next_y + next_h, f"content 高 {content_h} 容不下 groupBox_35（底 {next_y + next_h}）"
    # 底部留白不能被吃掉：改前 groupBox_35 底 2340、content 高 2470，留白 130
    assert content_h - (next_y + next_h) == 130


# 三段会换行的绿色说明文案（`.ui` 里以 &lt;p&gt; 富文本存储）
_WRAPPED_DESC_TEXTS = {
    "label_232": (
        "<span>「网站偏好」-「指定网站」指定madouqu、madou_club或文件路径含有「国产」、「麻豆」时，"
        "将自动使用以上网站刮削国产番号</span>"
    ),
    "label_318": (
        "<p>「网站偏好」-「指定网站」指定getchu、dmm等站点或文件路径包含有「里番」、「动漫」时，"
        "程序将会自动使用getchu进行刮削</p>"
    ),
    "label_323": (
        "<p>「网站偏好」-「指定网站」指定MyWife或文件路径含有MyWife时，将自动使用MyWife刮削，"
        "MyWife番号规则：MyWife No.1230</p>"
    ),
}


def test_wrapped_desc_texts_regression():
    """三段换行说明文案回归锁：MyWife 品牌大小写（全文统一 MyWife）改回 Mywife 即失败。"""
    ui_src = _ui_src()
    mismatches = {}
    for name, expected in _WRAPPED_DESC_TEXTS.items():
        block = _widget_block(ui_src, name)
        raw = block[block.index('<property name="text">') :]
        raw = raw[: raw.index("</property>")]
        start = raw.index("<string")
        value = raw[raw.index(">", start) + 1 : raw.index("</string>")]
        actual = value.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if actual != expected:
            mismatches[name] = actual
    assert not mismatches, f"类型刮削网站三段说明文案与预期不符: {mismatches}"


# 六条番号提示词文案（用户把「个摄番号：」改名为「FC2番号：」后一并锁死，
# 防止日后无声改回谐音写法，或某一条被单独改成别的品牌名）。
# 注意：2026-10-05 全站文案去空格统一后，FC2 后不再带空格，此处与 .ui 保持一致
# （v2.2.5 改名历史里记的是带空格的旧写法，见 docs/Changelog.md）。
_NUMBER_LABELS = {
    "label_153": "有码番号：",
    "label_151": "无码番号：",
    "label_152": "素人番号：",
    "label_148": "FC2番号：",
    "label_149": "欧美番号：",
    "label_217": "国产番号：",
}


def test_number_label_texts_regression():
    """六条番号提示词文案锁：第四行必须是「FC2番号：」（改回「个摄番号：」或加回空格即失败）。"""
    ui_src = _ui_src()
    mismatches = {}
    for name, expected in _NUMBER_LABELS.items():
        block = _widget_block(ui_src, name)
        raw = block[block.index('<property name="text">') :]
        raw = raw[: raw.index("</property>")]
        start = raw.index("<string")
        actual = raw[raw.index(">", start) + 1 : raw.index("</string>")]
        if actual != expected:
            mismatches[name] = actual
    assert not mismatches, f"六条番号提示词文案与预期不符: {mismatches}"


# --------------------------------------------------------------------------- #
# 运行期断言：真实主窗口的几何
# --------------------------------------------------------------------------- #
def _rect(win, name):
    """控件相对 layoutWidget_6 的 (y, bottom, height)。"""
    anchor = getattr(win.Ui, _INNER)
    w = getattr(win.Ui, name)
    p = w.mapTo(anchor, w.rect().topLeft())
    return p.y(), p.y() + w.height(), w.height()


def _gap(win, lower_name, upper_name):
    """upper_name 的底边到 lower_name 的顶边的间距。"""
    return _rect(win, lower_name)[0] - _rect(win, upper_name)[1]


def _show_at_width(win, app, width):
    _goto_website_tab(win, app)
    win.resize(width, 900)
    win.show()
    for _ in range(4):
        win._sync_page_layouts()
        app.processEvents()


@pytest.mark.parametrize("width", _WIDE_WIDTHS)
def test_desc_labels_sit_one_line_under_their_input(win, app, width):
    """需求 2：绿色说明紧贴上方输入框（7px，改前 24px = 上移一行 17px）。"""
    _show_at_width(win, app, width)

    for control, desc in _DESC_UNDER_CONTROL:
        gap = _gap(win, desc, control)
        assert abs(gap - _GAP_TIGHT) <= _TOL, (
            f"{width} 宽下 {control} → {desc} 间隙 {gap}px，应约 {_GAP_TIGHT}px（改前 24px）"
        )


@pytest.mark.parametrize("width", _WIDE_WIDTHS)
def test_desc_to_next_control_gap_is_tight(win, app, width):
    """需求 2 后半：说明文字下方的控件、组件同步上移（同样 7px）。"""
    _show_at_width(win, app, width)

    for desc, control in _DESC_TO_NEXT_CONTROL:
        gap = _gap(win, control, desc)
        assert abs(gap - _GAP_TIGHT) <= _TOL, f"{width} 宽下 {desc} → {control} 间隙 {gap}px，应约 {_GAP_TIGHT}px"


@pytest.mark.parametrize("width", _WIDE_WIDTHS)
def test_block_label_and_its_desc_share_a_row(win, app, width):
    """动漫里番 / MyWifes：块标签与说明在同一行（顶边基本齐平，说明没被挤到下一行）。"""
    _show_at_width(win, app, width)

    for label, desc in _LABEL_TO_OWN_DESC:
        offset = _rect(win, desc)[0] - _rect(win, label)[0]
        # 34px 行内 30px 高的块标签居中 → 最多差 2px；差一整行(≥17px)才是回归
        assert abs(offset) <= _DESC_ROW_H - _APP_FONT_LINE, (
            f"{width} 宽下 {label} / {desc} 顶边错位 {offset}px（应同行）"
        )


@pytest.mark.parametrize("width", _WIDE_WIDTHS)
def test_block_gaps_are_one_line_of_text(win, app, width):
    """需求 1：国产/动漫/MyWifes/锁定类型之间的块间间隙 ≈ 一行汉字高度（16px，改前 51px）。"""
    _show_at_width(win, app, width)

    for desc, next_block in _DESC_TO_NEXT_BLOCK:
        gap = _gap(win, next_block, desc)
        assert abs(gap - _GAP_BLOCK) <= _TOL_BLOCK, (
            f"{width} 宽下 {desc} → {next_block} 块间间隙 {gap}px，应约 {_GAP_BLOCK}px（改前 51px）"
        )


@pytest.mark.parametrize("width", _WIDE_WIDTHS)
def test_group_keeps_declared_height_and_does_not_overlap_next_group(win, app, width):
    """容器高度不被网格撑大（余量留在底部），且内容不越过组框 / 下一组。"""
    _show_at_width(win, app, width)

    grid = getattr(win.Ui, _GRID)
    inner = getattr(win.Ui, _INNER)
    group = getattr(win.Ui, _GROUP)

    assert inner.height() == 558, f"layoutWidget_6 高度被改成 {inner.height()}（声明 558）"
    assert grid.verticalSpacing() == _SPACING, f"运行期 verticalSpacing 被改成了 {grid.verticalSpacing()}"

    inner_bottom = inner.mapTo(group, inner.rect().topLeft()).y() + inner.height()
    assert inner_bottom <= group.height(), f"内容底 {inner_bottom} 越过组框高 {group.height()}"

    next_group = getattr(win.Ui, _NEXT_GROUP)
    next_y = next_group.mapTo(group, next_group.rect().topLeft()).y()
    assert inner_bottom <= next_y, f"类型刮削网站内容底 {inner_bottom} 压到下一组（y={next_y}）"


@pytest.mark.parametrize("width", [1400, 1014])
def test_wrapped_desc_text_is_not_clipped(win, app, width):
    """三段换行说明的行高要装得下真实排版高度（钉 34px = 两行文字后不能截字）。

    窗口窄于约 980 时三段说明需要三行（51px），被钉在 34px 会截掉第三行——这是让默认
    宽度下布局稳定的刻意取舍，因此只在用户常用的 ≥1014 宽下断言不截断。
    """
    _show_at_width(win, app, width)

    for name in ("label_232", "label_318", "label_323"):
        label = getattr(win.Ui, name)
        need = label.heightForWidth(label.width())
        assert label.height() >= need, f"{width} 宽下 {name} 高 {label.height()} < 需要 {need}（文字被截断）"


# --------------------------------------------------------------------------- #
# 宽态单行收敛（需求③：最大化时「动漫里番」上移一行，最小化逐像素不变）
# --------------------------------------------------------------------------- #
# 用户需求③：「软件设置-刮削网站-类型刮削网站页最大化时将动漫里番向上移动一行，
# 因为提示词已经在一行显示了，目前最大化时动漫里番离国产番号的间距太大了」，
# 且「最小化时的界面、布局、组件、控件、提示词等等均保持不变」。
#
# 根因：label_232（国产番号说明）开了 wordWrap 且 .ui 钉了 maximumSize 高 34
# （=两行），而 QGridLayout 定行高走 sizeHint 受 maximumSize 夹取、**不走
# heightForWidth**——所以任何静态 .ui 值都无法让这一行随窗口宽度收缩。最大化后该
# 说明只需一行（实测 need=15px），行高却仍钉在 34px，行下方 19px 死白把「动漫里番」
# 整块顶下去一行。
#
# 方案（main_window._sync_site_type_tip_single_line，在 _sync_page_layouts 里排在通用
# 拉伸之后）：量 need = heightForWidth(width)，确认确实单行且页面已被拉宽时把
# maximumSize 高收成 need；**同一笔高度必须以 gridLayout_36 的 bottomMargin 归还**
# ——否则网格自然高度 522→503 而容器仍是 558，QGridLayout 会把少掉的 19px 摊到 18
# 个 verticalSpacing 上（每档 +1px），结果「动漫里番」只上移 6px 而不是一行（实测）。
_GUOCHAN_TIP = "label_232"
_DONGMAN_LABEL = "label_316"  # 「动漫里番：」块标签，用户要求上移的那一行
# 收敛只允许动这一行下方的东西；这三项必须在宽窄两态保持一致（间距不得变化）
_STATE_INVARIANTS = ("lineEdit_website_youma", "label_154", "lineEdit_website_guochan")
_NARROW_WIDTHS = [860, 1014]  # 说明仍需两行 → 不收敛
_WIDE_SINGLE_LINE_WIDTHS = [1400, 1920]  # 说明只需一行 → 收敛


def _tip_state(win):
    """label_232 的收敛状态：需要高度 / 单行高 / 当前上限 / 已归还的下边距。"""
    grid = getattr(win.Ui, _GRID)
    tip = getattr(win.Ui, _GUOCHAN_TIP)
    return {
        "need": tip.heightForWidth(tip.width()),
        "line_h": tip.fontMetrics().height(),
        "max_h": tip.maximumHeight(),
        "bottom": grid.contentsMargins().bottom(),
        "height": tip.height(),
        "spacing": grid.verticalSpacing(),
        "natural": grid.sizeHint().height(),
        "inner_h": getattr(win.Ui, _INNER).height(),
    }


def _baseline_without_convergence(win, app, monkeypatch, take):
    """摘掉收敛方法并交回设计值后重跑同步，返回「改动前」的读数（随后复位方法）。

    只摘方法不够：本方法把收敛结果**持久**在 label_232 的 maximumHeight 与网格下边距
    上，no-op 的方法不会自动交回，故必须手工还原成 .ui 的设计值（34 / 0）再量。
    基线一律在**同一窗口宽度**下取——不同宽度之间列宽本就不同，跨宽度比对会把列宽
    差异误判成收敛带来的位移。
    """
    cls = type(win)
    original = cls._sync_site_type_tip_single_line
    monkeypatch.setattr(cls, "_sync_site_type_tip_single_line", lambda self: None)
    try:
        tip = getattr(win.Ui, _GUOCHAN_TIP)
        grid = getattr(win.Ui, _GRID)
        margins = grid.contentsMargins()
        tip.setMaximumHeight(_DESC_ROW_H)
        grid.setContentsMargins(margins.left(), margins.top(), margins.right(), 0)
        for _ in range(3):
            win._sync_page_layouts()
            app.processEvents()
        return take()
    finally:
        monkeypatch.setattr(cls, "_sync_site_type_tip_single_line", original)


def _converged(win) -> bool:
    """当前宽度下说明是否已收敛到单行（need 只占一行高 + 容差）。"""
    state = _tip_state(win)
    return state["need"] <= state["line_h"] + win._SITE_TYPE_SINGLE_LINE_SLACK


def _freed(win) -> int:
    return _DESC_ROW_H - _tip_state(win)["need"]


@pytest.mark.parametrize("width", _NARROW_WIDTHS)
def test_narrow_state_keeps_declared_row_height(win, app, width):
    """需求③ 后半：最小化时说明行仍是 .ui 声明的 34px，网格下边距仍是 0（零改动）。"""
    _show_at_width(win, app, width)

    state = _tip_state(win)
    assert state["max_h"] == _DESC_ROW_H, f"{width} 宽下 {_GUOCHAN_TIP} 上限变成 {state['max_h']}，应为 {_DESC_ROW_H}"
    assert state["bottom"] == 0, f"{width} 宽下网格下边距变成 {state['bottom']}，应为 0（最小化不得改动）"
    assert state["spacing"] == _SPACING, f"{width} 宽下 verticalSpacing 被改成 {state['spacing']}"
    assert state["inner_h"] == 558, f"{width} 宽下 layoutWidget_6 高度变成 {state['inner_h']}（声明 558）"


@pytest.mark.parametrize("width", _WIDE_SINGLE_LINE_WIDTHS)
def test_wide_state_collapses_guochan_tip_row_to_one_line(win, app, monkeypatch, width):
    """需求③：最大化时说明行收到「真实需要高度」，且省下的高度原样归还给下边距。"""
    _show_at_width(win, app, width)

    state = _tip_state(win)
    assert state["need"] <= state["line_h"] + win._SITE_TYPE_SINGLE_LINE_SLACK, (
        f"{width} 宽下前置条件不成立：need={state['need']} 仍需多行，本用例无意义"
    )
    freed = _DESC_ROW_H - state["need"]
    assert freed > 0, f"{width} 宽下没有可回收的高度（need={state['need']}）"
    assert state["max_h"] == state["need"], f"{width} 宽下上限 {state['max_h']} 应收到 need={state['need']}"
    assert state["height"] == state["need"], f"{width} 宽下说明高 {state['height']} 应等于 need={state['need']}"
    assert state["bottom"] == freed, f"{width} 宽下归还的下边距 {state['bottom']} 应为 {freed}"

    # 归还的判据是「网格自然高度与改动前一致」（自然高本身随字体而变，故与基线比、
    # 不写死）：没归还时自然高会掉 freed，QGridLayout 只能把余量摊进 verticalSpacing。
    base_natural = _baseline_without_convergence(win, app, monkeypatch, lambda: _tip_state(win)["natural"])
    assert state["natural"] == base_natural, (
        f"{width} 宽下网格自然高 {state['natural']} ≠ 改动前 {base_natural}"
        f"（少掉的 {freed}px 没还回下边距，只会被摊进行间距）"
    )
    assert state["spacing"] == _SPACING, f"{width} 宽下 verticalSpacing 被改成 {state['spacing']}"
    assert state["inner_h"] == 558, f"{width} 宽下 layoutWidget_6 高度变成 {state['inner_h']}（声明 558）"


@pytest.mark.parametrize("width", _WIDE_SINGLE_LINE_WIDTHS + _NARROW_WIDTHS)
def test_wide_state_moves_dongman_up_without_touching_gaps(win, app, monkeypatch, width):
    """需求③ 正题：宽态「动漫里番」上移恰好一行，且行间距与「改动前」的基线逐项相同。"""
    _show_at_width(win, app, width)
    names = (
        *_STATE_INVARIANTS,
        _GUOCHAN_TIP,
        _DONGMAN_LABEL,
        "label_318",
        "label_322",
        "label_fixed_scraping_type_desc",
    )

    def measure():
        return (
            {name: _rect(win, name) for name in names},
            {
                "input→desc": _gap(win, _GUOCHAN_TIP, "lineEdit_website_guochan"),
                "desc→dongman": _gap(win, _DONGMAN_LABEL, _GUOCHAN_TIP),
                "dongman→mywifes": _gap(win, "label_322", "label_318"),
            },
        )

    new_rows, new_gaps = measure()
    converged = _converged(win)
    freed = _freed(win)
    base_rows, base_gaps = _baseline_without_convergence(win, app, monkeypatch, measure)

    if not converged:
        # 未收敛时必须与改动前逐像素一致（最小化不得有任何改动）
        assert new_rows == base_rows, f"{width} 宽下说明仍需多行，收敛不应生效：{base_rows} -> {new_rows}"
        assert new_gaps == base_gaps, f"{width} 宽下间距被改动：{base_gaps} -> {new_gaps}"
        return

    moved = base_rows[_DONGMAN_LABEL][0] - new_rows[_DONGMAN_LABEL][0]
    assert moved == freed, f"{width} 宽下「动漫里番」上移 {moved}px，应恰好一行 {freed}px"
    # 说明行本身收高，上方的行纹丝不动
    shrunk = base_rows[_GUOCHAN_TIP][2] - new_rows[_GUOCHAN_TIP][2]
    assert shrunk == freed, f"{width} 宽下国产说明行高只收了 {shrunk}px，应为 {freed}px"
    for name in _STATE_INVARIANTS:
        assert new_rows[name] == base_rows[name], f"{width} 宽下 {name} 被带偏: {base_rows[name]} -> {new_rows[name]}"
    # 间距不变：省下的高度若没归还就会被摊进 verticalSpacing
    assert new_gaps == base_gaps, f"{width} 宽下间距变化: {base_gaps} -> {new_gaps}"
    assert abs(new_gaps["desc→dongman"] - _GAP_BLOCK) <= _TOL_BLOCK, (
        f"{width} 宽下 国产说明 → 动漫里番 间隙 {new_gaps['desc→dongman']}px，应约 {_GAP_BLOCK}px"
    )


def test_single_line_convergence_is_idempotent_and_round_trips(win, app):
    """幂等 + 宽↔窄往返自愈：重复同步不漂移，窄→宽→窄 逐项复原。"""
    _show_at_width(win, app, 1014)
    narrow = {name: _rect(win, name) for name in _STATE_INVARIANTS + (_GUOCHAN_TIP, _DONGMAN_LABEL)}
    narrow_state = _tip_state(win)
    _show_at_width(win, app, 1014)
    assert {name: _rect(win, name) for name in narrow} == narrow, "窄态二次同步漂移"
    assert _tip_state(win) == narrow_state, "窄态二次同步状态漂移"

    _show_at_width(win, app, 1920)
    wide = {name: _rect(win, name) for name in narrow}
    assert wide != narrow, "宽态未产生任何位移，收敛机制本身失效"
    _show_at_width(win, app, 1920)
    assert {name: _rect(win, name) for name in wide} == wide, "宽态二次同步漂移"

    _show_at_width(win, app, 1014)
    assert {name: _rect(win, name) for name in narrow} == narrow, "窄→宽→窄 往返未复原"
    assert _tip_state(win) == narrow_state, "窄→宽→窄 往返后收敛状态未复原（上限/下边距没交回设计值）"
