import pytest

from mdcx.config.models import Website
from mdcx.crawlers.r18dev import R18devCrawler, _generate_content_id_variations, _normalize_id, _series_number
from mdcx.models.model_types import CrawlerInput


def test_normalize_id():
    assert _normalize_id("IPX-535") == "ipx00535"
    assert _normalize_id("SSIS-001") == "ssis00001"
    assert _normalize_id("ABF-030") == "abf00030"
    assert _normalize_id("SSIS-1") == "ssis00001"
    assert _normalize_id("midv-512") == "midv00512"


def test_normalize_id_already_normalized():
    assert _normalize_id("ipx00535") == "ipx00535"
    assert _normalize_id("ssis00001") == "ssis00001"


def test_normalize_id_with_spaces():
    assert _normalize_id("IPX 535") == "ipx00535"
    assert _normalize_id("midv 512") == "midv00512"


def test_content_id_variations():
    vars = _generate_content_id_variations("ABF-030")
    assert "118abf00030" in vars
    assert "118abf030" in vars
    assert "436abf00030" not in vars  # 436 is not in our prefix table for abf


def test_content_id_variations_unknown_series():
    vars = _generate_content_id_variations("ZZZ-001")
    assert "1zzz00001" in vars or "zzz00001" in vars


def test_series_number():
    assert _series_number("IPX-535") == ("ipx", "535")
    assert _series_number("SSIS-001") == ("ssis", "001")
    assert _series_number("") == ("", "")


def test_site_enum():
    assert R18devCrawler.site() == Website.R18DEV


def test_display_name():
    assert R18devCrawler.display_name() == "R18.dev"


def test_supports_custom_url():
    assert R18devCrawler.supports_custom_url() is True


def test_parse_json_full_data():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "ipx00535",
            "content_id": "118ipx00535",
            "title_ja": "タイトル",
            "title_en": "Title English",
            "release_date": "2024-01-15",
            "runtime_mins": 120,
            "directors": [{"name_kanji": "監督A", "name_romaji": "Director A"}],
            "maker_name_ja": "メーカー",
            "maker_name_en": "Maker",
            "label_name_ja": "レーベル",
            "label_name_en": "Label",
            "series_name_ja": "シリーズ",
            "series_name_en": "Series",
            "actresses": [
                {"name_kanji": "女優A", "name_romaji": "Actress A"},
                {"name_kanji": "", "name_romaji": "Actress B"},
            ],
            "categories": [
                {"name_ja": "カテゴリA", "name_en": "Category A"},
                {"name_ja": "", "name_en": "Category B"},
            ],
            "jacket_full_url": "https://pics.dmm.co.jp/mono/abc/abcpl.jpg",
            "gallery": [{"image_full": "https://pics.dmm.co.jp/mono/abc/abcjp-1.jpg"}],
            "sample_url": "https://cc3001.dmm.co.jp/pv/abc.mp4",
        },
        ctx=None,
    )

    assert data.number == "IPX-535"
    assert data.title == "タイトル"
    assert data.originaltitle == "タイトル"
    assert data.actors == ["女優A", "Actress B"]
    assert data.all_actors == ["女優A", "Actress B"]
    assert data.studio == "メーカー"
    assert data.publisher == "レーベル"
    assert data.series == "シリーズ"
    assert data.release == "2024-01-15"
    assert data.year == "2024"
    assert data.runtime == "120"
    assert data.tags == ["カテゴリA", "Category B"]
    assert data.thumb == "https://pics.dmm.co.jp/mono/abc/abcpl.jpg"
    assert data.poster == "https://pics.dmm.co.jp/mono/abc/abcpl.jpg"
    assert data.extrafanart == ["https://pics.dmm.co.jp/mono/abc/abcjp-1.jpg"]
    assert data.trailer == "https://cc3001.dmm.co.jp/pv/abc.mp4"
    assert data.directors == ["監督A"]
    assert data.external_id == "118ipx00535"


def test_parse_json_minimal_data():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "ssis001",
            "content_id": "118ssis001",
            "title_ja": "テスト",
            "release_date": "2023-06-01",
            "runtime_mins": 90,
        },
        ctx=None,
    )

    assert data.number == "SSIS-001"
    assert data.title == "テスト"
    assert data.release == "2023-06-01"
    assert data.year == "2023"
    assert data.runtime == "90"
    assert data.actors == []
    assert data.tags == []


def test_parse_json_title_ja_missing_uses_uncensored_en():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "1hbad00051",
            "content_id": "1hbad00051",
            "title_ja": "",
            "title_en": "Female Teacher Shame: Sex S***e Anna Oguri",
            "title_en_uncensored": "Female Teacher Shame: Sex Slave Anna Oguri",
        },
        ctx=None,
    )

    assert data.title == "Female Teacher Shame: Sex Slave Anna Oguri"
    assert data.originaltitle == "Female Teacher Shame: Sex Slave Anna Oguri"


def test_parse_json_uncensored_en_missing_falls_back_to_en():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "1hbad00051",
            "content_id": "1hbad00051",
            "title_ja": "",
            "title_en": "Female Teacher Shame: Sex Slave Anna Oguri",
        },
        ctx=None,
    )

    assert data.title == "Female Teacher Shame: Sex Slave Anna Oguri"
    assert data.originaltitle == "Female Teacher Shame: Sex Slave Anna Oguri"


def test_parse_json_title_ja_wins_over_en():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "1hbad00051",
            "content_id": "1hbad00051",
            "title_ja": "女教師羞恥肉奴● 小栗杏奈",
            "title_en": "Female Teacher Shame: Sex S***e Anna Oguri",
            "title_en_uncensored": "Female Teacher Shame: Sex Slave Anna Oguri",
        },
        ctx=None,
    )

    assert data.title == "女教師羞恥肉奴● 小栗杏奈"
    assert data.originaltitle == "女教師羞恥肉奴● 小栗杏奈"


def test_parse_json_uses_jacket_from_images():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "test001",
            "content_id": "test001",
            "title_ja": "Test",
            "images": {
                "jacket_image": {
                    "large2": "https://pics.dmm.co.jp/mono/test/large2.jpg",
                    "large": "https://pics.dmm.co.jp/mono/test/large.jpg",
                }
            },
        },
        ctx=None,
    )

    assert data.thumb == "https://pics.dmm.co.jp/mono/test/large2.jpg"


def test_parse_json_trailer_from_sample_object():
    crawler = R18devCrawler(client=None)
    data = crawler._parse_json(
        {
            "dvd_id": "test001",
            "content_id": "test001",
            "title_ja": "Test",
            "sample": {"high": "https://cc3001.dmm.co.jp/pv/high.mp4"},
        },
        ctx=None,
    )

    assert data.trailer == "https://cc3001.dmm.co.jp/pv/high.mp4"


@pytest.mark.asyncio
async def test_run_with_dvd_id_match(monkeypatch):
    api_response = {
        "dvd_id": "ipx00535",
        "content_id": "118ipx00535",
        "title_ja": "タイトル",
        "title_en": "Title English",
        "release_date": "2024-01-15",
        "runtime_mins": 120,
        "maker_name_ja": "メーカー",
        "actresses": [{"name_kanji": "女優A", "name_romaji": "Actress A"}],
        "categories": [{"name_ja": "カテゴリA", "name_en": "Category A"}],
        "jacket_full_url": "https://pics.dmm.co.jp/mono/abc/abcpl.jpg",
    }

    call_count = 0

    class FakeClient:
        async def get_json(self, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "dvd_id=" in url:
                return (api_response, "")
            if "combined=" in url:
                return (api_response, "")
            return (None, "unknown url")

        async def get_text(self, url, **kwargs):
            return (None, "")

        async def request(self, *args, **kwargs):
            return (None, "")

    crawler = R18devCrawler(client=FakeClient())
    input_data = CrawlerInput.empty()
    input_data.number = "IPX-535"
    result = await crawler.run(input_data)

    assert result.data is not None
    assert result.data.number == "IPX-535"
    assert result.data.title == "タイトル"
    assert result.data.studio == "メーカー"
    assert result.data.actors == ["女優A"]
    assert call_count >= 1


@pytest.mark.asyncio
async def test_run_with_content_id_fallback(monkeypatch):
    api_response = {
        "dvd_id": "abf030",
        "content_id": "118abf00030",
        "title_ja": "ABFタイトル",
        "release_date": "2024-06-01",
        "runtime_mins": 150,
        "maker_name_ja": "メーカーB",
        "actresses": [{"name_kanji": "女優B", "name_romaji": "Actress B"}],
        "categories": [{"name_ja": "カテゴリB", "name_en": "Category B"}],
        "jacket_full_url": "https://pics.dmm.co.jp/mono/abc/abcpl.jpg",
    }

    call_count = 0

    class FakeClient:
        async def get_json(self, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "dvd_id=" in url:
                return (None, "404")
            if "combined=" in url:
                return (api_response, "")
            return (None, "unknown url")

        async def get_text(self, url, **kwargs):
            return (None, "")

        async def request(self, *args, **kwargs):
            return (None, "")

    crawler = R18devCrawler(client=FakeClient())
    input_data = CrawlerInput.empty()
    input_data.number = "ABF-030"
    result = await crawler.run(input_data)

    assert result.data is not None
    assert result.data.number == "ABF-030"
    assert result.data.title == "ABFタイトル"
    assert result.data.studio == "メーカーB"
    assert call_count >= 2


@pytest.mark.asyncio
async def test_post_process_fixes_trailer():
    from mdcx.crawlers.base.base_types import CrawlerData

    crawler = R18devCrawler(client=None)
    data = CrawlerData(
        number="TEST-001",
        title="Test",
        trailer="//example.com/video.mp4",
    )
    result = data.to_result()
    result = await crawler.post_process(None, result)

    assert result.trailer == "https://example.com/video.mp4"


@pytest.mark.asyncio
async def test_post_process_fills_originaltitle():
    from mdcx.crawlers.base.base_types import CrawlerData

    crawler = R18devCrawler(client=None)
    data = CrawlerData(
        number="TEST-001",
        title="Test Title",
        originaltitle="",
    )
    result = data.to_result()
    result = await crawler.post_process(None, result)

    assert result.originaltitle == "Test Title"


def test_build_aws_cover_candidates_ssis():
    from mdcx.crawlers.r18dev import _build_aws_cover_candidates

    assert _build_aws_cover_candidates("SSIS-001") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg"
    ]


def test_build_aws_poster_candidates_ssis():
    from mdcx.crawlers.r18dev import _build_aws_poster_candidates

    assert _build_aws_poster_candidates("SSIS-001") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg"
    ]


def test_build_aws_poster_candidates_prefixed_series():
    from mdcx.crawlers.r18dev import _build_aws_poster_candidates

    assert _build_aws_poster_candidates("WANZ-100")[0] == (
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/3wanz00100/3wanz00100ps.jpg"
    )
    assert _build_aws_poster_candidates("SW-123") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sw00123/1sw00123ps.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sw00123/sw00123ps.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/h_113sw00123/h_113sw00123ps.jpg",
    ]


class _FakeCtx:
    class _Input:
        number = "SSIS-001"

    input = _Input()

    def __init__(self):
        self.logs = []

    def debug(self, message: str):
        self.logs.append(message)


async def _ok(url: str) -> str:
    return url


async def _fail(url: str) -> None:
    return None


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_success(monkeypatch):
    from mdcx.crawlers.base.base_types import CrawlerData
    from mdcx.crawlers.r18dev import _upgrade_dmm_cover

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    ctx = _FakeCtx()
    data = CrawlerData(number="SSIS-001", thumb="old.jpg", poster="old.jpg")
    await _upgrade_dmm_cover(ctx, data)
    assert data.thumb.endswith("ssis00001pl.jpg")
    assert data.poster.endswith("ssis00001ps.jpg")


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_fail_keeps_original(monkeypatch):
    from mdcx.crawlers.base.base_types import CrawlerData
    from mdcx.crawlers.r18dev import _upgrade_dmm_cover

    monkeypatch.setattr("mdcx.base.web.check_url", _fail)
    ctx = _FakeCtx()
    data = CrawlerData(number="SSIS-001", thumb="old.jpg", poster="old.jpg")
    await _upgrade_dmm_cover(ctx, data)
    assert data.thumb == "old.jpg"
    assert data.poster == "old.jpg"


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_uses_data_number(monkeypatch):
    from mdcx.crawlers.base.base_types import CrawlerData
    from mdcx.crawlers.r18dev import _upgrade_dmm_cover

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    ctx = _FakeCtx()
    data = CrawlerData(number="WANZ-100", thumb="old.jpg", poster="old.jpg")
    await _upgrade_dmm_cover(ctx, data)
    assert data.thumb.endswith("3wanz00100pl.jpg")
    assert data.poster.endswith("3wanz00100ps.jpg")


@pytest.mark.asyncio
async def test_search_urls_follow_custom_base_url():
    """议题 #128 遗留: 搜索/详情 URL 必须跟随 self.base_url(用户自定义站点域名),
    不得硬编码 _API_BASE——否则「设置→站点自定义 URL」对 r18dev 搜索路径不生效。"""
    import ast

    crawler = R18devCrawler(client=None, base_url="https://r18-mirror.example", browser=None)
    inp = CrawlerInput.empty()
    inp.number = "SSNI-647"
    ctx = crawler.new_context(inp)
    url = await crawler._generate_search_url(ctx)
    assert url and "https://r18-mirror.example/videos/vod/movies/detail/-/dvd_id=ssni00647/json" in (
        url if isinstance(url, list) else [url]
    ), f"搜索 URL 未使用自定义域名: {url}"

    # AST 哨兵: 实例方法体内不得再出现 _API_BASE (类定义外 base_url_ 默认值除外)
    from pathlib import Path

    src = Path("mdcx/crawlers/r18dev.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "R18devCrawler")
    for fn in (n for n in ast.walk(cls) if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)):
        if fn.name == "base_url_":
            continue
        bad = [ast.unparse(node) for node in ast.walk(fn) if isinstance(node, ast.Name) and node.id == "_API_BASE"]
        assert not bad, f"{fn.name} 内不应再硬编码 _API_BASE: {bad}"
