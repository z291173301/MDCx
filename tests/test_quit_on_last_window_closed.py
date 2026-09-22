"""话题 #159：主窗隐藏后关闭演员管理器不得退出主程序。

根因：Qt 默认 quitOnLastWindowClosed=True，关闭最后一个**可见**顶层窗口
即触发 `QApplication.quit()`。主窗经托盘 `hide()` 后不再是可见窗口，
演员管理器（无父级、非模态 `show()` 的 QDialog）成为最后一个可见窗口，
用户关闭它 → Qt 判定"最后窗口已关闭" → 事件 loop 退出 → 整个程序退出。

修复：`main.py::_create_application` 设置 `setQuitOnLastWindowClosed(False)`，
退出由主窗 `exit_app()`/托盘菜单显式 `QApplication.quit()` 控制。

两层锁定（防恒真）：
1. 行为测试：走真实入口 `_create_application()`，断言属性实际生效为 False
   （撤掉修复立即转红，不依赖源码文本匹配）。
2. AST 哨兵：锁定该调用在 `_create_application` 函数体内、参数为 False，
   防止未来被挪到不生效的位置或改掉参数。
"""

import ast
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


def test_create_application_disables_quit_on_last_window_closed(monkeypatch, tmp_path):
    """真实执行启动入口后，Qt 的"最后窗口自动退出"必须处于关闭状态。"""
    # 注意：QApplication 实例必须持有引用（局部变量 app 承担），否则会被 GC 回收
    app = QApplication.instance() or QApplication(sys.argv)

    # 与启动冒烟测试同款打桩：跳过与 GUI 无关的启动副作用
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.chdir(tmp_path)

    # QApplication 是进程级单例，本测试会改写其属性，结束后必须恢复，
    # 避免污染同进程其它测试
    import main as main_mod

    # _create_application 的 QApplication 构造调用打桩为复用现有实例（pytest 同
    # 进程不允许二次构造），让被测的 quitOnLastWindowClosed 设置行在真实 app 上执行。
    def _fake_qapp(*a, **k):
        return app

    # setattr 绕过 ruff B010 对动态补属性的限制；staticmethod 包装保持类方法语义
    setattr(  # noqa: B010
        _fake_qapp,
        "setHighDpiScaleFactorRoundingPolicy",
        staticmethod(QApplication.setHighDpiScaleFactorRoundingPolicy),
    )
    monkeypatch.setattr(main_mod, "QApplication", _fake_qapp)
    original = app.quitOnLastWindowClosed()
    ui = None
    try:
        created_app, ui = main_mod._create_application()
        assert created_app is app
        assert app.quitOnLastWindowClosed() is False
    finally:
        if ui is not None:
            for timer in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
                getattr(ui, timer).stop()
            ui.close()
            ui.deleteLater()
            app.processEvents()
        app.setQuitOnLastWindowClosed(original)


@pytest.mark.parametrize("source_file", ["main.py"])
def test_quit_setting_ast_sentinel(source_file):
    """AST 哨兵：`setQuitOnLastWindowClosed(False)` 必须在 _create_application 内。"""
    tree = ast.parse((ROOT / source_file).read_text(encoding="utf-8"))
    func = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_create_application"
    )
    calls = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setQuitOnLastWindowClosed"
    ]
    assert len(calls) == 1, "必须在启动入口设置且仅设置一次 quitOnLastWindowClosed"
    args = calls[0].args
    assert len(args) == 1 and isinstance(args[0], ast.Constant) and args[0].value is False, (
        "quitOnLastWindowClosed 的参数必须是 False"
    )
