"""UI 几何回归测试：防止同一 gridLayout 内可见控件包围盒相交（重影/重叠）。

历史坑：
- 翻译页 label_baidu_hint 放 col0 长文本不换行向右溢出，被 col1 的 label_60
  不透明背景遮挡，露出前半截产生重影
- 网络页 trusted_hosts 输入框与超时行同 cell 冲突（同一 gridLayout cell 放两 widget）
- 多处 gridLayout 同行同列多 item 覆盖

这些都是运行时几何冲突，纯 XML 静态结构测试 (test_ui_structure) 抓不到。
本测试 offscreen 实例化 Ui_MDCx，强制激活每个 gridLayout，断言同 layout 内
任意两个可见直接子控件包围盒无交集。覆盖 .ui 静态控件层（运行时动态注入的
控件需收口到 .ui 后才能覆盖）。
"""

import os
import re
from itertools import combinations

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLayout,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QWidget,
)

import mdcx.views.MDCx as M

# comboBox popup 等内部子部件在 offscreen 下有 (0,0)/(100,30)/(640,480) 占位
# geometry，与几何校验无关，全部跳过（参见 MEMORY 的 findChildren 几何检查排除项）。
_POPUP_CLASSES = {"QListView", "QScrollBar", "QMenu", "QComboBoxListView", "QToolButton"}

# 已知的合法重叠（非 bug）。新增条目前请先确认是否真为 bug。
# 每项: (parent_objectname, widget1_objectname, widget2_objectname)
_KNOWN_OK_OVERLAPS: set[tuple[str, str, str]] = {
    # widget_setting 侧边栏：left_backgroud_widget 是全幅背景层，上层按钮/关闭区合法叠加
    ("widget_setting", "close_widget", "left_backgroud_widget"),
    ("widget_setting", "left_backgroud_widget", "widget_buttons"),
    # groupBox_10 内「演示动画：」label_7 与其后的链接 label_get_cookie_url 紧邻设计
    ("groupBox_10", "label_7", "label_get_cookie_url"),
}


def _skip_widget(w: QWidget) -> bool:
    if not w.isVisible():
        return True
    if w.__class__.__name__ in _POPUP_CLASSES:
        return True
    g = w.geometry()
    if g.isNull() or g.width() <= 0 or g.height() <= 0:
        return True
    return False


def _bbox_in(w: QWidget, ref: QWidget) -> tuple[int, int, int, int] | None:
    g = w.geometry()
    if g.isNull() or g.width() <= 0 or g.height() <= 0:
        return None
    tl = w.mapTo(ref, g.topLeft())
    br = w.mapTo(ref, g.bottomRight())
    return (tl.x(), tl.y(), br.x(), br.y())


def _overlap_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _activate_ancestors(w: QWidget) -> None:
    """offscreen 下 widget 必须自身及所有祖先可见才会被布局引擎计算几何。"""
    cur: QWidget | None = w
    while cur is not None:
        try:
            cur.setVisible(True)
        except Exception:
            break
        cur = cur.parentWidget()


def _activate_all_tabs(mw: QMainWindow) -> None:
    """切换每个 QTabWidget / QStackedWidget 的所有页，触发隐藏页子控件布局。"""
    app = QApplication.instance()
    for tw in mw.findChildren(QTabWidget):
        for i in range(tw.count()):
            tw.setCurrentIndex(i)
            if app is not None:
                app.processEvents()
    for sw in mw.findChildren(QStackedWidget):
        for i in range(sw.count()):
            w = sw.widget(i)
            if w is not None:
                sw.setCurrentWidget(w)
                if app is not None:
                    app.processEvents()


def _activate(layout: QLayout) -> None:
    """offscreen 下 tab 未激活时子控件 geometry 全 0，强制激活布局让 geometry 生效。"""
    pw = layout.parentWidget()
    if pw is None:
        return
    try:
        _activate_ancestors(pw)
        pw.show()
        pw.ensurePolished()
        sz = pw.sizeHint()
        if sz.isValid() and not sz.isEmpty():
            pw.resize(sz.expandedTo(pw.minimumSizeHint()))
        layout.activate()
        layout.invalidate()
        layout.activate()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:
        pass


_APP: QApplication | None = None
_MW: QMainWindow | None = None


@pytest.fixture(scope="module")
def main_window() -> QMainWindow:
    # QApplication / QMainWindow 必须由 module 级全局持有，否则 fixture 返回后
    # 局部 app 被 GC 析构会连带删除所有 Qt 窗体（offscreen 下复现）。
    global _APP, _MW
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    if _MW is None:
        _MW = QMainWindow()
        M.Ui_MDCx().setupUi(_MW)
        _MW.show()
        _APP.processEvents()
    return _MW


def test_gridlayouts_no_visible_overlap(main_window: QMainWindow) -> None:
    _activate_all_tabs(main_window)
    failures: list[str] = []
    for lay in main_window.findChildren(QLayout):
        if not isinstance(lay, QGridLayout):
            continue
        _activate(lay)
        ref = lay.parentWidget()
        if ref is None:
            continue
        ref_name = ref.objectName() or ""
        boxes: list[tuple[str, tuple[int, int, int, int]]] = []
        for i in range(lay.count()):
            it = lay.itemAt(i)
            w = it.widget() if it is not None else None
            if w is None:
                continue
            if _skip_widget(w):
                continue
            bb = _bbox_in(w, ref)
            if bb is None:
                continue
            boxes.append((w.objectName() or w.__class__.__name__, bb))
        for (n1, a), (n2, b) in combinations(boxes, 2):
            if _overlap_area(a, b) <= 0:
                continue
            key = tuple(sorted((n1, n2)))
            if (ref_name, key[0], key[1]) in _KNOWN_OK_OVERLAPS:
                continue
            failures.append(f"layout={ref_name!r} 重叠: {n1}{a} <-> {n2}{b} (面积 {_overlap_area(a, b)})")
    assert not failures, "检测到 gridLayout 内可见控件重叠（重影风险）:\n" + "\n".join(failures)


def test_absolutely_positioned_children_no_overlap(main_window: QMainWindow) -> None:
    """绝对定位子控件重叠检查。

    覆盖父 widget 无 layout（layout() is None）的情形：子控件靠 setGeometry
    绝对摆放（如 groupBox_10 内的 label_75/label_get_cookie_url/label_7 +
    gridLayoutWidget_10）。三处动态注入收口后这些绝对坐标已固化进 .ui，
    本测试防止「增高/下移固化时绝对定位控件互相压叠或溢出」类回归。
    QStackedWidget/QTabWidget 自带 layout 不会进入本分支，其堆叠页天然
    同位不误报。
    """
    _activate_all_tabs(main_window)
    app = QApplication.instance()
    failures: list[str] = []
    for parent in main_window.findChildren(QWidget):
        if parent.layout() is not None:
            continue
        # QMainWindow 的 centralWidget 在 offscreen 下未 resize，其直接子
        # （tabWidget/各分区容器）几何退化，无法做有效重叠校验。
        if parent.objectName() == "centralwidget":
            continue
        # tab 页容器（page_*）含运行时切换显示的日志/列表控件，offscreen 下
        # 默认全 visible 会误报；非本次收口范围，排除。
        if parent.objectName().startswith("page_"):
            continue
        _activate_ancestors(parent)
        try:
            parent.show()
            parent.ensurePolished()
            if app is not None:
                app.processEvents()
        except Exception:
            pass
        pg = parent.geometry()
        if pg.isNull() or pg.width() <= 0 or pg.height() <= 0:
            continue
        ref_name = parent.objectName() or parent.__class__.__name__
        boxes: list[tuple[str, tuple[int, int, int, int]]] = []
        for child in parent.children():
            if not isinstance(child, QWidget):
                continue
            if _skip_widget(child):
                continue
            bb = _bbox_in(child, parent)
            if bb is None:
                continue
            # offscreen 下未激活布局的子控件几何退化为 1x1 占位，跳过
            if bb[2] - bb[0] <= 1 and bb[3] - bb[1] <= 1:
                continue
            boxes.append((child.objectName() or child.__class__.__name__, bb))
        for (n1, a), (n2, b) in combinations(boxes, 2):
            if _overlap_area(a, b) <= 0:
                continue
            key = tuple(sorted((n1, n2)))
            if (ref_name, key[0], key[1]) in _KNOWN_OK_OVERLAPS:
                continue
            failures.append(f"parent={ref_name!r} 绝对定位子重叠: {n1}{a} <-> {n2}{b} (面积 {_overlap_area(a, b)})")
    assert not failures, "检测到绝对定位子控件重叠（重影风险）:\n" + "\n".join(failures)


def _ui_cells(ui_path: str, layout_name: str) -> dict[tuple[int, int], list[str]]:
    """按 .ui 文本解析指定 gridLayout 每个 (row,col) cell 挂的控件名。

    重影根因形态：同一 (row,col) cell 被多个独立 <item row=X col=Y> 块注册
    （pyuic 把两块都 addWidget 进同格，Qt 按顺序叠放 → #123「CF Bypass 代理
    与 超时时间 同格」）。返回 (row,col) -> [widget 名...]，同名可跨块出现。

    绕开 Qt API 盲区：QWidgetItem 无公开 row()/col()、itemAtPosition 对同 cell
    多控件只返回最后一个，包围盒检测读不出前一个（#123 即漏判者），只能按
    .ui 文本逐 <item> 块解析做结构级哨兵。纯 QHBoxLayout 型 item（item 内嵌
    子布局、无直接 widget）不计入，避免误伤设计器合法摆放。
    """
    import re

    text = open(ui_path, encoding="utf-8").read()
    m = re.search(r'<layout class="QGridLayout" name="' + re.escape(layout_name) + r'">', text)
    if m is None:
        return {}
    start = m.start()
    depth = 0
    end = start
    for mm in re.finditer(r"<layout\b|</layout>", text[start:]):
        if mm.group(0) == "</layout>":
            depth -= 1
            if depth == 0:
                end = start + mm.end()
                break
        else:
            depth += 1
    seg = text[start:end]
    cells: dict[tuple[int, int], list[str]] = {}
    for it in re.finditer(r'<item\s+row="(\d+)"\s+column="(\d+)"[^>]*>(.*?)</item>', seg, re.S):
        row, col = int(it.group(1)), int(it.group(2))
        body = it.group(3)
        # 仅取该 item 块**直接子级**（widget/layout 嵌套深度 0）的实控件；
        # 嵌套在 widget 或 layout 内的子控件不算与兄弟 cell 抢位。
        names: list[str] = []
        local_depth = 0
        for sub in re.finditer(r"<widget\b|</widget>|<layout\b|</layout>", body):
            tag = sub.group(0)
            if tag == "<widget" or tag == "<layout":
                if tag == "<widget" and local_depth == 0:
                    nm = re.match(r'<widget class="[^"]*" name="([a-zA-Z0-9_]+)"', body[sub.start() :])
                    if nm:
                        names.append(nm.group(1))
                local_depth += 1
            else:
                local_depth -= 1
        cells.setdefault((row, col), []).extend(names)
    return cells


def test_grid_no_two_items_in_same_cell(main_window: QMainWindow) -> None:
    """同一 gridLayout cell 不允许被多个 <item> 块注册不同实控件（重影根因）。

    历史坑：#123 网络页 8d119d28 新增直连白名单行后漏了下移超时/重试两行的
    row 号，CF Bypass 代理 与 超时时间 两块同占 row6，两个右对齐 label 横向叠
    出重影（「CF Bypass时…」）。QWidgetItem 无公开 row()/col()、itemAtPosition
    读不出同 cell 多控件，必须按 .ui 文本逐 <item> 块解析。判定口径：某
    (row,col) 收集到 >1 个不同直接 widget 名即冲突；同名跨 colspan 块重复
    （如说明文字 label_103 的 colspan=2 同列被两段匹配）去重后不算冲突。
    """
    from pathlib import Path

    ui_path = Path(M.__file__).parent / "MDCx.ui"
    assert ui_path.exists(), f"未找到 {ui_path}"
    text = open(ui_path, encoding="utf-8").read()
    layout_names = re.findall(r'<layout class="QGridLayout" name="([^"]+)">', text)
    failures: list[str] = []
    for name in sorted(set(layout_names)):
        cells = _ui_cells(str(ui_path), name)
        for key, names in cells.items():
            uniq = list(dict.fromkeys(names))
            if len(uniq) > 1:
                failures.append(f"layout={name!r} row{key[0]}col{key[1]} 同 cell 多控件: {uniq}")
    assert not failures, "检测到 gridLayout 同 cell 多控件（重影根因）:\n" + "\n".join(failures)


def test_cf_bypass_proxy_not_same_cell_as_timeout(main_window: QMainWindow) -> None:
    """基准断言：网络页 CF Bypass 代理 与 超时时间 不得同 cell（#123 回归锁）。"""
    from pathlib import Path

    ui_path = Path(M.__file__).parent / "MDCx.ui"
    cells = _ui_cells(str(ui_path), "gridLayout_9")
    by_name: dict[str, tuple[int, int]] = {}
    for key, names in cells.items():
        for nm in names:
            by_name[nm] = key
    assert "label_cf_bypass_proxy" in by_name, "label_cf_bypass_proxy 未注册进 gridLayout_9"
    assert "label_73" in by_name, "label_73(超时时间) 未注册进 gridLayout_9"
    assert by_name["label_cf_bypass_proxy"] != by_name["label_73"], (
        f"CF Bypass 代理{by_name['label_cf_bypass_proxy']} 与 超时时间{by_name['label_73']} 同 cell，将产生重影（#123）"
    )


def test_page_main_info_fields_cleared_of_cover_boxes() -> None:
    """#124/#135 回归锁：主页信息区字段保持设计左列并整体下移，不被封面黑框盖住。

    根因：#102 封面区横向等比放大（cover_scale = main_w/820）后，封面/缩略图框增高
    （底 = 160+220×scale，1920 宽 → 618），下方信息区（简介/标签/日期/导演/制作/
    右列时长/系列/发行 + 分隔线 + 勾选框）停在设计 y，被放大后的黑框纵向压叠。
    #124 曾把信息区整组**右移**到缩略图右侧，导致最小化时字段与「番号/标题/封面」
    不对齐（#135）；现改为保持设计 x（左列对齐）并整体**下移**封面增高量。

    本测试在 offscreen 实例化 controller 后驱动 resize 同步（走真实
    _sync_page_layouts），断言：x 保持设计值（左对齐）、y 下移到封面框下方。
    """
    from mdcx.controllers.main_window import main_window as mw_mod

    _app = QApplication.instance() or QApplication([])
    win = mw_mod.MyMAinWindow()
    win._app = _app  # 挂上 app 引用防 GC
    win.resize(1920, 1020)  # 模拟报告人实机（原生边框最大化）
    _app.processEvents()

    ui = win.Ui
    avail_w = max(1920 - 212, 400)
    cover_scale = avail_w / 820
    cover_bottom = int(160 + 220 * cover_scale)
    info_delta = cover_bottom - 380
    thumb_right = int(580 * cover_scale)
    wide_w = max(thumb_right - 70, 60)
    narrow_w = max(int(220 * cover_scale), 60)
    right_value_x = int(350 * cover_scale)
    right_line_w = max(thumb_right - right_value_x, 60)

    # 横向：左列标签保持设计 x=30（与「番号/标题/封面」对齐）；值/下划线按议题 #141
    # 等比例加长——简介/标签与右列下划线右缘延伸到缩略图右缘，左列窄字段 ×scale。
    for nm in ("label_18", "label_33", "label_13", "label_23", "label_30"):
        assert getattr(ui, nm).x() == 30, f"#135 回归：{nm} 左缘未保持设计 x=30"
    for nm in ("label_outline", "label_tag", "line_6", "line_7"):
        w = getattr(ui, nm)
        assert w.x() == 70, f"#141：{nm} 左缘应为 70"
        assert w.width() == wide_w, f"#141：{nm} 宽度未延伸到缩略图右缘（{w.width()} != {wide_w}）"
        assert w.x() + w.width() == thumb_right, f"#141：{nm} 右缘未到缩略图右缘"
    for nm in ("label_release", "label_director", "label_studio", "line_8", "line_12", "line_13"):
        w = getattr(ui, nm)
        assert w.x() == 70
        assert w.width() == narrow_w, f"#141：{nm} 宽度未按 ×scale 加长"
    for nm in ("label_31", "label_22", "label_24"):
        assert getattr(ui, nm).x() == int(310 * cover_scale), f"#141：{nm} 右列标签未随 ×scale 右移"
    for nm in ("label_series", "label_runtime", "label_publish", "line_9", "line_10", "line_11"):
        w = getattr(ui, nm)
        assert w.x() == right_value_x
        assert w.width() == right_line_w, f"#141：{nm} 宽度未延伸到缩略图右缘"
        assert w.x() + w.width() == thumb_right, f"#141：{nm} 右缘未到缩略图右缘"
    # 纵向：尺寸文字/勾选框 顶须等于封面底（不被压叠）
    for nm in ("label_poster_size", "label_thumb_size", "checkBox_cover"):
        w = getattr(ui, nm)
        assert w.y() == cover_bottom, f"#124 回归：{nm} 顶 {w.y()} 未跟随封面底 {cover_bottom}，纵向压叠"
    # 纵向：信息区首行（设计 y=430）须下移到封面底之下，且偏移量一致
    for nm in ("label_18", "label_outline"):
        w = getattr(ui, nm)
        assert w.y() == 430 + info_delta, f"#135 回归：{nm} 未按封面增高下移（y={w.y()}）"
        assert w.y() >= cover_bottom, f"#135 回归：{nm} 仍在封面框内（y={w.y()} < {cover_bottom}）"
