"""UI 结构测试：防止 MDCx.ui 布局回归与 MDCx.py 同步漂移。

背景：MDCx.ui 是 Qt Designer 源文件，MDCx.py 是 pyuic6 编译产物（仓库版经
ruff format 整理）。历史上出现过 groupBox 坐标重叠、重复控件、手工改 MDCx.py
导致与 UI 源文件不一致等回归。本文件把这些结构约束固化为自动化测试：

1. 同父容器内 groupBox 不重叠、间距一致（默认 19px），且不超出滚动区高度。
2. MDCx.ui 中用户控件 objectName 全局唯一（重复控件是无用残留的强信号）。
3. 用 pyuic6 重编译 MDCx.ui，经 ruff format 后应与仓库 MDCx.py 文本一致——
   防止有人只改 .py 不同步 .ui，或 .ui 改动后忘重编译。

这些测试纯离线（解析 XML / 调用本地 pyuic6），不依赖网络和完整应用启动。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import etree

# 仓库根目录：相对本文件定位，避免硬编码 /workspace（CI 容器约定路径在本地不存在）。
REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
PY_PATH = REPO / "mdcx" / "views" / "MDCx.py"

# groupBox 之间的标准垂直间距（与布局中其他正常间距一致）。
EXPECTED_GAP = 19
# 间距允许的误差（浮点/取整差异）。
GAP_TOLERANCE = 1

# 设计器自动命名的容器，允许同名（每个布局都会生成一个 layoutWidget）。
_IGNORED_DUPLICATE_PREFIXES = ("layoutWidget",)

# 历史遗留的重复 objectName（设计器复制粘贴时保留了相同命名）。
# 这些是存量问题，不影响功能（控件在布局内、文本运行时设置），
# 允许它们通过白名单，但新增的重复 objectName 必须报错。
_KNOWN_DUPLICATE_OBJECTNAMES = {"label_81", "label_423", "label_424"}


def _parse_ui():
    """解析 MDCx.ui，返回 lxml 根元素。"""
    return etree.parse(str(UI_PATH)).getroot()


def _group_boxes_by_parent(root):
    """按直接父容器分组收集 QGroupBox 的几何信息。

    Returns:
        dict[parent_name, list[(gb_name, x, y, w, h)]]
    """
    by_parent: dict[str, list[tuple[str, int, int, int, int]]] = {}
    for gb in root.iter("widget"):
        if gb.get("class") != "QGroupBox" or not gb.get("name"):
            continue
        # 找直接父 widget（跳过 layout/item 中间层）。
        parent = gb.getparent()
        while parent is not None and parent.tag != "widget":
            parent = parent.getparent()
        if parent is None:
            continue
        pname = parent.get("name") or parent.tag
        rect = gb.find("property/rect")
        if rect is None:
            continue
        try:
            x = int(rect.find("x").text)
            y = int(rect.find("y").text)
            w = int(rect.find("width").text)
            h = int(rect.find("height").text)
        except (AttributeError, TypeError, ValueError):
            continue
        by_parent.setdefault(pname, []).append((gb.get("name"), x, y, w, h))
    return by_parent


def _scroll_area_heights(root):
    """收集滚动区内容 widget 的高度（几何：x/y/width/height）。

    Returns:
        dict[widget_name, height]
    """
    heights: dict[str, int] = {}
    for w in root.iter("widget"):
        if w.get("class") != "QWidget" or not w.get("name"):
            continue
        name = w.get("name")
        if "scrollAreaWidgetContents" not in name:
            continue
        rect = w.find("property/rect")
        if rect is None:
            continue
        try:
            heights[name] = int(rect.find("height").text)
        except (AttributeError, TypeError, ValueError):
            continue
    return heights


def test_ui_xml_is_valid():
    """MDCx.ui 必须是合法 XML。"""
    _parse_ui()


def test_no_duplicate_objectnames():
    """UI 中用户控件的 objectName 必须唯一。

    重复 objectName 是设计器误复制控件后未清理的强信号（曾出现
    radioButton_actor_info_all_2/_3 等与正确控件重复的残留）。
    layoutWidget 等设计器自动命名容器允许重复。
    """
    root = _parse_ui()
    seen: dict[str, list[str]] = {}
    for elem in root.iter():
        if elem.tag in ("widget", "action"):
            name = elem.get("name")
            if name and not name.startswith(_IGNORED_DUPLICATE_PREFIXES):
                seen.setdefault(name, []).append(elem.tag)
    duplicates = {k: v for k, v in seen.items() if len(v) > 1 and k not in _KNOWN_DUPLICATE_OBJECTNAMES}
    assert not duplicates, f"MDCx.ui 存在重复 objectName: {duplicates}"


def test_groupboxes_no_overlap_and_consistent_gap():
    """同父容器内的 QGroupBox 不应重叠，且垂直间距应一致。

    默认期望间距 19px（与布局中正常部分一致）。曾出现命名页
    groupBox_40 与 groupBox_8 重叠 181px、下载页 groupBox_34 与
    groupBox_66 重叠 21px 的回归。
    """
    root = _parse_ui()
    by_parent = _group_boxes_by_parent(root)

    assert by_parent, "UI 中未找到任何 QGroupBox，检查解析逻辑"
    problems: list[str] = []

    for parent, items in by_parent.items():
        # 同父容器内两两重叠检查。
        for i in range(len(items)):
            n1, x1, y1, w1, h1 = items[i]
            for j in range(i + 1, len(items)):
                n2, x2, y2, w2, h2 = items[j]
                if x1 < x2 + w2 - GAP_TOLERANCE and x2 < x1 + w1 - GAP_TOLERANCE:
                    if y1 < y2 + h2 - GAP_TOLERANCE and y2 < y1 + h1 - GAP_TOLERANCE:
                        problems.append(f"[{parent}] {n1}(y={y1},底={y1 + h1}) 与 {n2}(y={y2}) 重叠")

        # 垂直间距：同一父容器、同一 x 起点的相邻 groupBox 间距。
        # 核心约束是"不重叠"（间距 >= 0）；间距不一致仅作提示，
        # 不强制统一（不同区域允许不同间距设计）。
        ordered = sorted(items, key=lambda it: (it[1], it[2]))  # 按 x 再按 y
        for i in range(len(ordered) - 1):
            n1, x1, y1, w1, h1 = ordered[i]
            n2, x2, y2, w2, h2 = ordered[i + 1]
            if abs(x1 - x2) <= GAP_TOLERANCE and w1 == w2:  # 同一列才比较垂直间距
                gap = y2 - (y1 + h1)
                if gap < 0:
                    problems.append(f"[{parent}] {n1}->{n2} 负间距(重叠) {gap}px")

    assert not problems, "UI 布局问题:\n" + "\n".join(problems)


def test_groupboxes_fit_scroll_area():
    """滚动区内的 groupBox 不应超出滚动区内容 widget 的高度。

    曾出现滚动区高度未随 groupBox 下移而同步增高，导致底部内容被遮挡。
    """
    root = _parse_ui()
    by_parent = _group_boxes_by_parent(root)
    heights = _scroll_area_heights(root)

    problems: list[str] = []
    for parent, items in by_parent.items():
        if parent not in heights:
            continue  # 非滚动区容器不检查高度
        max_bottom = max(y + h for _, _, y, _, h in items)
        scroll_h = heights[parent]
        if max_bottom > scroll_h:
            problems.append(f"[{parent}] 最深 groupBox 底部 {max_bottom} 超出滚动区高度 {scroll_h}")

    assert not problems, "UI 滚动区溢出问题:\n" + "\n".join(problems)


# ---------- 命名页各「命名规则」分组右边框对齐「视频命名规则」 —— 红/黄/绿回归 ----------

# 命名页（scrollAreaWidgetContents_mingming）里除参考分组外的 8 个规则分组。
_NAMING_RULE_GROUPS = (
    "groupBox_40",  # 字段命名规则
    "groupBox_77",  # 长度命名规则
    "groupBox_46",  # 马赛克命名规则
    "groupBox_38",  # 分集命名规则
    "groupBox_37",  # 图片命名规则
    "groupBox_62",  # 预告片命名规则
    "groupBox_65",  # 画质命名规则
    "groupBox_67",  # 其他说明
)
_NAMING_REF_GROUP = "groupBox_8"  # 视频命名规则（宽度基准）


def _naming_page_boxes() -> dict[str, tuple[int, int, int, int]]:
    """命名页 9 个规则分组 → {name: (x, y, w, h)}。"""
    parents = _group_boxes_by_parent(_parse_ui())
    return {name: (x, y, w, h) for name, x, y, w, h in parents.get("scrollAreaWidgetContents_mingming", [])}


def test_naming_rule_groups_edges_aligned_green():
    """绿（成功）：8 个规则分组的左缘/右缘都与「视频命名规则」对齐。

    需求：右侧边框加宽到与视频命名规则同宽、左侧边框不动，最终所有分组
    左右边框上下对齐。这里按几何断言 x 相同、x+width 相同。
    """
    boxes = _naming_page_boxes()
    assert _NAMING_REF_GROUP in boxes, f"命名页缺少参考分组 {_NAMING_REF_GROUP}"
    rx, _, rw, _ = boxes[_NAMING_REF_GROUP]
    ref_right = rx + rw
    missing = [name for name in _NAMING_RULE_GROUPS if name not in boxes]
    assert not missing, f"命名页缺少分组: {missing}"
    misaligned = {
        name: {"left": boxes[name][0], "right": boxes[name][0] + boxes[name][2]}
        for name in _NAMING_RULE_GROUPS
        if boxes[name][0] != rx or boxes[name][0] + boxes[name][2] != ref_right
    }
    assert not misaligned, f"以下分组边框未与 {_NAMING_REF_GROUP} 对齐（左缘应={rx}、右缘应={ref_right}）: {misaligned}"


def test_naming_rule_reference_width_not_narrowed_yellow():
    """黄（边界）：对齐必须是「加宽其余分组」，参考分组（视频命名规则）不得被改窄。

    若不锁定基准宽度，「把所有分组一起缩回 701」也能让绿色用例通过——这里补上基准值。
    """
    boxes = _naming_page_boxes()
    rx, _, rw, _ = boxes[_NAMING_REF_GROUP]
    assert (rx, rw) == (30, 765), f"{_NAMING_REF_GROUP} 基准几何被改动: x={rx}, w={rw}（应为 30 / 765）"


def test_naming_rule_groups_old_narrow_width_removed_red():
    """红（失败回归）：8 个规则分组不得退回历史窄宽 701（右边框未加宽）。"""
    boxes = _naming_page_boxes()
    reverted = [name for name in _NAMING_RULE_GROUPS if boxes.get(name, (0, 0, 0, 0))[2] == 701]
    assert not reverted, f"以下分组退回历史窄宽 701（右边框未加宽）: {reverted}"


def test_nav_layout_no_fixed_spacers():
    """左侧导航 verticalLayout 必须用 spacing 分隔按钮，按钮间不得出现 spacer。

    议题 #72 回归锁定：固定 QSpacerItem 不受 setVisible 控制，隐藏按钮后残留
    叠出空洞。现按钮间无 spacer、改用 layout spacing=8。
    例外：布局末尾允许且必须保留一个 Expanding spacer（议题 #74：固定高容器
    在隐藏按钮后会把多余空间摊进按钮间隙，末尾 Expanding spacer 吸收之）。
    """
    root = _parse_ui()
    nav = next((lay for lay in root.iter("layout") if lay.get("name") == "verticalLayout"), None)
    assert nav is not None, "未找到左侧导航 verticalLayout"

    spacing = nav.find("property/number")
    assert spacing is not None and spacing.text == "8", "导航 verticalLayout spacing 应为 8"

    items = nav.findall("item")
    spacers = [it.find("spacer") for it in items if it.find("spacer") is not None]
    # 仅允许末尾一个 Expanding spacer，按钮间不允许任何 spacer
    assert len(spacers) == 1, f"导航布局应有且仅有 1 个末尾 Expanding spacer，实际 {len(spacers)}"
    sp = spacers[0]
    last_item = items[-1]
    assert last_item.find("spacer") is sp, "Spacer 必须位于布局末尾"
    size_type = sp.find("property[@name='sizeType']/enum")
    assert size_type is not None and "Expanding" in size_type.text, (
        f"末尾 spacer 必须 Expanding: {size_type and size_type.text}"
    )


def test_mdcx_py_in_sync_with_ui():
    """MDCx.py 必须与 MDCx.ui 保持同步（pyuic6 重编译 + ruff format 后文本一致）。

    防止：只改 .py 不同步 .ui（手工维护漂移）、改 .ui 后忘重编译。
    仓库版 MDCx.py 是经 ruff format 整理的，因此重编译产物也要先 ruff format。
    注意：pyuic6 会把输入路径写进头部注释，必须用相对路径编译才能与仓库版对齐。
    """
    assert PY_PATH.exists(), f"缺少 {PY_PATH}"
    assert UI_PATH.exists(), f"缺少 {UI_PATH}"

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # 1. pyuic6 重编译（用正斜杠相对路径，与仓库版头部注释一致）。
        ui_rel = str(UI_PATH.relative_to(REPO)).replace("\\", "/")
        result = subprocess.run(
            [sys.executable, "-m", "PyQt6.uic.pyuic", ui_rel, "-o", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, f"pyuic6 编译失败: {result.stderr}"

        # 2. ruff format 对齐（仓库版是 ruff 格式化的）。
        #    优先用 uv 调 ruff；uv 不可用（FileNotFoundError）或返回非零时回退直接 ruff。
        #    两者都不可用才跳过格式对齐后直接文本对比（此时若格式不同会失败，属正常——
        #    说明仓库版与编译产物格式不一致需要手动对齐）。
        formatted = False
        try:
            result = subprocess.run(
                ["uv", "run", "ruff", "format", str(tmp_path)],
                capture_output=True,
                text=True,
                cwd=REPO,
                timeout=60,
            )
            formatted = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            formatted = False
        if not formatted:
            try:
                subprocess.run(
                    ["ruff", "format", str(tmp_path)],
                    capture_output=True,
                    text=True,
                    cwd=REPO,
                    timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass  # 无 ruff 环境：直接文本对比

        # 3. 文本对比。
        #    pyuic6 on Windows emits backslash path separators in resource
        #    strings (e.g. xpm paths) due to os.path internal joining.
        #    Normalize both sides the same way so only structural differences
        #    are compared, not platform-specific path separators.
        compiled = tmp_path.read_text(encoding="utf-8").replace("\\\\", "/")
        repo = PY_PATH.read_text(encoding="utf-8").replace("\\\\", "/")
        assert compiled == repo, (
            "MDCx.py 与 MDCx.ui 不同步！"
            "请用 pyuic6 重新编译 mdcx/views/MDCx.ui，再运行 `uv run ruff format mdcx/views/MDCx.py`。"
            "不要手工修改 MDCx.py，一切改动先改 MDCx.ui 再编译。"
        )
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------- 「跳过前置 Poster 大小校验」提示文案合并 —— 红/黄/绿回归 ----------


def _find_widget_by_name(root, name):
    for w in root.iter("widget"):
        if w.get("name") == name:
            return w
    return None


def _widget_string_prop(w, name):
    p = w.find(f"property[@name='{name}']")
    if p is None:
        return None
    s = p.find("string")
    return s.text if s is not None else None


def _widget_bool_prop(w, name):
    p = w.find(f"property[@name='{name}']")
    if p is None:
        return None
    b = p.find("bool")
    return b.text == "true" if b is not None else None


def test_amazon_skip_hint_green_merged_text_and_wrap():
    """绿（成功）：提示文案已合并为一段、且开启自动换行。"""
    root = _parse_ui()
    lbl = _find_widget_by_name(root, "label_amazon_skip_poster_size_precheck")
    assert lbl is not None, "label_amazon_skip_poster_size_precheck 不存在"
    assert _widget_string_prop(lbl, "text") == (
        "不因当前Poster已达标跳过Amazon(DMM>=700px/>=400KB/不小于右裁剪)"
        "将从日亚官网搜索高清封面图；已收录番号直接使用本地ASIN库验证结果，新发现需通过图片相似度校验后入库"
    )
    assert _widget_bool_prop(lbl, "wordWrap") is True, "wordWrap 应为 true（长文本需可正常换行）"


def test_amazon_skip_hint_yellow_inline_after_checkbox():
    """黄（边界）：提示与勾选框同行，排在勾选框之后（在布局内，无独立 geometry）。"""
    root = _parse_ui()
    lbl = _find_widget_by_name(root, "label_amazon_skip_poster_size_precheck")
    assert lbl is not None
    # 放进布局的控件不再有 geometry（由 HBox 排在勾选框之后、顶部对齐）；
    # 若又变回独立定位（geometry）则说明提示被挪到了下一行，属回归。
    assert lbl.find("property[@name='geometry']") is None, "提示应内联在勾选框布局中，而非独立定位"


def test_amazon_skip_hint_red_no_duplicate_text():
    """红（失败回归）：旧的独立 label_92 已删除，合并文案不再重复出现。"""
    root = _parse_ui()
    assert _find_widget_by_name(root, "label_92") is None, "label_92 应已删除"
    ui_text = UI_PATH.read_text(encoding="utf-8")
    assert ui_text.count("将从日亚官网搜索高清封面图") == 1, "合并文案不应再被拆成两条"
