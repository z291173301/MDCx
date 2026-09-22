"""议题 #128 回归: 探测失败原因可诊断 + mywife 探测番号更新。

1. base._search 旧版失败只抛"搜索失败"四字, 请求失败(如 CF 挑战页)与"页面可达但
   解析不到结果"两种根因无法区分, 网络诊断报告用户无从自查; 现聚合逐 URL 原因。
2. mywife 原探测番号 1500 的 model 页已被站点下架(HTTP 500, 用户日志实锤),
   换用户实测有效的 2306。
"""

import pytest

from mdcx.models.model_types import CrawlerInput

pytestmark = pytest.mark.asyncio


async def test_search_failure_aggregates_request_error():
    """全部搜索页请求失败: 异常消息须带每个 URL 的具体错误。"""
    from mdcx.crawlers.base import BaseCrawler

    class _ProbeCrawler(BaseCrawler):
        _skip_auto_register = True
        description = "probe test"

        @classmethod
        def site(cls):
            raise NotImplementedError

        @classmethod
        def base_url_(cls):
            return "https://example.invalid"

        async def _generate_search_url(self, ctx):
            return ["https://example.invalid/search?a=1", "https://example.invalid/search?a=2"]

        async def _fetch_search(self, ctx, url):
            return None, "HTTP 403 body=Just a moment..."

        async def _parse_search_page(self, ctx, html, search_url):
            return None

        async def _parse_detail_page(self, ctx, html, detail_url):
            return None

    crawler = _ProbeCrawler(client=None, browser=None)
    inp = CrawlerInput.empty()
    inp.number = "TEST-001"
    resp = await crawler.run(inp)
    assert resp.data is None
    err = str(resp.debug_info.error)
    assert "搜索失败" in err
    assert "HTTP 403" in err, "须带请求失败的具体原因"
    assert err.count("请求失败") == 2, "逐 URL 聚合"


async def test_search_failure_distinguishes_no_result():
    """页面可达但解析不到结果: 消息须区分「未解析到结果」而非笼统失败。"""
    from mdcx.crawlers.base import BaseCrawler

    class _ProbeCrawler2(BaseCrawler):
        _skip_auto_register = True
        description = "probe test 2"

        @classmethod
        def site(cls):
            raise NotImplementedError

        @classmethod
        def base_url_(cls):
            return "https://example.invalid"

        async def _generate_search_url(self, ctx):
            return "https://example.invalid/search"

        async def _fetch_search(self, ctx, url):
            return "<html>empty</html>", ""

        async def _parse_search_page(self, ctx, html, search_url):
            return None

        async def _parse_detail_page(self, ctx, html, detail_url):
            return None

    crawler = _ProbeCrawler2(client=None, browser=None)
    inp = CrawlerInput.empty()
    inp.number = "TEST-001"
    resp = await crawler.run(inp)
    assert resp.data is None
    err = str(resp.debug_info.error)
    assert "搜索失败" in err and "未解析到结果" in err


def test_mywife_probe_number_updated_to_live_model_page():
    """探测番号: 1500 已被站点下架(500), 2306 用户实测有效。"""
    from mdcx.crawlers.mywife import MywifeCrawler

    assert MywifeCrawler.probe_number == "mywife-2306"
