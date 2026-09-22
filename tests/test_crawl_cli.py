"""crawl CLI 客户端构造与退出码测试。

回归保护：
1. crawl.py 曾漏传 proxy_sites，导致 AsyncWebClient 的 _is_proxy_host
   对任何 host 都返回 False，--proxy 参数实际不生效（代理形同虚设）。
2. crawl.py 失败时仍返回 exit 0，无法在脚本中判断成败。
"""

from concurrent.futures import Future
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import typer

from mdcx.cmd import crawl as crawl_module
from mdcx.config.models import Website
from mdcx.models.model_types import CrawlerInput


@dataclass
class _FakeData:
    title: str = "成功标题"


class _FakeExecutor:
    """模拟全局 executor：不真正执行任务，直接返回带结果的 future."""

    def __init__(self, success: bool = True):
        self.futures = []
        self.success = success

    def submit(self, fn):
        if hasattr(fn, "close"):
            fn.close()  # fake 不执行真实任务，关闭协程避免 "coroutine never awaited" 警告
        future = Future()
        res = MagicMock()
        res.debug_info.logs = []
        res.debug_info.execution_time = 0.0
        if self.success:
            res.debug_info.error = None
            res.data = _FakeData()
        else:
            res.debug_info.error = "刮削失败: 站点不可达"
            res.data = None
        future.set_result(res)
        self.futures.append(future)
        return future

    def wait_all(self):
        return None

    def run(self, coro):
        return None


@patch.object(crawl_module, "executor", new=_FakeExecutor())
@patch.object(crawl_module, "AsyncWebClient")
def test_crawl_passes_proxy_sites(mock_client):
    """crawl CLI 构造 AsyncWebClient 时必须传递 proxy_sites 白名单."""
    input_data = CrawlerInput.empty()
    crawl_module._crawl(
        sites=[Website.JAVBUS],
        input=input_data,
        output=None,
        proxy="http://127.0.0.1:7890",
        timeout=5,
        retry=1,
    )

    call_kwargs = mock_client.call_args.kwargs
    assert "proxy_sites" in call_kwargs, "AsyncWebClient 未收到 proxy_sites 参数"
    assert isinstance(call_kwargs["proxy_sites"], list)
    assert call_kwargs["proxy"] == "http://127.0.0.1:7890"


@patch.object(crawl_module, "executor", new=_FakeExecutor(success=True))
@patch.object(crawl_module, "AsyncWebClient")
def test_crawl_success_returns_zero(mock_client):
    """全部站点成功时返回 0（不抛 Exit）."""
    input_data = CrawlerInput.empty()
    crawl_module._crawl(
        sites=[Website.JAVBUS],
        input=input_data,
        output=None,
        proxy=None,
        timeout=5,
        retry=1,
    )
    # 不抛 typer.Exit 即视为成功


@patch.object(crawl_module, "executor", new=_FakeExecutor(success=False))
@patch.object(crawl_module, "AsyncWebClient")
def test_crawl_failure_raises_exit_1(mock_client):
    """任一站点失败时抛 typer.Exit(1)，供脚本判断成败."""
    input_data = CrawlerInput.empty()
    try:
        crawl_module._crawl(
            sites=[Website.JAVBUS],
            input=input_data,
            output=None,
            proxy=None,
            timeout=5,
            retry=1,
        )
    except typer.Exit as exc:
        assert exc.exit_code == 1
    else:
        raise AssertionError("失败时应抛 typer.Exit(1)，但未抛出")
