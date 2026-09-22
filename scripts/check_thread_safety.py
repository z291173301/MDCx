#!/usr/bin/env python3
"""跨线程 Qt 安全静态扫描。

扫 mdcx/ 下所有 async def 函数体，找出在后台协程内直接操作 QWidget 的违规调用
（setEnabled/setText/setPlainText 等线程不安全操作）。后台协程应只发 pyqtSignal，
由主线程槽恢复 UI（见 mdcx/utils/qt_thread.py 与 MEMORY「executor.submit 与
跨线程 Qt 安全」）。

用法: uv run python -m scripts.check_thread_safety
      python scripts/check_thread_safety.py mdcx/

退出码: 发现违规返回 1，否则 0。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# QWidget 上线程不安全的 setter / 状态变更方法
# 只保留 QWidget 独有方法，排除 list/dict 通用的 append/addItem/clear/insertRow/setItem
# （这些与容器方法同名，AST 无法区分，留作人工 review）
_UNSAFE_METHODS = {
    "setEnabled",
    "setDisabled",
    "setVisible",
    "setHidden",
    "setText",
    "setPlainText",
    "setHtml",
    "setMarkdown",
    "setStyleSheet",
    "setGeometry",
    "move",
    "resize",
    "setPixmap",
    "setCheckState",
    "setCurrentIndex",
    "setCurrentText",
    "setValue",
    "setChecked",
    "setReadOnly",
    "setPlaceholderText",
    "setFocus",
    "setWindowTitle",
}

# 安全的信号发射通道（emit 是线程安全的，跨线程会 queued 到主线程）
_SAFE_BASES = {"signal_qt", "signal", "self"}


def _is_unsafe_call(node: ast.Call) -> bool:
    """判断 Call 是否是 async 内对 QWidget 的不安全操作。"""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _UNSAFE_METHODS:
        return False
    # emit 走信号通道，安全
    if func.attr == "emit":
        return False
    # PIL Image.resize 带 resample 参数，非 QWidget
    if func.attr == "resize" and any(kw.arg == "resample" for kw in node.keywords):
        return False
    # 排除明显的信号对象（signal_qt.xxx.emit / signal.xxx.emit）
    base = func.value
    if isinstance(base, ast.Name) and base.id in _SAFE_BASES:
        return False
    if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name) and base.value.id in _SAFE_BASES:
        return False
    return True


def _collect_async_violations(tree: ast.AST, path: Path) -> list[tuple[int, str, str]]:
    """收集文件内所有 async def 体内的不安全 QWidget 调用。"""
    results: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef,)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if _is_unsafe_call(child):
                func = child.func
                assert isinstance(func, ast.Attribute)
                # 拼接调用链文本便于定位
                try:
                    call_text = ast.unparse(child)
                except Exception:
                    call_text = f"...{func.attr}(...)"
                results.append((child.lineno, func.attr, call_text))
    return results


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or [Path("mdcx")]
    total = 0
    by_file: dict[Path, list[tuple[int, str, str]]] = {}
    for root in roots:
        for py in sorted(root.rglob("*.py")):
            if "/__pycache__/" in str(py) or "/.venv/" in str(py):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            except SyntaxError:
                continue
            violations = _collect_async_violations(tree, py)
            if violations:
                by_file[py] = violations
                total += len(violations)
    if total == 0:
        print("[check_thread_safety] 无违规：未发现 async def 内直接操作 QWidget 的调用。")
        return 0
    print(f"[check_thread_safety] 发现 {total} 处疑似违规（async def 内直接操作 QWidget）：\n")
    for py, violations in by_file.items():
        print(f"  {py}")
        for lineno, method, call in violations:
            print(f"    {lineno}: .{method}() -> {call}")
        print()
    print("后台协程应只发 pyqtSignal，由主线程槽恢复 UI。见 mdcx/utils/qt_thread.py。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
