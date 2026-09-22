"""刮削进度速率估算：滑动窗口完成速率 → 预计剩余时间。

用户痛点：刮几千个文件时只有 N/M 计数，感知不到还剩多久。
纯呈现层：从完成时间戳算滑动窗口速率，输出预计剩余时间，不参与任何流程控制。
"""

from __future__ import annotations

import time

_WINDOW_SIZE = 30  # 滑动窗口容纳的最近完成事件数（窗口本身即平滑器，无需再叠加 EMA）
_MIN_SAMPLES = 8  # 少于该样本数不出估算（避免前期抖动给出离谱数字）


class ScrapeRateEstimator:
    """基于最近完成事件时间戳的速率估算器（单批次内使用，线程安全性由调用方保证）。"""

    def __init__(self, total_count: int, now: float | None = None):
        self._total = max(int(total_count), 0)
        self._events: list[float] = []
        self._start = now if now is not None else time.monotonic()
        self._last_emitted_at = 0.0

    def record_done(self, now: float | None = None) -> None:
        """记录一个文件完成事件"""
        self._events.append(now if now is not None else time.monotonic())
        if len(self._events) > _WINDOW_SIZE:
            self._events = self._events[-_WINDOW_SIZE:]

    @property
    def done_count(self) -> int:
        return len(self._events)

    def rate_per_sec(self) -> float:
        """窗口瞬时完成速率（个/秒）；样本不足返回 0"""
        events = self._events
        if len(events) < _MIN_SAMPLES:
            return 0.0
        window_elapsed = events[-1] - events[0]
        if window_elapsed <= 0:
            return 0.0
        return (len(events) - 1) / window_elapsed

    def eta_text(self, now: float | None = None) -> str:
        """预计剩余时间文本；无法估算返回空串（调用方直接省略不显示）。"""
        rate = self.rate_per_sec()
        if rate <= 0:
            return ""
        remaining = self._total - self.done_count
        if remaining <= 0:
            return ""
        seconds = remaining / rate
        return _format_duration(seconds)


def _format_duration(seconds: float) -> str:
    """把秒数格式化为可读时长"""
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds} 秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时 {minutes % 60} 分"
    return f"{hours // 24} 天 {hours % 24} 小时"


def append_eta(info: str, estimator: ScrapeRateEstimator) -> str:
    """把估算文本附加到进度串（无估算原样返回）"""
    eta = estimator.eta_text()
    return f"{info} · 剩余约 {eta}" if eta else info
