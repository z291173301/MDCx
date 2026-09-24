"""传输层失败 → bypass 兜底回归测试。

背景：强制直连站点（用户直连白名单）在墙内直连即被 RST（curl 35/56，
无 HTTP 响应），挑战判定永不触发、bypass 从未被咨询。现 request() 与
检测链路在“整轮重试一次响应都没拿到”时，给 bypass 一次兜底机会
（真浏览器指纹可能通过 curl 指纹被 RST 的链路）。

约束：仅彻底失败后触发一次——正常通过的请求走不到这里；
enable_cf_bypass=False、非 GET/HEAD、流式请求一律不兜底。
"""

from types import SimpleNamespace

import pytest

from mdcx.core.network_check import (
    NetworkCheckSpec,
    NetworkCheckStatus,
    run_network_check_item,
)
from mdcx.web_async import AsyncWebClient


def _fake_ok_response():
    return SimpleNamespace(
        status_code=200,
        headers={"x-mdcx-bypass-mode": "mirror"},
        content=b"<html>ok</html>",
        url="https://avsex.cc/",
    )


def _make_client():
    # 只配外部 CF 服务：适配层懒启动（_trawl_adapter_enabled=True）。
    return AsyncWebClient(timeout=1, cf_bypass_trawl_url="http://127.0.0.1:8191")


def _mock_transport_failure(client, monkeypatch, *, bypass_ok=True):
    """直连永远拿不到响应；bypass 按开关返回成功/失败。返回调用计数器。"""
    calls = {"curl": 0, "ensure": 0, "bypass": 0}

    async def fake_curl_request(method, url, **kwargs):
        calls["curl"] += 1
        return None

    async def fake_ensure_local_bypass():
        calls["ensure"] += 1
        client._cf_bypass_enabled = True
        client.cf_bypass_url = "http://127.0.0.1:9"
        return True

    async def fake_try_bypass_cloudflare(**kwargs):
        calls["bypass"] += 1
        if not bypass_ok:
            return None, "FlareSolverr 连接失败"
        return _fake_ok_response(), ""

    monkeypatch.setattr(client, "_curl_request", fake_curl_request)
    monkeypatch.setattr(client, "_ensure_local_bypass", fake_ensure_local_bypass)
    monkeypatch.setattr(client, "_try_bypass_cloudflare", fake_try_bypass_cloudflare)
    return calls


@pytest.mark.asyncio
async def test_request_falls_back_to_bypass_on_transport_failure(monkeypatch):
    client = _make_client()
    calls = _mock_transport_failure(client, monkeypatch)

    response, error = await client.request(
        "GET", "https://avsex.cc/", retry_count=1, enable_cf_bypass=True
    )

    assert error == ""
    assert response is not None and response.status_code == 200
    assert calls == {"curl": 1, "ensure": 1, "bypass": 1}


@pytest.mark.asyncio
async def test_request_fallback_failure_keeps_original_error(monkeypatch):
    client = _make_client()
    calls = _mock_transport_failure(client, monkeypatch, bypass_ok=False)

    response, error = await client.request(
        "GET", "https://avsex.cc/", retry_count=1, enable_cf_bypass=True
    )

    assert response is None
    assert "失败" in error  # 原始传输错误为主错误，不被 bypass 错误覆盖
    assert calls["bypass"] == 1


@pytest.mark.asyncio
async def test_request_no_fallback_when_bypass_disabled(monkeypatch):
    client = _make_client()
    calls = _mock_transport_failure(client, monkeypatch)

    response, error = await client.request(
        "GET", "https://avsex.cc/", retry_count=1, enable_cf_bypass=False
    )

    assert response is None
    assert calls["ensure"] == 0 and calls["bypass"] == 0


@pytest.mark.asyncio
async def test_request_no_fallback_when_response_received(monkeypatch):
    """拿到过 HTTP 响应（即使失败）也不兜底：通过中/普通失败路径行为不变。"""
    client = _make_client()
    calls = _mock_transport_failure(client, monkeypatch)

    async def fake_curl_ok(method, url, **kwargs):
        calls["curl"] += 1
        return SimpleNamespace(status_code=200, headers={}, content=b"ok", url=url)

    monkeypatch.setattr(client, "_curl_request", fake_curl_ok)

    response, error = await client.request(
        "GET", "https://avsex.cc/", retry_count=1, enable_cf_bypass=True
    )

    assert error == "" and response is not None
    assert calls["ensure"] == 0 and calls["bypass"] == 0


@pytest.mark.asyncio
async def test_request_no_fallback_for_post(monkeypatch):
    """非幂等方法不兜底，避免经第三方服务重复提交。"""
    client = _make_client()
    calls = _mock_transport_failure(client, monkeypatch)

    response, _ = await client.request(
        "POST", "https://avsex.cc/", retry_count=1, enable_cf_bypass=True
    )

    assert response is None
    assert calls["bypass"] == 0


class _CheckFakeResponse:
    def __init__(self, text="<html>ok</html>", url="https://avsex.cc"):
        self.status_code = 200
        self.text = text
        self.url = url
        self.headers = {"x-mdcx-bypass-mode": "mirror"}
        self.encoding = "utf-8"


class _CheckTransportFailClient:
    """检测链路桩：直连永远无响应，bypass 按开关返回。"""

    def __init__(self, *, bypass_ok=True):
        self.bypass_ok = bypass_ok
        self.bypass_calls: list[dict] = []

    async def request(self, method, url, **kwargs):
        return None, "连接错误: Recv failure: Connection was reset"

    async def _ensure_local_bypass(self):
        return True

    async def _try_bypass_cloudflare(self, **kwargs):
        self.bypass_calls.append(kwargs)
        if not self.bypass_ok:
            return None, "FlareSolverr 连接失败"
        return _CheckFakeResponse(url=kwargs["target_url"]), ""


class _TrawlOnlyConfig:
    use_proxy = False
    proxy = ""
    cf_bypass_url = ""
    cf_bypass_proxy = ""
    cf_bypass_trawl_url = "http://127.0.0.1:8191"
    cf_bypass_trawl_backend = "flaresolverr"
    timeout = 5
    proxy_sites = ""
    direct_sites = ""

    def proxy_hosts_list(self):
        return []

    def direct_sites_list(self):
        return []


class _TrawlOnlyManager:
    config = _TrawlOnlyConfig()
    computed = None


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_check_falls_back_to_bypass_on_transport_failure(monkeypatch):
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: _TrawlOnlyManager())
    client = _CheckTransportFailClient(bypass_ok=True)
    spec = NetworkCheckSpec(
        name="avsex", group="刮削站点", url="https://avsex.cc", enable_cf_bypass=True
    )

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.OK
    assert "CF Bypass" in result.message
    assert len(client.bypass_calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_check_fallback_failure_keeps_transport_error(monkeypatch):
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: _TrawlOnlyManager())
    client = _CheckTransportFailClient(bypass_ok=False)
    spec = NetworkCheckSpec(
        name="avsex", group="刮削站点", url="https://avsex.cc", enable_cf_bypass=True
    )

    result = await run_network_check_item(spec, client=client)

    assert result.status == NetworkCheckStatus.FAILED
    assert "连接错误" in (result.error or "")
