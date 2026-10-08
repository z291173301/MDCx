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
    # 两个 URL 失败原因相同时按设计去重（base._search 只显示一次），否则报告会被重复文案刷屏
    assert err.count("请求失败") == 1


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
    # 报告里须带页面指纹，否则用户看不出站点到底返回了什么页面
    assert "页面标题=无" in err
    assert "正文长度=18" in err  # len("<html>empty</html>")


async def test_search_failure_collapses_same_cause_fingerprints():
    """同一根因的多候选番号指纹只留首条：检测行不能被近似的文案刷屏。

    实测 madouqu 探测 MDX-0236 时会生成 MDX-0236 / MDX0236 两组候选共 4 个搜索页，
    四条「搜索页未解析到结果（页面标题=…, 正文长度=…）」全进异常消息，检测行变成几百字。
    """
    from mdcx.crawlers.base import BaseCrawler

    class _ProbeCrawler3(BaseCrawler):
        _skip_auto_register = True
        description = "probe test 3"

        @classmethod
        def site(cls):
            raise NotImplementedError

        @classmethod
        def base_url_(cls):
            return "https://example.invalid"

        async def _generate_search_url(self, ctx):
            return [f"https://example.invalid/search?n={i}" for i in range(4)]

        async def _fetch_search(self, ctx, url):
            return f"<html><title>MDX-0236 {url[-1]}</title>{'x' * (100 + len(url))}</html>", ""

        async def _parse_search_page(self, ctx, html, search_url):
            return None

        async def _parse_detail_page(self, ctx, html, detail_url):
            return None

    crawler = _ProbeCrawler3(client=None, browser=None)
    inp = CrawlerInput.empty()
    inp.number = "MDX-0236"
    resp = await crawler.run(inp)
    err = str(resp.debug_info.error)
    assert "搜索失败" in err and "未解析到结果" in err
    assert err.count("搜索页未解析到结果") == 1, err
    assert " | " not in err, err
    # 首条指纹保留（页面标题 + 正文长度），用户仍能判断站点返回了什么页面
    assert "页面标题=" in err and "正文长度=" in err


async def test_mywife_probe_number_updated_to_live_model_page():
    """探测番号: 1500 已被站点下架(500), 2306 用户实测有效。"""
    from mdcx.crawlers.mywife import MywifeCrawler

    assert MywifeCrawler.probe_number == "mywife-2306"
