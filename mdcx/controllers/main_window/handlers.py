import time

from mdcx.config.manager import manager
from mdcx.signals import signal_qt
from mdcx.utils import mask_proxy_url


def net_separator_width(sep_width: int = 88) -> int:
    """把「可视宽 ÷ 单字宽」量出的字符数收敛成实际打印的分隔线长度。

    减 8 是 QSS `padding: 2px, 2px` 的左右合计再多留一格余量；下限 8 保证极窄
    窗口下不会塌成空串。面板横幅（``show_netstatus``）与检测报告内的「-」「=」
    （``run_network_check(separator_width=...)``）共用本函数，两边才永远同长——
    否则报告里硬编码的宽度和横幅的自适应宽度会对不上，参差不齐。
    """
    return max(int(sep_width or 0) - 8, 8)


def show_netstatus(sep_width: int = 88) -> None:
    """检测网络面板顶/底两条「=」分隔线。

    sep_width 由调用方按文本区真实可视宽算好（见 MyMAinWindow._net_separator_chars）：
    启动时只量一次并缓存，故最大化/还原两态的字符数相同；QSS 里该文本框是
    Consolas 13px 等宽，按可视宽取整除即可铺到右边缘且不折行。
    """
    sep_width = net_separator_width(sep_width)
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
