"""LLM 关闭思考参数映射与去参重试测试（issue #54）。"""

from __future__ import annotations

from httpx import Request, Response
from openai import BadRequestError

from mdcx.llm import _is_unsupported_param_error, get_disable_thinking_extra_body


def test_disable_thinking_mapping_by_provider():
    cases = {
        "https://api.siliconflow.cn/v1": {"enable_thinking": False},
        "https://dashscope.aliyuncs.com/compatible-mode/v1": {"enable_thinking": False},
        "https://ark.cn-beijing.volces.com/api/v3": {"thinking": {"type": "disabled"}},
        "http://localhost:11434/v1": None,  # localhost 无 ollama 字样不命中（不误发）
        "http://192.168.1.10:11434/v1": None,
        "https://ollama.example.com/v1": {"think": False},
        "https://generativelanguage.googleapis.com/v1beta/openai/": {"reasoning_effort": "none"},
        "https://api.openai.com/v1": None,  # 未收录不下发
        "https://api.deepseek.com/v1": None,
    }
    for url, expected in cases.items():
        assert get_disable_thinking_extra_body(url) == expected, url


def test_disable_thinking_mapping_returns_copy():
    body = get_disable_thinking_extra_body("https://api.siliconflow.cn/v1")
    assert body is not None
    body["enable_thinking"] = True
    assert get_disable_thinking_extra_body("https://api.siliconflow.cn/v1") == {"enable_thinking": False}


def _bad_request(msg: str) -> BadRequestError:
    req = Request("POST", "https://example.com/v1/chat/completions")
    resp = Response(400, request=req, content=msg.encode())
    return BadRequestError(msg, response=resp, body=None)


def test_unsupported_param_error_detection():
    body = {"enable_thinking": False}
    assert _is_unsupported_param_error(_bad_request("Unknown parameter: 'enable_thinking'"), body)
    assert _is_unsupported_param_error(_bad_request("unsupported parameter: enable_thinking"), body)
    # 与参数无关的 400（如内容过长）不误判
    assert not _is_unsupported_param_error(_bad_request("maximum context length exceeded"), body)
    assert not _is_unsupported_param_error(_bad_request("rate limit"), body)
    # 无 extra_body 时不触发
    assert not _is_unsupported_param_error(_bad_request("Unknown parameter: enable_thinking"), None)
    # 非 BadRequestError 不触发
    assert not _is_unsupported_param_error(ValueError("Unknown parameter: enable_thinking"), body)
