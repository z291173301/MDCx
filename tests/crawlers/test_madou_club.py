import asyncio

from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.madou_club import (
    MadouClubCrawler,
    _extract_number_candidates,
    normalize_cover_url,
    parse_title,
)
from mdcx.models.model_types import CrawlerInput


def test_extract_number_candidates_includes_no_separator_form():
    assert "MDX0236" in _extract_number_candidates("MDX-0236")
    assert "MDX0236" in _extract_number_candidates("MDX0236")
    assert "MDX-0236" in _extract_number_candidates("MDX0236")


def test_normalize_cover_url_strips_thumbnail_size_suffix():
    url = "https://madou.club/covers/2022/02/cb5aaf891e0253b-240x180.jpg"
    assert normalize_cover_url(url) == "https://madou.club/covers/2022/02/cb5aaf891e0253b.jpg"


def test_normalize_cover_url_keeps_original_when_no_suffix():
    url = "https://madou.club/covers/2022/02/cb5aaf891e0253b.jpg"
    assert normalize_cover_url(url) == url


def test_parse_title_splits_number_and_title():
    assert parse_title("MDX0236-01 / 淫荡静香的偷腥体验") == ("MDX0236-01", "淫荡静香的偷腥体验")
    assert parse_title("MD0215 / 巨乳成人女星") == ("MD0215", "巨乳成人女星")


def test_parse_title_fallback_to_whole_text():
    assert parse_title("没有分隔符的标题") == ("", "没有分隔符的标题")


def test_generate_search_urls_use_no_separator_keyword():
    crawler = MadouClubCrawler(client=None, base_url="https://madou.club", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "MDX-0236"

    urls = asyncio.run(crawler._generate_search_url(ctx))

    assert urls == ["https://madou.club/?s=MDX0236"]


def test_parse_search_page_returns_matching_detail_urls():
    html = Selector(
        text="""
        <html><body>
          <div class="excerpts-wrapper"><div class="excerpts">
            <article class="excerpt excerpt-c5">
              <a class="thumbnail" href="https://madou.club/mdx0236-02.html">
                <img src="https://madou.club/showcase/img/thumb.png"
                     data-src="https://madou.club/covers/2022/02/ff073d78eaf9708-240x180.jpg" class="thumb">
              </a>
              <h2><a href="https://madou.club/mdx0236-02.html">MDX0236-02 / 青梅竹马淫乱3P</a></h2>
            </article>
            <article class="excerpt excerpt-c5">
              <a class="thumbnail" href="https://madou.club/mdx0236-01.html">
                <img src="https://madou.club/showcase/img/thumb.png"
                     data-src="https://madou.club/covers/2022/02/cb5aaf891e0253b-240x180.jpg" class="thumb">
              </a>
              <h2><a href="https://madou.club/mdx0236-01.html">MDX0236-01 / 淫荡静香的偷腥体验</a></h2>
            </article>
          </div></div>
        </body></html>
        """
    )

    crawler = MadouClubCrawler(client=None, base_url="https://madou.club", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.number_candidates = ["MDX0236"]

    detail_urls = asyncio.run(crawler._parse_search_page(ctx, html, "https://madou.club/?s=MDX0236"))

    assert detail_urls == [
        "https://madou.club/mdx0236-02.html",
        "https://madou.club/mdx0236-01.html",
    ]
    assert ctx.search_cover_url == "https://madou.club/covers/2022/02/ff073d78eaf9708.jpg"


def test_parse_detail_page_extracts_fields():
    html = Selector(
        text="""
        <html><body>
          <h1 class="article-title">MDX0236-01 / 淫荡静香的偷腥体验</h1>
          <div class="article-meta">
            <span class="item item-3">分类：<a href="/category/xx" rel="category tag">麻豆番外篇</a></span>
            <span class="item item-4">观看(34.97K)</span>
          </div>
          <div class="article-tags">
            <a href="/tag/cosplay" rel="tag">cosplay</a>
            <a href="/tag/美乳" rel="tag">美乳</a>
          </div>
        </body></html>
        """
    )

    crawler = MadouClubCrawler(client=None, base_url="https://madou.club", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.search_cover_url = "https://madou.club/covers/2022/02/cb5aaf891e0253b.jpg"

    data = asyncio.run(crawler._parse_detail_page(ctx, html, "https://madou.club/mdx0236-01.html"))

    assert data.number == "MDX0236-01"
    assert data.title == "淫荡静香的偷腥体验"
    assert data.studio == "麻豆番外篇"
    assert data.tags == ["cosplay", "美乳"]
    assert data.thumb == "https://madou.club/covers/2022/02/cb5aaf891e0253b.jpg"
    assert data.mosaic == "国产"
    assert data.external_id == "https://madou.club/mdx0236-01.html"


def test_madou_club_crawler_is_registered():
    assert get_crawler(Website.MADOUCLUB) is MadouClubCrawler
