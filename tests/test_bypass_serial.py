"""检测页 bypass 串行化回归测试。

背景：检测组内并发跑项，直连失败站同时触发 bypass 兜底占浏览器，
TRAWL/FlareSolverr 浏览器池满后集体 502（浏览器池已饱和）。
现单 run 在 run 客户端上挂一把 `_bypass_serial_lock`，
所有 bypass 经 `_try_bypass_cloudflare` 包装器串行，同一时刻只占一个浏览器。
正常刮削不设该 attribute，走快路径，行为零变化。
"""

import asyncio
from types import SimpleNamespace

import pytest

from mdcx.core.network_check import NetworkCheckSpec
from mdcx.web_async import AsyncWebClient


def _make_client():
    return AsyncWebClient(timeout=1, cf_bypass_trawl_url="http://127.0.0.1:8191")


def _bypass_kwargs(i):
    return {
        "host": f"h{i}.test",
        "method": "GET",
        "target_url": f"https://h{i}.test/",
        "headers": None,
        "cookies": None,
        "data": None,
        "json_data": None,
        "timeout": None,
        "allow_redirects": True,
        "use_proxy": False,
    }


@pytest.mark.asyncio
async def test_bypass_serial_lock_serializes_concurrent_calls():
    """挂锁后 3 路并发 bypass 互斥，最大并发恒为 1。"""
    client = _make_client()
    state = {"active": 0, "max_active": 0, "calls": 0}

    async def fake_impl(**kwargs):
        state["calls"] += 1
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.05)
        state["active"] -= 1
        return SimpleNamespace(status_code=200, headers={}), ""

    client._try_bypass_cloudflare_impl = fake_impl
    client._bypass_serial_lock = asyncio.Lock()

    results = await asyncio.gather(*[client._try_bypass_cloudflare(**_bypass_kwargs(i)) for i in range(3)])

    assert state["calls"] == 3
    assert state["max_active"] == 1
    assert all(resp is not None for resp, _ in results)


@pytest.mark.asyncio
async def test_bypass_without_lock_keeps_fast_path():
    """不挂锁走快路径：直接调 impl，参数原样透传。"""
    client = _make_client()
    assert getattr(client, "_bypass_serial_lock", None) is None
    called = {}

    async def fake_impl(**kwargs):
        called.update(kwargs)
        return None, "nope"

    client._try_bypass_cloudflare_impl = fake_impl
    resp, err = await client._try_bypass_cloudflare(**_bypass_kwargs(0))

    assert resp is None and err == "nope"
    assert called["host"] == "h0.test"


class _RunFakeClient:
    """走完整 run：request 直接成功，记录请求时刻锁是否存在。"""

    def __init__(self):
        self.saw_lock_during_request = "unset"

    async def request(self, method, url, **kwargs):
        self.saw_lock_during_request = getattr(self, "_bypass_serial_lock", None)
        return SimpleNamespace(status_code=200, headers={}, text="<html>ok</html>"), ""


@pytest.mark.asyncio
async def test_run_mounts_and_clears_serial_lock(monkeypatch):
    """run 期间锁挂在 run 客户端上，结束后摘掉（正常刮削不背锁）。"""
    monkeypatch.setattr("mdcx.core.network_check._manager", lambda: _MinimalManager())
    from mdcx.core.network_check import run_network_check

    client = _RunFakeClient()
    spec = NetworkCheckSpec(name="t", group="刮削站点", url="https://t.test", enable_cf_bypass=False)

    results = await run_network_check(specs=[spec], client=client, emit_header=False, progress=lambda line: None)

    assert len(results) == 1
    assert client.saw_lock_during_request is not None
    assert getattr(client, "_bypass_serial_lock", None) is None


class _MinimalConfig:
    use_proxy = False
    proxy = ""
    cf_bypass_url = ""
    cf_bypass_proxy = ""
    cf_bypass_trawl_url = ""
    cf_bypass_trawl_backend = "trawl"
    timeout = 5
    proxy_sites = ""
    direct_sites = ""

    def proxy_hosts_list(self):
        return []

    def direct_sites_list(self):
        return []


class _MinimalManager:
    config = _MinimalConfig()
    computed = None
