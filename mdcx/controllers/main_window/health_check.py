import os
import socket
import threading
from pathlib import Path
from urllib.parse import urlparse

from mdcx.config.manager import manager
from mdcx.signals import signal_qt


def run_startup_health_checks() -> None:
    run_config_dir_writable_check()
    run_tmdb_key_check()
    run_proxy_reachability_check()


def run_config_dir_writable_check() -> None:
    d = Path(manager.data_folder)
    test = d / f".mdcx_write_test_{os.getpid()}"
    try:
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
    except OSError as e:
        signal_qt.show_net_info(f" ❌ 配置目录不可写：{d}（{e}）。配置将无法保存，请检查目录权限。")


def run_tmdb_key_check() -> None:
    if not manager.config.tmdb_api_key:
        signal_qt.show_net_info(
            " ⚠️ 未配置 TMDB API Key，演员信息/封面补全将受限。请在【设置】-【网络】-【网站设置】配置。"
        )


def run_proxy_reachability_check() -> None:
    use_proxy, proxy = manager.config.use_proxy, manager.config.proxy
    if not use_proxy or not proxy:
        return
    try:
        u = urlparse(proxy if "://" in proxy else f"http://{proxy}")
        host, port = u.hostname, u.port
        if not host or not port:
            signal_qt.show_net_info(f" ⚠️ 代理地址格式异常：{proxy}，无法探测可达性。")
            return
    except ValueError as e:
        signal_qt.show_net_info(f" ⚠️ 代理地址解析失败：{proxy}（{e}）。")
        return

    def _probe() -> None:
        try:
            with socket.create_connection((host, port), timeout=2):
                signal_qt.show_net_info(f" ✅ 代理可达：{proxy}")
        except OSError as e:
            signal_qt.show_net_info(
                f" ❌ 代理不可达：{proxy}（{e}）。请确认代理软件已启动，或在【设置】-【网络】临时禁用代理后刮削。"
            )

    threading.Thread(target=_probe, daemon=True).start()
