import pytest

from mdcx.crawlers.avheat import AvheatCrawler
from mdcx.crawlers.avmoo import AvmooCrawler
from mdcx.crawlers.avsox import AvsoxCrawler
from mdcx.models.model_types import CrawlerInput

SEARCH_RESPONSE = {
    "code": 200,
    "data": [
        {
            "movieId": "kgjavpj",
            "movieFanHao": "SSNI-804",
            "title": "Title",
        }
    ],
}

DETAIL_RESPONSE = {
    "code": 200,
    "data": {
        "movieId": "kgjavpj",
        "movieFanHao": "SSNI-804",
        "title": "巨乳上司と童貞部下",
        "title_ja": "巨乳上司と童貞部下",
        "releaseDate": "2020-06-14",
        "length": 119,
        "posterLarge": "https://img/pl.jpg",
        "posterSmall": "https://img/ps.jpg",
        "sampleLarge": ["https://img/s1.jpg", "https://img/s2.jpg"],
        "studio": {"studioName": "S1 NO.1 Style"},
        "series": {"seriesName": "Series"},
        "label": {"labelName": "S1 NO.1 STYLE"},
        "director": {"directorName": "苺原"},
        "star": [{"starName_en": "Aika Yumeno", "starName_ja": "夢乃あいか"}],
        "genre": [{"genreName": "ドラマ"}, {"genreName": "ギリモザ"}],
        "description_cn": "简介",
    },
}


class FakeClient:
    """模拟 async_client，记录请求参数并按顺序返回预设响应。"""

    def __init__(self, search=None, detail=None):
        self.calls: list[tuple[str, dict]] = []
        self.search = search or SEARCH_RESPONSE
        self.detail = detail or DETAIL_RESPONSE

    async def post_json(self, url, *, data=None, json_data=None, headers=None, **kwargs):
        self.calls.append((url, {"data": data, "json_data": json_data, "headers": headers}))
        if url.endswith("/search"):
            return self.search, ""
        return self.detail, ""


def _run(crawler_cls, number: str = "SSNI-804"):
    crawler = crawler_cls(client=FakeClient(), base_url="https://avmoo.shop")
    input_data = CrawlerInput.empty()
    input_data.number = number
    return crawler.run(input_data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("crawler_cls", "site_value", "mosaic"),
    [
        (AvmooCrawler, "avmoo", "有码"),
        (AvsoxCrawler, "avsox", "无码"),
        (AvheatCrawler, "avheat", "欧美"),
    ],
)
async def test_run_search_then_get_movie(crawler_cls, site_value, mosaic):
    response = await _run(crawler_cls)
    assert response.data is not None
    assert response.data.source == site_value
    assert response.data.number == "SSNI-804"
    assert response.data.title == "巨乳上司と童貞部下"
    assert response.data.release == "2020-06-14"
    assert response.data.year == "2020"
    assert response.data.runtime == "119"
    assert response.data.studio == "S1 NO.1 Style"
    assert response.data.publisher == "S1 NO.1 STYLE"
    assert response.data.series == "Series"
    assert response.data.directors == ["苺原"]
    assert response.data.actors == ["Aika Yumeno"]
    assert response.data.all_actors == ["Aika Yumeno"]
    assert response.data.tags == ["ドラマ", "ギリモザ"]
    assert response.data.thumb == "https://img/pl.jpg"
    assert response.data.poster == "https://img/ps.jpg"
    assert response.data.extrafanart == ["https://img/s1.jpg", "https://img/s2.jpg"]
    assert response.data.mosaic == mosaic


@pytest.mark.asyncio
async def test_search_request_uses_json_array_body():
    crawler = AvmooCrawler(client=FakeClient(), base_url="https://avmoo.shop")
    input_data = CrawlerInput.empty()
    input_data.number = "SSNI-804"
    await crawler.run(input_data)

    search_call = crawler.async_client.calls[0]
    assert search_call[0] == "https://avmoo.shop/jav/data/api/search"
    assert search_call[1]["data"] == '[{"search": "SSNI-804", "lang": "cn"}, 60, 1]'
    assert search_call[1]["headers"]["Content-Type"] == "application/json"

    detail_call = crawler.async_client.calls[1]
    assert detail_call[0] == "https://avmoo.shop/jav/data/api/getMovie"
    assert detail_call[1]["data"] == {"movieId": "kgjavpj"}


@pytest.mark.asyncio
async def test_namespace_and_fallback_domain():
    assert AvmooCrawler.namespace == "jav"
    assert AvmooCrawler.fallback_domain == "https://avmoo.shop"
    assert AvheatCrawler.namespace == "wav"
    assert AvheatCrawler.fallback_domain == "https://avheat.shop"
    assert AvsoxCrawler.namespace == "javu"
    assert AvsoxCrawler.fallback_domain == "https://avsox.click"


@pytest.mark.asyncio
async def test_with_outline_flags():
    assert AvmooCrawler.with_outline is False
    assert AvheatCrawler.with_outline is True
    assert AvsoxCrawler.with_outline is True


@pytest.mark.asyncio
async def test_outline_only_loaded_when_enabled(monkeypatch: pytest.MonkeyPatch):
    from mdcx.crawlers import aio_site as aio_module

    monkeypatch.setattr(aio_module, "get_aio_domain", lambda site: "https://avmoo.shop")

    response = await _run(AvmooCrawler)
    assert response.data is not None
    assert not response.data.outline

    avheat = AvheatCrawler(client=FakeClient(), base_url="https://avheat.shop")
    input_data = CrawlerInput.empty()
    input_data.number = "SSNI-804"
    response = await avheat.run(input_data)
    assert response.data is not None
    assert response.data.outline == "简介"
