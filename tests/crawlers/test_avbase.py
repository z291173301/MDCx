import pytest

import mdcx.crawlers.avbase as avbase_module
from mdcx.crawlers.avbase import AvbaseCrawler
from mdcx.models.model_types import CrawlerInput


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("55", "55"),
        ("収録分数 55", "55"),
        ("収録分数 0:55:00", "55"),
        ("収録分数 00:55:00", "55"),
        ("収録分数 1:05:30", "65"),
        ("収録分数 0:00:30", "1"),
    ],
)
def test_parse_runtime(raw: str, expected: str):
    assert AvbaseCrawler._parse_runtime(raw) == expected


@pytest.mark.asyncio
async def test_post_process_uses_dmm_validation_for_dmm_thumb_and_poster(monkeypatch: pytest.MonkeyPatch):
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        if url.endswith("ps.jpg"):
            return None
        return url

    monkeypatch.setattr(avbase_module, "check_url", fake_check_url)

    crawler = AvbaseCrawler(client=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    result = avbase_module.CrawlerData(
        title="VR SAMPLE",
        thumb="https://pics.dmm.co.jp/mono/movie/adult/pred816/pred816pl.jpg",
        studio="",
    ).to_result()

    processed = await crawler.post_process(ctx, result)

    assert processed.thumb == "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg"
    assert processed.poster == ""
    assert processed.image_download is False
    assert called_urls == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816pl.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/mono/movie/pred816/pred816ps.jpg",
    ]


@pytest.mark.asyncio
async def test_sanitize_extrafanart_urls_upgrades_full_batch_without_probe(
    monkeypatch: pytest.MonkeyPatch,
):
    """剧照「有就下、没有就没有」：全量做 pics→aws 无水印域名替换，不抽检、不预下载、不按字节卡。"""
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        return url

    monkeypatch.setattr(avbase_module, "check_url", fake_check_url)
    crawler = AvbaseCrawler(client=None)

    result = await crawler._sanitize_extrafanart_urls(
        [
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample2.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample3.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/unchecked.jpg",
        ]
    )

    # 全量升级 AWS 无水印路径，一张不丢
    assert result == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample2.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample3.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/unchecked.jpg",
    ]
    # 不再发起抽检预下载，check_url 未被调用
    assert called_urls == []


@pytest.mark.asyncio
async def test_sanitize_extrafanart_urls_dedupes_and_skips_blank():
    """重复剧照去重，非 DMM 原样保留。"""
    crawler = AvbaseCrawler(client=None)

    result = await crawler._sanitize_extrafanart_urls(
        [
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://example.com/other.jpg",
        ]
    )

    assert result == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://example.com/other.jpg",
    ]


@pytest.mark.asyncio
async def test_upgrade_dmm_image_url_falls_back_to_prefix_table(monkeypatch: pytest.MonkeyPatch):
    """特殊前缀系列（ABF）域名替换失败时，应回退到 dmm_direct 前缀表候选."""
    called_urls: list[str] = []

    async def fake_check_url(url: str, length: bool = False, real_url: bool = False):
        called_urls.append(url)
        # 域名替换候选（mono 路径）失败，仅前缀表候选 436abf00042pl.jpg 成功
        if "awsimgsrc.dmm.co.jp/pics_dig/mono/" in url:
            return None
        return url

    monkeypatch.setattr(avbase_module, "check_url", fake_check_url)

    crawler = AvbaseCrawler(client=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "ABF-042"

    result = await crawler._upgrade_dmm_image_url(
        ctx, "https://pics.dmm.co.jp/mono/movie/adult/118abf042/118abf042pl.jpg"
    )

    assert result == "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/436abf00042/436abf00042pl.jpg"
    assert "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/436abf00042/436abf00042pl.jpg" in called_urls


@pytest.mark.asyncio
async def test_sanitize_extrafanart_urls_keeps_blank_aws_urls_for_download_layer():
    """剧照全量升级后，失效图（aws 404/占位）交由下载层 now_printing/404 识别，抽检环节不再按字节丢弃。"""
    crawler = AvbaseCrawler(client=None)

    result = await crawler._sanitize_extrafanart_urls(
        [
            "https://pics.dmm.co.jp/digital/video/pred00816/sample1.jpg",
            "https://pics.dmm.co.jp/digital/video/pred00816/sample2.jpg",
        ]
    )

    # 两张都升级，不做任何可达性丢弃
    assert result == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample1.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/pred00816/sample2.jpg",
    ]
