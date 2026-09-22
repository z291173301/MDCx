"""aventertainments 爬虫测试"""

import re

import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers import get_crawler
from mdcx.crawlers.aventertainments import AventertainmentsCrawler
from mdcx.models.model_types import CrawlerInput


def test_aventertainments_crawler_is_registered():
    """测试爬虫已注册"""
    crawler_cls = get_crawler(Website.AVENTERTAINMENTS)
    assert crawler_cls is AventertainmentsCrawler


def test_aventertainments_ppv_vs_dvd_detection():
    """测试 PPV/DVD 番号类型识别"""
    ppv_numbers = ["082226_001", "010125001", "123456_789", "082226-001"]
    dvd_numbers = ["SSDV-120", "ABC-123", "HEYZO-3924"]

    for num in ppv_numbers:
        is_ppv = bool(re.match(r"^\d{6}[-_]?\d{1,3}$", num))
        assert is_ppv, f"{num} 应识别为 PPV"

    for num in dvd_numbers:
        is_ppv = bool(re.match(r"^\d{6}[-_]?\d{1,3}$", num))
        assert not is_ppv, f"{num} 应识别为 DVD"


def test_aventertainments_dl_prefix_removal():
    """测试 DL 前缀去除"""
    test_cases = [
        ("DL1pon_082226_001", "1pon_082226_001"),
        ("DLcarib_082226-001", "carib_082226-001"),
        ("dl1pondo_010125-001", "1pondo_010125-001"),
        ("SSDV-120", "SSDV-120"),  # 无 DL 前缀
    ]

    for raw, expected in test_cases:
        cleaned = re.sub(r"^DL", "", raw, flags=re.IGNORECASE)
        assert cleaned == expected, f"Expected {expected}, got {cleaned}"


@pytest.mark.asyncio
async def test_aventertainments_generate_ppv_search_url():
    """测试生成 PPV 搜索 URL"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "082226_001"
    ctx = crawler.new_context(inp)

    url = await crawler._generate_search_url(ctx)

    await client.close()

    assert url is not None
    assert "/ppv/search" in url
    assert "082226_001" in url
    assert ctx.is_ppv is True


@pytest.mark.asyncio
async def test_aventertainments_generate_dvd_search_url():
    """测试生成 DVD 搜索 URL"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "SSDV-120"
    ctx = crawler.new_context(inp)

    url = await crawler._generate_search_url(ctx)

    await client.close()

    assert url is not None
    assert "/dvd/search" in url
    assert "SSDV-120" in url
    assert ctx.is_ppv is False


@pytest.mark.asyncio
async def test_aventertainments_parse_search_page():
    """测试解析搜索页"""
    from mdcx.web_async import AsyncWebClient

    html = """
    <html>
    <a href="/ppv/detail?pro=104440&lang=2&culture=ja-JP&v=1">Detail</a>
    <a href="/ppv/detail?pro=104439&lang=2&culture=ja-JP&v=1">Detail</a>
    <a href="/ppv/detail?pro=104440&lang=2&culture=ja-JP&v=1">Duplicate</a>
    </html>
    """

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "082226_001"
    ctx = crawler.new_context(inp)
    ctx.is_ppv = True

    sel = Selector(text=html)
    urls = await crawler._parse_search_page(ctx, sel, "test_url")

    await client.close()

    assert urls is not None
    assert len(urls) == 2  # 去重后
    assert "pro=104440" in urls[0]
    assert "pro=104439" in urls[1]


@pytest.mark.asyncio
async def test_aventertainments_parse_ppv_detail():
    """测试解析 PPV 详情页"""
    from mdcx.web_async import AsyncWebClient

    html = """
    <html>
    <head><title>Test</title></head>
    <body>
        <span class="tag-title">DL1pon_082226_001</span>
        <h1 class="mb-10">朝ゴミ出しする近所の遊び好きノーブラ奥さん</h1>
        <a href="/ppv/idoldetail?idol=さくらみな">さくらみな</a>
        <div class="product-description mt-20">
            艶やかな色気と時折見せるエロ可愛らしさが、魅力のさくらみなさんが登場。
        </div>
        <div class="value-category">
            <a href="#">人妻</a>
            <a href="#">巨乳</a>
        </div>
        <a href="/ppv/series?series=2088">朝ゴミシリーズ</a>
        <img src="https://imgs02.aventertainments.com/vodimages/xlarge/1pon_082226_001.webp" />
        <strong>配信開始日</strong> 2022/08/26
        <strong>収録時間</strong> 60分
    </body>
    </html>
    """

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "082226_001"
    ctx = crawler.new_context(inp)
    ctx.search_keyword = "082226_001"

    sel = Selector(text=html)
    data = await crawler._parse_detail_page(ctx, sel, "https://www.aventertainments.com/ppv/detail?pro=104440")

    await client.close()

    assert data is not None
    assert data.number == "1pon_082226_001"  # DL 前缀被去除
    assert data.title == "朝ゴミ出しする近所の遊び好きノーブラ奥さん"
    assert "さくらみな" in data.actors
    assert "艶やかな色気" in data.outline
    assert len(data.tags) == 2
    assert "人妻" in data.tags
    assert data.series == "朝ゴミシリーズ"
    assert data.thumb == "https://imgs02.aventertainments.com/vodimages/xlarge/1pon_082226_001.webp"
    assert data.release == "2022-08-26"
    assert data.year == "2022"
    assert data.runtime == "60"
    assert data.mosaic == "无码"


@pytest.mark.asyncio
async def test_aventertainments_parse_dvd_detail():
    """测试解析 DVD 详情页"""
    from mdcx.web_async import AsyncWebClient

    html = """
    <html>
    <body>
        <span class="tag-title">SSDV-120</span>
        <h1>素人作品标题</h1>
        <a href="/dvd/idoldetail?idol=山田萌">山田萌</a>
        <div class="product-description mt-20">
            本日撮影にきてくれたのは笑顔がキュートな萌さん。
        </div>
        <a href="/dvd/studio?studio=123">厂牌名</a>
    </body>
    </html>
    """

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "SSDV-120"
    ctx = crawler.new_context(inp)
    ctx.search_keyword = "SSDV-120"

    sel = Selector(text=html)
    data = await crawler._parse_detail_page(ctx, sel, "https://www.aventertainments.com/dvd/detail?pro=141963")

    await client.close()

    assert data is not None
    assert data.number == "SSDV-120"
    assert data.title == "素人作品标题"
    assert "山田萌" in data.actors
    assert "本日撮影" in data.outline
    assert data.studio == "厂牌名"
    assert data.mosaic == "无码"


@pytest.mark.asyncio
async def test_aventertainments_number_matching():
    """测试番号匹配逻辑"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    # 测试精确匹配（下划线）
    assert crawler._match_number("082226_001", "DL1pon_082226_001") is True

    # 测试精确匹配（横杠）
    assert crawler._match_number("082226-001", "DLcarib_082226-001") is True

    # 测试模糊匹配（分隔符不同）
    assert crawler._match_number("082226_001", "DLcarib_082226-001") is True

    # 测试不匹配
    assert crawler._match_number("082226_001", "DL1pon_082227_001") is False
    assert crawler._match_number("SSDV-120", "SSDV-121") is False

    await client.close()


@pytest.mark.network
@pytest.mark.asyncio
async def test_aventertainments_ppv_real_search():
    """真实网络测试：PPV 番号 082226_001"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "082226_001"

    result = await crawler.run(inp)

    await client.close()

    assert result.data is not None, f"搜索失败: {result.debug_info}"
    assert result.data.number
    # 应该匹配 1pondo（因为搜索返回顺序中 1pondo 在前）
    assert "1pon" in result.data.number.lower() or "082226" in result.data.number.replace("-", "").replace("_", "")
    assert result.data.actors
    assert result.data.outline
    assert result.data.thumb
    assert result.data.mosaic == "无码"


@pytest.mark.network
@pytest.mark.asyncio
async def test_aventertainments_ppv_carib_search():
    """真实网络测试：Caribbeancom PPV 番号 082226-001"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "082226-001"  # 横杠格式，应只匹配 carib

    result = await crawler.run(inp)

    await client.close()

    assert result.data is not None, f"搜索失败: {result.debug_info}"
    assert result.data.number
    assert "carib" in result.data.number.lower()
    assert result.data.mosaic == "无码"


@pytest.mark.network
@pytest.mark.asyncio
async def test_aventertainments_dvd_real_search():
    """真实网络测试：DVD 番号 SSDV-120"""
    from mdcx.web_async import AsyncWebClient

    client = AsyncWebClient(timeout=30)
    crawler = AventertainmentsCrawler(client=client, browser=None)

    inp = CrawlerInput.empty()
    inp.number = "SSDV-120"

    result = await crawler.run(inp)

    await client.close()

    assert result.data is not None, f"搜索失败: {result.debug_info}"
    assert result.data.number == "SSDV-120"
    assert result.data.actors
    assert result.data.outline
    assert result.data.mosaic == "无码"
