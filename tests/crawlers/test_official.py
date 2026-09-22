import pytest

from mdcx.config.enums import Language, Website
from mdcx.config.manager import manager
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.official import OfficialCrawler
from mdcx.models.model_types import CrawlerInput


class FakeOfficialClient:
    async def get_text(self, url, **kwargs):
        if url == "https://s1s1s1.com/search/list?keyword=SSIS001":
            return (
                """
                <html><body>
                  <a class="img hover" href="https://s1s1s1.com/works/detail/ssis001">
                    <img data-src="https://example.test/poster.jpg" />
                  </a>
                </body></html>
                """,
                "",
            )
        if url == "https://s1s1s1.com/works/detail/ssis001":
            return _detail_html(), ""
        if url == "https://faleno.jp/top/?s=jimmy 003":
            return (
                """
                <html><body>
                  <div class="text_name">
                    <a href="https://faleno.jp/top/works/jimmy003/">JIMMY-003</a>
                  </div>
                  <a><img src="https://example.test/jimmy003-search.jpg"></a>
                </body></html>
                """,
                "",
            )
        if url == "https://faleno.jp/top/works/jimmy003/":
            return _faleno_detail_html(), ""
        return None, f"unexpected url: {url}"


def _faleno_detail_html() -> str:
    return """
    <html><body>
      <h1>Faleno Official Title</h1>
      <div class="box_works01_text"><p>Faleno outline</p></div>
      <div class="box_works01_list">
        <ul>
          <li class="clearfix"><span>収録時間</span><p>120分</p></li>
          <li class="clearfix"><span>出演女優</span><p>Actor F</p></li>
          <li class="clearfix"><span>メーカー</span><p>FALENO</p></li>
        </ul>
      </div>
      <a class="pop_sample" href="https://example.test/jimmy003.mp4">
        <img src="https://example.test/jimmy003_1200.jpg?output-quality=60">
      </a>
      <a class="pop_img" href="https://example.test/jimmy003-extra.jpg"></a>
      <a class="genre">Drama</a>
    </body></html>
    """


def _detail_html() -> str:
    return """
    <html>
      <head><meta name="description" content="【公式】Publisher A(Studio A)" /></head>
      <body>
        <h2 class="p-workPage__title">Official Title</h2>
        <a class="c-tag c-main-bg-hover c-main-font c-main-bd" href="/actress/a">Actor A</a>
        <p class="p-workPage__text">Official outline</p>
        <div class="th">収録時間</div><div><div><p>120分</p></div></div>
        <div class="th">シリーズ</div><div><a>Series A</a></div>
        <div class="th">レーベル</div><div><a>Label A</a></div>
        <div class="th">監督</div><div><div><p>Director A</p></div></div>
        <div>発売日</div><div><div><a>2026年04月03日</a></div></div>
        <div>ジャンル</div><div><div><a>Genre A</a><a>Blu-ray（ブルーレイ）</a></div></div>
        <img class="swiper-lazy" data-src="https://example.test/cover.jpg" />
        <img class="swiper-lazy" data-src="https://example.test/extra.jpg" />
        <div class="video"><video src="https://example.test/trailer.mp4"></video></div>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_official_crawler_uses_prefix_mapping_and_dynamic_source():
    manager.computed.official_websites = {"SSIS": "https://s1s1s1.com"}
    crawler = OfficialCrawler(client=FakeOfficialClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="SSIS-001",
            short_number="SSIS-001",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "s1s1s1"
    assert res.data.number == "SSIS-001"
    assert res.data.title == "Official Title"
    assert res.data.actors == ["Actor A"]
    assert res.data.outline == "Official outline"
    assert res.data.release == "2026-04-03"
    assert res.data.year == "2026"
    assert res.data.runtime == "120"
    assert res.data.series == "Series A"
    assert res.data.directors == ["Director A"]
    assert res.data.tags == ["Genre A"]
    assert res.data.publisher == "Label A"
    assert res.data.studio == "Studio A"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.poster == "https://example.test/poster.jpg"
    assert res.data.extrafanart == ["https://example.test/extra.jpg"]
    assert res.data.trailer == "https://example.test/trailer.mp4"


def test_official_crawler_is_registered():
    assert get_crawler(Website.OFFICIAL) is OfficialCrawler


@pytest.mark.asyncio
async def test_official_crawler_jimmy_prefix_routes_to_faleno():
    crawler = OfficialCrawler(client=FakeOfficialClient())
    res = await crawler.run(
        CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="",
            number="JIMMY-003",
            short_number="JIMMY-003",
            language=Language.JP,
            org_language=Language.JP,
        )
    )

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "official"
    assert res.data.number == "JIMMY-003"
    assert res.data.title == "Faleno Official Title"
    assert res.data.actors == ["Actor F"]
    assert res.data.outline == "Faleno outline"
    assert "jimmy003" in res.data.thumb
    assert res.data.extrafanart == ["https://example.test/jimmy003-extra.jpg"]


def test_official_description_three_tier_and_check_scope():
    """议题 #165: 站点描述须讲清「有码 30 家 + 无码 5 站 + 检测仅覆盖无码五站」,
    防止再被读成 official 只有无码路由。"""
    from mdcx.crawlers.official import OfficialCrawler

    desc = OfficialCrawler.site_description()
    assert "有码 30" in desc, "有码官网档位必须出现在描述中"
    assert "无码 5 站" in desc
    assert "检测网络" in desc or "「检测网络」" in desc, "须注明检测覆盖面与抓取面的差异"
    assert desc.index("有码 30") < desc.index("无码 5 站"), "有码在前, 与路由主体构成一致"
