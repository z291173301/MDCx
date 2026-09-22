"""启动自检测试：配置目录可写、TMDB key、代理可达性。

自检逻辑在 mdcx/controllers/main_window/health_check.py，仅做只读检查 +
发 signal_qt.show_net_info 信号，不影响启动主流程。本文件把三项检查的
判定逻辑固化为自动化测试，防止回归。
"""

import socket
import threading
import time
from unittest.mock import MagicMock

import mdcx.controllers.main_window.health_check as hc
from mdcx.controllers.main_window import health_check


def _collect_messages(monkeypatch) -> list[str]:
    msgs: list[str] = []
    monkeypatch.setattr(hc.signal_qt, "show_net_info", lambda text: msgs.append(text))
    return msgs


def test_tmdb_key_empty_warns(monkeypatch):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager.config, "tmdb_api_key", "")
    health_check.run_tmdb_key_check()
    assert any("未配置 TMDB API Key" in m for m in msgs)


def test_tmdb_key_configured_no_warning(monkeypatch):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager.config, "tmdb_api_key", "fake-key")
    health_check.run_tmdb_key_check()
    assert msgs == []


def test_proxy_disabled_skips(monkeypatch):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager.config, "use_proxy", False)
    monkeypatch.setattr(hc.manager.config, "proxy", "http://127.0.0.1:7890")
    health_check.run_proxy_reachability_check()
    assert msgs == []


def test_proxy_bad_format_warns(monkeypatch):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager.config, "use_proxy", True)
    monkeypatch.setattr(hc.manager.config, "proxy", "not-a-valid-url")
    health_check.run_proxy_reachability_check()
    assert any("格式异常" in m or "解析失败" in m for m in msgs)


def test_proxy_reachable_reports_ok(monkeypatch):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager.config, "use_proxy", True)
    monkeypatch.setattr(hc.manager.config, "proxy", "http://127.0.0.1:7890")
    real_create = socket.create_connection

    def _fake_create(addr, timeout=None):
        sock = MagicMock()
        sock.__enter__ = MagicMock(return_value=sock)
        sock.__exit__ = MagicMock(return_value=False)
        return sock

    monkeypatch.setattr(hc.socket, "create_connection", _fake_create)
    health_check.run_proxy_reachability_check()

    deadline = time.time() + 2
    while threading.active_count() > 1 and time.time() < deadline:
        time.sleep(0.05)
    assert any("代理可达" in m for m in msgs)
    monkeypatch.setattr(socket, "create_connection", real_create)


def test_proxy_unreachable_reports_error(monkeypatch):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager.config, "use_proxy", True)
    monkeypatch.setattr(hc.manager.config, "proxy", "http://127.0.0.1:7890")

    def _raise(addr, timeout=None):
        raise OSError("Connection refused")

    monkeypatch.setattr(hc.socket, "create_connection", _raise)
    health_check.run_proxy_reachability_check()

    deadline = time.time() + 2
    while threading.active_count() > 1 and time.time() < deadline:
        time.sleep(0.05)
    assert any("代理不可达" in m for m in msgs)


def test_config_dir_unwritable_warns(monkeypatch, tmp_path):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager, "data_folder", str(tmp_path / "no_such_dir"))
    health_check.run_config_dir_writable_check()
    assert any("配置目录不可写" in m for m in msgs)


def test_config_dir_writable_no_warning(monkeypatch, tmp_path):
    msgs = _collect_messages(monkeypatch)
    monkeypatch.setattr(hc.manager, "data_folder", str(tmp_path))
    health_check.run_config_dir_writable_check()
    assert msgs == []
