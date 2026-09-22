import json

import httpx
import pytest

import mdcx.cf_bypass.trawl_adapter as ta
from mdcx.cf_bypass.trawl_adapter import (
    _build_target_url,
    _cookie_to_set_cookie,
    create_trawl_adapter_app,
)

TRAWL_BASE = "http://fake-trawl:8191"
FS_BASE = "http://fake-flaresolverr:8191"


def _scrape_response(payload: dict, *, html: str = "<html>ok</html>", status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "url": payload.get("url", ""),
            "html": html,
            "cookies": [
                {"name": "cf_clearance", "value": "abc", "path": "/", "domain": "example.com", "httpOnly": True}
            ],
            "userAgent": "Mozilla/5.0 (TRAWL)",
            "statusCode": status_code,
        },
    )


def _flaresolverr_response(payload: dict, *, html: str = "<html>ok</html>", status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "ok",
            "message": "",
            "version": "2.0.0",
            "solution": {
                "url": payload.get("url", ""),
                "status": status_code,
                "headers": {"content-type": "text/html"},
                "response": html,
                "cookies": [
                    {"name": "cf_clearance", "value": "abc", "path": "/", "domain": "example.com", "httpOnly": True}
                ],
                "userAgent": "Mozilla/5.0 (FlareSolverr)",
            },
        },
    )


def _make_app(monkeypatch, trawl_requests: list[dict], response_fn, backend: str = "trawl"):
    """创建适配层 app：适配层内部请求外部服务时走 MockTransport。"""
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        # 测试侧显式传 transport（ASGITransport）时保持真实行为；
        # 适配层内部创建无 transport 的 client 时注入 MockTransport。
        if "transport" in kwargs:
            return real_client(*args, **kwargs)
        kwargs = dict(kwargs)
        kwargs["transport"] = _transport()
        return real_client(*args, **kwargs)

    def _transport():
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/scrape" and request.method == "POST":
                payload = json.loads(request.read())
                trawl_requests.append(payload)
                return response_fn(payload)
            if request.url.path == "/v1" and request.method == "POST":
                payload = json.loads(request.read())
                trawl_requests.append(payload)
                return response_fn(payload)
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/":
                return httpx.Response(200, json={"version": "2.0.0"})
            return httpx.Response(404, text="not found")

        return httpx.MockTransport(handler)

    monkeypatch.setattr(ta.httpx, "AsyncClient", factory)
    base = FS_BASE if backend == "flaresolverr" else TRAWL_BASE
    return create_trawl_adapter_app(base, backend)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://adapter")


@pytest.mark.asyncio
async def test_cookies_endpoint_translates_to_scrape(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _scrape_response(p))
    async with _client(app) as client:
        resp = await client.get("/cookies?url=https://example.com/protected")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cookies"]["cf_clearance"] == "abc"
    assert data["user_agent"] == "Mozilla/5.0 (TRAWL)"
    assert trawl_requests[0]["url"] == "https://example.com/protected"
    assert trawl_requests[0]["maxTimeout"] == 60_000


@pytest.mark.asyncio
async def test_html_endpoint_returns_html_and_final_url_header(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _scrape_response(p, html="<html>rendered</html>"))
    async with _client(app) as client:
        resp = await client.get("/html?url=https://example.com/protected")
    assert resp.status_code == 200
    assert resp.text == "<html>rendered</html>"
    assert resp.headers["x-cf-bypasser-final-url"] == "https://example.com/protected"
    assert resp.headers["x-cf-bypasser-cookies"] == "1"


@pytest.mark.asyncio
async def test_html_forwards_proxy_and_ignores_bypass_cache(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _scrape_response(p))
    async with _client(app) as client:
        resp = await client.get("/html?url=https://example.com/p&proxy=http://127.0.0.1:7890&bypassCookieCache=true")
    assert resp.status_code == 200
    assert trawl_requests[0]["proxy"] == "http://127.0.0.1:7890"
    # bypassCookieCache 不再映射为 skipHttp：让 TRAWL 走 Tier1 直连缓存路径
    assert "skipHttp" not in trawl_requests[0]


@pytest.mark.asyncio
async def test_mirror_endpoint_rebuilds_target_url_and_forwards_method(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _scrape_response(p, html="<html>mirror</html>"))
    async with _client(app) as client:
        resp = await client.get(
            "/api/data?id=1",
            headers={"x-hostname": "javbus.example"},
        )
    assert resp.status_code == 200
    assert trawl_requests[0]["url"] == "https://javbus.example/api/data?id=1"
    assert trawl_requests[0]["method"] == "GET"
    assert resp.text == "<html>mirror</html>"
    set_cookie = resp.headers.get("set-cookie", "")
    assert "cf_clearance=abc" in set_cookie


@pytest.mark.asyncio
async def test_mirror_strips_control_headers(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _scrape_response(p))
    async with _client(app) as client:
        await client.get(
            "/api",
            headers={
                "x-hostname": "a.example",
                "x-proxy": "http://127.0.0.1:7890",
                "x-bypass-cache": "true",
                "user-agent": "MyUA",
            },
        )
    payload = trawl_requests[0]
    assert payload["proxy"] == "http://127.0.0.1:7890"
    # x-bypass-cache 不再映射为 skipHttp：让 TRAWL 走 Tier1 直连缓存路径
    assert "skipHttp" not in payload
    assert payload["headers"]["user-agent"] == "MyUA"
    assert "x-hostname" not in payload["headers"]
    assert "x-proxy" not in payload["headers"]
    assert "x-bypass-cache" not in payload["headers"]


@pytest.mark.asyncio
async def test_mirror_requires_x_hostname(monkeypatch):
    app = _make_app(monkeypatch, [], lambda p: _scrape_response(p))
    async with _client(app) as client:
        resp = await client.get("/api/data")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_trawl_connection_error_becomes_502(monkeypatch):
    app = create_trawl_adapter_app(TRAWL_BASE)
    async with _client(app) as client:
        resp = await client.get("/cookies?url=https://example.com/x")
    assert resp.status_code == 502
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_flaresolverr_cookies_endpoint_uses_v1(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _flaresolverr_response(p), backend="flaresolverr")
    async with _client(app) as client:
        resp = await client.get("/cookies?url=https://example.com/protected")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cookies"]["cf_clearance"] == "abc"
    assert data["user_agent"] == "Mozilla/5.0 (FlareSolverr)"
    payload = trawl_requests[0]
    assert payload["cmd"] == "request.get"
    assert payload["url"] == "https://example.com/protected"


@pytest.mark.asyncio
async def test_flaresolverr_html_endpoint_returns_solution_response(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(
        monkeypatch, trawl_requests, lambda p: _flaresolverr_response(p, html="<html>fs</html>"), backend="flaresolverr"
    )
    async with _client(app) as client:
        resp = await client.get("/html?url=https://example.com/protected")
    assert resp.status_code == 200
    assert resp.text == "<html>fs</html>"
    assert resp.headers["x-cf-bypasser-final-url"] == "https://example.com/protected"
    assert trawl_requests[0]["cmd"] == "request.get"


@pytest.mark.asyncio
async def test_flaresolverr_mirror_posts_as_request_post(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _flaresolverr_response(p), backend="flaresolverr")
    async with _client(app) as client:
        resp = await client.post(
            "/api/submit",
            content=b'{"key": "value"}',
            headers={"x-hostname": "a.example", "content-type": "application/json"},
        )
    assert resp.status_code == 200
    payload = trawl_requests[0]
    assert payload["cmd"] == "request.post"
    assert payload["postData"] == '{"key": "value"}'
    assert payload["headers"]["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_flaresolverr_mirror_rebuilds_url(monkeypatch):
    trawl_requests: list[dict] = []
    app = _make_app(monkeypatch, trawl_requests, lambda p: _flaresolverr_response(p), backend="flaresolverr")
    async with _client(app) as client:
        resp = await client.get("/api/data?id=1", headers={"x-hostname": "javbus.example"})
    assert resp.status_code == 200
    payload = trawl_requests[0]
    assert payload["url"] == "https://javbus.example/api/data?id=1"
    assert payload["cmd"] == "request.get"


@pytest.mark.asyncio
async def test_flaresolverr_error_response_becomes_502(monkeypatch):
    app = create_trawl_adapter_app(FS_BASE, "flaresolverr")
    async with _client(app) as client:
        resp = await client.get("/cookies?url=https://example.com/x")
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_build_target_url_defaults_https():
    assert _build_target_url("example.com", "/api", "a=1") == "https://example.com/api?a=1"
    assert _build_target_url("https://a.b/c", "/d", "") == "https://a.b/d"
    assert _build_target_url("example.com", "/", "") == "https://example.com/"


def test_cookie_to_set_cookie():
    cookie = {
        "name": "cf_clearance",
        "value": "v",
        "path": "/",
        "domain": ".example.com",
        "httpOnly": True,
        "secure": True,
    }
    header = _cookie_to_set_cookie(cookie)
    assert "cf_clearance=v" in header
    assert "Path=/" in header
    assert "Domain=.example.com" in header
    assert "HttpOnly" in header
    assert "Secure" in header
