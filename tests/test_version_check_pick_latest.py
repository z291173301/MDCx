"""`check_version` 必须取 **tag 最大** 的 release，而不是列表第一条。

背景（缺陷 A）：`/releases` 按 `created_at` 倒序返回，**不是按 tag 倒序**。发版工作流
`build-py314.yml` 的四个 `Create Release` 步骤用**同一 tag + `overwrite: true`**
（`svenstaro/upload-release-action` 是先删后建），于是任何一次补发/重跑都会把那条
release 的 `created_at` 刷成"当前时间"、顶到列表第一位。原实现
`for release in releases: if tag.isdigit(): return int(tag)` 直接返回第一条 →
手动补发一次旧 tag（如 20260930）之后，`check_version()` 会永远返回那个旧版本号，
**所有用户从此看不到任何新版本提示**，且没有任何报错。

本文件锁三件事：
1. 列表顺序错乱（第一条是旧 tag）时仍取最大 tag；
2. 非纯数字 tag 一律跳过（含混在中间位置的 `v2.1.8` / `py314-20261001`）；
3. 同一 tag 的重复条目不报错，取该 tag 的首个标题。
"""

import pytest

import mdcx.base.web as base_web
from mdcx.base.web import RemoteVersion
from mdcx.config.manager import manager


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200, headers: dict[str, str] | None = None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeClient:
    """只实现 check_version 用到的那两个接口；记录被请求的 URL 与代理。"""

    calls: list[tuple[str, dict]] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def get(self, url, headers=None):
        _FakeClient.calls.append((url, self.kwargs))
        return _FakeClient.response


def _release(tag: str, name: str = "", created: str = "2026-01-01T00:00:00Z"):
    return {"tag_name": tag, "name": name, "created_at": created, "draft": False, "prerelease": False}


def _stub(monkeypatch: pytest.MonkeyPatch, payload, status_code: int = 200, headers=None):
    """桩掉 httpx.Client 与开关配置，让 check_version 走单次固定响应。"""
    _FakeClient.calls = []
    _FakeClient.response = _FakeResponse(payload, status_code=status_code, headers=headers)
    monkeypatch.setattr(base_web.httpx, "Client", _FakeClient)
    monkeypatch.setattr(manager.config, "update_check", True)
    monkeypatch.setattr(manager.config, "use_proxy", False)
    monkeypatch.setattr(manager.config, "proxy", "")
    monkeypatch.setattr(manager.config, "timeout", 10)


@pytest.fixture(autouse=True)
def _quiet_detail_log(monkeypatch: pytest.MonkeyPatch):
    """失败分支写 signal.add_log（详情日志框），桩掉免得污染断言与真实日志。"""
    logs: list[str] = []
    monkeypatch.setattr(base_web.signal, "add_log", lambda *text: logs.append(" ".join(map(str, text))))
    return logs


def test_picks_max_tag_when_oldest_release_comes_first(monkeypatch: pytest.MonkeyPatch):
    """缺陷 A 正身：补发的旧 tag 被 created_at 顶到第一位，仍须取最大 tag。"""
    _stub(
        monkeypatch,
        [
            # 补发 20260930 → created_at 被刷成最新，排到第一位
            _release("20260930", "v2.1.7 (20260930)", created="2026-10-05T00:00:00Z"),
            _release("20261001", "v2.1.8 (20261001)", created="2026-10-01T09:04:33Z"),
            _release("20260928", "v2.1.5 (20260928)", created="2026-09-28T04:52:01Z"),
        ],
    )

    assert base_web.check_version() == RemoteVersion(tag=20261001, name="v2.1.8 (20261001)")


def test_picks_max_tag_when_list_is_ascending(monkeypatch: pytest.MonkeyPatch):
    """列表顺序本身颠倒（最旧在前）时同样取最大 tag，不受 created_at 影响。"""
    _stub(
        monkeypatch,
        [
            _release("20260922", "v2.1.2 (20260922)"),
            _release("20260930", "v2.1.7 (20260930)"),
            _release("20261001", "v2.1.8 (20261001)"),
        ],
    )

    assert base_web.check_version() == RemoteVersion(tag=20261001, name="v2.1.8 (20261001)")


def test_skips_non_digit_tags_even_when_they_come_first(monkeypatch: pytest.MonkeyPatch):
    """非纯数字 tag 一律跳过，且不能因为它排在第一位就提前返回。"""
    _stub(
        monkeypatch,
        [
            _release("v2.2.0", "v2.2.0"),
            _release("py314-20261005", "preview"),
            _release("20261001", "v2.1.8 (20261001)"),
            _release("nightly", ""),
        ],
    )

    assert base_web.check_version() == RemoteVersion(tag=20261001, name="v2.1.8 (20261001)")


def test_duplicate_tag_keeps_first_seen_title(monkeypatch: pytest.MonkeyPatch):
    """同一 tag 重复出现不报错，取该 tag 首次见到的标题。"""
    _stub(
        monkeypatch,
        [
            _release("20261001", "v2.1.8 (20261001)"),
            _release("20261001", "v2.1.8 (20261001) 重建"),
            _release("20260930", "v2.1.7 (20260930)"),
        ],
    )

    assert base_web.check_version() == RemoteVersion(tag=20261001, name="v2.1.8 (20261001)")


def test_missing_release_name_falls_back_to_tag(monkeypatch: pytest.MonkeyPatch):
    """release 没有标题时 name 为空串，display 退回纯数字 tag（供提示文案使用）。"""
    _stub(monkeypatch, [_release("20261001", "")])

    remote = base_web.check_version()

    assert remote == RemoteVersion(tag=20261001, name="")
    assert remote.display == "20261001"


def test_no_numeric_tag_returns_none_and_logs(monkeypatch: pytest.MonkeyPatch, _quiet_detail_log):
    """全是非纯数字 tag 时返回 None 并在详情日志列出最近发布（不抛异常）。"""
    _stub(monkeypatch, [_release("v2.2.0", "v2.2.0"), _release("nightly", "")])

    assert base_web.check_version() is None
    assert any("未找到 MDCx 版本发布" in line for line in _quiet_detail_log)


def test_update_check_disabled_makes_no_request(monkeypatch: pytest.MonkeyPatch):
    """关掉「检查更新」开关时一个请求都不发（不是发了请求再丢弃结果）。"""
    _stub(monkeypatch, [_release("20261001", "v2.1.8 (20261001)")])
    monkeypatch.setattr(manager.config, "update_check", False)

    assert base_web.check_version() is None
    assert _FakeClient.calls == []
