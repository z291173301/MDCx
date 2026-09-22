"""跨线程 Qt 安全的通用后台任务模板。

项目反复踩坑（见 MEMORY「executor.submit 与跨线程 Qt 安全」）：后台协程直接
操作 QWidget（setEnabled/setText）会触发线程安全违规，GUI 卡死或静默退出。
本模块提供统一入口，固化正确模式：

- 主线程点击：按钮防重入 + setEnabled(False) + busy_signal.emit(busy_text)
- 后台协程：try/except 捕获异常并写日志，finally 发 finished_signal（线程安全）
- 主线程槽：按 finished_arg 恢复对应按钮状态

新代码禁止直接 ``executor.submit`` 后在协程内碰 QWidget，统一走本函数。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# button / pyqtSignal 实例用 Any 注解：PyQt6 信号实例类型（pyqtBoundSignal）
# 无公开类型名，强类型注解易触发 mypy attr-defined/arg-type 误报。


def run_in_background(
    *,
    button: Any,
    coro_factory: Callable[[], Any],
    finished_signal: Any,
    finished_arg: str,
    busy_signal: Any = None,
    busy_text: str = "",
    log_prefix: str = "",
) -> None:
    """按钮防重入 + 后台协程 + 完成信号的通用模板。

    Args:
        button: 触发按钮（防重入 + 禁用）。不可用则直接返回。
        coro_factory: 无参 callable，返回协程。协程内异常会被捕获并写日志。
        finished_signal: 完成信号（线程安全，主线程槽恢复按钮）。携带 finished_arg。
        finished_arg: 完成信号携带的标识（如 btn_attr），主线程槽据此定位恢复哪个按钮。
        busy_signal: 按钮按下时的文案更新信号（主线程 setText，跨线程不安全故走信号）。
        busy_text: 按下时临时文案。
        log_prefix: 异常日志前缀（如 "演员库维护"）。
    """
    if not button.isEnabled():
        return

    button.setEnabled(False)
    if busy_signal is not None and busy_text:
        busy_signal.emit(busy_text)

    # 延迟导入避免 utils ↔ signals 循环导入
    from ..signals import signal_qt
    from . import executor

    async def _run() -> None:
        try:
            await coro_factory()
        except Exception as e:
            if log_prefix:
                signal_qt.show_log_text(f"🔴 {log_prefix}异常: {e}")
            import traceback as tb

            signal_qt.show_log_text(tb.format_exc())
        finally:
            # 线程安全：仅发信号，由主线程槽恢复按钮状态
            finished_signal.emit(finished_arg)

    executor.submit(_run())
