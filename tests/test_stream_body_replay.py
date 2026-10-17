"""Regression for missing Content-Type consuming curl_cffi's stream sentinel."""

import asyncio
from io import BytesIO

import pytest
from curl_cffi import Response
from curl_cffi.requests.exceptions import RequestException
from curl_cffi.requests.models import STREAM_END
from PIL import Image

from mdcx.core import media_resource
from mdcx.core.media_resource import MediaResourceContext
from mdcx.web_async import AsyncWebClient


def response_for(chunks, *, complete=True, content_type=None):
    response = Response()
    response.status_code = 200
    response.headers = {} if content_type is None else {"content-type": content_type}
    response.curl = object()
    response.queue = asyncio.Queue()
    for chunk in chunks:
        response.queue.put_nowait(chunk)
    if complete:
        response.queue.put_nowait(STREAM_END)
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [0, 13, 8191, 8192, 18253, 524288])
@pytest.mark.parametrize("consumer", ["acontent", "image"])
async def test_missing_content_type_preserves_entire_body(length, consumer):
    payload = bytes(range(256)) * (length // 256) + bytes(range(length % 256))
    response = response_for([payload[i : i + 4096] for i in range(0, len(payload), 4096)])
    client = AsyncWebClient(timeout=1)
    assert not await client._is_cf_challenge_response(response)
    # Repeated detection must not consume any more bytes.
    assert not await client._is_cf_challenge_response(response)
    read = response.acontent() if consumer == "acontent" else MediaResourceContext._read_stream_content(response)
    content = await asyncio.wait_for(read, 1)
    assert content == (payload if consumer == "acontent" else payload or None)
    await client.close()


@pytest.mark.asyncio
async def test_challenge_detection_still_works_and_preserves_html():
    body = b"<html><title>Just a moment</title><script>cf-chl</script></html>"
    response = response_for([body])
    response.status_code = 403
    response.headers = {"server": "cloudflare", "content-type": "text/html"}
    client = AsyncWebClient(timeout=1)
    assert await client._is_cf_challenge_response(response)
    assert await asyncio.wait_for(response.acontent(), 1) == body
    await client.close()


@pytest.mark.asyncio
async def test_peek_reads_prefix_only_and_leaves_tail_streaming():
    response = response_for([b"x" * 8192], complete=False)
    client = AsyncWebClient(timeout=1)
    assert not await asyncio.wait_for(client._is_cf_challenge_response(response), 0.5)
    response.queue.put_nowait(b"tail")
    response.queue.put_nowait(STREAM_END)
    assert await asyncio.wait_for(response.acontent(), 1) == b"x" * 8192 + b"tail"
    await client.close()


@pytest.mark.asyncio
async def test_chunk_larger_than_peek_limit_is_not_truncated():
    payload = b"x" * 20000
    response = response_for([payload])
    client = AsyncWebClient(timeout=1)
    assert not await client._is_cf_challenge_response(response)
    assert await asyncio.wait_for(response.acontent(), 1) == payload
    await client.close()


@pytest.mark.asyncio
async def test_explicit_image_content_type_does_not_read_body():
    response = response_for([], complete=False, content_type="image/jpeg")
    client = AsyncWebClient(timeout=1)
    assert not await asyncio.wait_for(client._is_cf_challenge_response(response), 0.5)
    await client.close()


@pytest.mark.asyncio
async def test_empty_non_streaming_response_does_not_start_stream():
    response = Response()
    response.status_code = 200
    client = AsyncWebClient(timeout=1)
    assert await client._peek_response_body(response) == b""
    await client.close()


@pytest.mark.asyncio
async def test_cancelled_peek_aborts_response(monkeypatch):
    response = response_for([], complete=False)
    client = AsyncWebClient(timeout=1)
    reading = asyncio.Event()
    closed = asyncio.Event()
    original_get = response.queue.get

    async def get():
        reading.set()
        return await original_get()

    async def close(_response):
        closed.set()

    monkeypatch.setattr(response.queue, "get", get)
    monkeypatch.setattr(client, "_close_response", close)
    task = asyncio.create_task(client._is_cf_challenge_response(response))
    await reading.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    await client.close()


@pytest.mark.asyncio
async def test_midstream_error_is_preserved_after_peek():
    response = response_for([b"x" * 8192, RequestException("interrupted")], complete=False)
    client = AsyncWebClient(timeout=1)
    assert not await client._is_cf_challenge_response(response)
    with pytest.raises(RequestException, match="interrupted"):
        await asyncio.wait_for(response.acontent(), 1)
    await client.close()


@pytest.mark.asyncio
async def test_peek_timeout_aborts_and_propagates(monkeypatch):
    response = response_for([b"partial"], complete=False)
    client = AsyncWebClient(timeout=1)
    closed = asyncio.Event()

    async def close(_response):
        closed.set()

    monkeypatch.setattr(client, "_close_response", close)
    with pytest.raises(TimeoutError):
        await client._is_cf_challenge_response(response)
    assert closed.is_set()
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reader,expected", [("_read_stream_content", None), ("_read_stream_size", (0, 0))])
async def test_stalled_image_reads_finish_within_deadline(monkeypatch, reader, expected):
    response = response_for([], complete=False, content_type="image/jpeg")
    monkeypatch.setattr(media_resource, "_image_read_timeout", lambda: 0.02)
    assert await asyncio.wait_for(getattr(MediaResourceContext, reader)(response), 0.3) == expected


@pytest.mark.asyncio
async def test_cancelled_image_read_stays_cancelled():
    response = response_for([], complete=False)
    task = asyncio.create_task(MediaResourceContext._read_stream_content(response))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_real_http_image_without_content_type():
    buffer = BytesIO()
    Image.new("RGB", (16, 24), "white").save(buffer, "PNG")
    payload = buffer.getvalue()

    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(payload)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + payload
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = AsyncWebClient(timeout=1)
    try:
        response, error = await client.request(
            "GET", f"http://127.0.0.1:{port}/cover.png", stream=True, use_proxy=False
        )
        assert response is not None, error
        try:
            actual = await asyncio.wait_for(MediaResourceContext._read_stream_content(response), 1)
            assert actual == payload
            assert await MediaResourceContext._read_size(actual) == (16, 24)
        finally:
            await client._close_response(response)
    finally:
        await client.close()
        server.close()
        await server.wait_closed()
