#!/usr/bin/env python3
"""UI 布局静态检查（只读，不写入任何文件）。

扫描 .ui 文件里"打包到用户机器（不同分辨率 / DPI / 字体 / 数据长度）
后才暴露"的 UI 隐患。

检查项：
  1. wordWrap 加在 QCheckBox/QRadioButton/QPushButton/QGroupBox 上
     → 运行时 AttributeError，**critical error（exit 1）**
  2. QScrollArea widgetResizable=false → 内容不自适应，高 DPI 被横向裁切
  3. QGroupBox maximumWidth=739 → 容器写死偏窄（NFO 设置页已放宽到 860 作样板）
  4. QLabel 长文本缺 wordWrap（纯文本非富文本）→ 窄容器内被硬截断

用法: uv run python -m scripts.check_ui_layout [ui文件路径]
      不传参数则默认扫描 mdcx/views/MDCx.ui

退出码: 发现 critical（wordWrap 误用）返回 1，否则 0（warning 不阻断）。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_UI = SCRIPT_DIR.parent / "mdcx" / "views" / "MDCx.ui"

# 不继承 wordWrap 的控件——加了会被 pyuic6 生成 setWordWrap(True)，运行时 AttributeError
_NO_WORDWRAP_CLASSES = frozenset(
    {
        "QCheckBox",
        "QRadioButton",
        "QPushButton",
        "QGroupBox",
        "QToolButton",
        "QCommandLinkButton",
    }
)

# Qt Designer 写的 "无限制" 大数，不算硬编码
_PSEUDO_UNLIMITED = {16777215, 66666, 16000}


@dataclass
class WidgetInfo:
    name: str
    cls: str
    chain: list[str]
    props: dict[str, object] = field(default_factory=dict)


def _localname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _is_rich_text(txt: str) -> bool:
    return bool(txt) and txt.lstrip().startswith("<")


def _parse_widget(el: ET.Element, parent_chain: list[str]) -> WidgetInfo:
    name = el.get("name", "")
    cls = el.get("class", "")
    entry = WidgetInfo(name=name, cls=cls, chain=parent_chain + [name] if name else parent_chain)

    for p in el.findall("property"):
        pname = p.get("name", "")
        if (txt := p.find("string")) is not None:
            if pname == "text":
                entry.props["text"] = txt.text or ""
        if (b := p.find("bool")) is not None:
            entry.props[pname] = b.text == "true"
        if (n := p.find("number")) is not None:
            try:
                entry.props[pname] = int(n.text or "")
            except (TypeError, ValueError):
                pass
        if (rect := p.find("rect")) is not None:
            d: dict[str, int] = {}
            for sub in rect:
                ln = _localname(sub.tag)
                if ln in ("x", "y", "width", "height"):
                    try:
                        d[ln] = int(sub.text or "")
                    except (TypeError, ValueError):
                        pass
            entry.props[pname] = d
        if (sz := p.find("size")) is not None:
            d2: dict[str, int] = {}
            for sub in sz:
                ln = _localname(sub.tag)
                if ln in ("width", "height"):
                    try:
                        d2[ln] = int(sub.text or "")
                    except (TypeError, ValueError):
                        pass
            entry.props[pname] = d2
        if (sp := p.find("sizepolicy")) is not None:
            entry.props[pname] = {
                "hsizetype": sp.get("hsizetype"),
                "vsizetype": sp.get("vsizetype"),
            }
    return entry


def _walk(el: ET.Element, parent_chain: list[str], widgets: list[WidgetInfo]) -> None:
    for child in list(el):
        ln = _localname(child.tag)
        if ln == "widget":
            entry = _parse_widget(child, parent_chain)
            widgets.append(entry)
            _walk(child, entry.chain, widgets)
        else:
            _walk(child, parent_chain, widgets)


def _chain_str(chain: list[str], depth: int = 4) -> str:
    return " > ".join(chain[:depth])


def check_wordwrap_unsupported(widgets: list[WidgetInfo]) -> list[tuple[str, str, str]]:
    """Critical: wordWrap 加在不支持的控件上 → 运行时 AttributeError。"""
    issues = []
    for w in widgets:
        if w.cls in _NO_WORDWRAP_CLASSES and w.props.get("wordWrap") is True:
            issues.append((w.name, w.cls, _chain_str(w.chain)))
    return issues


def check_scroll_areas(widgets: list[WidgetInfo]) -> list[tuple[str, int | None, str]]:
    """Warning: QScrollArea widgetResizable=false → 内容不自适应。"""
    issues = []
    for w in widgets:
        if w.cls != "QScrollArea":
            continue
        resizable = w.props.get("widgetResizable")
        if resizable is True:
            continue  # OK
        # 找内容区 geometry width
        content_w = None
        for child in widgets:
            if len(child.chain) == len(w.chain) + 1 and child.chain[:-1] == w.chain:
                g = child.props.get("geometry", {})
                if isinstance(g, dict):
                    content_w = g.get("width")
                break
        issues.append((w.name, content_w, _chain_str(w.chain)))
    return issues


def check_groupbox_maxwidth(widgets: list[WidgetInfo], threshold: int = 740) -> list[tuple[str, int, str]]:
    """Warning: QGroupBox maximumWidth 写死偏窄（< threshold）。"""
    issues = []
    for w in widgets:
        if w.cls != "QGroupBox":
            continue
        mw = w.props.get("maximumWidth")
        if isinstance(mw, int) and mw in _PSEUDO_UNLIMITED:
            continue
        ms = w.props.get("maximumSize", {})
        if isinstance(ms, dict):
            mw = ms.get("width")
            if mw in _PSEUDO_UNLIMITED or mw is None:
                continue
            if isinstance(mw, int) and mw < threshold:
                issues.append((w.name, mw, _chain_str(w.chain)))
            continue
        if isinstance(mw, int) and mw < threshold:
            issues.append((w.name, mw, _chain_str(w.chain)))
    return issues


def check_long_labels(widgets: list[WidgetInfo], min_len: int = 30) -> list[tuple[int, str, str, str]]:
    """Warning: QLabel 长纯文本缺 wordWrap → 窄容器内被硬截断。

    已排除：富文本（<p> 自动换行）、已有 wordWrap=true 的 Label。
    """
    issues = []
    for w in widgets:
        if w.cls != "QLabel":
            continue
        txt = w.props.get("text", "")
        if not isinstance(txt, str) or not txt or _is_rich_text(txt):
            continue
        if w.props.get("wordWrap") is True:
            continue  # 已有 wordWrap，OK
        if len(txt) >= min_len:
            issues.append((len(txt), w.name, txt, _chain_str(w.chain)))
    issues.sort(key=lambda x: x[0], reverse=True)
    return issues


def check_long_checkbox(widgets: list[WidgetInfo], min_len: int = 20) -> list[tuple[int, str, str, str]]:
    """Warning: QCheckBox 等长文本控件（不可用 wordWrap，需 sizePolicy=Minimum+容器放宽）。"""
    issues = []
    for w in widgets:
        if w.cls not in _NO_WORDWRAP_CLASSES:
            continue
        txt = w.props.get("text", "")
        if not isinstance(txt, str) or not txt or _is_rich_text(txt):
            continue
        if len(txt) >= min_len:
            issues.append((len(txt), w.name, txt, _chain_str(w.chain)))
    issues.sort(key=lambda x: x[0], reverse=True)
    return issues


def main() -> int:
    ui_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_UI
    if not ui_path.exists():
        print(f"[check_ui_layout] 错误: 找不到 UI 文件: {ui_path}")
        return 2

    tree = ET.parse(ui_path)
    root = tree.getroot()
    widgets: list[WidgetInfo] = []
    _walk(root, [], widgets)
    print(f"[check_ui_layout] 分析: {ui_path}  |  总 widget 数: {len(widgets)}")

    has_critical = False

    # 1. Critical: wordWrap 误用（运行时 AttributeError）
    ww_issues = check_wordwrap_unsupported(widgets)
    print("\n===== 1. wordWrap 误用（critical, 运行时 AttributeError）=====")
    if ww_issues:
        has_critical = True
        for name, cls, chain in ww_issues:
            print(f"  ❌ {name} ({cls}) 加了 wordWrap  | {chain}")
    else:
        print("  ✅ 无 wordWrap 误用")

    # 2. Warning: QScrollArea widgetResizable=false
    sa_issues = check_scroll_areas(widgets)
    print("\n===== 2. QScrollArea widgetResizable=false（warning）=====")
    if sa_issues:
        for name, cw, chain in sa_issues:
            cw_info = f"内容区 geo_w={cw}" if cw else "无内容区宽度信息"
            print(f"  ⚠️  {name} -> false  | {cw_info}  | {chain}")
    else:
        print("  ✅ 全部自适应")
    print(f"  -- 需改: {len(sa_issues)} 个")

    # 3. Warning: QGroupBox maximumWidth 偏窄
    gb_issues = check_groupbox_maxwidth(widgets)
    print("\n===== 3. QGroupBox maximumWidth 偏窄（< 740, warning）=====")
    if gb_issues:
        for name, mw, chain in gb_issues[:30]:
            print(f"  ⚠️  maxWidth={mw}  {name}  | {chain}")
        if len(gb_issues) > 30:
            print(f"  ... 还有 {len(gb_issues) - 30} 个")
    else:
        print("  ✅ 无偏窄 GroupBox")
    print(f"  -- 需改: {len(gb_issues)} 个")

    # 4. Warning: QLabel 长纯文本缺 wordWrap
    lbl_issues = check_long_labels(widgets)
    print("\n===== 4. QLabel 长纯文本缺 wordWrap（>= 30 字, warning）=====")
    if lbl_issues:
        for length, name, txt, chain in lbl_issues[:20]:
            print(f"  ⚠️  [{length}字] {name}: {txt[:40]!r}  | {chain}")
        if len(lbl_issues) > 20:
            print(f"  ... 还有 {len(lbl_issues) - 20} 个")
    else:
        print("  ✅ 全部已有 wordWrap 或文本较短")
    print(f"  -- 需改: {len(lbl_issues)} 个")

    # 5. Warning: QCheckBox 等长文本控件
    cb_issues = check_long_checkbox(widgets)
    print("\n===== 5. QCheckBox 等长文本控件（不可用 wordWrap, 需 sizePolicy=Minimum）=====")
    if cb_issues:
        for length, name, txt, chain in cb_issues[:20]:
            print(f"  ⚠️  [{length}字] {name}: {txt[:40]!r}  | {chain}")
        if len(cb_issues) > 20:
            print(f"  ... 还有 {len(cb_issues) - 20} 个")
    else:
        print("  ✅ 无长文本勾选项")
    print(f"  -- 需关注: {len(cb_issues)} 个")

    # Summary
    print("\n" + "=" * 60)
    print("汇总:")
    print(f"  [critical] wordWrap 误用: {len(ww_issues)} 个 {'❌ 阻断' if has_critical else '✅'}")
    print(f"  [warning]  滚动区不自适应: {len(sa_issues)} 个")
    print(f"  [warning]  GroupBox 偏窄: {len(gb_issues)} 个")
    print(f"  [warning]  QLabel 缺 wordWrap: {len(lbl_issues)} 个")
    print(f"  [warning]  长文本勾选项: {len(cb_issues)} 个")
    print("=" * 60)

    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
