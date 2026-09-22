"""lulubar 爬虫解析逻辑测试（纯函数，无网络依赖）."""

import importlib

from lxml import etree

lulubar = importlib.import_module("mdcx.crawlers.lulubar")


def _html(body: str) -> etree._Element:
    return etree.fromstring(f"<html><body>{body}</body></html>", etree.HTMLParser())


def test_probe_number_is_site_specific():
    """SSNI-647 该站未收录，探针改用实测存在的 IPZZ-547（人工验证）."""
    assert lulubar.LulubarCrawler.probe_number == "IPZZ-547"


def test_get_real_url_matches_uppercase_number():
    """搜索页 img@alt 为大写番号前缀时必须能命中（议题：SSNI-647 搜索不到）."""
    html = _html(
        '<a class="imgBoxW" href="/video/abc">'
        '<img alt="SSNI-647 女朋友不在的日子里被她的闺蜜勾引出轨" src="/images/a.jpg"></a>'
        '<a class="imgBoxW" href="/video/other"><img alt="SSNI-646 另一个" src="/images/b.jpg"></a>'
    )
    assert lulubar.get_real_url(html, "SSNI-647") == (
        "https://lulubar.co/video/abc",
        "https://lulubar.co/images/a.jpg",
    )


def test_get_real_url_matches_lowercase_number():
    html = _html('<a class="imgBoxW" href="/video/abc"><img alt="ssni-647 标题" src="/images/a.jpg"></a>')
    assert lulubar.get_real_url(html, "SSNI-647") == (
        "https://lulubar.co/video/abc",
        "https://lulubar.co/images/a.jpg",
    )


def test_get_real_url_no_match_returns_empty():
    html = _html('<a class="imgBoxW" href="/video/x"><img alt="IPX-535 标题" src="/images/x.jpg"></a>')
    assert lulubar.get_real_url(html, "SSNI-647") == ("", "")
