import time

from mdcx.config.manager import manager
from mdcx.signals import signal_qt
from mdcx.utils import mask_proxy_url


def show_netstatus(sep_width: int = 88) -> None:
    """检测网络面板顶/底两条「=」分隔线。

    sep_width 由调用方按文本区真实可视宽算好（见 MyMAinWindow._net_separator_chars）：
    启动时只量一次并缓存，故最大化/还原两态的字符数相同；QSS 里该文本框是
    Consolas 13px 等宽，按可视宽取整除即可铺到右边缘且不折行。
    """
    sep_width = max(int(sep_width or 0), 8)
    signal_qt.show_net_info(time.strftime("%Y-%m-%d %H:%M:%S").center(sep_width, "="))

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
            f" CloudFlare Bypass：{bypass_status}    CloudFlare Bypass代理：{bypass_proxy_status}    外部CF服务：{trawl_status}    超时：{timeout!s}    重试：{retry_count!s}"
        )
    else:
        signal_qt.show_net_info(
            f" 当前网络状态：✅ 已启用代理\n"
            f" 地址：{mask_proxy_url(proxy)}\n"
            f" CloudFlare Bypass：{bypass_status}    CloudFlare Bypass代理：{bypass_proxy_status}    外部CF服务：{trawl_status}    超时：{timeout!s}    重试：{retry_count!s}"
        )
    signal_qt.show_net_info("=" * sep_width)
