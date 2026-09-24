"""avsex 爬虫搜索页解析测试（挑战页点名 / 正常解析 / 真无结果）"""

import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers import get_crawler
from mdcx.crawlers.avsex import AvsexCrawler
from mdcx.crawlers.base import CrawlerException
from mdcx.models.model_types import CrawlerInput


def _make_crawler():
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AvsexCrawler(client=client, browser=None)
    inp = CrawlerInput.empty()
    inp.number = "SSNI-452"
    ctx = crawler.new_context(inp)
    return client, crawler, ctx


def test_avsex_crawler_is_registered():
    """测试爬虫已注册"""
    assert get_crawler(Website.AVSEX) is AvsexCrawler


@pytest.mark.asyncio
async def test_avsex_search_page_challenge_named():
    """CF 挑战页必须点名，不能报未解析到结果"""
    client, crawler, ctx = _make_crawler()
    try:
        challenge_html = (
            "<html><head><title>Just a moment...</title></head>"
            '<body><div id="cf-chl">Verifying you are human</div>'
            '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
            "</body></html>"
        )
        with pytest.raises(CrawlerException, match="Cloudflare"):
            await crawler._parse_search_page(
                ctx, Selector(text=challenge_html), "https://avsex.cc/tw/search?query=ssni-452"
            )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_avsex_search_page_normal_result():
    """正常结果页解析出详情页 URL"""
    client, crawler, ctx = _make_crawler()
    try:
        normal_html = (
            '<html><body><ul class="grid"><li>'
            '<a href="https://avsex.cc/video/1"><div>'
            '<h4 class="truncate">SSNI-452 Title</h4>'
            "</div></a></li></ul></body></html>"
        )
        urls = await crawler._parse_search_page(
            ctx, Selector(text=normal_html), "https://avsex.cc/tw/search?query=ssni-452"
        )
        assert urls == ["https://avsex.cc/video/1"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_avsex_search_page_no_result_returns_none():
    """干净的无结果页返回 None（走"未解析到结果"分支）"""
    client, crawler, ctx = _make_crawler()
    try:
        empty_html = "<html><body><div>no results found</div></body></html>"
        assert (
            await crawler._parse_search_page(
                ctx, Selector(text=empty_html), "https://avsex.cc/tw/search?query=ssni-452"
            )
            is None
        )
    finally:
        await client.close()
