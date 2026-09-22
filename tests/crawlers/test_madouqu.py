from lxml import etree

from mdcx.crawlers.madouqu import get_detail_info, get_real_url, normalize_cover_url


def test_normalize_cover_url_rewrites_legacy_wp_proxy_host():
    url = "https://i0.wp.com/md.hm1225.cyou/wp-content/uploads/2022/02/demo.jpg?resize=700%2C394&ssl=1"

    assert (
        normalize_cover_url(url)
        == "https://i0.wp.com/madouqu.com/wp-content/uploads/2022/02/demo.jpg?resize=700%2C394&ssl=1"
    )


def test_get_real_url_prefers_search_result_data_src_cover():
    html = etree.fromstring(
        """
        <html>
          <body>
            <div class="entry-media">
              <div>
                <a href="https://madouqu.com/video/md0217/">
                  <img
                    class="thumb"
                    alt="MD0217 換母盪元宵"
                    src="data:image/gif;base64,xxx"
                    data-src="https://i0.wp.com/madouqu.com/wp-content/uploads/2022/02/demo.jpg?fit=700%2C394&ssl=1"
                  />
                </a>
              </div>
            </div>
          </body>
        </html>
        """,
        etree.HTMLParser(),
    )

    assert get_real_url(html, ["MD0217"]) == (
        True,
        "MD0217",
        "MD0217 換母盪元宵",
        "https://madouqu.com/video/md0217/",
        "https://i0.wp.com/madouqu.com/wp-content/uploads/2022/02/demo.jpg?fit=700%2C394&ssl=1",
    )


def test_get_detail_info_normalizes_detail_cover_url():
    html = etree.fromstring(
        """
        <html>
          <body>
            <div class="cao_entry_header">
              <header>
                <h1>MD0217 換母盪元宵</h1>
              </header>
            </div>
            <span class="meta-category">麻豆传媒</span>
            <div class="entry-content u-text-format u-clearfix">
              <p>番号：MD0217</p>
              <p>片名：換母盪元宵</p>
              <p><img src="https://i0.wp.com/md.hm1225.cyou/wp-content/uploads/2022/02/demo.jpg?resize=700%2C394&ssl=1" /></p>
            </div>
            <time datetime="2022-02-16T10:00:00+08:00"></time>
          </body>
        </html>
        """,
        etree.HTMLParser(),
    )

    number, title, actor, cover_url, studio, release, year = get_detail_info(html, "MD0217", "MD0217")

    assert number == "MD0217"
    assert title == "換母盪元宵"
    assert actor == ""
    assert cover_url == "https://i0.wp.com/madouqu.com/wp-content/uploads/2022/02/demo.jpg?resize=700%2C394&ssl=1"
    assert studio == "麻豆传媒"
    assert release == "2022-02-16"
    assert year == "2022"


def test_parse_madouqu_domains_extracts_md_block():
    from mdcx.base.web import _parse_madouqu_domains

    config_js = """
const domainConfig = [
    { id: 'md', name: '麻豆区', urls: ['https://madouqu.shop', 'https://madouqu2.sbs', 'https://madouqu.sbs'] },
    { id: 'bt', name: '国产BT', urls: ['https://gcbt3.sbs'] },
];
"""
    assert _parse_madouqu_domains(config_js) == ["https://madouqu.shop", "https://madouqu2.sbs", "https://madouqu.sbs"]


def test_parse_madouqu_domains_empty_on_missing_block():
    from mdcx.base.web import _parse_madouqu_domains

    assert _parse_madouqu_domains("const x = 1;") == []
    assert _parse_madouqu_domains("") == []


def test_generate_search_urls_use_all_dynamic_domains(monkeypatch):
    """未自定义 URL 时搜索候选应覆盖发布页解析的全部域名."""
    import asyncio

    from mdcx.crawlers.madouqu import MadouquCrawler
    from mdcx.models.model_types import CrawlerInput

    async def fake_domains():
        return ["https://a.example", "https://b.example"]

    monkeypatch.setattr("mdcx.base.web.get_madouqu_domains", fake_domains)
    crawler = MadouquCrawler(client=None, base_url="https://madouqu.shop", browser=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "MDX-0236"

    urls = asyncio.run(crawler._generate_search_url(ctx))

    hosts = [u.split("/")[2] for u in urls]
    assert set(hosts) == {"a.example", "b.example"}
