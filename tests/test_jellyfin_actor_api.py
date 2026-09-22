from urllib.parse import parse_qs, urlparse

import pytest

from mdcx.config.manager import manager
from mdcx.tools import emby_actor_image
from mdcx.tools.emby_shared import _build_jellyfin_headers


def _expected_auth(token: str) -> str:
    """Jellyfin 10.11+/12.x 要求完整 MediaBrowser 设备标识 (议题 #32)."""
    from mdcx.consts import VERSION_NAME

    return f'MediaBrowser Client="MDCx", Device="MDCx", DeviceId="MDCx", Version="{VERSION_NAME}", Token="{token}"'


def test_build_jellyfin_headers_has_full_authorization_fields():
    headers = _build_jellyfin_headers(token="secret-token")
    auth = headers["Authorization"]
    assert 'Client="MDCx"' in auth
    assert 'Device="MDCx"' in auth
    assert 'DeviceId="MDCx"' in auth
    assert "Version=" in auth
    assert 'Token="secret-token"' in auth


def test_build_jellyfin_headers_keeps_extra_headers():
    headers = _build_jellyfin_headers({"Content-Type": "image/jpeg"}, token="t")
    assert headers["Content-Type"] == "image/jpeg"
    assert "Authorization" in headers


@pytest.mark.asyncio
async def test_upload_actor_photo_sends_base64_image_body_for_emby(monkeypatch: pytest.MonkeyPatch, tmp_path):
    import base64

    captured: dict = {}
    pic_path = tmp_path / "actor.jpg"
    pic_bytes = b"\xff\xd8\xfftest-bytes"
    pic_path.write_bytes(pic_bytes)

    class _Resp:
        status_code = 204

    async def fake_request(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return _Resp(), ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr("mdcx.tools.emby_shared._emby_request", fake_request)
    monkeypatch.setattr(emby_actor_image.signal, "show_log_text", lambda text: None)

    result, error = await emby_actor_image._upload_actor_photo(
        "http://127.0.0.1:8096/emby/Items/1/Images/Primary?api_key=test-token", pic_path
    )

    assert result is True
    assert error == ""
    expected_b64 = base64.b64encode(pic_bytes).decode("ascii")
    assert captured["data"] == expected_b64  # 服务端期望 Base64 编码字符串而非原始二进制
    assert captured["headers"] == {"Content-Type": "image/jpeg", "Authorization": _expected_auth("")}


@pytest.mark.asyncio
async def test_get_emby_actor_list_uses_jellyfin_actor_endpoint(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    async def fake_get_json(url: str, *, headers=None, use_proxy=True, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["use_proxy"] = use_proxy
        return {"Items": [{"Name": "演员A"}]}, ""

    monkeypatch.setattr(manager.config, "server_type", "jellyfin")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "secret-token")
    monkeypatch.setattr(manager.config, "user_id", "user-1")
    monkeypatch.setattr(manager.computed.async_client, "get_json", fake_get_json)
    monkeypatch.setattr(emby_actor_image.signal, "show_log_text", lambda text: None)

    actor_list = await emby_actor_image._get_emby_actor_list()

    parsed = urlparse(captured["url"])
    query = parse_qs(parsed.query)

    assert actor_list == [{"Name": "演员A"}]
    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8096"
    # Jellyfin 12 的 /Persons 列表端点走独立 PeopleRepository 全量返回（议题 #103 回退）
    assert parsed.path == "/Persons"
    assert "includeItemTypes" not in query
    assert query["personTypes"] == ["Actor"]
    assert query["fields"] == [",".join(emby_actor_image.JELLYFIN_PERSON_FIELDS)]
    assert query["enableImages"] == ["true"]
    assert query["userId"] == ["user-1"]
    assert "api_key" not in query
    assert "ApiKey" not in query
    assert captured["headers"] == {"Authorization": _expected_auth("secret-token")}
    assert captured["use_proxy"] is False


@pytest.mark.asyncio
async def test_upload_actor_photo_sends_base64_image_body_for_jellyfin(monkeypatch: pytest.MonkeyPatch, tmp_path):
    import base64

    captured: dict = {}
    pic_path = tmp_path / "actor.jpg"
    pic_bytes = b"\xff\xd8\xfftest-bytes"
    pic_path.write_bytes(pic_bytes)

    class _Resp:
        status_code = 204

    async def fake_request(method, url, *, headers=None, data=None, token=None, **kwargs):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        return _Resp(), ""

    monkeypatch.setattr(manager.config, "server_type", "jellyfin")
    monkeypatch.setattr(manager.config, "api_key", "secret-token")
    monkeypatch.setattr("mdcx.tools.emby_shared._emby_request", fake_request)
    monkeypatch.setattr(emby_actor_image.signal, "show_log_text", lambda text: None)

    result, error = await emby_actor_image._upload_actor_photo("http://127.0.0.1:8096/Items/1/Images/Primary", pic_path)

    assert result is True
    assert error == ""
    expected_b64 = base64.b64encode(pic_bytes).decode("ascii")
    assert captured["data"] == expected_b64  # 服务端期望 Base64 编码字符串而非原始二进制
    assert captured["headers"] == {
        "Content-Type": "image/jpeg",
        "Authorization": _expected_auth("secret-token"),
    }


@pytest.mark.asyncio
async def test_get_actor_detail_reuses_jellyfin_list_payload(monkeypatch: pytest.MonkeyPatch):
    actor = {
        "Name": "演员A",
        "Id": "1",
        "ServerId": "server-1",
        "Overview": "",
        "ProviderIds": {},
        "ProductionLocations": [],
        "Taglines": [],
        "Genres": [],
        "Tags": [],
    }

    async def fake_get_json(*args, **kwargs):
        raise AssertionError("Jellyfin 演员详情不应再次请求 /Persons/{name}")

    monkeypatch.setattr(manager.config, "server_type", "jellyfin")
    monkeypatch.setattr(manager.computed.async_client, "get_json", fake_get_json)

    result, error = await emby_actor_image._get_actor_detail(actor)

    assert result is actor
    assert error == ""


def test_generate_server_url_uses_new_jellyfin_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "server_type", "jellyfin")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096/")
    monkeypatch.setattr(manager.config, "api_key", "legacy-key-should-not-appear")
    monkeypatch.setattr(manager.config, "user_id", "user-1")

    homepage, actor_person, pic_url, backdrop_url, backdrop_url_0, update_url = emby_actor_image._generate_server_url(
        {"Name": "梦乃 爱华", "Id": "item-1", "ServerId": "server-1"}
    )

    assert homepage == "http://127.0.0.1:8096/web/index.html#!/details?id=item-1&serverId=server-1"
    assert actor_person.startswith("http://127.0.0.1:8096/Persons/")
    assert "%E6%A2%A6%E4%B9%83%20%E7%88%B1%E5%8D%8E" in actor_person
    assert actor_person.endswith("?userId=user-1")
    assert pic_url == "http://127.0.0.1:8096/Items/item-1/Images/Primary"
    assert backdrop_url == "http://127.0.0.1:8096/Items/item-1/Images/Backdrop"
    assert backdrop_url_0 == "http://127.0.0.1:8096/Items/item-1/Images/Backdrop/0"
    assert update_url == "http://127.0.0.1:8096/Items/item-1"
    assert "api_key" not in actor_person
    assert "api_key" not in pic_url
    assert "api_key" not in backdrop_url
    assert "api_key" not in backdrop_url_0
    assert "api_key" not in update_url


def test_is_jellyfin_server_emby_actor_image(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "server_type", "ln")
    assert emby_actor_image._is_jellyfin_server() is True
    monkeypatch.setattr(manager.config, "server_type", "jellyfin")
    assert emby_actor_image._is_jellyfin_server() is True
    monkeypatch.setattr(manager.config, "server_type", "emby")
    assert emby_actor_image._is_jellyfin_server() is False


def test_is_jellyfin_server_emby_actor_manager(monkeypatch: pytest.MonkeyPatch):
    from mdcx.tools import emby_actor_manager

    monkeypatch.setattr(manager.config, "server_type", "ln")
    assert emby_actor_manager._is_jellyfin_server() is True
    monkeypatch.setattr(manager.config, "server_type", "emby")
    assert emby_actor_manager._is_jellyfin_server() is False


@pytest.mark.asyncio
async def test_get_emby_actor_list_emby_uses_actor_filter(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    async def fake_get_json(url: str, *, headers=None, use_proxy=True, **kwargs):
        captured["url"] = url
        return {"Items": []}, ""

    monkeypatch.setattr(manager.config, "server_type", "emby")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "api_key", "secret-token")
    monkeypatch.setattr(manager.config, "user_id", "user-1")
    monkeypatch.setattr(manager.computed.async_client, "get_json", fake_get_json)
    monkeypatch.setattr(emby_actor_image.signal, "show_log_text", lambda text: None)

    actor_list = await emby_actor_image._get_emby_actor_list()

    assert actor_list == []
    assert captured["url"].startswith("http://127.0.0.1:8096/emby/Persons?")
    assert "personTypes=Actor" in captured["url"]
    assert "ImageTags" in captured["url"]
