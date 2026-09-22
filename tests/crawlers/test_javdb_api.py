import re

import pytest
from parsel import Selector

from mdcx.config.models import Website
from mdcx.crawlers.javdb_api import JavdbApiCrawler, normalize_actor_name
from mdcx.models.model_types import CrawlerInput


def _load_html(name: str) -> Selector:
    path = f"tests/crawlers/data/javdb_api/{name}"
    with open(path, encoding="utf-8") as f:
        return Selector(text=f.read())


def test_normalize_actor_name_simplified_to_traditional():
    assert normalize_actor_name("樱空桃") == "櫻空桃"
    assert normalize_actor_name("深田咏美") == "深田詠美"
    assert normalize_actor_name("筱田优") == "篠田優"


def test_normalize_actor_name_alias():
    assert normalize_actor_name("藤森理穗") == "藤森裏穂"
    assert normalize_actor_name("筱田") == "篠田"


def test_normalize_actor_name_no_change():
    assert normalize_actor_name("葵つかさ") == "葵つかさ"
    assert normalize_actor_name("") == ""


def test_site_enum():
    assert JavdbApiCrawler.site() == Website.JAVDB_API


def test_display_name():
    assert JavdbApiCrawler.display_name() == "JavDB API"


def test_supports_custom_url():
    assert JavdbApiCrawler.supports_custom_url() is True


def test_parse_search_list():
    html = _load_html("search_list.html")
    hrefs = html.xpath("//a[@class='box']")
    assert len(hrefs) == 3

    items = []
    for each in hrefs:
        href = each.xpath("@href").get()
        code = each.xpath("div[@class='video-title']/strong/text()").get()
        title = each.xpath("div[@class='video-title']/text()").get()
        meta = each.xpath("div[@class='meta']/text()").get()
        score = each.xpath("div[@class='score']/text()").get()
        cover = each.xpath("div[@class='cover']/img/@src").get()
        items.append((href, code, title, meta, score, cover))

    assert len(items) == 3
    assert items[0][0] == "/v/abc123"
    assert items[0][1] == "IPX-535"
    assert items[1][1] == "SSIS-001"
    assert items[2][2] == " Title C"


@pytest.mark.asyncio
async def test_parse_search_page_matches_exact():
    crawler = JavdbApiCrawler(client=None)
    html = _load_html("search_list.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "IPX-535"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is not None
    assert any("abc123" in url for url in result)


@pytest.mark.asyncio
async def test_parse_search_page_matches_fuzzy():
    crawler = JavdbApiCrawler(client=None)
    html = _load_html("search_single.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "URE-018"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is not None
    assert any("xyz000" in url for url in result)


@pytest.mark.asyncio
async def test_parse_search_page_no_match():
    crawler = JavdbApiCrawler(client=None)
    html = _load_html("search_single.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "ZZZ-999"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is None


@pytest.mark.asyncio
async def test_parse_search_page_bf_not_matched_by_abf():
    crawler = JavdbApiCrawler(client=None)
    html = _load_html("search_list.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "BF-030"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is None


@pytest.mark.asyncio
async def test_parse_search_page_abf_still_matches():
    crawler = JavdbApiCrawler(client=None)
    html = _load_html("search_list.html")
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "ABF-030"
    result = await crawler._parse_search_page(ctx, html, "http://test/search")
    assert result is not None
    assert any("ghi789" in url for url in result)


@pytest.mark.asyncio
async def test_generate_search_url():
    crawler = JavdbApiCrawler(client=None)
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "IPX-535"
    urls = await crawler._generate_search_url(ctx)
    assert len(urls) == 1
    assert "f=all" in urls[0]
    assert "q=IPX-535" in urls[0]


@pytest.mark.asyncio
async def test_fetch_search_preserves_q_param(monkeypatch):
    """回归保护: _fetch_search 必须保留搜索 URL 的 q=番号 参数, 不能硬编码成无 q 的路径."""
    crawler = JavdbApiCrawler(client=None)
    captured = {}

    async def fake_try_mirrors(ctx, path: str, request_type: str):
        captured["path"] = path
        captured["request_type"] = request_type
        return "<html>ok</html>", ""

    monkeypatch.setattr(crawler, "_try_mirrors", fake_try_mirrors)
    monkeypatch.setattr(crawler, "_throttle_page_request", lambda *a, **k: __import__("asyncio").sleep(0))

    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    search_url = "https://mirror/search?f=all&q=IPX-535&page=1"
    html, error = await crawler._fetch_search(ctx, search_url)

    assert html == "<html>ok</html>"
    assert "q=IPX-535" in captured["path"], f"搜索 path 丢了 q 参数: {captured['path']}"
    assert "f=all" in captured["path"]
    assert captured["request_type"] == "搜索"


@pytest.mark.asyncio
async def test_parse_detail_full():
    html = _load_html("detail_full.html")
    crawler = JavdbApiCrawler(client=None)
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())

    data = await crawler.parser.parse(ctx, html, external_id="XzkY4")

    assert data.number == "IPX-535"
    assert data.title == "3・2・1 GO！ いきなり追撃ピストンSEX"
    assert data.originaltitle == "3・2・1 GO！ いきなり追撃ピストンSEX"
    assert data.actors == ["桜空もも"]
    assert data.all_actors == ["桜空もも", "男優A"]
    assert data.studio == "エスワン"
    assert data.publisher == "S1 NO.1 STYLE"
    assert data.series == "S1 系列"
    assert data.release == "2024-01-15"
    assert data.year == "2024"
    assert data.runtime == "120"
    assert data.tags == ["ドラマ", "ギリモザ"]
    assert data.thumb == "https://c0.jdbstatic.com/covers/xz/XzkY4.jpg"
    assert data.extrafanart == [
        "https://c0.jdbstatic.com/samples/xz/XzkY4_1.jpg",
        "https://c0.jdbstatic.com/samples/xz/XzkY4_2.jpg",
    ]
    assert data.trailer == "https://video.example.com/preview.mp4"
    assert data.directors == ["監督A"]
    assert data.external_id == "XzkY4"


@pytest.mark.asyncio
async def test_parse_detail_minimal():
    html = _load_html("detail_minimal.html")
    crawler = JavdbApiCrawler(client=None)
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "MIDV-512"

    data = await crawler.parser.parse(ctx, html, external_id="midv512")

    assert data.number == "MIDV-512"
    assert data.title == "MIDV Title"
    assert data.originaltitle == ""
    assert data.actors == ["女優B"]
    assert data.studio == "MOODYZ"
    assert data.release == "2024-06-01"
    assert data.runtime == "150"
    assert data.tags == ["高清"]
    assert data.thumb == "https://c0.jdbstatic.com/covers/mi/midv512.jpg"
    assert data.extrafanart == []
    assert data.trailer == ""


@pytest.mark.asyncio
async def test_post_process_fixes():
    from mdcx.crawlers.base.base_types import CrawlerData

    crawler = JavdbApiCrawler(client=None)
    data = CrawlerData(
        number="IPX-535",
        title="IPX Title",
        thumb="https://c0.jdbstatic.com/covers/xz/XzkY4.jpg",
        trailer="//example.com/trailer.mp4",
    )
    result = data.to_result()
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    result = await crawler.post_process(ctx, result)

    assert result.poster == "https://c0.jdbstatic.com/thumbs/xz/XzkY4.jpg"
    assert result.trailer == "https://example.com/trailer.mp4"
    assert result.originaltitle == "IPX Title"
    assert result.mosaic == "有码"


@pytest.mark.asyncio
async def test_post_process_uncensored():
    from mdcx.crawlers.base.base_types import CrawlerData

    crawler = JavdbApiCrawler(client=None)
    data = CrawlerData(
        number="TEST-001",
        title="無碼 Title",
        thumb="https://c0.jdbstatic.com/covers/xx/test.jpg",
    )
    result = data.to_result()
    from mdcx.crawlers.base.base_types import Context

    ctx = Context(input=CrawlerInput.empty())
    result = await crawler.post_process(ctx, result)

    assert result.mosaic == "无码"


def test_score_parsing():
    html = _load_html("detail_full.html")
    score = html.xpath("//span[@class='score-stars']/../text()").get()
    m = re.search(r"(\d{1}\.\d+)", score)
    assert m is not None
    assert m.group(1) == "8.5"


def test_wanted_matches():
    html_text = _load_html("detail_full.html").get()
    m = re.search(r"(\d+)(人想看| want to watch it)", html_text)
    assert m is None


def test_copy_uses_direct_url():
    crawler = JavdbApiCrawler(client=None)
    assert crawler._get_headers(None) is None or "cookie" in (crawler._get_headers(None) or {})


def test_search_candidates_adds_base_for_dmm_z_suffix():
    # 议题 #106：DMM `z` 尾缀番号在 javdb 收录为基础番号，搜索候选应附带
    assert JavdbApiCrawler._search_candidates("IBW-786Z") == ["IBW-786Z", "IBW-786"]
    assert JavdbApiCrawler._search_candidates("BF-030") == ["BF-030"]
