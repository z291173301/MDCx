"""议题 #98 回归：curl_cffi 流式响应与共享图片任务的收尾。

两类 "Task was destroyed but it is pending!" 根因的锁定测试：
1. ``AsyncWebClient._close_response`` 置 ``quit_now`` 让传输 abort 后，必须
   ``await aclose()`` 等 ``response.astream_task``（curl_cffi 内部 perform()
   任务）终结才返回；
2. ``MediaResourceContext.aclose()`` cancel 共享图片任务后必须 await 收尾，
   返回时无未终结任务。

同时锁定既有性能约束（abort 立即生效、不拉满响应体）不回退——
详见 test_stream_close_aborts.py。
"""

import asyncio
import contextlib
import time

import pytest

from mdcx.core.media_resource import MediaResourceContext
from mdcx.web_async import _STREAM_TASK_JOIN_TIMEOUT, AsyncWebClient


class _FakeStreamTaskResponse:
    """带可控 astream_task 的假流式响应：模拟 curl_cffi 内部任务未终结窗口。"""

    def __init__(self, *, exit_delay: float = 0.0):
        self._exit_delay = exit_delay
        self.quit_now = asyncio.Event()
        self.aclose_called = False

        async def _perform() -> None:
            await asyncio.sleep(exit_delay)

        self.astream_task = asyncio.get_running_loop().create_task(_perform())

    async def aclose(self) -> None:
        # curl_cffi 的 aclose 只 await 内部任务；abort 是否已生效由 quit_now 决定
        self.aclose_called = True
        await self.astream_task


@pytest.mark.asyncio
async def test_close_response_waits_for_pending_astream_task():
    """内部任务毫秒级退场时：_close_response 置 quit_now 后等它结束，不 cancel。"""
    resp = _FakeStreamTaskResponse(exit_delay=0.05)
    client = AsyncWebClient(timeout=5)
    try:
        started = time.monotonic()
        await client._close_response(resp)
        elapsed = time.monotonic() - started
    finally:
        await client.close()

    assert resp.quit_now.is_set(), "未先置 quit_now 让传输 abort"
    assert resp.aclose_called, "未走 aclose() 收尾路径"
    assert resp.astream_task.done(), "返回时内部流任务未终结"
    assert not resp.astream_task.cancelled(), "任务本可正常退场，不应被 cancel"
    assert elapsed < 1.0, f"_close_response 阻塞 {elapsed:.2f}s，未立即中止"


@pytest.mark.asyncio
async def test_close_response_cancels_stuck_astream_task():
    """内部任务卡死时：宽限超时 → cancel → 消费异常，返回时任务已终结。"""
    resp = _FakeStreamTaskResponse(exit_delay=10.0)  # 远超宽限
    client = AsyncWebClient(timeout=5)
    try:
        started = time.monotonic()
        await client._close_response(resp)
        elapsed = time.monotonic() - started
    finally:
        await client.close()

    assert resp.quit_now.is_set()
    assert resp.astream_task.done(), "卡死任务被 cancel 后仍未终结"
    assert resp.astream_task.cancelled(), "卡死任务未被 cancel"
    # 宽限 + cancel 收尾都应在锁定的"立即中止"阈值内完成
    assert elapsed < 1.0, f"超时路径阻塞 {elapsed:.2f}s"
    assert elapsed >= _STREAM_TASK_JOIN_TIMEOUT, "未等满宽限就提前 cancel"


@pytest.mark.asyncio
async def test_close_response_without_astream_task_is_instant():
    """非流式/已收尾响应：无 astream_task 属性或已 done 时直通，零额外等待。"""

    class _PlainResponse:
        close_called = False

        def close(self) -> None:
            self.close_called = True

    resp = _PlainResponse()
    client = AsyncWebClient(timeout=5)
    try:
        started = time.monotonic()
        await client._close_response(resp)
        elapsed = time.monotonic() - started
    finally:
        await client.close()
    assert resp.close_called
    assert elapsed < 0.1, "无内部任务的响应不应有等待"


@pytest.mark.asyncio
async def test_media_context_aclose_terminates_running_fetch_tasks(monkeypatch: pytest.MonkeyPatch):
    """图片任务运行中 aclose()：cancel 后等 finally 跑完，无未 await 任务。"""
    context = MediaResourceContext()
    finally_ran = asyncio.Event()

    async def _fetch_image(self, normalized_url: str):
        try:
            await asyncio.sleep(10.0)  # 模拟慢传输，aclose 时仍在运行
        finally:
            finally_ran.set()

    monkeypatch.setattr(MediaResourceContext, "_fetch_image", _fetch_image)

    fetch_task = asyncio.get_running_loop().create_task(context.fetch_image("https://example.test/a.jpg"))

    # 等任务真正进入 _fetch_image（避开 shield 前的入队窗口）
    await asyncio.sleep(0.05)

    started = time.monotonic()
    await context.aclose()
    elapsed = time.monotonic() - started

    # fetch_image 的 shield 会向等待方抛 CancelledError，就地消费
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.sleep(0)
    assert fetch_task.done(), "共享图片任务未被 aclose 终结"
    assert fetch_task.cancelled() or fetch_task.exception() is not None or fetch_task.done()
    assert finally_ran.is_set(), "任务的 finally（响应收尾所在）未被等待执行"
    assert elapsed < 1.0, "aclose 收尾不应长时间阻塞"
    assert not context._image_fetch_tasks, "任务表未清空"


@pytest.mark.asyncio
async def test_media_context_aclose_with_no_tasks_is_instant():
    """无任务时 aclose() 直通。"""
    context = MediaResourceContext()
    started = time.monotonic()
    await context.aclose()
    assert time.monotonic() - started < 0.1
