"""Selenium + Edge headless CF bypass 后端。

当普通 HTTP 请求遇到 Cloudflare JS challenge 时，使用 Edge 浏览器以
headless 模式渲染页面，通过真实浏览器引擎绕过 CF 挑战。

经实测验证：Selenium+Edge headless 能稳定通过 JavLibrary 的 CF JS challenge
（低级防护），但对 JavDB（managed challenge）、Lulubar（Turnstile）、
MissAV（连接关闭）无效。

仅适用于 Windows 10/11 + Edge 浏览器环境。Selenium 包作为可选依赖，
首次使用时自动安装。driver 由 Selenium Manager（4.6+）自动匹配，
无需手动打包 msedgedriver。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)

# CF 挑战检测 markers（与 web_async._is_cf_challenge_response 对齐）
CF_MARKERS: tuple[str, ...] = (
    "just a moment",
    "cf-chl",
    "cdn-cgi/challenge-platform",
    "attention required",
    "enable javascript and cookies",
    "checking your browser before accessing",
)

# 连续失败冷却配置
_MAX_CONSECUTIVE_FAILURES = 3
_COOLDOWN_SECONDS = 300.0  # 5 分钟

# 运行时状态
_consecutive_failures = 0
_cooldown_until = 0.0
_selenium_checked = False
_selenium_available = False
_selenium_state_lock = threading.Lock()  # 保护并发 to_thread 下的计数器


def is_cf_html(html: str) -> bool:
    """检测 HTML 是否为 CF 挑战页。"""
    low = html.lower()
    return any(marker in low for marker in CF_MARKERS)


def _is_edge_available() -> bool:
    """检查系统是否安装 Edge 浏览器。"""
    if sys.platform == "win32":
        edge_paths = [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ]
        return any(os.path.isfile(p) for p in edge_paths)
    return shutil.which("microsoft-edge") is not None or shutil.which("microsoft-edge-stable") is not None


def _ensure_selenium() -> bool:
    """确保 selenium 已安装，返回是否可用。"""
    try:
        import selenium  # noqa: F401

        return True
    except ImportError:
        try:
            logger.info("selenium 未安装，正在自动安装...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium"])
            logger.info("selenium 安装完成")
            return True
        except Exception as e:
            logger.warning("selenium 自动安装失败: %s", e)
            return False


def is_available() -> bool:
    """检查 Selenium bypass 是否可用（Edge + selenium）。

    首次调用时检测，结果缓存。
    """
    global _selenium_checked, _selenium_available
    if not _selenium_checked:
        _selenium_available = _is_edge_available() and _ensure_selenium()
        _selenium_checked = True
        if not _selenium_available:
            logger.info("Selenium bypass 不可用（无 Edge 或 selenium 安装失败）")
    return _selenium_available


def _create_driver():
    """创建 Edge driver，配置反检测参数。"""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.edge.service import Service

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-features=IsolateOrigins,site-per-process")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    )
    opts.page_load_strategy = "eager"

    service = Service()
    driver = webdriver.Edge(service=service, options=opts)
    driver.set_page_load_timeout(90)
    return driver


def _wait_cf_pass(driver, max_wait: int = 60) -> str:
    """等待 CF 挑战通过，返回页面 HTML。"""
    driver.get(driver.current_url if driver.current_url else "")
    for _ in range(max_wait // 3):
        time.sleep(3)
        html = driver.page_source
        if not is_cf_html(html):
            return html
    return driver.page_source


def _get_html_sync(url: str, timeout: int = 90) -> str | None:
    """同步获取页面 HTML，自动过 CF。"""
    if not is_available():
        return None

    global _consecutive_failures, _cooldown_until

    now = time.monotonic()
    if now < _cooldown_until:
        logger.debug("Selenium bypass 冷却中，跳过")
        return None

    driver = None
    try:
        driver = _create_driver()
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        html = _wait_cf_pass(driver)
        if is_cf_html(html):
            logger.warning("Selenium bypass: CF 挑战未通过")
            _incr_failures()
            return None
        _reset_failures()
        return html
    except Exception as e:
        logger.warning("Selenium bypass 异常: %s", e)
        _incr_failures()
        return None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def _incr_failures() -> None:
    """记录一次失败；达到阈值进入冷却（并发安全）。"""
    global _consecutive_failures, _cooldown_until
    with _selenium_state_lock:
        _consecutive_failures += 1
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            _cooldown_until = time.monotonic() + _COOLDOWN_SECONDS
            logger.warning(
                "Selenium bypass 连续失败 %d 次，进入 %.0f 秒冷却期",
                _consecutive_failures,
                _COOLDOWN_SECONDS,
            )


def _reset_failures() -> None:
    """成功时清零失败计数（并发安全）。"""
    global _consecutive_failures
    with _selenium_state_lock:
        _consecutive_failures = 0


async def get_html(url: str, timeout: int = 90) -> str | None:
    """用 Selenium+Edge headless 获取页面 HTML，自动过 CF。

    在 asyncio 线程池中执行同步 Selenium 调用，避免阻塞事件循环。

    Args:
        url: 目标 URL
        timeout: 页面加载超时秒数

    Returns:
        过 CF 后的页面 HTML，失败返回 None
    """
    return await asyncio.to_thread(_get_html_sync, url, timeout)
