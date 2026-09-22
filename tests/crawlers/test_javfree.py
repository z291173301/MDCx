import asyncio

from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.javfree import (
    JavfreeCrawler,
    _match_number,
    classify_mosaic,
    extract_number_candidates,
    parse_metadata_lines,
    parse_title,
)
from mdcx.models.model_types import CrawlerInput


def test_extract_number_candidates_standard():
    assert extract_number_candidates("SSNI-647") == ["SSNI-647"]
    assert extract_number_candidates("SSNI647") == ["SSNI-647"]


def test_extract_number_candidates_fc2_variants():
    assert extract_number_candidates("FC2-4965111") == ["FC2-PPV-4965111"]
    assert extract_number_candidates("FC2-PPV-4965111") == ["FC2-PPV-4965111"]
    assert extract_number_candidates("FC2PPV-4965111") == ["FC2-PPV-4965111"]


def test_extract_number_candidates_prefers_appoint_number():
    # appoint_number 与 number 都会作为候选（搜索依次尝试），appoint_number 在前
    assert extract_number_candidates("SSNI-647", appoint_number="HEYZO-3924") == ["HEYZO-3924", "SSNI-647"]


def test_extract_number_candidates_from_file_path():
    assert extract_number_candidates("", file_path="C:/movies/SSNI-647.mp4") == ["SSNI-647"]


def test_match_number_requires_digit_boundary():
    assert _match_number("SSNI647一ヶ月間", "SSNI647")
    assert not _match_number("SSNI6470一ヶ月間", "SSNI647")


def test_match_number_fc2_accepts_following_count_digits():
    # "FC2 PPV 4965111 30%OFF" 归一化后番号后紧跟计数 30，仍应命中
    assert _match_number("FC2PPV496511130OFF", "FC2PPV4965111")
    assert _match_number("FC2PPV4965111その女", "FC2PPV4965111")


def test_parse_title_bracket_form():
    assert parse_title("[SSNI-647] 一ヶ月間の禁欲の果てに 橋本ありな") == (
        "SSNI-647",
        "一ヶ月間の禁欲の果てに 橋本ありな",
    )


def test_parse_title_fc2_form():
    assert parse_title("FC2 PPV 4965111 30%OFF! その女") == ("FC2-4965111", "30%OFF! その女")


def test_parse_title_heyzo_form():
    assert parse_title("Heyzo 3924 敏感フリーター娘 SNSで募集したら") == (
        "HEYZO-3924",
        "敏感フリーター娘 SNSで募集したら",
    )


def test_parse_title_fallback():
    assert parse_title("没有番号的标题") == ("", "没有番号的标题")


def test_parse_metadata_lines_fields_and_outline():
    blockquote = (
        "<blockquote><p>発売日： 2019/12/19<br />"
        "収録時間： 120分<br />"
        "出演者： 橋本ありな<br />"
        "監督： 朝霧浄<br />"
        "シリーズ： 一ヶ月間の禁欲の果てに彼女の親友と僕が浮気SEX<br />"
        "メーカー： エスワン ナンバーワンスタイル<br />"
        "レーベル： S1 NO.1 STYLE<br />"
        "ジャンル： 美少女 スレンダー 単体作品<br />"
        "品番： <strong>ssni647</strong><br />"
        "AV業界で一大流行している不在NTRドラマ、その元祖作品。"
        "</p></blockquote>"
    )
    fields, outline = parse_metadata_lines(blockquote)
    assert fields["発売日"] == "2019/12/19"
    assert fields["収録時間"] == "120分"
    assert fields["出演者"] == "橋本ありな"
    assert fields["監督"] == "朝霧浄"
    assert fields["メーカー"] == "エスワン ナンバーワンスタイル"
    assert fields["レーベル"] == "S1 NO.1 STYLE"
    assert fields["ジャンル"] == "美少女 スレンダー 単体作品"
    assert fields["品番"] == "ssni647"
    assert outline == "AV業界で一大流行している不在NTRドラマ、その元祖作品。"


def test_classify_mosaic():
    assert classify_mosaic("mosaic/s1") == "有码"
    assert classify_mosaic("mosaic") == "有码"
    assert classify_mosaic("avi/fc2") == "无码"
    assert classify_mosaic("avi/heyzo") == "无码"
    assert classify_mosaic("demosaic") == "无码"
    assert classify_mosaic("") == "无码"


def test_generate_search_url_standard():
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "SSNI-647"
    urls = asyncio.run(crawler._generate_search_url(ctx))
    assert urls == ["https://javfree.me/?s=SSNI-647"]


def test_generate_search_url_fc2():
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "FC2-4965111"
    urls = asyncio.run(crawler._generate_search_url(ctx))
    assert urls == ["https://javfree.me/?s=FC2-PPV-4965111"]


def test_parse_search_page_matching_result():
    html = Selector(
        text="""
        <html><body>
          <div class="content-loop post-loop clear">
            <article class="hentry clear">
              <a class="thumbnail-link" href="https://javfree.me/127653/ipx-078">
                <div class="thumbnail-wrap">
                  <span class="tag-con-decensored">Decensored</span>
                  <img src="//cf.javfree.me/cover/320x216/IPX-078.jpg" alt="" />
                </div>
              </a>
              <h2 class="entry-title"><a href="https://javfree.me/127653/ipx-078">[IPX-078] 別タイトル</a></h2>
              <div class="entry-meta">
                <span class="entry-category">
                  <a href="https://javfree.me/category/mosaic/ideapocket" title="View all posts in IdeaPocket">IdeaPocket</a>
                </span>
              </div>
            </article>
            <article class="hentry clear">
              <a class="thumbnail-link" href="https://javfree.me/171620/ssni-647">
                <div class="thumbnail-wrap">
                  <span class="tag-con-decensored">Decensored</span>
                  <img src="//cf.javfree.me/cover/320x216/SSNI-647.jpg" alt="" />
                </div>
              </a>
              <h2 class="entry-title"><a href="https://javfree.me/171620/ssni-647">[SSNI-647] 一ヶ月間の禁欲の果てに 橋本ありな</a></h2>
              <div class="entry-meta">
                <span class="entry-category">
                  <a href="https://javfree.me/category/mosaic/s1" title="View all posts in S1">S1</a>
                </span>
              </div>
            </article>
          </div>
        </body></html>
        """
    )
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.number_candidates = ["SSNI-647"]
    urls = asyncio.run(crawler._parse_search_page(ctx, html, "https://javfree.me/?s=SSNI-647"))
    assert urls == ["https://javfree.me/171620/ssni-647"]
    assert ctx.search_cover_url == "https://cf.javfree.me/cover/320x216/SSNI-647.jpg"
    assert ctx.category_path == "mosaic/s1"


def test_parse_search_page_no_match_returns_none():
    html = Selector(
        text="""
        <html><body>
          <article class="hentry clear">
            <a class="thumbnail-link" href="https://javfree.me/171620/ssni-647">
              <img src="//cf.javfree.me/cover/320x216/SSNI-647.jpg" alt="" />
            </a>
            <h2 class="entry-title"><a href="https://javfree.me/171620/ssni-647">[SSNI-647] 一ヶ月間</a></h2>
          </article>
        </body></html>
        """
    )
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.number_candidates = ["IPX-078"]
    urls = asyncio.run(crawler._parse_search_page(ctx, html, "https://javfree.me/?s=IPX-078"))
    assert urls is None


def test_parse_detail_page_extracts_fields():
    html = Selector(
        text="""
        <html><body>
          <h1 class="entry-title">[SSNI-647] 一ヶ月間の禁欲の果てに 橋本ありな</h1>
          <div class="entry-content">
            <blockquote><p>
              発売日： 2019/12/19<br />
              収録時間： 120分<br />
              出演者： 橋本ありな<br />
              監督： 朝霧浄<br />
              シリーズ： 一ヶ月間の禁欲<br />
              メーカー： エスワン ナンバーワンスタイル<br />
              レーベル： S1 NO.1 STYLE<br />
              ジャンル： 美少女 スレンダー 単体作品<br />
              品番： <strong>ssni647</strong><br />
              AV業界で一大流行している不在NTRドラマ。
            </p></blockquote>
            <img src="//cf.javfree.me/HLIC/SSNI-647.jpg" />
            <img src="//cf.javfree.me/HLIC/SSNI-647-demosaic.jpeg" />
            <img src="//cf.javfree.me/HLIC/SSNI-647-1.jpg" />
          </div>
        </body></html>
        """
    )
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.number_candidates = ["SSNI-647"]
    ctx.category_path = "mosaic/s1"
    data = asyncio.run(crawler._parse_detail_page(ctx, html, "https://javfree.me/171620/ssni-647"))
    assert data.number == "SSNI-647"
    assert data.title == "一ヶ月間の禁欲の果てに 橋本ありな"
    assert data.actors == ["橋本ありな"]
    assert data.directors == ["朝霧浄"]
    assert data.studio == "エスワン ナンバーワンスタイル"
    assert data.publisher == "S1 NO.1 STYLE"
    assert data.tags == ["美少女", "スレンダー", "単体作品"]
    assert data.release == "2019-12-19"
    assert data.year == "2019"
    assert data.runtime == "120"
    assert data.outline == "AV業界で一大流行している不在NTRドラマ。"
    assert data.thumb == "https://cf.javfree.me/HLIC/SSNI-647.jpg"
    assert data.extrafanart == ["https://cf.javfree.me/HLIC/SSNI-647-1.jpg"]
    assert data.mosaic == "有码"


def test_parse_detail_page_fc2_fields():
    html = Selector(
        text="""
        <html><body>
          <h1 class="entry-title">FC2 PPV 4965111 30%OFF! その女</h1>
          <div class="entry-content">
            <blockquote><p>30%OFF! その女、セックスレスにつき。登録数 66</p></blockquote>
            <p>販売日 : 2026/08/22</p>
            <p>商品ID : FC2 PPV 4965111</p>
            <img src="//cf.javfree.me/HLIC/FC2-PPV-4965111.jpg" />
          </div>
        </body></html>
        """
    )
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.category_path = "avi/fc2"
    data = asyncio.run(crawler._parse_detail_page(ctx, html, "https://javfree.me/447225/fc2-ppv-4965111"))
    assert data.number == "FC2-4965111"
    assert data.release == "2026-08-22"
    assert data.year == "2026"
    assert data.mosaic == "无码"


def test_parse_detail_page_category_fallback_uses_deepest_parent():
    html = Selector(
        text="""
        <html><body>
          <h1 class="entry-title">[IPX-078] タイトル</h1>
          <div class="entry-content">
            <blockquote><p>品番： <strong>ipx-078</strong><br /></p></blockquote>
          </div>
          <nav id="primary-nav" class="main-navigation">
            <ul id="primary-menu" class="sf-menu">
              <li class="menu-item menu-item-object-category current-post-ancestor"><a href="https://javfree.me/category/mosaic">Censored</a></li>
              <li class="menu-item menu-item-object-category current-post-ancestor current-post-parent"><a href="https://javfree.me/category/mosaic/ideapocket">IdeaPocket</a></li>
              <li class="menu-item menu-item-object-category current-post-ancestor current-post-parent"><a href="https://javfree.me/category/avi">Uncensored</a></li>
              <li class="menu-item menu-item-object-category current-post-ancestor current-post-parent"><a href="https://javfree.me/category/demosaic">Decensored</a></li>
            </ul>
          </nav>
        </body></html>
        """
    )
    crawler = JavfreeCrawler(client=None, base_url="https://javfree.me", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    data = asyncio.run(crawler._parse_detail_page(ctx, html, "https://javfree.me/127653/ipx-078"))
    assert data.mosaic == "有码"


def test_javfree_crawler_is_registered():
    assert get_crawler(Website.JAVFREE) is JavfreeCrawler
