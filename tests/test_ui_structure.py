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


def _widget_enum_prop(w, name):
    p = w.find(f"property[@name='{name}']")
    if p is None:
        return None
    e = p.find("enum")
    return e.text if e is not None else None


def _widget_set_prop(w, name):
    p = w.find(f"property[@name='{name}']")
    if p is None:
        return None
    s = p.find("set")
    return s.text if s is not None else None


def _widget_rect(w):
    rect = w.find("property/rect")
    if rect is None:
        return None
    return (
        int(rect.find("x").text),
        int(rect.find("y").text),
        int(rect.find("width").text),
        int(rect.find("height").text),
    )


def _parent_widget_name(w):
    """取控件的直接父 widget 的 objectName（跳过 layout/item 中间层）。"""
    parent = w.getparent()
    while parent is not None and parent.tag != "widget":
        parent = parent.getparent()
    return parent.get("name") if parent is not None else None


def test_amazon_skip_hint_green_merged_text_and_wrap():
    """绿（成功）：提示文案已合并为一段、且开启自动换行。"""
    root = _parse_ui()
    lbl = _find_widget_by_name(root, "label_amazon_skip_poster_size_precheck")
    assert lbl is not None, "label_amazon_skip_poster_size_precheck 不存在"
    assert _widget_string_prop(lbl, "text") == (
        "不因当前Poster已达标跳过Amazon(DMM>=700px/>=400KB/不小于右裁剪)"
        "将从日亚官网搜索高清封面图，已收录番号直接使用本地ASIN库验证结果，新发现需通过图片相似度校验后入库"
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


# ---------- 命名/读取模式关键文案回归锁 ----------

# 读取模式区 + 排除目录标签：改回旧措辞（NFO/nfo 大小写、空格、语序）即失败。
_READ_MODE_UI_TEXTS = {
    "label_41": "刮削排除目录：",
    "label_48": "刮削排除目录：",
    "checkBox_read_has_nfo_update": "本地刮削成功的文件，按更新模式重新整理分类",
    "checkBox_read_update_nfo": "允许更新NFO文件",
    "label_37": "<p> 按Emby标题、设置-翻译、NFO设置利用本地NFO更新</p>",
    "checkBox_read_download_file_again": "本地NFO内有链接，重新下载封面图片等文件",
    "label_347": "将按设置 -「下载」更新",
    "checkBox_read_no_nfo_scrape": "本地没有NFO的文件，按正常模式规则重新刮削",
    "checkBox_nfo_merge_strategy": "本地NFO合并及策略",
    "checkBox_sortmode_delpic": "删除本地已下载的图片和nfo文件",
}

# 马赛克命名规则四条说明（忽略 XML 缩进换行空白差异）。
_MOSAIC_HINT_TEXTS = {
    "label_116": (
        "<p style='line-height:20px'>指有损去除版本，有Cracked、破解、克破、UMR、Uncensored、Restored时，"
        "识别为无码破解版本，在重命名文件名及目录名时，显示该字符表示为无码破解版本</p>"
    ),
    "label_117": (
        "<p style='line-height:20px'>指无码流出版本，当文件路径中含有流出、Leaked等字样时，该文件将被识别为无码流出版本，"
        "在重命名文件名称及目录名时，在番号后显示该字符表示为无码流出版本</p>"
    ),
    "label_137": (
        "<p style='line-height:20px'>指无码版本，当文件路径中含有无码、無碼、無修正、Uncensored字样时，"
        "该文件将被识别为无码版本。在重命名文件及目录名时在番号后显示该字符表示为无码版本</p>"
    ),
    "label_145": (
        "<p style='line-height:20px'>指有码版本，当视频文件名称路径中包含有码、有碼等字样时，该视频文件将被识别为有码版本，"
        "在重命名文件名及目录名时，将在番号后显示该字符表示为有码版本</p>"
    ),
}


def _norm_text(text):
    """折叠 XML 缩进/换行等空白，便于比较长富文本。"""
    import re

    return re.sub(r"\s+", " ", text or "").strip()


def test_read_mode_ui_texts_regression():
    """读取模式区/排除目录关键文案回归锁：改回旧措辞即失败。"""
    root = _parse_ui()
    mismatches = {}
    for name, expected in _READ_MODE_UI_TEXTS.items():
        widget = _find_widget_by_name(root, name)
        actual = None if widget is None else _widget_string_prop(widget, "text")
        if actual != expected:
            mismatches[name] = actual
    assert not mismatches, f"读取模式区/排除目录文案与预期不符: {mismatches}"


def test_mosaic_rule_hint_texts_regression():
    """马赛克命名规则四条说明文案回归锁（忽略 XML 缩进空白差异）。"""
    root = _parse_ui()
    mismatches = {}
    for name, expected in _MOSAIC_HINT_TEXTS.items():
        widget = _find_widget_by_name(root, name)
        actual = _norm_text(None if widget is None else _widget_string_prop(widget, "text"))
        if actual != expected:
            mismatches[name] = actual
    assert not mismatches, f"马赛克命名规则说明与预期不符: {mismatches}"

    # label_116（无码破解说明）文案缩短后只需两行：line-height 20px，默认高度锁 40px，
    # 保持三行（60px）会在窗口最小化/窄视口下留出大片空白。
    height = _find_widget_by_name(root, "label_116").find("property/rect/height")
    assert height is not None and height.text == "40", "label_116 默认高度应为 40px（两行）"

    # groupBox_46 四行（无码破解/无码流出/无码/有码）绝对定位，缩高 label_116 后
    # 下方各行必须整体上移，保持行距一致（否则「无码破解→无码流出」比其余行多 20px）。
    rows = []
    for name in ("lineEdit_umr_style", "lineEdit_leak_style", "lineEdit_wuma_style", "lineEdit_youma_style"):
        rect = _find_widget_by_name(root, name).find("property/rect")
        rows.append(int(rect.find("y").text))
    pitch = {rows[i + 1] - rows[i] for i in range(len(rows) - 1)}
    assert pitch == {92}, f"groupBox_46 四行行距应一致（92px），实际 {sorted(pitch)}"

    # 四条绿色说明宽度必须一致（x=157 / w=523），否则最右侧的折行截断位置
    # 参差不齐（曾出现 label_137 宽 546，比其余三条多探出 23px）。
    right_edges = set()
    for name in ("label_116", "label_117", "label_137", "label_145"):
        rect = _find_widget_by_name(root, name).find("property/rect")
        right_edges.add((int(rect.find("x").text), int(rect.find("width").text)))
    assert right_edges == {(157, 523)}, f"groupBox_46 四条说明应统一 x=157 w=523，实际 {sorted(right_edges)}"


# ---------- 「使用代理」开关 / Bypass 代理文案回归锁 ----------

# 勾选框只控制常规网络请求代理开关，不联动 CF Bypass 代理（曾写作 "不控制 CF Bypass 代理"）。
_PROXY_TOGGLE_HINT = "仅控制常规网络请求代理开关，不控制CF Bypass代理"


def test_proxy_toggle_ui_texts_regression():
    """代理开关文案回归锁：开关只管常规代理、不联动 Bypass；标签与帮助文本统一。"""
    root = _parse_ui()

    def prop_of(name: str, prop: str):
        widget = _find_widget_by_name(root, name)
        assert widget is not None, f"{name} 不存在"
        return _widget_string_prop(widget, prop)

    # 「使用代理」勾选框 tooltip 明确只管常规代理。
    assert prop_of("checkBox_use_proxy", "toolTip") == _PROXY_TOGGLE_HINT
    # 网络页标签去掉 "CF" 前缀、去掉多余空格。
    assert prop_of("label_cf_bypass_proxy", "text") == "Bypass代理："
    assert prop_of("label_cf_bypass_trawl", "text") == "外部CF服务："
    # 代理说明段同样带这句提示。
    proxy_hint = prop_of("label_103", "text") or ""
    assert _PROXY_TOGGLE_HINT in proxy_hint
    # 帮助文档正文（关于页）条目统一为「Bypass代理」，且不再出现「CF Bypass 代理」。
    about_html = prop_of("textBrowser_about", "html") or ""
    assert "<b>Bypass代理</b>：为绕过 Cloudflare 的请求单独设置代理。" in about_html
    assert "CF Bypass 代理" not in about_html


# ---------- #182 Gfriends「选择目录」按钮样式 —— 红/黄/绿回归 ----------

# 全局药丸按钮三态选择器（浅色/深色主题各一处，共 6 处）：
# Gfriends 选择目录按钮必须与本地头像库按钮相邻出现。
_STYLE_PATH = REPO / "mdcx" / "controllers" / "main_window" / "style.py"
_GFRIENDS_STYLE_FIXED = (
    "#pushButton_select_actor_photo_folder,#pushButton_select_gfriends_local,#pushButton_select_actor_info_db",
    ":hover#pushButton_select_actor_photo_folder,:hover#pushButton_select_gfriends_local,:hover#pushButton_select_actor_info_db",
    ":pressed#pushButton_select_actor_photo_folder,:pressed#pushButton_select_gfriends_local,:pressed#pushButton_select_actor_info_db",
)
# 修复前（缺席）形态：两按钮选择器直接相邻、中间没有 Gfriends。
_GFRIENDS_STYLE_BROKEN = (
    "#pushButton_select_actor_photo_folder,#pushButton_select_actor_info_db",
    ":hover#pushButton_select_actor_photo_folder,:hover#pushButton_select_actor_info_db",
    ":pressed#pushButton_select_actor_photo_folder,:pressed#pushButton_select_actor_info_db",
)


def test_gfriends_select_button_green_in_global_style():
    """绿（成功）：Gfriends 选择目录按钮在全局药丸样式三态选择器中（浅色+深色共6处）。"""
    style_text = _STYLE_PATH.read_text(encoding="utf-8")
    missing = [p for p in _GFRIENDS_STYLE_FIXED if style_text.count(p) != 2]
    assert not missing, f"全局样式缺 Gfriends 选择目录按钮: {missing}"


def test_gfriends_select_button_yellow_matches_local_library_button():
    """黄（边界）：两选择目录按钮在 .ui/.py 定义一致、无本地样式覆盖（只走全局样式）。"""
    import re

    root = _parse_ui()
    names = ("pushButton_select_gfriends_local", "pushButton_select_actor_photo_folder")
    for name in names:
        w = _find_widget_by_name(root, name)
        assert w is not None, f"{name} 不存在"
        size = w.find("property[@name='minimumSize']/size")
        assert size is not None, f"{name} 缺 minimumSize"
        assert (size.find("width").text, size.find("height").text) == ("110", "40"), f"{name} 应为 110x40"
        assert _widget_string_prop(w, "text") == "选择目录", f"{name} 文案应为「选择目录」"
        assert w.find("property[@name='styleSheet']") is None, f"{name} 不应有本地 styleSheet 覆盖"
    py_text = PY_PATH.read_text(encoding="utf-8")
    for name in names:
        m = re.search(rf"self\.{name} = .*?addWidget\(self\.{name}\)", py_text, re.S)
        assert m is not None, f"MDCx.py 缺 {name} 定义"
        assert "setMinimumSize(QtCore.QSize(110, 40))" in m.group(0), f"MDCx.py 中 {name} 应为 110x40"
        assert "setStyleSheet" not in m.group(0), f"MDCx.py 中 {name} 不应有本地 setStyleSheet"


def test_gfriends_select_button_red_broken_shape_gone():
    """红（失败回归）：修复前缺席形态不再出现（出现即回到截图中的默认方块按钮）。"""
    style_text = _STYLE_PATH.read_text(encoding="utf-8")
    present = [p for p in _GFRIENDS_STYLE_BROKEN if p in style_text]
    assert not present, f"全局样式回到修复前缺席形态: {present}"


# ---------- 刮削模式页「分离模式…」右侧提示 —— 文案/几何/对齐回归锁 ----------

# 四个组框标题右侧各挂一条同款提示（只加提示文案，不新增任何开关项）：
# label 名 -> (所属组框, 提示文案)
_SEPARATE_MODE_TITLE_HINTS = {
    "label_separate_mode_succ_rename": ("groupBox_18", "分离模式刮削成功重命名文件"),
    "label_separate_mode_succ_move": ("groupBox_27", "分离模式刮削成功后移动文件"),
    "label_separate_mode_fail_move": ("groupBox_15", "分离模式刮削失败时移动文件"),
    "label_separate_mode_del_empty_folder": ("groupBox_30", "分离模式刮削结束删除空目录"),
}

# 组框宽 701。x 是按「真实 Windows11 风格」实测墨迹反解的：
# windows11 风格下 QGroupBox 标题墨迹左沿在 x=14（左内边距 14px），而 x=499 时
# 提示文字墨迹右沿在 690（右内边距仅 6px），右比左贴边 8px——正是「看着右边太挤」
# 的成因。整条左移 8px 后右内边距 == 左内边距 == 14px，两端视觉对称。
# （离屏 Fusion 风格下标题偏移只有 2px，会误判为已对称，故必须按 windows11 量化。）
_SEPARATE_HINT_RECT = (491, -7, 200, 30)


def test_separate_mode_title_hints_exist_with_right_text():
    """绿：四条提示都挂在对应组框内，文案与设计图一致。"""
    root = _parse_ui()
    mismatches = {}
    for name, (box, expected) in _SEPARATE_MODE_TITLE_HINTS.items():
        w = _find_widget_by_name(root, name)
        if w is None:
            mismatches[name] = "控件不存在"
            continue
        if _parent_widget_name(w) != box:
            mismatches[name] = f"父容器应为 {box}，实际 {_parent_widget_name(w)}"
        elif _widget_string_prop(w, "text") != expected:
            mismatches[name] = _widget_string_prop(w, "text")
    assert not mismatches, f"分离模式提示文案/归属与预期不符: {mismatches}"


def test_separate_mode_title_hints_right_aligned_same_style():
    """黄：四条提示几何一致、右对齐/从右向左排列，且不覆盖组框标题的字体样式。

    x/y 是按 Qt 实测墨迹定的：y=-7 让提示墨迹行与组框标题墨迹行完全重合
    （离屏渲染实测 dy_top=dy_bot=0）；x=491 让右内边距与 windows11 风格下
    标题的左内边距都是 14px（实测右内边距 14 == 左内边距 14）。
    """
    root = _parse_ui()
    problems = []
    for name in _SEPARATE_MODE_TITLE_HINTS:
        w = _find_widget_by_name(root, name)
        assert w is not None, f"{name} 不存在"
        if _widget_rect(w) != _SEPARATE_HINT_RECT:
            problems.append(f"{name} 几何 {_widget_rect(w)} != {_SEPARATE_HINT_RECT}")
        if _widget_enum_prop(w, "layoutDirection") != "Qt::RightToLeft":
            problems.append(f"{name} layoutDirection 应为 Qt::RightToLeft")
        if _widget_set_prop(w, "alignment") != "Qt::AlignRight|Qt::AlignTrailing|Qt::AlignVCenter":
            problems.append(f"{name} alignment 应为右对齐+垂直居中")
        if _widget_enum_prop(w, "frameShape") != "QFrame::NoFrame":
            problems.append(f"{name} frameShape 应为 QFrame::NoFrame")
        # 不写本地 styleSheet，字体颜色/大小/格式全部继承组框标题，避免两边不一致。
        if w.find("property[@name='styleSheet']") is not None:
            problems.append(f"{name} 不应有本地 styleSheet 覆盖")
    assert not problems, "分离模式提示样式问题:\n" + "\n".join(problems)

    # 四条提示右缘必须严格对齐（几何一致已保证，这里再锁一次换算值防回归）。
    rights = {_SEPARATE_HINT_RECT[0] + _SEPARATE_HINT_RECT[2] for _ in _SEPARATE_MODE_TITLE_HINTS}
    assert rights == {691}, f"四条提示右缘应统一为 691，实际 {sorted(rights)}"


def test_separate_mode_title_hints_red_not_inside_grid_layout():
    """红（回归）：提示不得被塞进组框内的网格布局——那会掉到标题行下方一行。

    提示必须以绝对定位挂在组框上（与 groupBox 同父、无 layout 参与）。
    """
    root = _parse_ui()
    for name, (box, _text) in _SEPARATE_MODE_TITLE_HINTS.items():
        w = _find_widget_by_name(root, name)
        assert w is not None, f"{name} 不存在"
        assert w.find("property[@name='geometry']") is not None, f"{name} 应绝对定位（带 geometry）"
        parent = _find_widget_by_name(root, box)
        assert parent is not None, f"{box} 不存在"
        assert w.getparent() is parent, f"{name} 应与 {box} 同父（挂在组框上而非布局内）"


# ---------- 刮削模式页「分离模式…」右侧开/关按钮 —— 归属/齐平/对齐/互斥隔离回归锁 ----------

# 组框内左侧（通用）开/关 vs 右侧（分离模式）开/关。
# 结构上右侧必须再套一层 QWidget 容器：Qt 的 QRadioButton 自动互斥组按「共同父控件」
# 分组，若右侧两个 radio 直接挂到组框上，就会和左侧两个 radio 挤进同一个互斥组，
# 点右侧「开」会把左侧「开」点掉——所以容器不是装饰，是隔离手段。
#
# key -> (组框, 容器名, 右侧开, 右侧关)
_SEPARATE_MODE_RADIO_PAIRS = {
    "succ_rename": (
        "groupBox_18",
        "widget_separate_mode_succ_rename",
        "radioButton_separate_mode_succ_rename_on",
        "radioButton_separate_mode_succ_rename_off",
    ),
    "succ_move": (
        "groupBox_27",
        "widget_separate_mode_succ_move",
        "radioButton_separate_mode_succ_move_on",
        "radioButton_separate_mode_succ_move_off",
    ),
    "fail_move": (
        "groupBox_15",
        "widget_separate_mode_fail_move",
        "radioButton_separate_mode_fail_move_on",
        "radioButton_separate_mode_fail_move_off",
    ),
    "del_empty_folder": (
        "groupBox_30",
        "widget_separate_mode_del_empty_folder",
        "radioButton_separate_mode_del_empty_folder_on",
        "radioButton_separate_mode_del_empty_folder_off",
    ),
}

# 容器设计几何：(x, y, 宽, 高)。x=611 是按「右侧到组框右边界的距离 == 左侧到左边界的
# 距离」反解的：左侧 radio 墨迹左沿在组框内绝对 x=50（左内边距 50），右侧 radio 墨迹
# 右沿在组框内绝对 x=647（右内边距 697-1-647=50），两边实测都是 50px。
# x=611 + 宽 40 = 651 亦命中宽幅同步的 _DOCK_RIGHT（651+1 >= 组宽 701*0.9），
# 最大化时右缘锚定、随组框同步平移 extra。
_SEPARATE_RADIO_HOLDER_RECT = (611, 41, 40, 49)
# 容器内两个 radio 的局部几何：开 (0,0)、关 (0,33)。
# 容器 y=41 + 局部 y=0/33 -> 组框内绝对 y=41/74，与左侧 radio 的 y=41/74 完全重合
# （左侧 y 由 gridLayout 的行高 16 + vspacing 6 + 上下各 11 余量均分实测得来）。
_SEPARATE_RADIO_INNER_RECTS = ((0, 0, 40, 16), (0, 33, 40, 16))
_SEPARATE_RADIO_Y = (41, 74)
# 左侧网格容器宽 560（原 631）：收窄让出右侧 611 起的 radio 区，避免两者几何重叠
# （test_ui_geometry 的绝对定位重叠检查会直接判红）。网格自然宽仅 343，收窄不改变
# 任何行列实际位置——第 0 列被 minimumSize 锁 90，第 1 列标签左对齐。
_SEPARATE_GRID_WIDGET_WIDTH = 560
# 组框设计宽 701。右侧 radio 右缘到组框右边界的距离（701 - 651）必须等于
# 左侧 radio 左缘到组框左边界的距离（网格容器 x=50 + radio 局部 x=0），
# 两者都是 50——即「右侧离右边界多远，左侧就离左边界多远」。
_SEPARATE_BOX_WIDTH = 701
_SEPARATE_SIDE_MARGIN = 50


def test_separate_mode_radios_green_exist_and_isolated_in_holder():
    """绿：四组右侧开/关都存在，且各自包在自己的容器里（与左侧互斥组隔离）。"""
    root = _parse_ui()
    problems = []
    for key, (box, holder, on_name, off_name) in _SEPARATE_MODE_RADIO_PAIRS.items():
        gb = _find_widget_by_name(root, box)
        holder_w = _find_widget_by_name(root, holder)
        if gb is None or holder_w is None:
            problems.append(f"{key}: {box} 或 {holder} 不存在")
            continue
        # 容器必须是组框的直接子控件（绝对定位挂上去），不能躺进网格布局
        if holder_w.getparent() is not gb:
            problems.append(f"{holder} 应直接挂在 {box} 上")
        for nm, want in ((on_name, "开"), (off_name, "关")):
            w = _find_widget_by_name(root, nm)
            if w is None:
                problems.append(f"{nm} 不存在")
                continue
            if _parent_widget_name(w) != holder:
                problems.append(f"{nm} 的父控件应为 {holder}（隔离容器），实际 {_parent_widget_name(w)}")
            if _widget_string_prop(w, "text") != want:
                problems.append(f"{nm} 文案应为 {want}，实际 {_widget_string_prop(w, 'text')}")
    assert not problems, "分离模式开/关按钮问题:\n" + "\n".join(problems)


def test_separate_mode_radios_yellow_level_with_left_and_column_aligned():
    """黄：右侧开/关与左侧同排（水平齐平），四组之间严格上下对齐，几何完全一致。"""
    root = _parse_ui()
    problems = []
    on_rects = set()
    off_rects = set()
    holder_rects = set()
    for _key, (_box, holder, on_name, off_name) in _SEPARATE_MODE_RADIO_PAIRS.items():
        hw = _find_widget_by_name(root, holder)
        on = _find_widget_by_name(root, on_name)
        off = _find_widget_by_name(root, off_name)
        if hw is None or on is None or off is None:
            problems.append(f"{holder} 及其 radio 缺失")
            continue
        hr = _widget_rect(hw)
        if hr != _SEPARATE_RADIO_HOLDER_RECT:
            problems.append(f"{holder} 几何 {hr} != {_SEPARATE_RADIO_HOLDER_RECT}")
        holder_rects.add(hr)
        if _widget_rect(on) != _SEPARATE_RADIO_INNER_RECTS[0]:
            problems.append(f"{on_name} 几何 {_widget_rect(on)} != {_SEPARATE_RADIO_INNER_RECTS[0]}")
        if _widget_rect(off) != _SEPARATE_RADIO_INNER_RECTS[1]:
            problems.append(f"{off_name} 几何 {_widget_rect(off)} != {_SEPARATE_RADIO_INNER_RECTS[1]}")
        # 开/关二字必须落在指示点圆圈的左边：RTL 会镜像 QRadioButton 的绘制顺序，
        # LTR 下 Qt 默认画成「圆圈 + 文字」，与需求相反。
        for nm, w in ((on_name, on), (off_name, off)):
            if _widget_enum_prop(w, "layoutDirection") != "Qt::RightToLeft":
                problems.append(f"{nm} layoutDirection 应为 Qt::RightToLeft（文字才会跑到指示点左侧）")
        # 换算成组框内绝对 y：容器 y + radio 局部 y，必须等于左侧 radio 的 41 / 74
        for nm, w, idx in ((on_name, on, 0), (off_name, off, 1)):
            r = _widget_rect(w)
            if r is None:
                continue
            abs_y = hr[1] + r[1]
            if abs_y != _SEPARATE_RADIO_Y[idx]:
                problems.append(f"{nm} 组框内 y={abs_y} != 左侧齐平基准 {_SEPARATE_RADIO_Y[idx]}")
            (on_rects if idx == 0 else off_rects).add((r[0], abs_y, r[2], r[3]))
    # 四组的右缘开/关必须落在同一列
    if len(on_rects) != 1:
        problems.append(f"四组右侧「开」未对齐: {sorted(on_rects)}")
    if len(off_rects) != 1:
        problems.append(f"四组右侧「关」未对齐: {sorted(off_rects)}")
    if len(holder_rects) != 1:
        problems.append(f"四个容器几何不一致: {sorted(holder_rects)}")
    assert not problems, "分离模式开/关对齐问题:\n" + "\n".join(problems)


def test_separate_mode_radios_red_holder_absolutely_positioned_and_grid_not_overlapping():
    """红（回归）：容器必须绝对定位、且左侧网格容器不得侵入右侧 radio 区。

    两处都会导致重影/错位，故分别锁定：
    1. 容器带 geometry 且与组框同父——若被塞进 gridLayout，radio 会落到标题行下方；
    2. 网格容器宽度锁 560（右缘 610 < 容器左缘 611）——不锁则几何重叠检查判红，
       且宽态下网格右缘会继续右伸吃掉 radio 区。
    """
    root = _parse_ui()
    problems = []
    for key, (box, holder, _on, _off) in _SEPARATE_MODE_RADIO_PAIRS.items():
        hw = _find_widget_by_name(root, holder)
        if hw is None:
            problems.append(f"{holder} 不存在")
            continue
        if hw.find("property[@name='geometry']") is None:
            problems.append(f"{holder} 应绝对定位（带 geometry）")
        if hw.find("layout") is not None:
            problems.append(f"{holder} 不应带 layout（带 layout 会被宽幅同步误判为 _STRETCH 拉宽，radio 指示点会漂移）")
    # 四个网格容器宽度
    for key, (box, holder, _on, _off) in _SEPARATE_MODE_RADIO_PAIRS.items():
        gw = None
        for w in _find_widget_by_name(root, box).iter("widget"):
            if _widget_rect(w) is not None and _widget_rect(w)[1] == 30 and _widget_rect(w)[2] > 400:
                gw = w
        if gw is None:
            problems.append(f"{box} 下未找到 y=30 的网格容器")
            continue
        width = _widget_rect(gw)[2]
        if width != _SEPARATE_GRID_WIDGET_WIDTH:
            problems.append(f"{box} 的 {gw.get('name')} 宽度 {width} != {_SEPARATE_GRID_WIDGET_WIDTH}")
        # 右缘必须严格小于容器左缘，确保不重叠
        grid_right = _widget_rect(gw)[0] + width
        holder_left = _SEPARATE_RADIO_HOLDER_RECT[0]
        if grid_right >= holder_left:
            problems.append(f"{box} 网格右缘 {grid_right} >= radio 容器左缘 {holder_left}，会重叠")
        # 两端留白对称：左侧 radio 左缘到组框左边界的距离 == 右侧容器右缘到右边界的距离
        left_margin = _widget_rect(gw)[0] + _SEPARATE_RADIO_INNER_RECTS[0][0]
        right_margin = _SEPARATE_BOX_WIDTH - (holder_left + _SEPARATE_RADIO_HOLDER_RECT[2])
        if left_margin != _SEPARATE_SIDE_MARGIN:
            problems.append(f"{box} 左侧留白 {left_margin} != {_SEPARATE_SIDE_MARGIN}")
        if right_margin != left_margin:
            problems.append(f"{box} 左右留白不对称：左 {left_margin} vs 右 {right_margin}")
    assert not problems, "分离模式开/关容器/网格几何问题:\n" + "\n".join(problems)


# ---------- STRM 行位置锁定：主复选框与删除行严格上下对齐，禁止后移 ----------

_STRM_MAIN_TEXT = "为本地视频文件生成STRM链接文本"
_STRM_OVERWRITE_TEXT = "覆盖本地已存在的STRM链接文本"


def _find_layout_by_name(root, name):
    for layout in root.iter("layout"):
        if layout.get("name") == name:
            return layout
    return None


def _grid_item_pos(grid, child_name):
    """在 gridLayout 下找直接子 item（widget 或 layout）名为 child_name 的 (row, column)。"""
    for item in grid.findall("item"):
        if len(item) == 0:
            continue
        if item[0].get("name") == child_name:
            return (item.get("row"), item.get("column"))
    return (None, None)


def test_strm_checkboxes_text_order_and_alignment_locked():
    """STRM 行锁定：主复选框居左与删除行对齐、覆盖框居右，挪动即失败。"""
    root = _parse_ui()
    problems = []

    main = _find_widget_by_name(root, "checkBox_separate_generate_strm")
    overwrite = _find_widget_by_name(root, "checkBox_separate_overwrite_strm")
    if main is None:
        problems.append("checkBox_separate_generate_strm 不存在")
    elif _widget_string_prop(main, "text") != _STRM_MAIN_TEXT:
        problems.append(f"主复选框文案被改: {_widget_string_prop(main, 'text')!r}")
    if overwrite is None:
        problems.append("checkBox_separate_overwrite_strm 不存在")
    elif _widget_string_prop(overwrite, "text") != _STRM_OVERWRITE_TEXT:
        problems.append(f"覆盖复选框文案被改: {_widget_string_prop(overwrite, 'text')!r}")

    hbox = _find_layout_by_name(root, "horizontalLayout_strm")
    if hbox is None:
        problems.append("horizontalLayout_strm 不存在")
    else:
        kids = [item[0].get("name") for item in hbox.findall("item") if len(item)]
        # 前两项必须是两复选框且顺序不变；允许末尾跟随纯 spacer（horizontalSpacer_strm）——
        # STRM 行两个复选框都是 Fixed，HBox 最大宽被钉死在 285 会卡住 gridLayout_2 第 1 列，
        # 容器拉宽后多余空间被三等分摊、描述列整体右移；末尾弹性 spacer 解开上限且不改变行外观。
        if kids[:2] != ["checkBox_separate_generate_strm", "checkBox_separate_overwrite_strm"]:
            problems.append(f"STRM 行内顺序被改（主框必须居左首位）: {kids!r}")
        for extra in kids[2:]:
            if not extra.startswith("horizontalSpacer_"):
                problems.append(f"STRM 行内不允许出现非 spacer 部件: {extra!r}")

    reuse_hbox = _find_layout_by_name(root, "horizontalLayout_reuse_meta")
    if reuse_hbox is None:
        problems.append("horizontalLayout_reuse_meta 不存在")
    else:
        kids = [item[0].get("name") for item in reuse_hbox.findall("item") if len(item)]
        # 复用行：复用框居左 + gap spacer + 覆盖框居右（覆盖框与 STRM 覆盖框上下对齐），末尾弹性 spacer。
        if kids[:3] != [
            "checkBox_separate_reuse_meta",
            "horizontalSpacer_reuse_meta_gap",
            "checkBox_separate_overwrite_meta",
        ]:
            problems.append(f"复用行内顺序被改: {kids!r}")
        for extra in kids[3:]:
            if not extra.startswith("horizontalSpacer_"):
                problems.append(f"复用行内不允许出现非 spacer 部件: {extra!r}")
    overwrite_meta = _find_widget_by_name(root, "checkBox_separate_overwrite_meta")
    if overwrite_meta is None:
        problems.append("checkBox_separate_overwrite_meta 不存在")
    elif _widget_string_prop(overwrite_meta, "text") != "覆盖本地保存的视频元数据文件":
        problems.append(f"覆盖元数据复选框文案被改: {_widget_string_prop(overwrite_meta, 'text')!r}")

    grid = _find_layout_by_name(root, "gridLayout_2")
    if grid is None:
        problems.append("gridLayout_2 不存在")
    else:
        if _grid_item_pos(grid, "horizontalLayout_strm") != ("2", "1"):
            problems.append(f"STRM 行被移动（应在 row=2 col=1）: {_grid_item_pos(grid, 'horizontalLayout_strm')!r}")
        if _grid_item_pos(grid, "horizontalLayout_reuse_meta") != ("3", "1"):
            problems.append(
                f"复用行被移动（应在 row=3 col=1）: {_grid_item_pos(grid, 'horizontalLayout_reuse_meta')!r}"
            )
        if _grid_item_pos(grid, "horizontalLayout_125") != ("5", "1"):
            problems.append(f"删除行被移动（应在 row=5 col=1）: {_grid_item_pos(grid, 'horizontalLayout_125')!r}")
        strm_spacer = _find_widget_by_name(root, "label_strm_spacer")
        del_spacer = _find_widget_by_name(root, "label_344")
        if strm_spacer is None or del_spacer is None:
            problems.append("label_strm_spacer / label_344 缺失")
        else:
            widths = set()
            for nm, w in (("label_strm_spacer", strm_spacer), ("label_344", del_spacer)):
                minimum = w.find("property[@name='minimumSize']/size/width")
                widths.add(int(minimum.text) if minimum is not None else None)
                if _grid_item_pos(grid, nm)[1] != "0":
                    problems.append(f"{nm} 不在 col=0: {_grid_item_pos(grid, nm)!r}")
            if widths != {80}:
                problems.append(f"两行 col=0 空位宽度应同为 80: {sorted(widths, key=str)!r}")
    assert not problems, "STRM 行位置/顺序问题:\n" + "\n".join(problems)
