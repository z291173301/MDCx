from types import SimpleNamespace

import pytest

from mdcx.base.web import _AdaptiveRequestThrottle, _amazon_request_throttle, get_amazon_data
from mdcx.config.manager import manager


def _monotonic_factory(values: iter):
    """Return a monotonic() mock that yields from values, falling back to last value."""
    last = [0.0]

    def _monotonic():
        try:
            v = next(values)
            last[0] = v
            return v
        except StopIteration:
            return last[0]

    return _monotonic


@pytest.mark.asyncio
async def test_get_amazon_data_prefers_utf8(monkeypatch: pytest.MonkeyPatch):
    await _amazon_request_throttle.reset()
    called_encodings: list[str] = []
    called_headers: list[dict | None] = []

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        called_headers.append(headers)
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings == ["utf-8"]
    assert called_headers[0] is not None
    assert "ja" in str(called_headers[0].get("accept-language", "")).lower()


@pytest.mark.asyncio
async def test_get_amazon_data_retry_still_uses_utf8(monkeypatch: pytest.MonkeyPatch):
    await _amazon_request_throttle.reset()
    called_encodings: list[str] = []
    called_headers: list[dict | None] = []

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        called_headers.append(headers)
        if len(called_encodings) == 1:
            return None, "utf8 failed"
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings[:2] == ["utf-8", "utf-8"]
    assert all(headers is not None for headers in called_headers[:2])
    assert all("ja" in str(headers.get("accept-language", "")).lower() for headers in called_headers[:2])


@pytest.mark.asyncio
async def test_get_amazon_data_dynamic_backoff_after_429(monkeypatch: pytest.MonkeyPatch):
    await _amazon_request_throttle.reset()
    called_encodings: list[str] = []
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    async def fake_get_text(url: str, *, headers=None, encoding: str = "utf-8"):
        called_encodings.append(encoding)
        if len(called_encodings) == 1:
            return None, "HTTP 429"
        return "<html>ok</html>", ""

    monkeypatch.setattr(manager.computed.async_client, "get_text", fake_get_text)
    monkeypatch.setattr("mdcx.base.web.asyncio.sleep", fake_sleep)

    success, html = await get_amazon_data("https://www.amazon.co.jp/s?k=test")

    assert success is True
    assert html == "<html>ok</html>"
    assert called_encodings[:2] == ["utf-8", "utf-8"]
    assert any(seconds >= 1.0 for seconds in sleep_calls)
    await _amazon_request_throttle.reset()


@pytest.mark.asyncio
async def test_adaptive_request_throttle_coalesces_same_burst_429(monkeypatch: pytest.MonkeyPatch):
    throttle = _AdaptiveRequestThrottle(
        base_spacing=0.18,
        max_spacing=1.6,
        cooldown_base=1.4,
        cooldown_max=8.0,
        throttle_burst_window=2.2,
        same_burst_extension=0.7,
    )
    monotonic_values = iter([10.0, 10.6, 11.8, 14.8])

    monkeypatch.setattr("mdcx.utils.rate_limit.random", SimpleNamespace(uniform=lambda _a, _b: 0.0))
    monkeypatch.setattr("time.monotonic", _monotonic_factory(monotonic_values))

    cooldown1, level1, escalated1 = await throttle.register_result(throttled=True)
    cooldown2, level2, escalated2 = await throttle.register_result(throttled=True)
    cooldown3, level3, escalated3 = await throttle.register_result(throttled=True)
    cooldown4, level4, escalated4 = await throttle.register_result(throttled=True)

    assert escalated1 is True
    assert level1 == 1
    assert cooldown1 == pytest.approx(1.4)

    assert escalated2 is False
    assert level2 == 1
    assert cooldown2 == pytest.approx(0.8)

    assert escalated3 is False
    assert level3 == 1
    assert cooldown3 == pytest.approx(0.7)

    assert escalated4 is True
    assert level4 == 2
    assert cooldown4 == pytest.approx(2.52)


@pytest.mark.asyncio
async def test_adaptive_request_throttle_recovers_after_success(monkeypatch: pytest.MonkeyPatch):
    throttle = _AdaptiveRequestThrottle(
        base_spacing=0.2,
        max_spacing=1.6,
        cooldown_base=1.4,
        cooldown_max=8.0,
    )
    monotonic_values = iter([20.0, 24.0, 24.1, 24.2])

    monkeypatch.setattr("mdcx.utils.rate_limit.random", SimpleNamespace(uniform=lambda _a, _b: 0.0))
    monkeypatch.setattr("time.monotonic", _monotonic_factory(monotonic_values))

    _, level1, _ = await throttle.register_result(throttled=True)
    _, level2, _ = await throttle.register_result(throttled=True)
    boosted_spacing = throttle._request_spacing
    _, level3, _ = await throttle.register_result(throttled=False)
    _, level4, _ = await throttle.register_result(throttled=False)

    assert level1 == 1
    assert level2 == 2
    assert level3 == 1
    assert level4 == 0
    assert throttle.base_spacing < throttle._request_spacing < boosted_spacing


@pytest.mark.asyncio
async def test_amazon_search_create_candidate_no_typeerror(monkeypatch):
    """议题 #91：搜索页候选收集走 create_candidate 新建分支不得抛 TypeError。

    抽取重构把 create_candidate 的 detail_url 改为 keyword-only 必填后，
    barcode 路径（1540）与主搜索路径（1744）两处调用点均未同步传参——
    任何走到「新建候选」的刮削都会炸 TypeError，亚马逊封面获取整体失效。
    """
    from mdcx.core import amazon
    from mdcx.models.model_types import CrawlersResult

    html_search = """
    <html><body>
    <div data-component-type="s-search-result" data-asin="B0IPIT009">
      <a class="a-text-bold">DVD</a>
      <h2><a href="https://www.amazon.co.jp/dp/B0IPIT009"><span>IPIT-009 愛田みる</span></a></h2>
      <img class="s-image" src="https://m.media-amazon.com/images/I/test._SL500_.jpg">
    </div>
    </body></html>
    """

    async def _no_cache(number):
        return None

    async def _fake_get_amazon_data(url, *args, **kwargs):
        if "/dp/" in url:
            return False, ""
        return True, html_search

    async def _no_size(_url, _ctx=None):
        return 0, 0

    async def _fake_barcodes(result, media_context=None):
        # 触发 try_get_big_pic_by_amazon_via_barcode 的条码快路径（1540 调用点）
        return ["4544031474779"]

    monkeypatch.setattr(amazon, "_check_asin_cache", _no_cache)
    monkeypatch.setattr(amazon, "try_get_amazon_barcodes_from_covers", _fake_barcodes)
    monkeypatch.setattr(amazon, "get_amazon_data", _fake_get_amazon_data)
    monkeypatch.setattr(amazon, "_get_image_size", _no_size)

    result = CrawlersResult.empty()
    result.number = "IPIT-009"
    hd_pic_url = await amazon.get_big_pic_by_amazon(result, "IPIT-009", ["演员"])
    assert isinstance(hd_pic_url, str)
