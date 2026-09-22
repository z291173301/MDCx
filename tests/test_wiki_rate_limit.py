"""议题 #125/#137：MediaWiki（Wikidata/Wikipedia）请求限速与合规 User-Agent 回归测试。

维基媒体按客户端类型限速（未识别 10 req/min、仅合规 User-Agent 200 req/min）。
#125 曾对 wiki 域名单独限速 1 req/s 并改用可识别 UA；#137 放宽为「双桶」——
每秒 5 req/s 突发 + 每分钟 180 req/min 总量，等效持续约 3/s。
"""

import asyncio

import pytest

from mdcx.config.manager import manager
from mdcx.models.emby import EMbyActressInfo
from mdcx.tools import wiki
from mdcx.web_async import (
    _MEDIAWIKI_HOSTS,
    _MEDIAWIKI_RATE_PER_MIN,
    _MEDIAWIKI_RATE_PER_SEC,
    AsyncWebLimiters,
    _CompositeLimiter,
)


def test_mediawiki_hosts_use_dual_bucket_limiter():
    """wiki 域名须使用「5 req/s + 180 req/min」双桶限速；其它域名保持通用 8 req/s。"""
    limiters = AsyncWebLimiters()
    for host in _MEDIAWIKI_HOSTS:
        limiter = limiters.get(host)
        assert isinstance(limiter, _CompositeLimiter), f"{host} 未使用 wiki 双桶限速"
        buckets = {(lim.max_rate, lim.time_period) for lim in limiter.limiters}
        assert buckets == {
            (_MEDIAWIKI_RATE_PER_SEC, 1),
            (_MEDIAWIKI_RATE_PER_MIN, 60),
        }, f"{host} 双桶参数不符: {buckets}"
    # 非 wiki 域名仍是单个 8 req/s 限速器
    assert limiters.get("example.com").max_rate == 8


@pytest.mark.asyncio
async def test_composite_limiter_gates_by_tightest_bucket():
    """组合限速器的通过量取各桶的最小值（先到瓶颈的桶决定）。"""
    from aiolimiter import AsyncLimiter

    # 2/s + 1/min：受 1/min 桶限制，只应有 1 个请求立即通过
    comp = _CompositeLimiter(AsyncLimiter(2, 1000), AsyncLimiter(1, 1000))
    passed = 0
    for _ in range(2):
        try:
            async with asyncio.timeout(0.3):
                async with comp:
                    passed += 1
        except TimeoutError:
            break
    assert passed == 1, f"应受最紧桶限制只通过 1 个，实际 {passed}"

    # 2/s + 2/min：两个桶容量都为 2，应有 2 个请求立即通过
    comp2 = _CompositeLimiter(AsyncLimiter(2, 1000), AsyncLimiter(2, 1000))
    passed2 = 0
    for _ in range(3):
        try:
            async with asyncio.timeout(0.3):
                async with comp2:
                    passed2 += 1
        except TimeoutError:
            break
    assert passed2 == 2, f"两个桶容量 2 时应通过 2 个，实际 {passed2}"


def test_wiki_headers_use_identifiable_user_agent():
    """wiki 请求头须携带可识别 UA，避免被划入「未识别」档。"""
    headers = wiki._wiki_headers()
    ua = headers["User-Agent"]
    assert "Mozilla" not in ua
    assert "mdcx-diy" in ua


@pytest.mark.asyncio
async def test_search_wiki_sends_identifiable_user_agent(monkeypatch):
    """search_wiki 实际发出的请求须带合规 UA（而非随机浏览器指纹）。"""
    captured: dict = {}

    async def fake_get_json(url, *, headers=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        return {"search": []}, ""

    monkeypatch.setattr(manager.computed.async_client, "get_json", fake_get_json)

    info = EMbyActressInfo(name="测试演员", server_id="server", id="actor")
    res, _msg = await wiki.search_wiki(info)

    assert res is None
    assert "wikidata.org" in captured["url"]
    ua = captured["headers"]["User-Agent"]
    assert "Mozilla" not in ua
    assert "mdcx-diy" in ua
