"""议题 #158 回归: 「获取演员类型」勾选/不勾选两档的数据正确性与健壮性。

真机 (Emby, 24 个库 / 49299 条目 / 14518 人) 全量审查发现的问题:

1. IncludeItemTypes 只扫 Movie,Episode → 只挂剧集级卡司、没写进任何一集的人员不在
   统计集合里, 被「仅演员」交集过滤当成库外人员误删。真机 Series 的 31 个唯一人名
   中有 25 个不在 Movie/Episode 扫描结果内, 且服务端仍把这批人算作 personTypes=Actor。
2. /Persons 单次全量响应 (1.4W 人, 1.65s) 在万人库上会把服务端组装拖到超时
   (与议题 #32 的 Items 教训同类), 且中途无法响应「停止」。
3. 出演统计分页循环没有停止检查 → 真机 99 页 / 65s 期间「停止」按钮完全无响应。
4. TotalRecordCount 走裸 int() → 脏值(""/"N/A"/[]) 抛 ValueError/TypeError 冒泡
   出协程, 一条异常打断整次抓取。
5. FetchActorsThread 每次抓取都再拉一次全量 /Persons 只为算「总数」; 未勾选
   「仅演员」时主查询拿到的就是全量名单, 纯属重复重查询。
6. 全量统计查询单独失败(0) 时把统计栏「总数」抹成 0。
7. 注释断言「Emby /Persons 不支持按角色过滤」与真机实测不符 (personTypes=Actor
   实测 13568/14518 确实生效), 已更正。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _configure(monkeypatch, server_type: str = "emby"):
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "api_key", "test-token")
    monkeypatch.setattr(manager.config, "emby_url", "http://test:8096")
    monkeypatch.setattr(manager.config, "server_type", server_type)
    monkeypatch.setattr(manager.config, "user_id", "user-1")


def _make_lease(client):
    """构造可直接 async with 的 fake lease, .async_client 指向 client。"""
    lease = MagicMock()
    lease.__aenter__ = AsyncMock(return_value=MagicMock(async_client=client))
    lease.__aexit__ = AsyncMock(return_value=False)
    return lease


def _patch_persons_client(monkeypatch, handler):
    """把 curl_cffi 客户端的 get_json 接到 handler(url)->(dict|None, err) 缝上。

    返回捕获到的 url 列表。
    """
    from mdcx.tools import emby_actor_manager as eam

    captured: list[str] = []

    async def fake_get_json(url, **kwargs):
        captured.append(url)
        return await handler(url)

    client = MagicMock()
    client.get_json = fake_get_json
    monkeypatch.setattr(eam.manager, "acquire_computed", lambda: _make_lease(client))
    return captured


def _patch_items_request(monkeypatch, handler):
    """把 _emby_request 接到 handler(path)->(dict|None, err) 缝上, 返回 path 列表。"""
    from mdcx.tools import emby_actor_manager as eam
    from mdcx.tools import emby_shared as esh

    captured: list[str] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    async def fake(method: str, path: str, **kwargs):
        captured.append(path)
        payload, err = await handler(path)
        if payload is None:
            return None, err
        return _Resp(payload), ""

    monkeypatch.setattr(eam, "_emby_request", fake)
    monkeypatch.setattr(esh, "_emby_request", fake)
    return captured


@pytest.fixture
def reset_staff_count_cache():
    from mdcx.tools import emby_actor_manager as eam

    eam._all_staff_count_cache = None
    yield
    eam._all_staff_count_cache = None


# --------------------------------------------------------------------------------------
# 1. _safe_int
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5, 5),
        ("5", 5),
        ("  7 ", 7),
        (9.0, 9),
        (None, None),
        ("", None),
        ("N/A", None),
        ([], None),
        ({}, None),
        (True, None),
    ],
)
def test_safe_int_coercion(raw, expected):
    """TotalRecordCount 是脏值时必须退化为 None, 不能抛 ValueError/TypeError。"""
    from mdcx.tools.emby_actor_manager import _safe_int

    assert _safe_int(raw) == expected


# --------------------------------------------------------------------------------------
# 2. /Persons 分页
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persons_list_paginates_and_merges_pages(monkeypatch, reset_staff_count_cache):
    """/Persons 必须分页拉取并合并——万人库单次全量响应会让服务端组装超时(#32 同类)。"""
    from urllib.parse import parse_qs, urlparse

    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    limit = eam._PERSONS_PAGE_LIMIT
    total = limit * 2 + 7  # 三页: 满 / 满 / 短页

    async def handler(url):
        start = int(parse_qs(urlparse(url).query)["StartIndex"][0])
        size = min(limit, total - start)
        items = [{"Name": f"人{start + i}", "Id": str(start + i), "ServerId": "s"} for i in range(max(size, 0))]
        return {"Items": items, "TotalRecordCount": total}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    actors = await eam.get_emby_actor_list(filter_actor_only=True)

    assert len(actors) == total
    assert [a["Name"] for a in actors[:2]] == ["人0", "人1"]
    assert len(urls) == 3, f"应分 3 页, 实际 {len(urls)}"
    starts = [int(parse_qs(urlparse(u).query)["StartIndex"][0]) for u in urls]
    assert starts == [0, limit, limit * 2]


@pytest.mark.asyncio
async def test_persons_list_paging_keeps_person_types_actor(monkeypatch, reset_staff_count_cache):
    """分页不得丢掉 personTypes=Actor——否则「仅演员」会退化成全量。"""
    from urllib.parse import parse_qs, urlparse

    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        return {"Items": [{"Name": "演员A", "Id": "1", "ServerId": "s"}], "TotalRecordCount": 1}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    await eam.get_emby_actor_list(filter_actor_only=True)

    for u in urls:
        assert parse_qs(urlparse(u).query)["personTypes"] == ["Actor"]
        assert "/emby/Persons" in u


@pytest.mark.asyncio
async def test_persons_list_does_not_query_person_types_when_unchecked(monkeypatch, reset_staff_count_cache):
    """不勾选「仅演员」时不得带 personTypes(要全量, 含导演/编剧/制片)。"""
    from urllib.parse import parse_qs, urlparse

    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        return {"Items": [{"Name": "导演B", "Id": "2", "ServerId": "s"}], "TotalRecordCount": 1}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    await eam.get_emby_actor_list(filter_actor_only=False)

    assert "personTypes" not in parse_qs(urlparse(urls[0]).query)


@pytest.mark.asyncio
async def test_persons_list_keeps_partial_result_when_later_page_fails(monkeypatch, reset_staff_count_cache):
    """中途分页失败应保住已取回的人员, 而不是整轮归零(防误删, 同 #32 教训)。"""
    from urllib.parse import parse_qs, urlparse

    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    limit = eam._PERSONS_PAGE_LIMIT
    logs: list[str] = []
    monkeypatch.setattr(eam.signal, "show_log_text", logs.append)

    total = limit * 3

    async def handler(url):
        start = int(parse_qs(urlparse(url).query)["StartIndex"][0])
        if start == 0:
            # 必须是满页, 否则短页信号会在第 1 页就终止, 走不到失败分支
            items = [{"Name": f"人{i}", "Id": str(i), "ServerId": "s"} for i in range(limit)]
            return {"Items": items, "TotalRecordCount": total}, ""
        return None, "HTTP 504 超时"

    _patch_persons_client(monkeypatch, handler)

    actors = await eam.get_emby_actor_list(filter_actor_only=True)

    assert len(actors) == limit, "第 2 页失败应保住第 1 页已取回的全部人员"
    assert any("分页中断" in m and f"已取回 {limit} 人" in m for m in logs), logs


@pytest.mark.asyncio
async def test_persons_list_survives_garbage_total_record_count(monkeypatch, reset_staff_count_cache):
    """TotalRecordCount 是脏字符串时靠短页终止, 不能抛异常打断整次抓取。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        return {"Items": [{"Name": "演员A", "Id": "1", "ServerId": "s"}], "TotalRecordCount": "N/A"}, ""

    _patch_persons_client(monkeypatch, handler)

    actors = await eam.get_emby_actor_list(filter_actor_only=True)

    assert [a["Name"] for a in actors] == ["演员A"]


@pytest.mark.asyncio
async def test_persons_list_survives_non_dict_body(monkeypatch, reset_staff_count_cache):
    """服务端返回非对象(数组/null)时按失败处理, 不让 .get 抛错。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        return None, "非法响应"

    _patch_persons_client(monkeypatch, handler)

    assert await eam.get_emby_actor_list(filter_actor_only=True) == []


@pytest.mark.asyncio
async def test_persons_list_responds_to_stop_between_pages(monkeypatch, reset_staff_count_cache):
    """分页之间必须检查停止请求——单次 1.4W 人响应期间无法中断。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    calls = {"n": 0}
    limit = eam._PERSONS_PAGE_LIMIT

    async def handler(url):
        calls["n"] += 1
        # 满页才能继续翻页, 否则短页信号会先终止循环
        items = [{"Name": f"人{i}", "Id": str(i), "ServerId": "s"} for i in range(limit)]
        return {"Items": items, "TotalRecordCount": limit * 10}, ""

    _patch_persons_client(monkeypatch, handler)

    # 第 1 页放行、第 2 页前判定为已停止 —— 验证检查点在页与页之间
    calls_seen: list[int] = []

    def fake_is_stop_requested() -> bool:
        calls_seen.append(1)
        return len(calls_seen) > 2

    monkeypatch.setattr(eam, "_is_stop_requested", fake_is_stop_requested)

    with pytest.raises(eam.ActorTaskStopped):
        await eam.get_emby_actor_list(filter_actor_only=True)

    assert calls["n"] < 3, f"应在早于第 3 页停下, 实际请求 {calls['n']} 页"


@pytest.mark.asyncio
async def test_persons_list_skips_request_without_api_key(monkeypatch, reset_staff_count_cache):
    """没填 API 密钥时直接返回 [], 不得发起任何请求。"""
    from mdcx.config.manager import manager
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    monkeypatch.setattr(manager.config, "api_key", "")
    monkeypatch.setattr(eam.signal, "show_log_text", lambda _m: None)

    async def handler(url):  # pragma: no cover - 不应被调用
        raise AssertionError("无密钥时不应发起请求")

    _patch_persons_client(monkeypatch, handler)

    assert await eam.get_emby_actor_list(filter_actor_only=True) == []


@pytest.mark.asyncio
async def test_persons_list_uses_jellyfin_path_without_emby_prefix(monkeypatch, reset_staff_count_cache):
    """Jellyfin 走 /Persons(无 /emby 前缀), Emby 走 /emby/Persons。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "jellyfin")

    async def handler(url):
        return {"Items": [{"Name": "演员A", "Id": "1", "ServerId": "s"}], "TotalRecordCount": 1}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    await eam.get_emby_actor_list(filter_actor_only=True)

    assert "/emby/Persons" not in urls[0]
    assert "/Persons" in urls[0]


# --------------------------------------------------------------------------------------
# 3. 总数复用 (不重复重查询)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_staff_count_reuses_unchecked_query_result(monkeypatch, reset_staff_count_cache):
    """未勾选「仅演员」时主查询已是全量, 取总数不得再发第二次全量 /Persons。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        return {"Items": [{"Name": f"人{i}", "Id": str(i), "ServerId": "s"} for i in range(3)], "TotalRecordCount": 3}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    await eam.get_emby_actor_list(filter_actor_only=False)
    before = len(urls)
    assert before > 0

    assert await eam.get_all_staff_count() == 3
    assert len(urls) == before, "总数必须复用主查询结果, 不能再请求一次"


@pytest.mark.asyncio
async def test_all_staff_count_fetches_when_cache_cold(monkeypatch, reset_staff_count_cache):
    """缓存为空时(勾选了「仅演员」)才自己拉一次全量。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        return {"Items": [{"Name": f"人{i}", "Id": str(i), "ServerId": "s"} for i in range(4)], "TotalRecordCount": 4}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    assert await eam.get_all_staff_count() == 4
    assert len(urls) == 1
    assert "personTypes" not in urls[0]


@pytest.mark.asyncio
async def test_all_staff_count_expires(monkeypatch, reset_staff_count_cache):
    """短 TTL 到期后要重新取, 免得统计栏「总数」长期陈旧。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    monkeypatch.setattr(eam, "_ALL_STAFF_COUNT_TTL", 0.0)

    async def handler(url):
        return {"Items": [{"Name": "人1", "Id": "1", "ServerId": "s"}], "TotalRecordCount": 1}, ""

    urls = _patch_persons_client(monkeypatch, handler)

    await eam.get_all_staff_count()
    await eam.get_all_staff_count()

    assert len(urls) == 2


@pytest.mark.asyncio
async def test_all_staff_count_not_cached_when_fetch_fails(monkeypatch, reset_staff_count_cache):
    """失败返回的 0 不能进缓存, 否则后续成功也取不到真实总数。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    state = {"fail": True}

    async def handler(url):
        if state["fail"]:
            return None, "连接失败"
        return {"Items": [{"Name": "人1", "Id": "1", "ServerId": "s"}], "TotalRecordCount": 1}, ""

    _patch_persons_client(monkeypatch, handler)

    assert await eam.get_all_staff_count() == 0
    assert eam._all_staff_count_cache is None

    state["fail"] = False
    assert await eam.get_all_staff_count() == 1


@pytest.mark.asyncio
async def test_unchecked_persons_feed_total_even_when_actor_filter_on(monkeypatch, reset_staff_count_cache):
    """勾选「仅演员」的主查询(带 personTypes)不得污染「总数」缓存。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        if "personTypes" in url:
            return {"Items": [{"Name": "演员A", "Id": "1", "ServerId": "s"}], "TotalRecordCount": 1}, ""
        return {"Items": [{"Name": f"人{i}", "Id": str(i), "ServerId": "s"} for i in range(9)], "TotalRecordCount": 9}, ""

    _patch_persons_client(monkeypatch, handler)

    await eam.get_emby_actor_list(filter_actor_only=True)
    assert await eam.get_all_staff_count() == 9


# --------------------------------------------------------------------------------------
# 4. 出演统计: Series 卡司 / 停止检查 / 脏 TotalRecordCount
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_only_actor_survives_intersection_filter(monkeypatch):
    """回归: 只挂剧集级卡司的演员, 勾选「仅演员」时不得被交集过滤误删。

    真机: Series 的 31 个唯一人名中 25 个不在 Movie/Episode 扫描结果内。
    """
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(path):
        return {
            "Items": [
                {
                    "Name": "某剧集",
                    "Type": "Series",
                    "People": [{"Name": "剧集级演员", "Type": "Actor"}],
                }
            ],
            "TotalRecordCount": 1,
        }, ""

    _patch_items_request(monkeypatch, handler)

    counts, titles, names = await eam.fetch_person_item_stats(filter_actor_only=True)

    assert "剧集级演员" in names, "剧集级卡司必须进入出演人名集合, 否则被当成库外人员剔除"
    assert counts["剧集级演员"] == 1
    assert titles["剧集级演员"] == ["[Series] 某剧集"]


@pytest.mark.asyncio
async def test_series_still_respects_role_whitelist(monkeypatch):
    """Series 纳入后, 其 Director/Writer 仍不得混进「仅演员」集合。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(path):
        return {
            "Items": [
                {
                    "Name": "某剧集",
                    "Type": "Series",
                    "People": [
                        {"Name": "演员A", "Type": "Actor"},
                        {"Name": "客串B", "Type": "GuestStar"},
                        {"Name": "导演C", "Type": "Director"},
                        {"Name": "编剧D", "Type": "Writer"},
                    ],
                }
            ],
            "TotalRecordCount": 1,
        }, ""

    _patch_items_request(monkeypatch, handler)

    _counts, _titles, names = await eam.fetch_person_item_stats(filter_actor_only=True)

    assert names == {eam._actor_dedup_key("演员A"), eam._actor_dedup_key("客串B")}


@pytest.mark.asyncio
async def test_person_stats_query_includes_series_type(monkeypatch):
    """IncludeItemTypes 必须含 Series, 且仍保留 #32 的瘦身参数。"""
    from urllib.parse import parse_qs, urlparse

    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "jellyfin")

    async def handler(path):
        return {"Items": [], "TotalRecordCount": 0}, ""

    paths = _patch_items_request(monkeypatch, handler)

    await eam.fetch_person_item_stats(parent_ids=["lib-1"])

    query = parse_qs(urlparse(paths[0]).query)
    assert query["IncludeItemTypes"] == ["Movie,Episode,Series"]
    assert query["EnableImages"] == ["false"]
    assert query["EnableUserData"] == ["false"]


@pytest.mark.asyncio
async def test_person_stats_responds_to_stop_between_pages(monkeypatch):
    """回归: 分页循环无停止检查 → 真机 99 页 / 65s 期间「停止」无响应。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    calls = {"n": 0}

    async def handler(path):
        calls["n"] += 1
        items = [
            {"Name": f"影片{calls['n']}", "Type": "Movie", "People": [{"Name": f"演员{calls['n']}", "Type": "Actor"}]}
            for _ in range(500)
        ]
        return {"Items": items, "TotalRecordCount": 5000}, ""

    _patch_items_request(monkeypatch, handler)

    # 第 1 页放行、第 2 页前判定为已停止
    checks: list[int] = []

    def fake_is_stop_requested() -> bool:
        checks.append(1)
        return len(checks) > 1

    monkeypatch.setattr(eam, "_is_stop_requested", fake_is_stop_requested)

    with pytest.raises(eam.ActorTaskStopped):
        await eam.fetch_person_item_stats(filter_actor_only=True)

    assert calls["n"] < 3, f"应在早于第 3 页停下, 实际请求 {calls['n']} 页"


@pytest.mark.asyncio
async def test_person_stats_survives_garbage_total_record_count(monkeypatch):
    """回归: 裸 int() 遇脏 TotalRecordCount 抛 ValueError, 冒泡打断整次抓取。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(path):
        return (
            {
                "Items": [{"Name": "影片1", "Type": "Movie", "People": [{"Name": "演员A", "Type": "Actor"}]}],
                "TotalRecordCount": "很多",
            },
            "",
        )

    _patch_items_request(monkeypatch, handler)

    with contextlib.suppress(eam.ActorTaskStopped):
        counts, _titles, names = await eam.fetch_person_item_stats(filter_actor_only=True)

    assert names == {eam._actor_dedup_key("演员A")}


@pytest.mark.asyncio
async def test_person_stats_short_page_terminates_when_total_record_count_zero(monkeypatch):
    """TotalRecordCount 为 0 时不能恒真短路, 也不能死循环——靠短页退出。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    pages = {"n": 0}

    async def handler(path):
        pages["n"] += 1
        return (
            {
                "Items": [{"Name": f"影片{pages['n']}", "Type": "Movie", "People": [{"Name": f"演员{pages['n']}", "Type": "Actor"}]}],
                "TotalRecordCount": 0,
            },
            "",
        )

    _patch_items_request(monkeypatch, handler)

    _counts, _titles, names = await eam.fetch_person_item_stats(filter_actor_only=True)

    assert pages["n"] == 1, "单页(< page_limit)必须立刻终止"
    assert names == {eam._actor_dedup_key("演员1")}


# --------------------------------------------------------------------------------------
# 5. UI: 统计栏总数不被 0 抹掉
# --------------------------------------------------------------------------------------


def test_fetch_finished_keeps_known_total_when_count_query_failed(monkeypatch):
    """全量统计查询单独失败(0)时, 不得把统计栏「总数」抹成 0。"""
    _ensure_app()
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog.__new__(ui.EmbyActorManagerDialog)
    dlg._actors = []
    dlg._raw_count = 0
    dlg._all_staff_count = 12345
    dlg._is_stale_session = lambda: False
    dlg._set_status = lambda _m: None
    dlg.log = lambda _m: None
    dlg._populate_table = lambda _a: None
    dlg._update_statistics = lambda _a: None
    dlg.btn_preview = MagicMock()
    dlg.progress_bar = MagicMock()
    dlg._set_buttons_enabled = lambda _b: None

    with contextlib.suppress(Exception):
        dlg._on_fetch_finished([], 0, 0)

    assert dlg._all_staff_count == 12345, "统计查询失败(0)不应覆盖已知总数"


def test_fetch_finished_updates_total_when_count_available(monkeypatch):
    """拿到有效总数时正常更新。"""
    _ensure_app()
    from mdcx.tools import emby_actor_manager_ui as ui

    dlg = ui.EmbyActorManagerDialog.__new__(ui.EmbyActorManagerDialog)
    dlg._actors = []
    dlg._raw_count = 0
    dlg._all_staff_count = 1
    dlg._is_stale_session = lambda: False
    dlg._set_status = lambda _m: None
    dlg.log = lambda _m: None
    dlg._populate_table = lambda _a: None
    dlg._update_statistics = lambda _a: None
    dlg.btn_preview = MagicMock()
    dlg.progress_bar = MagicMock()
    dlg._set_buttons_enabled = lambda _b: None

    with contextlib.suppress(Exception):
        dlg._on_fetch_finished([], 0, 777)

    assert dlg._all_staff_count == 777


def test_fetch_thread_does_not_refetch_full_persons(monkeypatch):
    """FetchActorsThread 取总数必须走 get_all_staff_count(带缓存), 不能裸调 /Persons。

    未勾选「仅演员」时主查询已经是全量, 再发一次全量 /Persons 是纯浪费。
    """
    _ensure_app()
    from mdcx.tools import emby_actor_manager_ui as ui

    calls = {"all_staff": 0, "raw_persons": 0}

    async def fake_fetch_all(**kwargs):
        return [], 0

    async def fake_get_all_staff_count(refresh: bool = False):
        calls["all_staff"] += 1
        return 42

    async def fake_get_emby_actor_list(filter_actor_only=True):
        calls["raw_persons"] += 1
        return [{"Name": "人1"}]

    monkeypatch.setattr(ui, "fetch_all_actors", fake_fetch_all)
    monkeypatch.setattr(ui, "get_all_staff_count", fake_get_all_staff_count)
    monkeypatch.setattr(ui.manager.config, "actor_filter_only", False)
    monkeypatch.setattr(ui.manager.config, "actor_deduplicate", True)

    thread = ui.FetchActorsThread()
    thread.library_ids = None
    emitted: list[tuple] = []
    thread.fetch_done.connect(lambda *a: emitted.append(a))
    thread.run()

    assert calls["all_staff"] == 1, "应通过带缓存的 get_all_staff_count 取总数"
    assert calls["raw_persons"] == 0, "不得再直接调 get_emby_actor_list 拉第二次全量 /Persons"
    assert emitted and emitted[0][2] == 42


# --------------------------------------------------------------------------------------
# 6. 角色过滤端到端语义（不再依赖「Emby 不支持 personTypes」的错误前提）
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checked_keeps_actors_drops_director(monkeypatch, reset_staff_count_cache):
    """勾选「仅演员」: 服务端 personTypes=Actor 与本地交集共同剔除导演/编剧/制片。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")
    server_side = [
        {"Name": "演员A", "Id": "1", "ServerId": "s", "Overview": "简介"},
        {"Name": "客串B", "Id": "2", "ServerId": "s", "Overview": "简介"},
    ]

    async def handler(url):
        return {"Items": server_side, "TotalRecordCount": 2}, ""

    _patch_persons_client(monkeypatch, handler)

    async def fake_stats(parent_ids=None, filter_actor_only=True, page_limit=500):
        # 服务端把客串也归到 personTypes=Actor, 但本地扫描额外核到了 GuestStar
        # 统计映射以去重键为键(议题 #164)
        ka, kb = eam._actor_dedup_key("演员A"), eam._actor_dedup_key("客串B")
        return {ka: 1, kb: 1}, {}, {ka, kb}

    monkeypatch.setattr(eam, "fetch_person_item_stats", fake_stats)

    actors, raw = await eam.fetch_all_actors(filter_actor_only=True, deduplicate=True)

    assert [a.name for a in actors] == ["演员A", "客串B"]
    assert raw == 2


@pytest.mark.asyncio
async def test_checked_drops_non_performer_present_in_person_list(monkeypatch, reset_staff_count_cache):
    """勾选「仅演员」: 名单里出现但不在任何条目 People 中的导演必须被剔除。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        items = [
            {"Name": "演员A", "Id": "1", "ServerId": "s", "Overview": "简介"},
            {"Name": "导演B", "Id": "2", "ServerId": "s", "Overview": "简介"},
            {"Name": "编剧C", "Id": "3", "ServerId": "s", "Overview": "简介"},
        ]
        return {"Items": items, "TotalRecordCount": 3}, ""

    _patch_persons_client(monkeypatch, handler)

    async def fake_stats(parent_ids=None, filter_actor_only=True, page_limit=500):
        ka = eam._actor_dedup_key("演员A")
        return {ka: 2}, {}, {ka}

    monkeypatch.setattr(eam, "fetch_person_item_stats", fake_stats)

    actors, raw = await eam.fetch_all_actors(filter_actor_only=True, deduplicate=True)

    assert [a.name for a in actors] == ["演员A"]
    assert raw == 1


@pytest.mark.asyncio
async def test_unchecked_keeps_every_role(monkeypatch, reset_staff_count_cache):
    """不勾选「仅演员」且未选媒体库子集: 不做任何过滤, 导演/编剧/制片全部保留。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        assert "personTypes" not in url
        items = [
            {"Name": "演员A", "Id": "1", "ServerId": "s", "Overview": "简介"},
            {"Name": "导演B", "Id": "2", "ServerId": "s", "Overview": "简介"},
            {"Name": "编剧C", "Id": "3", "ServerId": "s", "Overview": "简介"},
        ]
        return {"Items": items, "TotalRecordCount": 3}, ""

    _patch_persons_client(monkeypatch, handler)

    actors, raw = await eam.fetch_all_actors(filter_actor_only=False, deduplicate=True)

    assert {a.name for a in actors} == {"演员A", "导演B", "编剧C"}
    assert raw == 3


@pytest.mark.asyncio
async def test_unchecked_with_library_subset_still_filters_by_library(monkeypatch, reset_staff_count_cache):
    """不勾选「仅演员」但选了媒体库子集: 仍按库过滤, 只放宽角色维度。"""
    from mdcx.tools import emby_actor_manager as eam

    _configure(monkeypatch, "emby")

    async def handler(url):
        items = [
            {"Name": "演员A", "Id": "1", "ServerId": "s", "Overview": "简介"},
            {"Name": "导演B", "Id": "2", "ServerId": "s", "Overview": "简介"},
            {"Name": "库外D", "Id": "4", "ServerId": "s", "Overview": "简介"},
        ]
        return {"Items": items, "TotalRecordCount": 3}, ""

    _patch_persons_client(monkeypatch, handler)

    async def fake_stats(parent_ids=None, filter_actor_only=True, page_limit=500):
        # 不勾选时统计集合含全部角色
        ka, kb = eam._actor_dedup_key("演员A"), eam._actor_dedup_key("导演B")
        return {ka: 1, kb: 1}, {}, {ka, kb}

    monkeypatch.setattr(eam, "fetch_person_item_stats", fake_stats)

    actors, _raw = await eam.fetch_all_actors(
        filter_actor_only=False, deduplicate=True, parent_ids=["lib-1"]
    )

    assert {a.name for a in actors} == {"演员A", "导演B"}