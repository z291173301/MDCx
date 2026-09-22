"""AsyncWebClient.download 的 max_bytes 大小上限测试。"""

import pytest

from mdcx.web_async import AsyncWebClient


class _FakeResponse:
    def __init__(self, headers: dict[str, str], status_code: int = 200, content: bytes = b""):
        self.headers = headers
        self.status_code = status_code
        self.content = content
        self.url = "https://example.test/image.jpg"


@pytest.mark.asyncio
async def test_download_rejects_known_size_over_limit(monkeypatch: pytest.MonkeyPatch, tmp_path):
    logs: list[str] = []
    client = AsyncWebClient(timeout=1, log_fn=logs.append)
    target = tmp_path / "out.jpg"

    async def fake_request(method: str, url: str, **kwargs):
        if method == "HEAD":
            return _FakeResponse({"content-length": "60"}), ""
        return _FakeResponse({"content-length": "60"}, content=b"x" * 60), ""

    monkeypatch.setattr(client, "request", fake_request)

    try:
        assert await client.download("https://example.test/image.jpg", target, max_bytes=50) is False
        assert not target.exists()
        assert any("超过大小上限" in log for log in logs)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_download_accepts_known_size_within_limit(monkeypatch: pytest.MonkeyPatch, tmp_path):
    logs: list[str] = []
    client = AsyncWebClient(timeout=1, log_fn=logs.append)
    target = tmp_path / "out.jpg"

    async def fake_request(method: str, url: str, **kwargs):
        return _FakeResponse({"content-length": "30"}, content=b"x" * 30), ""

    monkeypatch.setattr(client, "request", fake_request)

    try:
        assert await client.download("https://example.test/image.jpg", target, max_bytes=50) is True
        assert target.exists()
        assert target.stat().st_size == 30
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_download_rejects_content_over_limit_when_size_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path):
    logs: list[str] = []
    client = AsyncWebClient(timeout=1, log_fn=logs.append)
    target = tmp_path / "out.jpg"

    # DMM 图跳过 HEAD，file_size 为 None，走 get_content 全量
    async def fake_request(method: str, url: str, **kwargs):
        return _FakeResponse({"content-type": "image/jpeg"}, content=b"x" * 60), ""

    monkeypatch.setattr(client, "request", fake_request)
    monkeypatch.setattr(client, "_is_dmm_image_url", lambda url: True)

    try:
        assert await client.download("https://awsimgsrc.dmm.co.jp/pics_dig/.../x.jpg", target, max_bytes=50) is False
        assert not target.exists()
        assert any("超过大小上限" in log for log in logs)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_download_without_max_bytes_unlimited(monkeypatch: pytest.MonkeyPatch, tmp_path):
    logs: list[str] = []
    client = AsyncWebClient(timeout=1, log_fn=logs.append)
    target = tmp_path / "out.jpg"

    async def fake_request(method: str, url: str, **kwargs):
        return _FakeResponse({"content-length": "60000"}, content=b"x" * 60000), ""

    monkeypatch.setattr(client, "request", fake_request)

    try:
        assert await client.download("https://example.test/image.jpg", target) is True
        assert target.exists()
        assert target.stat().st_size == 60000
    finally:
        await client.close()
