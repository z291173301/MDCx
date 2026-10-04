"""`check_version` 的两级取数（REST API → releases.atom）与本地缓存回归测试。

缺陷 B（用户实测「检测新版本的代码很不稳定，一会能检测到一会检测不到」）：原实现只打
`api.github.com/repos/.../releases`。**匿名调 GitHub API 只有 60 次/小时/出口 IP 的配额**
（`X-RateLimit-Limit: 60`，实测 `Remaining: 0` 时同一出口 IP 下的所有人一起被拒），且
配额按小时重置——于是「能不能检测到新版本」变成了一件随时间跳变的事，跟本地版本比较
逻辑毫无关系。同一出口 IP（CGNAT / 公司网关 / 代理池）下多人同时启动 MDCx 最容易把它打空。

本文件钉住三件事：
1. **API 任何失败（限流 403 / 超时 / 5xx / 解析异常）都要退回 `releases.atom`**
   （走 github.com 站点主机，不受那个 60/h 配额约束），且仍取 tag 最大、标题照旧参与
   版本号比较；
2. **缓存新鲜时不发任何请求**（同一 IP 下反复启动不再消耗配额）；
3. **两条网络路径都失败时用上次成功记录兜底**，不让「有没有新版本」随网络抖动飘。
"""

import json
import time

import pytest

import mdcx.base.web as base_web
from mdcx.base.web import RemoteVersion
from mdcx.config.manager import manager
from mdcx.consts import GITHUB_RELEASES_API_LIST, GITHUB_RELEASES_ATOM

_RATE_LIMIT_HEADERS = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1791156189"}


class _FakeResponse:
    def __init__(self, payload=None, text="", status_code: int = 200, headers: dict[str, str] | None = None):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeClient:
    """按 URL 返回预设响应；记录被请求的 URL，用于断言「有没有多打一次 atom 请求」。"""

    calls: list[str] = []
    responses: dict[str, _FakeResponse] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def get(self, url, headers=None):
        _FakeClient.calls.append(url)
        return _FakeClient.responses[url]


class _BoomClient:
    """所有请求都抛异常（断网 / DNS 失败 / 代理不可用）。"""

    calls: list[str] = []

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def get(self, url, headers=None):
        _BoomClient.calls.append(url)
        raise OSError("network is unreachable")


def _atom(*entries: tuple[str, str]) -> str:
    """按 (标题, tag) 组装一条 releases.atom；tag 传空串表示非纯数字 tag。"""
    items = []
    for title, tag in entries:
        href = f"https://github.com/z291173301/MDCx/releases/tag/{tag or title}"
        items.append(
            f"""<entry>
  <id>tag:github.com,2008:Repository/{hash(title) % 10**8}</id>
  <updated>2026-10-05T00:00:00Z</updated>
  <link rel="alternate" type="text/html" href="{href}"/>
  <title>{title}</title>
</entry>"""
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
        + "".join(items)
        + "</feed>"
    )


def _api(*releases: tuple[str, str]) -> _FakeResponse:
    payload = [{"tag_name": tag, "name": name} for tag, name in releases]
    return _FakeResponse(payload=payload)


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """缓存重定向到临时目录：本文件要断言缓存的**行为**（不重复请求 / 兜底），不能写到真实数据目录。"""
    cache_path = tmp_path / "version_check_cache.json"
    monkeypatch.setattr(base_web, "_version_cache_path", lambda: cache_path)
    monkeypatch.setattr(manager.config, "update_check", True)
    monkeypatch.setattr(manager.config, "use_proxy", False)
    monkeypatch.setattr(manager.config, "proxy", "")
    monkeypatch.setattr(manager.config, "timeout", 10)
    _FakeClient.calls = []
    _BoomClient.calls = []
    _FakeClient.responses = {}
    return cache_path


@pytest.fixture(autouse=True)
def _quiet_detail_log(monkeypatch: pytest.MonkeyPatch):
    logs: list[str] = []
    monkeypatch.setattr(base_web.signal, "add_log", lambda *text: logs.append(" ".join(map(str, text))))
    return logs


def _use_fake_client(monkeypatch: pytest.MonkeyPatch, responses: dict[str, _FakeResponse]):
    _FakeClient.responses = responses
    monkeypatch.setattr(base_web.httpx, "Client", _FakeClient)


# --------------------------------------------------------------------------- 1. atom 兜底


def test_atom_fallback_when_api_rate_limited(monkeypatch: pytest.MonkeyPatch, _quiet_detail_log):
    """API 403 配额耗尽（正是用户实测到的状态）→ 退回 atom，且仍返回可用的版本号。"""
    _use_fake_client(
        monkeypatch,
        {
            GITHUB_RELEASES_API_LIST: _FakeResponse(status_code=403, headers=_RATE_LIMIT_HEADERS),
            GITHUB_RELEASES_ATOM: _FakeResponse(text=_atom(("v2.2.4 (20261007)", "20261007"))),
        },
    )

    remote = base_web.check_version()

    assert remote == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")
    # 降级必须留痕：用户报「检测不到」时要能一眼看出是 API 配额打满后走的兜底
    assert any("releases.atom" in line for line in _quiet_detail_log)
    assert any("限流" in line for line in _quiet_detail_log)


@pytest.mark.parametrize(
    ("api_response", "case"),
    [
        (_FakeResponse(status_code=500), "5xx"),
        (_FakeResponse(status_code=403, headers={"x-ratelimit-remaining": "9"}), "403 非配额耗尽"),
        (_FakeResponse(payload={"message": "Not Found"}), "响应不是数组"),
        (_FakeResponse(payload=[{"tag_name": "v2.2.4", "name": "v2.2.4"}]), "列表里没有纯数字 tag"),
    ],
)
def test_atom_fallback_on_every_api_failure_mode(monkeypatch: pytest.MonkeyPatch, api_response, case):
    """API 的各类失败形态都要退回 atom，而不是直接放弃检测。"""
    _use_fake_client(
        monkeypatch,
        {
            GITHUB_RELEASES_API_LIST: api_response,
            GITHUB_RELEASES_ATOM: _FakeResponse(text=_atom(("v2.2.4 (20261007)", "20261007"))),
        },
    )

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")


def test_atom_fallback_when_api_times_out(monkeypatch: pytest.MonkeyPatch):
    """API 连接超时/断网 → atom 仍能取到版本（atom 走另一个主机，可能通）。"""

    class _ApiDeadClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def get(self, url, headers=None):
            if url == GITHUB_RELEASES_API_LIST:
                raise TimeoutError("timed out")
            return _FakeResponse(text=_atom(("v2.2.4 (20261007)", "20261007")))

    monkeypatch.setattr(base_web.httpx, "Client", _ApiDeadClient)

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")


def test_atom_picks_max_tag_not_first_entry():
    """atom 按发布时间倒序：补发的旧 tag 排在第一条时也必须取最大 tag。"""
    feed = _atom(
        ("v2.1.7 (20260930)", "20260930"),
        ("v2.2.4 (20261007)", "20261007"),
        ("nightly", ""),
        ("v2.2.3 (20261006)", "20261006"),
    )

    assert base_web.parse_release_atom(feed) == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")


def test_atom_title_is_html_unescaped():
    """atom 里标题是转义过的 HTML 实体，必须反转义后当标题用。"""

    assert base_web.parse_release_atom(_atom(("v2.2.4 &amp; 20261007", "20261007"))) == RemoteVersion(
        tag=20261007, name="v2.2.4 & 20261007"
    )


def test_atom_without_numeric_tag_returns_none():
    """整份 feed 都取不到纯数字 tag（仓库还没发过版）→ None，不抛异常。"""

    assert base_web.parse_release_atom(_atom(("nightly", ""), ("v2.2.4", ""))) is None
    assert base_web.parse_release_atom("") is None
    assert base_web.parse_release_atom("<html>404</html>") is None


def test_atom_version_still_comparable_to_local():
    """兜底取到的版本号要能照常参与比较（版本号优先、版本号相等才比日期）。"""
    remote = base_web.parse_release_atom(_atom(("v2.2.4 (20261007)", "20261007")))

    # 本地 v2.2.3 / 20261006 → 提示更新
    assert base_web.is_remote_version_newer(remote, 20261006, "v2.2.3")
    # 本地已是 v2.2.4 / 20261007 → 已是最新
    assert not base_web.is_remote_version_newer(remote, 20261007, "v2.2.4")


def test_api_success_never_touches_atom(monkeypatch: pytest.MonkeyPatch):
    """API 成功时**不能**再多打一次 atom 请求（否则每次检查都白白多一个网络往返）。"""
    _use_fake_client(monkeypatch, {GITHUB_RELEASES_API_LIST: _api(("20261007", "v2.2.4 (20261007)"))})

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")
    assert _FakeClient.calls == [GITHUB_RELEASES_API_LIST]


def test_atom_fallback_tries_configured_proxy_first(monkeypatch: pytest.MonkeyPatch):
    """atom 兜底同样遵守「配置代理 → 直连」的顺序（代理用户的第一条路仍是代理）。"""
    seen: list[tuple[str, str | None]] = []

    class _RecordingClient:
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def get(self, url, headers=None):
            seen.append((url, self.proxy))
            if url == GITHUB_RELEASES_API_LIST:
                return _FakeResponse(status_code=403, headers=_RATE_LIMIT_HEADERS)
            if self.proxy:
                raise OSError("proxy refused")
            return _FakeResponse(text=_atom(("v2.2.4 (20261007)", "20261007")))

    monkeypatch.setattr(base_web.httpx, "Client", _RecordingClient)
    monkeypatch.setattr(manager.config, "use_proxy", True)
    monkeypatch.setattr(manager.config, "proxy", "http://127.0.0.1:7890")

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")
    atom_calls = [proxy for url, proxy in seen if url == GITHUB_RELEASES_ATOM]
    assert atom_calls == ["http://127.0.0.1:7890", None]


# --------------------------------------------------------------------------- 2. 缓存


def test_fresh_cache_skips_all_requests(monkeypatch: pytest.MonkeyPatch, _isolated_cache):
    """TTL 内的缓存直接复用，一个请求都不发——这正是省下 60 次/小时配额的那一层。"""
    _use_fake_client(monkeypatch, {GITHUB_RELEASES_API_LIST: _api(("20261007", "v2.2.4 (20261007)"))})

    first = base_web.check_version()
    assert first == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")
    assert len(_FakeClient.calls) == 1
    assert json.loads(_isolated_cache.read_text(encoding="UTF-8"))["tag"] == 20261007

    second = base_web.check_version()

    assert second == first
    assert _FakeClient.calls == [GITHUB_RELEASES_API_LIST]  # 第二次没有新增请求


def test_cache_still_refreshes_after_ttl(monkeypatch: pytest.MonkeyPatch, _isolated_cache):
    """超过 TTL 必须重新联网（否则新版本发布后永远看不到提示）。"""
    _isolated_cache.write_text(
        json.dumps({"tag": 20261006, "name": "v2.2.3 (20261006)", "checked_at": time.time() - 3600}),
        encoding="UTF-8",
    )
    monkeypatch.setattr(base_web, "_VERSION_CACHE_TTL", 60.0)
    _use_fake_client(monkeypatch, {GITHUB_RELEASES_API_LIST: _api(("20261007", "v2.2.4 (20261007)"))})

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")
    assert _FakeClient.calls == [GITHUB_RELEASES_API_LIST]


def test_network_failure_falls_back_to_stale_cache(monkeypatch: pytest.MonkeyPatch, _isolated_cache, _quiet_detail_log):
    """两条网络路径全挂时用上次成功记录兜底：宁可稍旧，也不要让提示随网络抖动消失。"""
    _isolated_cache.write_text(
        json.dumps({"tag": 20261007, "name": "v2.2.4 (20261007)", "checked_at": time.time() - 30 * 86400}),
        encoding="UTF-8",
    )
    monkeypatch.setattr(base_web.httpx, "Client", _BoomClient)

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")
    assert any("上次成功记录" in line for line in _quiet_detail_log)


def test_no_cache_and_network_failure_returns_none(monkeypatch: pytest.MonkeyPatch, _quiet_detail_log):
    """既没缓存又断网 → 返回 None 并报错（与旧行为一致，不抛异常打断启动流程）。"""
    monkeypatch.setattr(base_web.httpx, "Client", _BoomClient)

    assert base_web.check_version() is None
    assert any("获取最新版本失败" in line for line in _quiet_detail_log)


@pytest.mark.parametrize("broken", ["", "not json", "[]", '{"tag": "abc", "name": "x", "checked_at": 1}', "{}"])
def test_broken_cache_is_ignored_not_fatal(monkeypatch: pytest.MonkeyPatch, _isolated_cache, broken):
    """缓存损坏/字段非法 → 当作没有缓存，重新联网，而不是抛异常。"""
    _isolated_cache.write_text(broken, encoding="UTF-8")
    _use_fake_client(monkeypatch, {GITHUB_RELEASES_API_LIST: _api(("20261007", "v2.2.4 (20261007)"))})

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")


def test_unwritable_cache_does_not_break_check(monkeypatch: pytest.MonkeyPatch):
    """缓存写不出去（如只读数据目录）不影响本次检测结果。"""
    monkeypatch.setattr(base_web, "_version_cache_path", lambda: _UnwritablePath())
    _use_fake_client(monkeypatch, {GITHUB_RELEASES_API_LIST: _api(("20261007", "v2.2.4 (20261007)"))})

    assert base_web.check_version() == RemoteVersion(tag=20261007, name="v2.2.4 (20261007)")


class _UnwritablePath:
    """任何读写都抛 OSError，模拟只读目录 / 权限不足。"""

    def with_suffix(self, suffix):
        return self

    def write_text(self, *args, **kwargs):
        raise PermissionError("read-only file system")

    def read_text(self, *args, **kwargs):
        raise PermissionError("read-only file system")


def test_update_check_disabled_makes_no_request(monkeypatch: pytest.MonkeyPatch, _isolated_cache):
    """关掉「检查更新」开关时：既不联网，也不读缓存（用户明确关了就不该有任何痕迹）。"""
    _isolated_cache.write_text(
        json.dumps({"tag": 20261007, "name": "v2.2.4 (20261007)", "checked_at": time.time()}),
        encoding="UTF-8",
    )
    _use_fake_client(monkeypatch, {GITHUB_RELEASES_API_LIST: _api(("20261007", "v2.2.4 (20261007)"))})
    monkeypatch.setattr(manager.config, "update_check", False)

    assert base_web.check_version() is None
    assert _FakeClient.calls == []
