"""回归测试: emby_actor_manager 与服务器的 POST/DELETE 交互。

背景
----
当 Emby/Jellyfin 服务器对 POST/DELETE 返回 200/204 但 body 为空（b""）时,
旧的 ``post_content`` 调用方会把**成功的空响应误判为失败**。本测试验证:
- 空 body 判成功 (HTTP 200/204)
- 5xx 判失败
- 本地文件不存在时直接失败不发请求
- 并发 fetch_all_actors 每演员仅调一次详情
- #126: payload 中的哨兵/非法日期与年份值被过滤, 合法值规范化类型后再下发
- #145: 非零填充/多分隔符的合法生日(如 1990-1-2 / 1990/05/12)补零后下发完整 ISO
- #148: Genres/Tags/ProviderIds 恒为集合, 规避服务器 UpdateItem 空引用 400

实现说明
--------
议题 #133 之后, POST/DELETE/fetch 类回调改走轻量直连 ``_emby_request`` (不再经
``manager.acquire_computed`` 的重型恐怖栈)。对这类函数, 测试用 ``_patch_ctx``
同时 patch 掉 ``emby_actor_manager`` 与 ``emby_shared`` 的 ``_emby_request`` 缝,
伪造 ``httpx.Response`` 子集 (见 ``_EmbyResp``), 专注验证调用方的 payload 归一化
与 200/5xx 状态判定。仍走重型列表查询的 ``fetch_all_actors`` (经 ``get_emby_actor_list``)
保留用 patch ``manager.acquire_computed`` 注入 fake client。
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _make_lease(client):
    """构造一个可直接 async with 的 fake lease, .async_client 指向 client."""
    lease = MagicMock()
    lease.__aenter__ = AsyncMock(return_value=MagicMock(async_client=client))
    lease.__aexit__ = AsyncMock(return_value=False)
    return lease


class _EmbyResp:
    """伪造 httpx.Response 的轻量子集(轻量直连 _emby_request 返回它)."""

    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        return self._json_data


# 议题 #133 之后, 回调函数改走轻量直连 _emby_request(不再经 manager.acquire_computed)。
# _patch_ctx 把这个 _emby_request fake 同时打到 manager 与 shared 两个模块(见下)。


def _capture_request(captured: dict, return_value):
    """构造一个捕获 (method, path, data) 的 _emby_request fake."""

    async def fake(method: str, path: str, *, headers=None, data=None, token=None, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["headers"] = headers or {}
        captured["data"] = data
        return return_value

    return fake


@contextlib.contextmanager
def _patch_ctx(fake):
    """把同一个 _emby_request fake 同时 patch 到 manager 与 shared 两个模块."""
    with (
        patch("mdcx.tools.emby_actor_manager._emby_request", fake),
        patch("mdcx.tools.emby_shared._emby_request", fake),
    ):
        yield


@pytest.fixture
def emby_configured(monkeypatch):
    """填必需的 api_key/emby_url/server_type, 否则 get_emby_actor_list 会提前 return []."""
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "api_key", "test-token")
    monkeypatch.setattr(manager.config, "emby_url", "http://test:8096")
    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "user_id", "user-1")


@pytest.fixture
def actor_stub():
    from mdcx.tools.emby_actor_manager import ActorInfo

    return ActorInfo(
        name="测试演员",
        actor_id="actor-001",
        server_id="srv",
        has_image=False,
    )


async def test_update_person_info_returns_success_on_200_empty_body(actor_stub):
    """Emby POST /Items/{id} 返回 200 + 空 body 必须判成功.

    回归: update_person_info 走 _emby_request, 200/204 且 body 判成功;
    调用方 ``if err == "" and body is not None`` 不能误判。
    """
    from mdcx.tools.emby_actor_manager import update_person_info

    resp = _EmbyResp(200)
    ctx, _ = _captured_post(return_value=(resp, ""))

    with ctx:
        ok, msg = await update_person_info(actor_stub)

    assert ok, f"200 空 body 应成功, 实际: {msg!r}"
    assert "成功" in msg


async def test_update_person_info_failure_on_error(actor_stub):
    """_emby_request 返回 (None, err) 时判失败."""
    from mdcx.tools.emby_actor_manager import update_person_info

    ctx, _ = _captured_post(return_value=(None, "HTTP 500"))

    with ctx:
        ok, msg = await update_person_info(actor_stub)

    assert not ok
    assert "失败" in msg


def _captured_post(return_value=None):
    """返回 (patch_ctx, captured dict): patch 掉 _emby_request 并捕获 update_person_info 的 POST body."""
    if return_value is None:
        return_value = (_EmbyResp(200), "")
    captured: dict = {}

    async def _fake_emby_request(method, path, *, headers=None, data=None, token=None, **kwargs):
        captured["payload"] = json.loads(data)
        return return_value

    return _patch_ctx(_fake_emby_request), captured


async def test_update_person_info_drops_sentinel_date_and_year(actor_stub):
    """#126 回归: 无生日演员的哨兵值 "0000-00-00"/"0000" 不得下发, 否则服务器 400.

    EMbyActressInfo.dump() 对未命中的演员输出哨兵默认值, 是字符串且 truthy,
    旧实现按真值直接放进 payload, Emby/Jellyfin 模型绑定拒收。
    """
    from mdcx.tools.emby_actor_manager import update_person_info

    actor_stub.new_premiere_date = "0000-00-00"
    actor_stub.new_production_year = "0000"
    actor_stub.new_overview = "简介文本"

    ctx, captured = _captured_post()
    with ctx:
        ok, msg = await update_person_info(actor_stub)

    assert ok, msg
    payload = captured["payload"]
    assert "PremiereDate" not in payload, f"哨兵日期不应下发: {payload}"
    assert "ProductionYear" not in payload, f"哨兵年份不应下发: {payload}"
    assert payload.get("Overview") == "简介文本"


async def test_update_person_info_keeps_valid_date_and_normalizes_types(actor_stub):
    """合法生日规范化为完整 ISO; 年份字符串转 int."""
    from mdcx.tools.emby_actor_manager import update_person_info

    actor_stub.new_premiere_date = "1990-05-12"
    actor_stub.new_production_year = "1990"
    actor_stub.new_overview = "x"

    ctx, captured = _captured_post()
    with ctx:
        ok, _ = await update_person_info(actor_stub)

    assert ok
    payload = captured["payload"]
    assert payload["PremiereDate"] == "1990-05-12T00:00:00.0000000Z"
    assert payload["ProductionYear"] == 1990
    assert isinstance(payload["ProductionYear"], int)


async def test_update_person_info_drops_invalid_dates(actor_stub):
    """非法日期(月份越界/不存在日期/截断/非日期串)一律不下发."""
    from mdcx.tools.emby_actor_manager import update_person_info

    for bad in ("1990-13-40", "1990-02-30", "1990-", "1990-1", "未知", "abc-def-ghij"):
        actor_stub.new_premiere_date = bad
        actor_stub.new_production_year = None
        actor_stub.new_overview = "x"
        ctx, captured = _captured_post()
        with ctx:
            ok, _ = await update_person_info(actor_stub)
        assert ok
        assert "PremiereDate" not in captured["payload"], f"非法日期 {bad!r} 不应下发"


async def test_update_person_info_normalizes_lenient_date_formats(actor_stub):
    """议题 #145: 非零填充/多分隔符的合法生日应补零下发, 而非丢弃."""
    from mdcx.tools.emby_actor_manager import update_person_info

    cases = {
        "1990-1-2": "1990-01-02T00:00:00.0000000Z",
        "1990/5/12": "1990-05-12T00:00:00.0000000Z",
        "1990.1.2": "1990-01-02T00:00:00.0000000Z",
        "1990年1月2日": "1990-01-02T00:00:00.0000000Z",
        "19900102": "1990-01-02T00:00:00.0000000Z",
    }
    for raw, expected in cases.items():
        actor_stub.new_premiere_date = raw
        actor_stub.new_production_year = None
        actor_stub.new_overview = "x"
        ctx, captured = _captured_post()
        with ctx:
            ok, _ = await update_person_info(actor_stub)
        assert ok
        assert captured["payload"]["PremiereDate"] == expected, f"{raw!r} 归一化错误"


async def test_update_person_info_always_sends_collection_fields(actor_stub):
    """议题 #148: Genres/Tags/ProviderIds 必须恒为集合, 否则服务器 UpdateItem 空引用 400."""
    from mdcx.tools.emby_actor_manager import update_person_info

    ctx, captured = _captured_post()
    with ctx:
        ok, _ = await update_person_info(actor_stub)
    assert ok
    payload = captured["payload"]
    assert payload["Genres"] == []
    assert payload["Tags"] == []
    assert payload["ProviderIds"] == {}

    actor_stub.existing_genres = ["女优", ""]
    actor_stub.existing_tags = ["身高: 164cm", ""]
    actor_stub.existing_provider_ids = {"Imdb": "nm1", "Tmdb": ""}
    ctx, captured = _captured_post()
    with ctx:
        ok, _ = await update_person_info(actor_stub)
    assert ok
    payload = captured["payload"]
    assert payload["Genres"] == ["女优"]
    assert payload["Tags"] == ["身高: 164cm"]
    assert payload["ProviderIds"] == {"Imdb": "nm1"}


async def test_update_person_info_merges_provider_ids(actor_stub):
    """议题 #148: 新增 ProviderIds 覆盖同名键, 并保留服务器已有键."""
    from mdcx.tools.emby_actor_manager import update_person_info

    actor_stub.existing_provider_ids = {"Tmdb": "1", "Imdb": "tt2"}
    actor_stub.new_provider_ids = {"Tmdb": "9", "Douban": ""}
    ctx, captured = _captured_post()
    with ctx:
        ok, _ = await update_person_info(actor_stub)
    assert ok
    assert captured["payload"]["ProviderIds"] == {"Tmdb": "9", "Imdb": "tt2"}


async def test_update_person_info_drops_bad_year_types(actor_stub):
    """年份非正数/bool/非数字字符串一律不下发, int 正数正常下发."""
    from mdcx.tools.emby_actor_manager import update_person_info

    for bad_year in (0, -5, True, "abc", "  ", None):
        actor_stub.new_production_year = bad_year
        actor_stub.new_premiere_date = ""
        actor_stub.new_overview = "x"
        ctx, captured = _captured_post()
        with ctx:
            ok, _ = await update_person_info(actor_stub)
        assert ok
        assert "ProductionYear" not in captured["payload"], f"坏年份 {bad_year!r} 不应下发"

    actor_stub.new_production_year = 2001
    ctx, captured = _captured_post()
    with ctx:
        ok, _ = await update_person_info(actor_stub)
    assert ok
    assert captured["payload"]["ProductionYear"] == 2001


async def test_upload_actor_image_success_on_204_empty(actor_stub, tmp_path: Path):
    """Emby 上传图片 204/空 body 判成功."""
    from mdcx.tools.emby_actor_manager import upload_actor_image

    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    resp = _EmbyResp(204)

    with _patch_ctx(_capture_request({}, (resp, ""))):
        ok, msg = await upload_actor_image(actor_stub, img)

    assert ok, f"204 空 body 应成功, 实际: {msg!r}"


async def test_upload_actor_image_fails_when_file_missing(actor_stub, tmp_path: Path):
    """本地文件不存在直接失败, 不发请求."""
    from mdcx.tools.emby_actor_manager import upload_actor_image

    ok, msg = await upload_actor_image(actor_stub, tmp_path / "nonexistent.jpg")

    assert not ok
    assert "不存在" in msg


async def test_upload_actor_backdrop_targets_index_zero(actor_stub, tmp_path: Path, emby_configured):
    """P0-2 回归：背景上传应覆盖 /Backdrop/0，而不是追加到未指定 index 的列表。"""
    from mdcx.tools.emby_actor_manager import upload_actor_backdrop

    img = tmp_path / "bg.jpg"
    img.write_bytes(b"\xff\xd8\xff")

    captured: dict[str, str] = {}

    async def _fake_emby_request(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["path"] = url if isinstance(url, str) and url.startswith("http") else url
        return _EmbyResp(204), ""

    with _patch_ctx(_fake_emby_request):
        ok, msg = await upload_actor_backdrop(actor_stub, img)

    assert ok, f"上传应成功, 实际: {msg!r}"
    assert str(captured["path"]).endswith("/Items/actor-001/Images/Backdrop/0")


async def test_delete_actor_image_200_is_success(actor_stub):
    """HTTP 200/204 删除成功."""
    from mdcx.tools.emby_actor_manager import delete_actor_image

    for status in (200, 204):
        with _patch_ctx(_capture_request({}, (_EmbyResp(status), ""))):
            ok, msg = await delete_actor_image(actor_stub)

        assert ok, f"HTTP {status} 应成功, 实际: {msg!r}"


async def test_delete_actor_image_404_is_already_gone(actor_stub):
    """404 表示本来就没头像, 视为删除干净以便后续上传."""
    from mdcx.tools.emby_actor_manager import delete_actor_image

    with _patch_ctx(_capture_request({}, (_EmbyResp(404), ""))):
        ok, _ = await delete_actor_image(actor_stub)

    assert ok


async def test_delete_actor_image_500_is_failure(actor_stub):
    """5xx 服务端错误必须判失败, 上层会跳过后续上传."""
    from mdcx.tools.emby_actor_manager import delete_actor_image

    with _patch_ctx(_capture_request({}, (_EmbyResp(500), ""))):
        ok, msg = await delete_actor_image(actor_stub)

    assert not ok
    assert "500" in msg


async def test_delete_actor_image_network_failure(actor_stub):
    """_emby_request 返回 (None, err) 时判失败."""
    from mdcx.tools.emby_actor_manager import delete_actor_image

    with _patch_ctx(_capture_request({}, (None, "ConnRefused"))):
        ok, msg = await delete_actor_image(actor_stub)

    assert not ok


async def test_concurrent_fetch_all_actors_does_not_duplicate_network_calls(actor_stub, emby_configured):
    """asyncio.gather 并发抓详情时, fetch_actor_detail 不应对同一 name 调用多次.

    回归目标: 重构并发后保证 per-actor 只调用一次, 不重复请求。
    """

    from mdcx.tools.emby_actor_manager import fetch_all_actors

    actor_names = [f"演员{i}" for i in range(5)]
    call_log: list[str] = []

    async def fake_detail(name: str):
        call_log.append(name)
        return {"Overview": "test"}

    persons_resp = {
        "Items": [
            {"Name": n, "Id": f"id-{i}", "ServerId": "srv", "ImageTags": {}, "BackdropImageTags": []}
            for i, n in enumerate(actor_names)
        ]
    }

    fake_client = MagicMock()

    async def fake_get_json(url, **kwargs):
        if "Persons" in url:
            return persons_resp, ""
        return {"Items": []}, ""

    fake_client.get_json = fake_get_json

    with (
        patch(
            "mdcx.tools.emby_actor_manager.manager.acquire_computed",
            return_value=_make_lease(fake_client),
        ),
        patch("mdcx.tools.emby_actor_manager.fetch_actor_detail", side_effect=fake_detail),
    ):
        result, raw_count = await fetch_all_actors(filter_actor_only=False, deduplicate=True, parent_ids=None)

    assert len(result) == 5
    # 每个 name 只被调一次 (N+1 重构后必须)
    assert sorted(call_log) == sorted(actor_names), f"实际调用 {len(call_log)} 次: {call_log}"


async def test_fetch_all_actors_reuses_list_fields_when_present(emby_configured):
    """P1-5 回归：/Persons 列表项已含 detail 字段时，不再逐人 fetch_actor_detail。"""
    from mdcx.tools.emby_actor_manager import fetch_all_actors

    call_log: list[str] = []

    persons_resp = {
        "Items": [
            {
                "Name": "演员1",
                "Id": "id-1",
                "ServerId": "srv",
                "ImageTags": {},
                "BackdropImageTags": [],
                "Overview": "已有简介",
                "Taglines": ["t"],
                "ProductionYear": 2020,
            }
        ]
    }

    fake_client = MagicMock()

    async def fake_get_json(url, **kwargs):
        if "Persons" in url:
            return persons_resp, ""
        return {"Items": []}, ""

    fake_client.get_json = fake_get_json

    async def fake_detail(name: str):
        call_log.append(name)
        return {"Overview": "detail"}

    with (
        patch("mdcx.tools.emby_actor_manager.manager.acquire_computed", return_value=_make_lease(fake_client)),
        patch("mdcx.tools.emby_actor_manager.fetch_actor_detail", side_effect=fake_detail),
    ):
        result, raw_count = await fetch_all_actors(filter_actor_only=False, deduplicate=True, parent_ids=None)

    assert len(result) == 1
    assert result[0].existing_overview == "已有简介"
    assert call_log == []


class _FakeResp:
    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        return self._json_data


async def test_media_folders_uses_light_httpx_transport_not_computed(monkeypatch, emby_configured):
    """议题 #133 回归：get_media_folders 走轻量 httpx(无指纹/无池), 不再走 manager.acquire_computed."""
    from mdcx.tools import emby_actor_manager

    captured: dict = {}

    async def fake_get_json(path, **kwargs):
        captured["path"] = path
        return {"Items": [{"Name": "库A", "Id": "lib-1"}]}, ""

    monkeypatch.setattr(emby_actor_manager, "_emby_get_json", fake_get_json)

    # 若误回退到 computered async_client, acquire_computed 被调就应失败
    def boom(*a, **k):
        raise AssertionError("不应再走 manager.acquire_computed 重型客户端")

    monkeypatch.setattr(emby_actor_manager.manager, "acquire_computed", boom)

    result = await emby_actor_manager.get_media_folders()

    assert result == [{"Name": "库A", "Id": "lib-1"}]
    assert captured["path"] == "/emby/Library/MediaFolders", f"Emby 前缀错误: {captured['path']}"


async def test_emby_api_prefix_differs_by_server_type(monkeypatch):
    """Emby 带 /emby 前缀, Jellyfin 不带."""
    from mdcx.config.manager import manager
    from mdcx.tools.emby_shared import _emby_api_prefix

    monkeypatch.setattr(manager.config, "server_type", "emby")
    assert _emby_api_prefix() == "/emby"
    monkeypatch.setattr(manager.config, "server_type", "ln")
    assert _emby_api_prefix() == ""


async def test_emby_request_builds_url_and_auth_header(monkeypatch, emby_configured):
    """轻量客户端: URL=base+path, Authorization 用入参 token, 4xx 返回 (None, 错误)."""
    from mdcx.tools import emby_shared

    captured: dict = {}

    class FakeAsyncClient:
        def __init__(self, timeout=None, verify=None):
            captured["verify"] = verify

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, *, headers=None, content=None):
            captured["url"] = url
            captured["auth"] = (headers or {}).get("Authorization", "")
            return _FakeResp(500, None)

    monkeypatch.setattr(emby_shared.httpx, "AsyncClient", FakeAsyncClient)

    resp, err = await emby_shared._emby_request(
        "GET", "/System/Info", headers={"Content-Type": "application/json"}, token="secret-token"
    )

    assert resp is None
    assert captured["url"] == "http://test:8096/System/Info"
    assert "MediaBrowser" in captured["auth"] and "secret-token" in captured["auth"]
    assert err.startswith("HTTP 500")
