"""CF 相关站点代理路由回归测试。

背景：missav/avsex/getchu/javlibrary/r18dev 在墙内直连会被 RST（curl 35/56，
无 HTTP 响应——bypass 机制救不了，只能走代理）。此前三处路由缺陷：
1. 默认走代理名单漏了 avsex.cc/getchu.com/dl.getchu.com；
2. javlibrary 动态镜像（f101w/c97k/GitHub 学习域）与名单里的 javlibrary.com
   既不相等也非子域，全部逃逸直连；
3. r18dev 硬编码 use_proxy=False，用户无手段让它走代理。
另：FlareSolverr/TRAWL 本地实例只 serving 纯 HTTP，配成 https://回环 会导致
适配层与检测全部 TLS 超时，现统一归一化为 http。
"""

import ast
from pathlib import Path

import pytest

from mdcx.cf_bypass.trawl_adapter import normalize_trawl_url
from mdcx.config.migrations import migrate_config_data
from mdcx.config.models import Config
from mdcx.web_async import is_proxy_host

DEFAULT_PROXY_SITES = Config.model_fields["proxy_sites"].default.split(",")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://127.0.0.1:8191/", "http://127.0.0.1:8191"),
        ("https://127.0.0.1:8191", "http://127.0.0.1:8191"),
        ("https://localhost:8191/", "http://localhost:8191"),
        ("http://127.0.0.1:8191", "http://127.0.0.1:8191"),
        # 非回环 https 必须原样保留，不得降级
        ("https://example.com:8191/", "https://example.com:8191"),
        ("https://cf.example.com/v1", "https://cf.example.com/v1"),
        ("", ""),
    ],
)
def test_normalize_trawl_url_loopback_https_downgrade(url, expected):
    assert normalize_trawl_url(url) == expected


def test_migrate_config_data_normalizes_loopback_https():
    data = {"cf_bypass_trawl_url": "https://127.0.0.1:8191/"}
    migrate_config_data(data)
    assert data["cf_bypass_trawl_url"] == "http://127.0.0.1:8191"


@pytest.mark.parametrize(
    "host",
    [
        # 本次补进默认名单的三域
        "avsex.cc",
        "www.avsex.cc",
        "getchu.com",
        "www.getchu.com",
        "dl.getchu.com",
        # 既有站：主域 + 动态镜像（3b 同站跟随分支覆盖后者）
        "javlibrary.com",
        "www.javlibrary.com",
        "www.f101w.com",
        "f101w.com",
        "www.c97k.com",
        "r18.dev",
        "missav.ai",
        "missav.ws",
        "javbus.com",
    ],
)
def test_cf_sites_route_via_proxy_by_default(host):
    assert is_proxy_host(host, DEFAULT_PROXY_SITES, []) is True


def test_direct_sites_still_override_proxy():
    """直连白名单（分支 1）优先于一切跟随分支，不得被 3b 绕过。"""
    assert is_proxy_host("www.f101w.com", DEFAULT_PROXY_SITES, ["f101w.com"]) is False
    assert is_proxy_host("avsex.cc", DEFAULT_PROXY_SITES, ["avsex.cc"]) is False


def test_unrelated_host_not_proxied():
    assert is_proxy_host("example.com", DEFAULT_PROXY_SITES, []) is False


def test_r18dev_no_hardcoded_use_proxy_false():
    """r18dev 不得再硬编码 use_proxy=False：代理路由交由 request 按配置判定。"""
    src = Path("mdcx/crawlers/r18dev.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "R18devCrawler")
    bad: list[str] = []
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "use_proxy"
            and isinstance(node.value, ast.Constant)
            and node.value.value is False
        ):
            bad.append(ast.unparse(node))
    assert not bad, f"r18dev 内不应再硬编码 use_proxy=False: {bad}"


def test_getchu_base_url_follows_custom_url():
    """getchu base_url_ 必须走 get_site_url（支持站点自定义 URL）。"""
    src = Path("mdcx/crawlers/getchu.py").read_text(encoding="utf-8")
    assert "get_site_url(Website.GETCHU" in src


def test_getchu_default_base_url_unchanged():
    """无自定义 URL 时 getchu 默认域名保持 http://www.getchu.com。"""
    from mdcx.crawlers.getchu import GetchuCrawler

    assert GetchuCrawler.base_url_() == "http://www.getchu.com"
