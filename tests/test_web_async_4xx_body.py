"""议题 #88：4xx 响应错误信息必须携带响应体预览。

Emby 400 的响应体含字段校验错误 JSON，此前 request 只取状态码
（"HTTP 400"），上层无从定位根因。本测试锁定 4xx 错误串包含截断响应体，
同时保留 "HTTP {status}" 前缀（既有匹配/分类逻辑兼容）。
"""

import pytest

from mdcx.web_async import AsyncWebClient


class _FakeResp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {}


@pytest.mark.asyncio
async def test_request_4xx_error_includes_body_preview():
    client = AsyncWebClient(timeout=10)

    body = '{"ValidationErrors": {"ProductionYear": ["year out of range"]}}'

    async def _fake_curl_request(**kwargs):
        return _FakeResp(400, body)

    client._curl_request = _fake_curl_request  # type: ignore[method-assign]

    _, err = await client.request(
        "POST",
        "http://example.test/Items/1",
        use_proxy=False,
        enable_cf_bypass=False,
        retry_count=1,
    )
    assert err, "应返回 4xx 错误"
    # 保留状态码前缀（网络检查/失败分类依赖）
    assert "HTTP 400" in err
    # 新增：携带响应体预览以便定位 Emby 校验错误
    assert "ProductionYear" in err or "ValidationErrors" in err, f"错误串未含响应体预览: {err!r}"


@pytest.mark.asyncio
async def test_request_4xx_error_without_body_keeps_prefix():
    client = AsyncWebClient(timeout=10)

    async def _fake_curl_request(**kwargs):
        return _FakeResp(404, "")  # 无响应体

    client._curl_request = _fake_curl_request  # type: ignore[method-assign]

    _, err = await client.request(
        "GET",
        "http://example.test/missing",
        use_proxy=False,
        enable_cf_bypass=False,
        retry_count=1,
    )
    assert "HTTP 404" in err
    assert "body=" not in err, "空响应体不应追加 body= 前缀"
