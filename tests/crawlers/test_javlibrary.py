import pytest

from mdcx.config.enums import Language, Website
from mdcx.config.manager import manager
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.javlibrary import JavlibraryCrawler
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.models.model_types import CrawlerInput


class FakeJavlibraryClient:
    async def get_text(self, url, **kwargs):
        if url == "https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=FSDSS-200":
            return _search_html("/ja/?v=javtest200", "FSDSS-200 Japanese Title"), ""
        if url == "https://www.javlibrary.com/ja/?v=javtest200":
            return _detail_html("FSDSS-200 Japanese Title", "女優A"), ""
        if url == "https://www.javlibrary.com/cn/?v=javtest200":
            return _detail_html("FSDSS-200 中文标题", "演员A"), ""
        return None, f"unexpected url: {url}"


def _search_html(href: str, title: str) -> str:
    return f"""
    <html><body>
      <a href="{href}" title="{title}"></a>
    </body></html>
    """


def _detail_html(title: str, actor: str) -> str:
    return f"""
    <html><body>
      <div id="video_title"><h3><a>{title}</a></h3></div>
      <div id="video_id"><table><tr><td class="text">FSDSS-200</td></tr></table></div>
      <div id="video_cast"><table><tr><td class="text"><span><span class="star"><a>{actor}</a></span></span></td></tr></table></div>
      <img id="video_jacket_img" src="//img.example.test/cover.jpg" />
      <div id="video_genres"><table><tr><td class="text"><span><a>剧情</a></span></td></tr></table></div>
      <div id="video_date"><table><tr><td class="text">2026-04-03</td></tr></table></div>
      <div id="video_maker"><table><tr><td class="text"><span><a>制作商</a></span></td></tr></table></div>
      <div id="video_label"><table><tr><td class="text"><span><a>发行商</a></span></td></tr></table></div>
      <div id="video_length"><table><tr><td><span class="text">120</span></td></tr></table></div>
      <div id="video_review"><table><tr><td><span class="score">(4.20)</span></td></tr></table></div>
      <div id="video_director"><table><tr><td class="text"><span><a>导演A</a></span></td></tr></table></div>
      <a href="userswanted.php?mode=add">99</a>
    </body></html>
    """


def _detail_html_with_tbody(title: str, actor: str) -> str:
    """Selenium page_source 返回的 HTML 会被浏览器自动补全 <tbody> 标签。"""
    return f"""
    <html><body>
      <div id="video_title"><h3><a>{title}</a></h3></div>
      <div id="video_id"><table><tbody><tr><td class="text">FSDSS-200</td></tr></tbody></table></div>
      <div id="video_cast"><table><tbody><tr><td class="text"><span><span class="star"><a>{actor}</a></span></span></td></tr></tbody></table></div>
      <img id="video_jacket_img" src="//img.example.test/cover.jpg" />
      <div id="video_genres"><table><tbody><tr><td class="text"><span><a>剧情</a></span></td></tr></tbody></table></div>
      <div id="video_date"><table><tbody><tr><td class="text">2026-04-03</td></tr></tbody></table></div>
      <div id="video_maker"><table><tbody><tr><td class="text"><span><a>制作商</a></span></td></tr></tbody></table></div>
      <div id="video_label"><table><tbody><tr><td class="text"><span><a>发行商</a></span></td></tr></tbody></table></div>
      <div id="video_length"><table><tbody><tr><td><span class="text">120</span></td></tr></tbody></table></div>
      <div id="video_review"><table><tbody><tr><td><span class="score">(4.20)</span></td></tr></tbody></table></div>
      <div id="video_director"><table><tbody><tr><td class="text"><span><a>导演A</a></span></td></tr></tbody></table></div>
      <a href="userswanted.php?mode=add">99</a>
    </body></html>
    """


def _make_input(number: str = "FSDSS-200", language: Language = Language.ZH_CN) -> CrawlerInput:
    return CrawlerInput(
        appoint_number="",
        appoint_url="",
        file_path=None,
        mosaic="",
        number=number,
        short_number=number,
        language=language,
        org_language=language,
    )


@pytest.fixture(autouse=True)
def _mock_dmm_upgrade(monkeypatch):
    """Mock DMM 封面升级，避免测试网络请求。"""

    async def fake_upgrade(ctx, number, cover, poster):
        return cover, poster

    monkeypatch.setattr("mdcx.crawlers.dmm_direct.upgrade_dmm_cover", fake_upgrade)


@pytest.mark.asyncio
async def test_javlibrary_crawler_keeps_jp_original_title_for_zh_cn():
    manager.config.set_field_language(CrawlerResultFields.TITLE, Language.ZH_CN)
    crawler = JavlibraryCrawler(client=FakeJavlibraryClient(), base_url="https://www.javlibrary.com")
    res = await crawler.run(_make_input())

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.debug_info.search_urls == ["https://www.javlibrary.com/ja/vl_searchbyid.php?keyword=FSDSS-200"]
    assert res.debug_info.detail_urls == [
        "https://www.javlibrary.com/ja/?v=javtest200",
        "https://www.javlibrary.com/cn/?v=javtest200",
    ]
    assert res.data.source == "javlibrary"
    assert res.data.number == "FSDSS-200"
    assert res.data.title == "中文标题"
    assert res.data.originaltitle == "Japanese Title"
    assert res.data.actors == ["演员A"]
    assert res.data.tags == ["剧情"]
    assert res.data.release == "2026-04-03"
    assert res.data.year == "2026"
    assert res.data.runtime == "120"
    assert res.data.score == "4.20"
    assert res.data.directors == ["导演A"]
    assert res.data.studio == "制作商"
    assert res.data.publisher == "发行商"
    assert res.data.thumb == "https://img.example.test/cover.jpg"
    assert res.data.wanted == "99"


@pytest.mark.asyncio
async def test_javlibrary_xpath_compat_with_tbody():
    """验证 xpath 兼容 Selenium page_source 自动补全的 <tbody>。"""
    from lxml import etree

    html = _detail_html_with_tbody("FSDSS-200 Test Title", "女優A")
    tree = etree.fromstring(html, etree.HTMLParser())

    from mdcx.crawlers.javlibrary import (
        get_actor,
        get_cover,
        get_director,
        get_number,
        get_publisher,
        get_release,
        get_runtime,
        get_score,
        get_studio,
        get_tag,
        get_title,
    )

    assert get_title(tree) == "FSDSS-200 Test Title"
    assert get_number(tree, "FSDSS-200") == "FSDSS-200"
    assert get_actor(tree) == "女優A"
    assert get_tag(tree) == "剧情"
    assert get_release(tree) == "2026-04-03"
    assert get_runtime(tree) == "120"
    assert get_score(tree) == "4.20"
    assert get_studio(tree) == "制作商"
    assert get_publisher(tree) == "发行商"
    assert get_director(tree) == "导演A"
    assert get_cover(tree) == "https://img.example.test/cover.jpg"


@pytest.mark.asyncio
async def test_javlibrary_xpath_compat_without_tbody():
    """验证 xpath 兼容普通 HTTP 请求的无 <tbody> HTML。"""
    from lxml import etree

    html = _detail_html("FSDSS-200 Test Title", "女優A")
    tree = etree.fromstring(html, etree.HTMLParser())

    from mdcx.crawlers.javlibrary import (
        get_actor,
        get_cover,
        get_director,
        get_number,
        get_publisher,
        get_release,
        get_runtime,
        get_score,
        get_studio,
        get_tag,
        get_title,
    )

    assert get_title(tree) == "FSDSS-200 Test Title"
    assert get_number(tree, "FSDSS-200") == "FSDSS-200"
    assert get_actor(tree) == "女優A"
    assert get_tag(tree) == "剧情"
    assert get_release(tree) == "2026-04-03"
    assert get_runtime(tree) == "120"
    assert get_score(tree) == "4.20"
    assert get_studio(tree) == "制作商"
    assert get_publisher(tree) == "发行商"
    assert get_director(tree) == "导演A"
    assert get_cover(tree) == "https://img.example.test/cover.jpg"


def test_javlibrary_crawler_is_registered():
    assert get_crawler(Website.JAVLIBRARY) is JavlibraryCrawler


def test_parse_javlibcom_domain():
    from mdcx.base.web import _parse_javlibcom_domain

    html = '<a rel="nofollow me" href="https://www.f101w.com">https://www.f101w.com</a>'
    assert _parse_javlibcom_domain(html) == "https://www.f101w.com"
    # 属性顺序不同也能解析
    html2 = '<a href="https://www.c97k.com" rel="nofollow me">c97k</a>'
    assert _parse_javlibcom_domain(html2) == "https://www.c97k.com"
    # 非 me 链接忽略
    html3 = '<a rel="nofollow" href="https://www.javlibrary.com">x</a>'
    assert _parse_javlibcom_domain(html3) == ""
    # github 链接忽略
    html4 = '<a rel="nofollow me" href="https://github.com/user">x</a>'
    assert _parse_javlibcom_domain(html4) == ""


@pytest.mark.asyncio
async def test_get_javlibrary_domain_uses_cache(monkeypatch):
    import mdcx.base.web as web
    from mdcx.base.web import get_javlibrary_domain

    web._JAVLIBRARY_DOMAIN_CACHE.clear()

    async def fake_get_text(url, **kwargs):
        assert url == "https://github.com/javlibcom"
        return '<a rel="nofollow me" href="https://www.f101w.com">f101w</a>', ""

    class FakeComputed:
        async_client = None

    class FakeManager:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        class Computed:
            async_client = type("C", (), {"get_text": staticmethod(fake_get_text)})()

        @property
        def computed(self):
            return self.Computed()

    monkeypatch.setattr(web.manager, "acquire_computed", lambda: FakeManager())

    domain = await get_javlibrary_domain()
    assert domain == "https://www.f101w.com"
    # 缓存命中，第二次不重新请求
    domain2 = await get_javlibrary_domain()
    assert domain2 == "https://www.f101w.com"
    web._JAVLIBRARY_DOMAIN_CACHE.clear()


def test_selenium_cf_detection():
    """测试 CF 挑战页检测。"""
    from mdcx.cf_bypass.selenium_adapter import is_cf_html

    assert is_cf_html("<html><head><title>Just a moment...</title></head></html>")
    assert is_cf_html("<html><body>cf-chl challenge</body></html>")
    assert is_cf_html("<html><body>Checking your browser before accessing</body></html>")
    assert not is_cf_html("<html><body>Normal page content</body></html>")
    assert not is_cf_html("<html><head><title>SSNI-804 Detail</title></head></html>")


@pytest.mark.asyncio
async def test_selenium_bypass_disabled_when_config_off(monkeypatch):
    """配置关闭时 Selenium bypass 不触发，遇 CF 直接报错。"""
    monkeypatch.setattr(manager.config, "cf_selenium_bypass", False)

    selenium_called = False

    async def fake_get_html(url, timeout=90):
        nonlocal selenium_called
        selenium_called = True
        return None

    monkeypatch.setattr("mdcx.cf_bypass.selenium_adapter.get_html", fake_get_html)
    monkeypatch.setattr("mdcx.cf_bypass.selenium_adapter.is_available", lambda: True)

    class FakeClientWithCF:
        async def get_text(self, url, **kwargs):
            return "<html><title>Just a moment...</title></html>", ""

    crawler = JavlibraryCrawler(client=FakeClientWithCF(), base_url="https://www.javlibrary.com")
    res = await crawler.run(_make_input(language=Language.JP))

    assert res.data is None
    assert res.debug_info.error is not None
    assert "Cloudflare" in str(res.debug_info.error)
    assert not selenium_called


@pytest.mark.asyncio
async def test_post_process_upgrades_dmm_cover(monkeypatch):
    """post_process 调用 DMM 封面升级。"""
    upgrade_called = False
    upgrade_args = None

    async def fake_upgrade(ctx, number, cover, poster):
        nonlocal upgrade_called, upgrade_args
        upgrade_called = True
        upgrade_args = (number, cover, poster)
        return "https://dmm.hd/cover.jpg", "https://dmm.hd/poster.jpg"

    monkeypatch.setattr("mdcx.crawlers.dmm_direct.upgrade_dmm_cover", fake_upgrade)
    monkeypatch.setattr("mdcx.crawlers.dmm_direct.is_uncensored_number", lambda n: False)

    from mdcx.models.model_types import CrawlerResult

    res = CrawlerResult(
        number="SSNI-804",
        mosaic="有码",
        image_download=False,
        actors=[],
        all_actors=[],
        directors=[],
        extrafanart=[],
        originalplot="",
        originaltitle="",
        outline="",
        poster="",
        publisher="",
        release="",
        runtime="",
        score="0.0",
        series="",
        studio="",
        tags=[],
        thumb="https://original/cover.jpg",
        title="test",
        trailer="",
        wanted="",
        year="",
        source="javlibrary",
        external_id="",
    )

    crawler = JavlibraryCrawler(client=FakeJavlibraryClient(), base_url="https://www.javlibrary.com")
    result = await crawler.post_process(None, res)  # type: ignore[arg-type]

    assert upgrade_called
    assert result.thumb == "https://dmm.hd/cover.jpg"
    assert result.poster == "https://dmm.hd/poster.jpg"
