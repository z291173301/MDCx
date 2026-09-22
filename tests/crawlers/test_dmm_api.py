import re

from mdcx.crawlers.dmm_api import DmmApiCrawler, _DmmApiItem
from mdcx.models.model_types import CrawlerInput


def _make_api_item(**overrides) -> _DmmApiItem:
    defaults = {
        "service_code": "mono",
        "content_id": "ssis200",
        "product_id": "ssis200",
        "title": "テスト作品",
        "date": "2021-02-18 00:00:00",
        "volume": 120,
        "review": {"count": 369, "average": "4.36"},
        "imageURL": {
            "list": "https://pics.dmm.co.jp/mono/movie/adult/ssis200/ssis200pt.jpg",
            "small": "https://pics.dmm.co.jp/mono/movie/adult/ssis200/ssis200ps.jpg",
        },
        "sampleImageURL": {
            "sample_s": {
                "image": [
                    "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200-1.jpg",
                    "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200-2.jpg",
                ]
            }
        },
        "iteminfo": {
            "actress": [{"name": "三上悠亜"}, {"name": "葵つかさ"}],
            "director": [{"name": "苺原"}],
            "genre": [{"name": "ギリモザ"}, {"name": "痴女"}],
            "maker": [{"name": "エスワン ナンバーワンスタイル"}],
            "label": [{"name": "S1 NO.1 STYLE"}],
            "series": [{"name": "テストシリーズ"}],
        },
        "URL": "https://www.dmm.co.jp/mono/dvd/-/detail/=/cid=ssis200/",
        "affiliateURL": "https://al.dmm.co.jp/?l=999&q=ssis200",
    }
    defaults.update(overrides)
    return _DmmApiItem.model_validate(defaults)


class TestDmmApiItemModel:
    def test_actresses_extraction(self):
        item = _make_api_item()
        assert item.actresses == ["三上悠亜", "葵つかさ"]

    def test_directors_extraction(self):
        item = _make_api_item()
        assert item.directors == ["苺原"]

    def test_genres_extraction(self):
        item = _make_api_item()
        assert item.genres == ["ギリモザ", "痴女"]

    def test_thumb_urls_prefers_large_over_small(self):
        item = _make_api_item(
            imageURL={
                "large": "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200pl.jpg",
                "small": "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200ps.jpg",
                "list": "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200pt.jpg",
            }
        )
        assert item.thumb_urls[0] == "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200pl.jpg"
        assert item.thumb_urls[1] == "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200ps.jpg"

    def test_thumb_urls_mono_only_list_and_small(self):
        item = _make_api_item()
        # mono 没有 large，应返回 [small(ps), list(pt)]
        assert "ssis200ps.jpg" in item.thumb_urls[0]
        assert "ssis200pt.jpg" in item.thumb_urls[1]

    def test_sample_images_prefers_sample_l(self):
        item = _make_api_item(
            sampleImageURL={
                "sample_l": {"image": ["https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200jp-1.jpg"]},
                "sample_s": {"image": ["https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200-1.jpg"]},
            }
        )
        assert item.sample_images == ["https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200jp-1.jpg"]

    def test_sample_images_falls_back_to_sample_s(self):
        item = _make_api_item()
        assert len(item.sample_images) == 2
        assert "ssis00200-1.jpg" in item.sample_images[0]

    def test_digital_cid_extracted_from_sample_images(self):
        item = _make_api_item()
        assert item.digital_cid == "ssis00200"

    def test_digital_cid_falls_back_to_thumb_urls(self):
        item = _make_api_item(
            sampleImageURL={},
            imageURL={"small": "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200ps.jpg"},
        )
        assert item.digital_cid == "ssis00200"

    def test_digital_cid_empty_when_no_digital_url(self):
        item = _make_api_item(
            sampleImageURL={},
            imageURL={"small": "https://pics.dmm.co.jp/mono/movie/adult/ssis200/ssis200ps.jpg"},
        )
        assert item.digital_cid == ""


class TestMatchScore:
    def test_exact_content_id_match(self):
        item = _make_api_item(content_id="ssis200")
        assert DmmApiCrawler._match_score(item, "ssis200") == 100

    def test_stripped_prefix_match(self):
        """content_id 带 DMM 前缀（如 118abp001）应去前缀后匹配。"""
        item = _make_api_item(content_id="118abp001")
        assert DmmApiCrawler._match_score(item, "abp001") == 90

    def test_content_id_leading_zeros_match(self):
        """content_id 编号段 5 位补零（sone00244），番号去横杠（sone244），应命中 90 分支。"""
        item = _make_api_item(content_id="sone00244", product_id="sone244")
        assert DmmApiCrawler._match_score(item, "sone244") == 90

    def test_product_id_with_hyphen_match(self):
        """product_id 带横杠（sone-244）应归一化后命中 80 分支。"""
        item = _make_api_item(content_id="xx", product_id="sone-244")
        assert DmmApiCrawler._match_score(item, "sone244") == 80

    def test_substring_match_with_bluray_penalty(self):
        """content_id 以 9 开头（蓝光版）且去前缀不匹配时应走子串匹配并扣分。"""
        item = _make_api_item(content_id="9ssis2000")
        score = DmmApiCrawler._match_score(item, "ssis200")
        # 9ssis2000 包含 ssis200 子串，且以 9 开头扣分
        assert score == 40  # 50 - 10

    def test_substring_match_normal(self):
        item = _make_api_item(content_id="77ssis267", product_id="77ssis267")
        assert DmmApiCrawler._match_score(item, "ssis200") == -1  # 不包含 ssis200

    def test_product_id_exact_match(self):
        item = _make_api_item(content_id="xx", product_id="ssis200")
        assert DmmApiCrawler._match_score(item, "ssis200") == 80

    def test_no_match(self):
        item = _make_api_item(content_id="mide988", product_id="mide988")
        assert DmmApiCrawler._match_score(item, "ssis200") == -1


class TestFindBestItem:
    def test_finds_exact_match_among_multiple(self):
        crawler = DmmApiCrawler(client=None)
        items = [
            _make_api_item(content_id="ssis267", product_id="ssis267"),
            _make_api_item(content_id="ssis200", product_id="ssis200"),
            _make_api_item(content_id="ssis201", product_id="ssis201"),
        ]
        best = crawler._find_best_item(items, "SSIS-200")
        assert best is not None
        assert best.content_id == "ssis200"

    def test_returns_none_when_no_match(self):
        crawler = DmmApiCrawler(client=None)
        items = [_make_api_item(content_id="mide988", product_id="mide988")]
        assert crawler._find_best_item(items, "SSIS-200") is None


class TestToCrawlerData:
    def test_maps_all_fields(self):
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item()
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")

        assert data.title == "テスト作品"
        assert data.number == "SSIS-200"
        assert data.release == "2021-02-18"
        assert data.runtime == "120"
        assert data.score == "4.36"
        assert data.studio == "エスワン ナンバーワンスタイル"
        assert data.publisher == "S1 NO.1 STYLE"
        assert data.series == "テストシリーズ"
        assert data.actors == ["三上悠亜", "葵つかさ"]
        assert data.directors == ["苺原"]
        assert data.tags == ["ギリモザ", "痴女"]
        assert data.mosaic == "有码"

    def test_thumb_from_mono_small(self):
        """mono 无 large 时应取 small(ps.jpg) 作为 thumb。"""
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item()
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")
        assert "ssis200ps.jpg" in data.thumb

    def test_thumb_from_digital_large(self):
        """digital 有 large 时应取 pl.jpg 作为 thumb。"""
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item(
            imageURL={
                "large": "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200pl.jpg",
                "small": "https://pics.dmm.co.jp/digital/video/ssis00200/ssis00200ps.jpg",
            }
        )
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")
        assert "ssis00200pl.jpg" in data.thumb

    def test_poster_left_empty(self):
        """poster 应留空，由 post_process 从 thumb 派生。"""
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item()
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")
        assert data.poster == ""

    def test_extrafanart_upgraded_to_jp_format(self):
        """剧照 URL 应从 -N.jpg 升级为 jp-N.jpg。"""
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item()
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")
        assert len(data.extrafanart) == 2
        for url in data.extrafanart:
            assert "jp-" in url
            assert re.search(r"jp-\d+\.jpg", url)

    def test_release_strips_time(self):
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item(date="2021-02-18 00:00:00")
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")
        assert data.release == "2021-02-18"

    def test_external_id_prefers_affiliate_url(self):
        crawler = DmmApiCrawler(client=None)
        item = _make_api_item()
        data = crawler._to_crawler_data(item, fallback_number="SSIS-200")
        assert data.external_id == "https://al.dmm.co.jp/?l=999&q=ssis200"

    def test_score_extracts_average_from_dict(self):
        crawler = DmmApiCrawler(client=None)
        assert crawler._score({"count": 100, "average": "4.50"}) == "4.50"
        assert crawler._score(None) == ""
        assert crawler._score({}) == ""


class TestNumberContext:
    def test_normal_number(self):
        crawler = DmmApiCrawler(client=None)
        ctx = crawler.new_context(CrawlerInput.empty())
        ctx.input.number = "SSIS-200"
        crawler._set_number_context(ctx, "SSIS-200")
        assert ctx.number_00 == "ssis00200"
        assert ctx.number_no_00 == "ssis200"

    def test_5digit_with_00_prefix(self):
        """5位数字且以00开头时应去掉前导00（如 snis0027 -> snis027）。"""
        crawler = DmmApiCrawler(client=None)
        ctx = crawler.new_context(CrawlerInput.empty())
        ctx.input.number = "SNIS-0027"
        crawler._set_number_context(ctx, "SNIS-0027")
        # digits="0027", len=4 -> 走 elif 分支: replace("-","0") -> "snis00027"
        # 此时已无连字符，number_00/number_no_00 均为 "snis00027"
        assert ctx.number_00 == "snis00027"
        assert ctx.number_no_00 == "snis00027"

    def test_4digit_number(self):
        """4位数字时应补0（如 SSIS-001 -> ssis0001）。"""
        crawler = DmmApiCrawler(client=None)
        ctx = crawler.new_context(CrawlerInput.empty())
        ctx.input.number = "SSIS-001"
        crawler._set_number_context(ctx, "SSIS-001")
        assert ctx.number_00 == "ssis00001"
        assert ctx.number_no_00 == "ssis001"


class TestBuildApiUrl:
    def test_url_contains_required_params(self):
        url = DmmApiCrawler._build_api_url(keyword="SSIS-200", sort="match", hits="20")
        assert "api.dmm.com/affiliate/v3/ItemList" in url
        assert "api_id=" in url
        assert "affiliate_id=" in url
        assert "output=json" in url
        assert "keyword=SSIS-200" in url
        assert "sort=match" in url
        assert "hits=20" in url

    def test_uses_default_credentials_when_empty(self):
        url = DmmApiCrawler._build_api_url(keyword="test")
        # 默认 api_id 硬编码在 URL 中
        assert "UrwskPfkqQ0DuVry2gYL" in url
        assert "10278-996" in url


class TestSearchKeywords:
    def test_standard_number_converts_to_content_id_form(self):
        # 带横杠格式 keyword 实测 0 结果，content_id 形态精确命中
        assert DmmApiCrawler._search_keywords("SSIS-200") == ["ssis00200", "ssis"]

    def test_number_with_leading_zeros(self):
        assert DmmApiCrawler._search_keywords("MIDE-083") == ["mide00083", "mide"]

    def test_prefix_containing_digits(self):
        assert DmmApiCrawler._search_keywords("T28-655") == ["t2800655", "t28"]

    def test_non_standard_number_falls_back_to_raw(self):
        assert DmmApiCrawler._search_keywords("ssis00200") == ["ssis00200"]
        assert DmmApiCrawler._search_keywords("SSIS-200001") == ["SSIS-200001"]
        assert DmmApiCrawler._search_keywords("") == [""]


def test_build_aws_thumb_candidates_includes_dmm_direct_prefix(monkeypatch):
    """特殊前缀系列（ABF）的低清图应能构造出 dmm_direct 前缀表高清候选."""
    from mdcx.crawlers.dmm import DmmCrawler

    crawler = DmmCrawler(client=None)
    ctx = crawler.new_context(CrawlerInput.empty())
    ctx.input.number = "ABF-042"
    ctx.number_00 = "abf00042"
    ctx.number_no_00 = "abf042"

    candidates = crawler._build_aws_thumb_candidates(
        ctx, "https://pics.dmm.co.jp/mono/movie/adult/118abf042/118abf042pl.jpg"
    )

    assert "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/436abf00042/436abf00042pl.jpg" in candidates
    assert candidates[0].startswith("https://awsimgsrc.dmm.co.jp/pics_dig/")
