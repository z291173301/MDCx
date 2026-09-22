"""演员工具页按钮信号-UI 一致性校验（纯静态，无需 Qt 运行时）。

背景：`_run_actor_db_async(btn_attr, ...)` 通过 `getattr(self.Ui, "pushButton_<btn_attr>")`
和 `getattr(self, "pushButton_<btn_attr>")` 动态访问按钮与信号。一旦某条链
（.ui 定义 / MDCx.py 编译产物 / MyMainWindow 顶层 pyqtSignal 定义 / `_ACTOR_DB_IDLE_TEXT_MAP`）
不一致，按钮就不会被防重入或文案恢复错误（曾有历史教训）。

本测试强制断言：

1. `_ACTOR_DB_IDLE_TEXT_MAP` 中所有 btn_attr 都在 `.ui` 中存在对应 pushButton；
2. 每个 btn_attr 都在 MyMainWindow 顶层声明了 `pyqtSignal(str)`；
3. 不允许 map 中多出 `.ui`/未声明信号的按钮（说明 map 与 UI 漂移）。
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
MAIN_WINDOW_PATH = REPO / "mdcx" / "controllers" / "main_window" / "main_window.py"

# 不走「异步任务防重入-恢复」路径的 actor_db 按钮（停止/打开文件/选择目录）。
# 它们不应出现在 _ACTOR_DB_IDLE_TEXT_MAP 中。
_NON_ASYNC_BUTTONS = {"stop", "open", "pick_nfo_dir"}


def _parse_idle_map_keys() -> set[str]:
    """从 main_window.py 源码中提取 _ACTOR_DB_IDLE_TEXT_MAP 的键。"""
    text = MAIN_WINDOW_PATH.read_text(encoding="utf-8")
    m = re.search(r"_ACTOR_DB_IDLE_TEXT_MAP[^=]*=\s*\{([^}]+)\}", text, re.S)
    assert m, "未找到 _ACTOR_DB_IDLE_TEXT_MAP 定义（重构后请保持该名称）"
    return set(re.findall(r'"(actor_db_[a-z_]+)":', m.group(1)))


def _parse_ui_actor_db_buttons() -> set[str]:
    """从 MDCx.ui 中提取所有 actor_db 前缀的 pushButton objectName。"""
    text = UI_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'name="(pushButton_actor_db[a-zA-Z_]*)"', text))


def _parse_main_window_pyqt_signals() -> set[str]:
    """从 main_window.py 提取顶层声明的 actor_db pyqtSignal 名。"""
    text = MAIN_WINDOW_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"(pushButton_actor_db[a-zA-Z_]*)\s*=\s*pyqtSignal", text))


def test_actor_db_idle_map_keys_in_ui():
    """IDLE_TEXT_MAP 里的每个 btn_attr 都必须真实存在 .ui 中的 pushButton。"""
    map_keys = _parse_idle_map_keys()
    ui_buttons = _parse_ui_actor_db_buttons()
    missing = {f"pushButton_{k}" for k in map_keys} - ui_buttons
    assert not missing, (
        f"以下 btn_attr 在 MDCx.ui 中找不到对应 pushButton，_run_actor_db_async 将无法禁用/恢复按钮：{sorted(missing)}"
    )


def test_actor_db_idle_map_keys_have_pyqt_signal():
    """IDLE_TEXT_MAP 里的每个 btn_attr 都必须在 MyMainWindow 顶层有 pyqtSignal(str)。"""
    map_keys = _parse_idle_map_keys()
    signals = _parse_main_window_pyqt_signals()
    missing = {f"pushButton_{k}" for k in map_keys} - signals
    assert not missing, (
        f"以下 btn_attr 未在 MyMainWindow 顶层声明 pyqtSignal(str)，"
        f"任务开始/结束的按钮文案 emit 会失败：{sorted(missing)}"
        f"（修复：在 MyMainWindow 类顶部加 `pushButton_<attr> = pyqtSignal(str)`，init.py 中 setText 槽连接）"
    )


def test_actor_db_ui_signals_cover_map():
    """反向：映射不应比顶层信号定义稀疏——多余的 UI 按钮有人误漏。"""
    map_keys = _parse_idle_map_keys()
    signals = _parse_main_window_pyqt_signals()
    extra_signals = signals - {f"pushButton_{k}" for k in map_keys}
    unexpected = {s.removeprefix("pushButton_actor_db_") for s in extra_signals} - _NON_ASYNC_BUTTONS
    assert not unexpected, (
        f"MyMainWindow 顶层声明了 actor_db 信号但 _ACTOR_DB_IDLE_TEXT_MAP 没收录：{sorted(unexpected)}"
        f"若非异步按钮请在 _NON_ASYNC_BUTTONS 中加白名单；否则补 map"
    )


def test_actor_db_check_finished_calls_exist():
    """信号 actor_db_finished 必须保留 str 参数（task_id），且默认值为空串。"""
    text = MAIN_WINDOW_PATH.read_text(encoding="utf-8")
    # pyqtSignal(str) 定义
    assert re.search(r"actor_db_finished\s*=\s*pyqtSignal\(str\)", text), (
        "actor_db_finished 应是 pyqtSignal(str)（task_id），用于精确恢复单个按钮"
    )
    # 槽函数签名带默认空串，兼容无参 emit
    assert re.search(
        r"def _on_actor_db_finished\(self,\s*task_id:\s*str\s*=\s*[\"'][\"']",
        text,
    ), "_on_actor_db_finished 必须接受 task_id: str = '' 默认参数"
