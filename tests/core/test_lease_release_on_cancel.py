"""议题 #98 追加反馈回归：取消打断收尾时的租约释放。

「网络/LLM 客户端等待空闲超过 300 秒仍未空闲（残留租约 1）」根因链：
点「停止」→ executor.cancel_async() 无差别取消运行中的刮削协程 → 取消恰好
落在收尾动作的 await 点 → release 未执行 → 租约计数永不归零 →
close_when_idle 等满 300s 强制关闭。

两个已复现的泄漏窗口与对应防护（2026-09-14 实验 3/4）：
1. ``ComputedLease.__aexit__`` 直接 ``await release()``（内部是 gather 双客户端
   release），取消落在 gather 挂起点 → 两客户端各漏 1 → 防护：shield；
2. ``CrawlerProvider.close()`` 逐实例收尾后 release，任一实例 close 异常/取消
   打断 → release 跳过 → 防护：try/finally + 逐实例 suppress。
"""

import asyncio

import pytest

from mdcx.crawler import CrawlerProvider
from mdcx.web_async import AsyncWebClient


class _LeaseCounter:
    """复刻 AsyncWebClient/LLMClient 的 retain/release 计数语义。"""

    def __init__(self) -> None:
        self.leases = 0

    def retain(self) -> None:
        self.leases += 1

    async def release(self) -> None:
        if self.leases > 0:
            self.leases -= 1


class _ComputedLike:
    """复刻 Computed.release 的 gather 双客户端结构。"""

    def __init__(self) -> None:
        self.async_client = _LeaseCounter()
        self.llm_client = _LeaseCounter()

    def retain(self) -> None:
        self.async_client.retain()
        self.llm_client.retain()

    async def release(self) -> None:
        await asyncio.gather(self.async_client.release(), self.llm_client.release(), return_exceptions=True)


class _LeaseCtx:
    """复刻 ComputedLease 的 __aenter__/__aexit__ 形态（含 shield 防护）。"""

    def __init__(self, computed: _ComputedLike) -> None:
        self.computed = computed

    async def __aenter__(self):
        self.computed.retain()
        return self.computed

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await asyncio.shield(self.computed.release())


@pytest.mark.asyncio
async def test_lease_release_survives_cancel_storm_in_aexit():
    """取消风暴打在 __aexit__ 的 gather 窗口：双客户端租约必须归零。

    对应实验 4：无 shield 时 4/4 次复现 leases=(1,1)。
    """
    computed = _ComputedLike()

    async def child():
        async with _LeaseCtx(computed):
            await asyncio.sleep(10)  # 刮削主体

    task = asyncio.get_running_loop().create_task(child())
    await asyncio.sleep(0.05)  # child 已拿到租约并挂起
    task.cancel()
    await asyncio.sleep(0)  # 取消到达 __aexit__ 的 gather 挂起点
    task.cancel()  # 取消风暴（停止场景 _cancel_all 逐 future cancel）
    await asyncio.gather(task, return_exceptions=True)

    assert (computed.async_client.leases, computed.llm_client.leases) == (0, 0), (
        "取消打断 __aexit__ 的 release：网络/LLM 双残留租约——"
        "close_when_idle 将等满 300 秒后强制关闭（议题 #98 残留租约）"
    )


def test_real_computed_lease_aexit_shielded(tmp_path):
    """真实 ComputedLease.__aexit__ 的 release 不可被取消打断（AST 哨兵 + 行为双锁）。

    conftest 用 dummy 替换了 mdcx.config.manager，无法在进程内导入真实
    ComputedLease——AST 哨兵锁源码结构（`__aexit__` 内必须 shield release），
    行为语义由上一条的复刻形态测试锁定。
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "mdcx" / "config" / "manager.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))

    aexit_found = False
    shielded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "__aexit__":
            aexit_found = True
            for sub in ast.walk(node):
                if isinstance(sub, ast.Await) and isinstance(sub.value, ast.Call):
                    func = sub.value.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "shield"
                        and isinstance(sub.value.args[0], ast.Call)
                        and getattr(sub.value.args[0].func, "attr", "") == "release"
                    ):
                        shielded = True
    assert aexit_found, "未找到 ComputedLease.__aexit__"
    assert shielded, (
        "ComputedLease.__aexit__ 的 release 未加 shield：取消落在 gather 挂起点时"
        "网络/LLM 双客户端各漏 1 个租约（议题 #98 残留租约）"
    )


@pytest.mark.asyncio
async def test_crawler_provider_close_releases_lease_even_if_instance_close_fails():
    """任一爬虫实例 close 抛异常：client.release() 仍必须执行。"""
    client = AsyncWebClient(timeout=5)
    leases_before = client._lease_count()
    provider = CrawlerProvider(_FakeConfig(), client)

    class _BrokenInstance:
        async def close(self):
            raise RuntimeError("instance cleanup failed")

    provider.instances["broken"] = _BrokenInstance()  # type: ignore[assignment]

    await provider.close()

    assert client._lease_count() == leases_before, "实例 close 异常阻断了租约归还"


@pytest.mark.asyncio
async def test_scraper_run_release_survives_cancel_during_close():
    """取消恰好落在 run finally 的 provider.close() 执行中：release 仍执行。

    对应实验 3（2026-09-14）：close 收尾被取消打断 → 租据停留在 1。
    用慢实例拉长真 close 的收尾窗口，等进入窗口后再取消。
    """
    client = AsyncWebClient(timeout=5)
    leases_before = client._lease_count()
    provider = CrawlerProvider(_FakeConfig(), client)
    in_close = asyncio.Event()

    class _SlowInstance:
        async def close(self):
            in_close.set()
            await asyncio.sleep(0.3)  # 拉长 provider.close 的逐实例收尾窗口

    provider.instances["slow"] = _SlowInstance()  # type: ignore[assignment]

    async def scraper_run():
        try:
            await asyncio.sleep(0.05)  # 模拟刮削主体
        finally:
            await asyncio.shield(provider.close())

    task = asyncio.get_running_loop().create_task(scraper_run())
    await asyncio.wait_for(in_close.wait(), timeout=2)  # 已进入 close 内部
    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # shield 下的 close 在后台继续收尾，等它跑完慢实例的 0.3s 窗口
    for _ in range(100):
        if client._lease_count() == leases_before:
            break
        await asyncio.sleep(0.02)

    assert client._lease_count() == leases_before, (
        "取消打断 Scraper.run 收尾：provider 未归还租约——残留租约将让 close_when_idle 等 300 秒（议题 #98 残留租约）"
    )


@pytest.mark.asyncio
async def test_crawler_provider_close_release_survives_direct_cancel():
    """provider.close() 自身被取消打断（不依赖外层 shield）：release 仍执行。

    直接锁 CrawlerProvider.close 的 try/finally 防护——这是 stop 取消打断
    收尾窗口时的主防线（shield 撤掉仍须归零）。
    """
    client = AsyncWebClient(timeout=5)
    leases_before = client._lease_count()
    provider = CrawlerProvider(_FakeConfig(), client)
    in_close = asyncio.Event()

    class _SlowInstance:
        async def close(self):
            in_close.set()
            await asyncio.sleep(0.3)

    provider.instances["slow"] = _SlowInstance()  # type: ignore[assignment]

    close_task = asyncio.get_running_loop().create_task(provider.close())
    await asyncio.wait_for(in_close.wait(), timeout=2)
    await asyncio.sleep(0.02)
    close_task.cancel()  # 取消直接打入 close 的逐实例收尾 await
    await asyncio.gather(close_task, return_exceptions=True)
    for _ in range(100):
        if client._lease_count() == leases_before:
            break
        await asyncio.sleep(0.02)

    assert client._lease_count() == leases_before, (
        "close 被取消打断后 release 未执行：finally 兜底缺失——"
        "租约残留会让 close_when_idle 等 300 秒（议题 #98 残留租约）"
    )


class _FakeConfig:
    """CrawlerProvider 构造仅需要的最小配置形态。"""

    def get_site_url(self, site):  # noqa: ANN001, ANN202
        return ""
