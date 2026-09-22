import time

from mdcx.config.manager import manager
from mdcx.signals import signal_qt
from mdcx.utils import mask_proxy_url


def show_netstatus() -> None:
    signal_qt.show_net_info(time.strftime("%Y-%m-%d %H:%M:%S").center(80, "="))

    use_proxy, proxy, cf_bypass_url, cf_bypass_proxy, cf_bypass_trawl_url, timeout, retry_count = (
        manager.config.use_proxy,
        manager.config.proxy,
        manager.config.cf_bypass_url,
        manager.config.cf_bypass_proxy,
        manager.config.cf_bypass_trawl_url,
        manager.config.timeout,
        manager.config.retry,
    )
    bypass_status = "已配置" if cf_bypass_url else "未配置"
    bypass_proxy_status = "已配置" if cf_bypass_proxy else "未配置"
    trawl_status = "已配置" if cf_bypass_trawl_url else "未配置"

    if not use_proxy or not proxy:
        signal_qt.show_net_info(
            f" 当前网络状态：❌ 未启用代理\n"
            f"   CF Bypass：{bypass_status}    Bypass代理：{bypass_proxy_status}    外部CF：{trawl_status}    超时：{timeout!s}    重试：{retry_count!s}"
        )
    else:
        signal_qt.show_net_info(
            f" 当前网络状态：✅ 已启用代理\n"
            f"   地址：{mask_proxy_url(proxy)}\n"
            f"   CF Bypass：{bypass_status}    Bypass代理：{bypass_proxy_status}    外部CF：{trawl_status}    超时：{timeout!s}    重试：{retry_count!s}"
        )
    signal_qt.show_net_info("=" * 80)
