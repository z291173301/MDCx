import oshash
import pytest

from mdcx.config.enums import Language, Switch, Website
from mdcx.config.manager import manager
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.theporndb import TheporndbCrawler
from mdcx.models.model_types import CrawlerInput


class FakeTheporndbClient:
    async def get_json(self, url, **kwargs):
        if url == "https://api.theporndb.net/scenes/test-scene":
            return {"data": _api_data("test-scene", "scenes")}, ""
        if url == "https://api.theporndb.net/scenes/test-movie":
            return {"data": None}, ""
        if url == "https://api.theporndb.net/movies/test-movie":
            return {"data": _api_data("test-movie", "movies")}, ""
        return None, f"unexpected url: {url}"


class FakeTheporndbSearchClient:
    async def get_json(self, url, **kwargs):
        if url == "https://api.theporndb.net/scenes/hash/fakehash":
            return None, "HTTP 404"
        if url == "https://api.theporndb.net/scenes?parse=nurumassage 2026-02-23&per_page=100":
            return {"data": [_api_data("nurumassage-ellie-nova", "scenes", title="Ellie Nova", date="2026-02-23")]}, ""
        if url == "https://api.theporndb.net/scenes/nurumassage-ellie-nova":
            return {"data": _api_data("nurumassage-ellie-nova", "scenes", title="Ellie Nova", date="2026-02-23")}, ""
        return None, f"unexpected url: {url}"


def _api_data(slug: str, kind: str, title: str | None = None, date: str = "2026-04-03") -> dict:
    return {
        "slug": slug,
        "title": title or f"{kind} title",
        "description": "Outline",
        "date": date,
        "trailer": "https://example.test/trailer.mp4",
        "background": {"large": "https://example.test/cover.jpg"},
        "posters": {"large": "https://example.test/poster.jpg"},
        "duration": 7200,
        "site": {"name": "Series A", "short_name": "seriesa", "network": {"name": "Network A"}},
        "director": {"name": "Director A"},
        "tags": [{"name": "Tag A"}],
        "performers": [
            {"name": "Actor A", "parent": {"extras": {"gender": "Female"}}},
            {"name": "Actor B", "parent": {"extras": {"gender": "Male"}}},
        ],
    }


def _input(appoint_url: str) -> CrawlerInput:
    return CrawlerInput(
        appoint_number="",
        appoint_url=appoint_url,
        file_path=None,
        mosaic="",
        number="SceneTest",
        short_number="SceneTest",
        language=Language.JP,
        org_language=Language.JP,
    )


def _file_input() -> CrawlerInput:
    data = _input("")
    data.number = "Nurumassage.26.02.23"
    data.short_number = "Nurumassage.26.02.23"
    data.file_path = "D:/Code/Personal/daiguaxiao/nurumassage.26.02.23.ellie.nova.mp4"
    return data


@pytest.mark.asyncio
async def test_theporndb_crawler_reads_scene_detail_url():
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = "token"
    try:
        crawler = TheporndbCrawler(client=FakeTheporndbClient())
        res = await crawler.run(_input("https://theporndb.net/scenes/test-scene"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.source == "theporndb"
    assert res.data.number == "SeriesA.26.04.03"
    assert res.data.title == "scenes title"
    assert res.data.actors == ["Actor A"]
    assert res.data.all_actors == ["Actor A", "Actor B"]
    assert res.data.directors == ["Director A"]
    assert res.data.tags == ["Tag A"]
    assert res.data.runtime == "120"
    assert res.data.thumb == "https://example.test/cover.jpg"
    assert res.data.poster == "https://example.test/poster.jpg"
    assert res.data.external_id == "https://api.theporndb.net/scenes/test-scene"


@pytest.mark.asyncio
async def test_theporndb_appoint_url_works_without_api_token():
    """议题 #81：指定网址（公开 slug 端点）不能因缺 Token 被拒。

    ThePornDB 的 /scenes/{slug} 是公开端点（实测无 Bearer 也能 200），
    此前 _headers() 无论场景都先校验 Token 直接拒绝，导致用户改输入网址也刮不出。
    """
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = ""

    class NoTokenClient:
        async def get_json(self, url, **kwargs):
            assert "Authorization" not in (kwargs.get("headers") or {})
            if url == "https://api.theporndb.net/scenes/test-scene":
                return {"data": _api_data("test-scene", "scenes")}, ""
            return None, f"unexpected url: {url}"

    try:
        crawler = TheporndbCrawler(client=NoTokenClient())
        res = await crawler.run(_input("https://theporndb.net/scenes/test-scene"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "scenes title"


@pytest.mark.asyncio
async def test_theporndb_crawler_falls_back_to_movies():
    old_token = manager.config.theporndb_api_token
    manager.config.theporndb_api_token = "token"
    try:
        crawler = TheporndbCrawler(client=FakeTheporndbClient())
        res = await crawler.run(_input("https://theporndb.net/movies/test-movie"))
    finally:
        manager.config.theporndb_api_token = old_token

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "movies title"
    assert res.data.external_id == "https://api.theporndb.net/movies/test-movie"


@pytest.mark.asyncio
async def test_theporndb_crawler_continues_search_when_hash_misses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]
    try:
        crawler = TheporndbCrawler(client=FakeTheporndbSearchClient())
        res = await crawler.run(_file_input())
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "Ellie Nova"
    assert res.debug_info.search_urls == [
        "https://api.theporndb.net/scenes/hash/fakehash",
        "https://api.theporndb.net/scenes?parse=nurumassage 2026-02-23&per_page=100",
    ]


def test_theporndb_crawler_is_registered():
    assert get_crawler(Website.THEPORNDB) is TheporndbCrawler


def _scene_hit(slug: str, title: str, date: str, site_short: str, site_url: str, performers: list[str]) -> dict:
    return {
        "slug": slug,
        "title": title,
        "date": date,
        "site": {"short_name": site_short, "url": site_url},
        "performers": [{"name": p} for p in performers],
    }


def test_get_real_url_prefers_title_hit_over_date_bucket():
    """议题 #94 实测误配：ThePornDB 同日同厂多部作品，日期桶命中 Wanilianna
    《The Squirting Harlot》（错的），真正目标的站点归属 HobbyPorn（非 Faphouse）。
    标题精确命中必须优先于日期桶。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = (
        r"U:\Service\欧美转移\FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    )
    payload = {
        "data": [
            _scene_hit(
                "faphouse-wanilianna-the-squirting-harlot",
                "The Squirting Harlot",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Wanilianna"],
            ),
            _scene_hit(
                "hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over",
                "Fucking My Big Tit Best Friend - Friendship Is Over",
                "2025-06-28",
                "HobbyPorn",
                "https://hobbyporn.com",
                ["Comatozze"],
            ),
        ]
    }
    got = get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes")
    assert (
        got == "https://api.theporndb.net/scenes/hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over"
    )


def test_get_real_url_date_bucket_rejects_low_similarity_candidates():
    """日期桶候选与文件名毫无标题/演员重合时不得硬配（宁可未命中交给下一搜索词/其它站点）。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = r"U:\Media\FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    payload = {
        "data": [
            _scene_hit(
                "faphouse-wanilianna-the-squirting-harlot",
                "The Squirting Harlot",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Wanilianna"],
            ),
            _scene_hit(
                "faphouse-someone-else-same-day",
                "Totally Different Scene",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Someone Else"],
            ),
        ]
    }
    assert get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes") is False


def test_get_real_url_bare_number_file_does_not_guess_from_date_bucket():
    """裸番号文件（无标题信息）不得从日期桶里随便挑一条押中——宁可报未找到。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = r"U:\Media\FapHouse.25.06.28.strm"
    payload = {
        "data": [
            _scene_hit(
                "faphouse-wanilianna-the-squirting-harlot",
                "The Squirting Harlot",
                "2025-06-28",
                "Faphouse",
                "https://faphouse.com",
                ["Wanilianna"],
            )
        ]
    }
    assert get_real_url(payload, file_path, "faphouse", "2025-06-28", "scenes") is False


def test_get_real_url_date_bucket_still_accepts_title_like_filename():
    """既有语义保真：文件名含完整标题时，日期桶仍按相似度选中正确条目。"""
    from mdcx.crawlers.theporndb import get_real_url

    file_path = (
        r"U:\Media\manyvids.26.05.04.ittybittycherry.rough.fuckdoll.free.use."
        "titty.slapping.degrading.sex.xxx.strm"
    )
    payload = {
        "data": [
            _scene_hit(
                "manyvids-wrong-same-day",
                "Something Else Entirely",
                "2026-05-04",
                "manyvids",
                "https://manyvids.com",
                ["Someone Else"],
            ),
            _scene_hit(
                "manyvidsittybittycherry-rough-fuckdoll",
                "Rough Fuckdoll Free Use Titty Slapping Degrading Sex",
                "2026-05-04",
                "manyvids",
                "https://manyvids.com",
                ["IttyBittyCherry"],
            ),
        ]
    }
    got = get_real_url(payload, file_path, "manyvids", "2026-05-04", "scenes")
    assert got == "https://api.theporndb.net/scenes/manyvidsittybittycherry-rough-fuckdoll"


@pytest.mark.asyncio
async def test_theporndb_search_falls_through_when_date_bucket_mismatches(monkeypatch: pytest.MonkeyPatch):
    """端到端复现议题 #94：首个搜索词（厂牌+日期）只回同日不同片 → 拒收 →
    第二个搜索词（厂牌+演员/标题）命中真正目标。"""
    from mdcx.crawlers.theporndb import get_real_url  # noqa: F401

    monkeypatch.setattr(oshash, "oshash", lambda file_path: "fakehash")
    old_token = manager.config.theporndb_api_token
    old_switch_on = list(manager.config.switch_on)
    manager.config.theporndb_api_token = "token"
    manager.config.switch_on = [switch for switch in manager.config.switch_on if switch != Switch.THEPORNDB_NO_HASH]

    wrong_slug = "faphouse-wanilianna-the-squirting-harlot"
    right_slug = "hobbyporncomatozze-fucking-my-big-tit-best-friend-friendship-is-over"

    class Issue94Client:
        async def get_json(self, url, **kwargs):
            if url == "https://api.theporndb.net/scenes/hash/fakehash":
                return None, "HTTP 404"
            if url == "https://api.theporndb.net/scenes?parse=faphouse 2025-06-28&per_page=100":
                return {
                    "data": [
                        _scene_hit(
                            wrong_slug,
                            "The Squirting Harlot",
                            "2025-06-28",
                            "Faphouse",
                            "https://faphouse.com",
                            ["Wanilianna"],
                        )
                    ]
                }, ""
            if url == "https://api.theporndb.net/scenes?parse=faphouse COMATOZZE FUCKING&per_page=100":
                return {
                    "data": [
                        _scene_hit(
                            right_slug,
                            "Fucking My Big Tit Best Friend - Friendship Is Over",
                            "2025-06-28",
                            "HobbyPorn",
                            "https://hobbyporn.com",
                            ["Comatozze"],
                        )
                    ]
                }, ""
            if url == f"https://api.theporndb.net/scenes/{right_slug}":
                return {"data": _api_data(right_slug, "scenes", title="Fucking My Best Friend", date="2025-06-28")}, ""
            return None, f"unexpected url: {url}"

    data = _input("")
    data.number = "Faphouse.25.06.28"
    data.short_number = "Faphouse.25.06.28"
    data.file_path = (
        "U:/Service/欧美转移/FapHouse.25.06.28.Comatozze.Fucking.My.Big.Tit.Best.Friend.Friendship.Is.Over.strm"
    )
    try:
        crawler = TheporndbCrawler(client=Issue94Client())
        res = await crawler.run(data)
    finally:
        manager.config.theporndb_api_token = old_token
        manager.config.switch_on = old_switch_on

    assert res.debug_info.error is None
    assert res.data is not None
    assert res.data.title == "Fucking My Best Friend"
    assert res.debug_info.detail_urls == [f"https://api.theporndb.net/scenes/{right_slug}"]
