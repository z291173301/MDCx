"""刮削进度速率估算测试：滑动窗口 / 平滑 / 剩余时间格式化 / 附加展示。"""

import math

from mdcx.core.scrape_progress import ScrapeRateEstimator, _format_duration, append_eta


def _feed(estimator: ScrapeRateEstimator, count: int, interval: float, start: float = 0.0) -> float:
    """模拟匀速完成事件，返回最后时间戳"""
    now = start
    for i in range(count):
        now = start + i * interval
        estimator.record_done(now)
    return now


def test_eta_empty_below_min_samples():
    """样本不足不出估算（返回空串，不显示误导数字）"""
    est = ScrapeRateEstimator(total_count=100)
    _feed(est, 5, 1.0)  # 少于 8 个样本
    assert est.rate_per_sec() == 0.0
    assert est.eta_text() == ""


def test_eta_uniform_rate():
    """匀速 2 秒/个、剩 40 个 → 约 80 秒"""
    est = ScrapeRateEstimator(total_count=50)
    _feed(est, 10, 2.0)
    rate = est.rate_per_sec()
    assert math.isclose(rate, 0.5, rel_tol=0.05)
    eta = est.eta_text()
    assert eta in ("80 秒", "1 分钟")


def test_window_drops_old_events():
    """窗口只保留最近 30 个事件：补充快事件后速率较纯慢窗口明显上升"""
    est = ScrapeRateEstimator(total_count=1000)
    _feed(est, 30, 10.0, start=0.0)  # 30 个慢事件 10 秒/个
    slow_rate = est.rate_per_sec()
    assert math.isclose(slow_rate, 0.1, rel_tol=0.05)
    # 再补 10 个：1 秒/个（窗口滑动，慢事件占比下降 → 速率上升）
    _feed(est, 10, 1.0, start=300.0)
    mixed_rate = est.rate_per_sec()
    assert mixed_rate > slow_rate * 1.2


def test_ema_smooths_jitter():
    """速率平滑验证：突增事件后速率渐进上升，不剧烈跳变"""
    est = ScrapeRateEstimator(total_count=100)
    _feed(est, 30, 1.0)  # 1 个/秒
    base_rate = est.rate_per_sec()
    for i in range(10):
        est.record_done(30 + i * 0.1)  # 突然 0.1 秒/个
    new_rate = est.rate_per_sec()
    assert base_rate > 0.5
    assert new_rate > base_rate  # 变快
    assert new_rate < 5.0  # 混合窗口下不会直接跳到 10 个/秒


def test_done_and_format_duration():
    """时长格式化各档位"""
    assert _format_duration(45) == "45 秒"
    assert _format_duration(90) == "1 分钟"
    assert _format_duration(3700) == "1 小时 1 分"
    assert _format_duration(90000) == "1 天 1 小时"


def test_append_eta_appends_when_available():
    """有估算时附加，无估算时原样返回"""
    est = ScrapeRateEstimator(total_count=100)
    assert append_eta("🔎 已刮削 3/100", est) == "🔎 已刮削 3/100"  # 无样本
    _feed(est, 10, 1.0)
    text = append_eta("🔎 已刮削 10/100", est)
    assert "剩余约" in text
