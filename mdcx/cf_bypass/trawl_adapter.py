import asyncio
import atexit
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import httpx

from mdcx.consts import IS_PYINSTALLER

if TYPE_CHECKING:
    import uvicorn

try:
    import uvicorn  # type: ignore[import-untyped]
except ImportError:  # 仅在冻结模式(in-process)下需要
    uvicorn = None  # type: ignore[assignment, no-redef]

logger = logging.getLogger(__name__)
ADAPTER_HOST = "127.0.0.1"
SERVER_START_TIMEOUT = 60
HEALTH_CHECK_INTERVAL = 0.5
BACKEND_REQUEST_TIMEOUT = 65.0
DEFAULT_MAX_TIMEOUT_MS = 60_000

# 外部 CF 服务后端类型
BACKEND_TRAWL = "trawl"
BACKEND_FLARESOLVERR = "flaresolverr"
VALID_BACKENDS = (BACKEND_TRAWL, BACKEND_FLARESOLVERR)


def _normalize_backend(backend: str | None) -> str:
    backend = (backend or BACKEND_TRAWL).strip().lower()
    if backend not in VALID_BACKENDS:
        backend = BACKEND_TRAWL
    return backend


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((ADAPTER_HOST, 0))
        return s.getsockname()[1]


async def _send_text(send, status: int, body: bytes, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    response_headers = list(headers or [])
    response_headers.extend(
        [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
        ]
    )
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": response_headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _call_backend(
    client: httpx.AsyncClient,
    *,
    backend: str,
    base_url: str,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    proxy: str = "",
    body: str = "",
    skip_http: bool = False,
    max_timeout_ms: int = DEFAULT_MAX_TIMEOUT_MS,
    timeout: float = BACKEND_REQUEST_TIMEOUT,
) -> dict:
    """调用外部 CF 服务（TRAWL /scrape 或 FlareSolverr /v1），归一化为统一结构。

    返回结构：{url, statusCode, headers, cookies, userAgent, html, body}
    失败时返回 {"error": ...}。
    """
    if backend == BACKEND_FLARESOLVERR:
        return await _call_flaresolverr(
            client,
            base_url=base_url,
            url=url,
            method=method,
            headers=headers,
            proxy=proxy,
            body=body,
            max_timeout_ms=max_timeout_ms,
            timeout=timeout,
        )
    return await _call_trawl(
        client,
        base_url=base_url,
        url=url,
        method=method,
        headers=headers,
        proxy=proxy,
        body=body,
        skip_http=skip_http,
        max_timeout_ms=max_timeout_ms,
        timeout=timeout,
    )


async def _call_trawl(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    url: str,
    method: str,
    headers: dict[str, str] | None,
    proxy: str,
    body: str,
    skip_http: bool,
    max_timeout_ms: int,
    timeout: float,
) -> dict:
    """调用 TRAWL 原生 /scrape API（比 /v1 多返回 statusCode/responseHeaders/body）。"""
    payload: dict = {"url": url, "maxTimeout": max_timeout_ms, "method": method or "GET"}
    if headers:
        payload["headers"] = headers
    if proxy:
        payload["proxy"] = proxy
    if body:
        payload["body"] = body
    if skip_http:
        payload["skipHttp"] = True
    try:
        resp = await client.post(f"{base_url}/scrape", json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        return {"error": f"TRAWL 连接失败: {exc}"}
    if resp.status_code == 503:
        return {"error": "TRAWL 浏览器池初始化中，请稍后重试"}
    if resp.status_code == 429:
        return {"error": "TRAWL 浏览器池已饱和，请稍后重试"}
    if resp.status_code != 200:
        return {"error": f"TRAWL 返回 HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except Exception as exc:
        return {"error": f"TRAWL 响应解析失败: {exc}"}
    if isinstance(data, dict) and data.get("error"):
        return {"error": f"TRAWL 错误: {data['error']}"}

    body_bytes: bytes | None = None
    raw_body = data.get("body")
    if isinstance(raw_body, list) and raw_body and isinstance(raw_body[0], int):
        body_bytes = bytes(raw_body)
    elif isinstance(raw_body, str) and raw_body:
        body_bytes = raw_body.encode("utf-8")
    return {
        "url": data.get("url") or url,
        "statusCode": int(data.get("statusCode") or 200),
        "headers": dict(data.get("responseHeaders") or {}),
        "cookies": list(data.get("cookies") or []),
        "userAgent": data.get("userAgent") or "",
        "html": data.get("html") or "",
        "body": body_bytes,
    }


async def _call_flaresolverr(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    url: str,
    method: str,
    headers: dict[str, str] | None,
    proxy: str,
    body: str,
    max_timeout_ms: int,
    timeout: float,
) -> dict:
    """调用 FlareSolverr POST /v1（FlareSolverr v2 兼容）。

    FlareSolverr 只有 request.get / request.post 两种 cmd；/v1 的 solution 里
    headers 是真实上游响应头（区别于 TRAWL 的 /v1 空 headers），足以还原镜像响应。
    """
    cmd = "request.post" if str(method or "GET").upper() == "POST" else "request.get"
    payload: dict = {"cmd": cmd, "url": url, "maxTimeout": max_timeout_ms}
    if headers:
        payload["headers"] = headers
    if proxy:
        payload["proxy"] = proxy
    if body and cmd == "request.post":
        payload["postData"] = body
    try:
        resp = await client.post(f"{base_url}/v1", json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        return {"error": f"FlareSolverr 连接失败: {exc}"}
    if resp.status_code == 503:
        return {"error": "FlareSolverr 浏览器池初始化中，请稍后重试"}
    if resp.status_code == 429:
        return {"error": "FlareSolverr 浏览器池已饱和，请稍后重试"}
    if resp.status_code != 200:
        return {"error": f"FlareSolverr 返回 HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except Exception as exc:
        return {"error": f"FlareSolverr 响应解析失败: {exc}"}
    if isinstance(data, dict) and data.get("status") == "error":
        return {"error": f"FlareSolverr 错误: {data.get('message') or ''}"}

    solution = (data or {}).get("solution") or {}
    html = solution.get("response") or ""
    return {
        "url": solution.get("url") or url,
        "statusCode": int(solution.get("status") or 200),
        "headers": dict(solution.get("headers") or {}),
        "cookies": list(solution.get("cookies") or []),
        "userAgent": solution.get("userAgent") or "",
        "html": html,
        "body": html.encode("utf-8") if html else None,
    }


def _build_target_url(hostname: str, path: str, query_string: str) -> str:
    """按 cf_bypasser mirror 协议重建目标 URL：https://{x-hostname}{path}?{query}。"""
    if not hostname.startswith(("http://", "https://")):
        hostname = f"https://{hostname}"
    parsed = urlparse(hostname)
    base = f"{parsed.scheme}://{parsed.netloc}"
    safe_path = path or "/"
    url = base + safe_path
    if query_string:
        url += f"?{query_string}"
    return url


def _cookie_to_set_cookie(cookie: dict) -> str:
    name = cookie.get("name", "")
    value = cookie.get("value", "")
    parts = [f"{name}={value}"]
    if cookie.get("path"):
        parts.append(f"Path={cookie['path']}")
    if cookie.get("domain"):
        parts.append(f"Domain={cookie['domain']}")
    if cookie.get("secure"):
        parts.append("Secure")
    if cookie.get("httpOnly"):
        parts.append("HttpOnly")
    if cookie.get("sameSite"):
        parts.append(f"SameSite={cookie['sameSite']}")
    return "; ".join(parts)


def create_trawl_adapter_app(trawl_url: str, backend: str = BACKEND_TRAWL):
    """创建把 cf_bypasser 协议翻译成外部 CF 服务（TRAWL /scrape 或 FlareSolverr /v1）的 ASGI 适配层。"""
    backend = _normalize_backend(backend)

    async def app(scope, receive, send):
        if scope["type"] != "http":
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return

        path = scope.get("path", "") or "/"
        query_string = scope.get("query_string", b"").decode("latin-1")
        qs = parse_qs(query_string)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}

        # 只接受本地 127.0.0.1 的连接（mdcx 客户端总是本地转发）
        client_host = ""
        if "client" in scope:
            client_host = (scope["client"] or ("", 0))[0] or ""
        if client_host and client_host not in ("127.0.0.1", "::1"):
            await _send_json(send, 403, {"error": "forbidden"})
            return

        try:
            client = httpx.AsyncClient(timeout=BACKEND_REQUEST_TIMEOUT)
        except Exception as exc:
            await _send_json(send, 500, {"error": f"创建 HTTP 客户端失败: {exc}"})
            return

        try:
            if path == "/cookies":
                await _handle_cookies(client, trawl_url, backend, qs, send)
            elif path == "/html":
                await _handle_html(client, trawl_url, backend, qs, headers, send)
            else:
                await _handle_mirror(client, trawl_url, backend, scope, path, query_string, headers, receive, send)
        finally:
            await client.aclose()

    return app


async def _handle_cookies(client, trawl_url, backend, qs, send) -> None:
    target = qs.get("url", [""])[0]
    if not target:
        await _send_json(send, 400, {"error": "缺少 url 参数"})
        return
    data = await _call_backend(client, backend=backend, base_url=trawl_url, url=target)
    if "error" in data:
        await _send_json(send, 502, {"error": data["error"]})
        return
    cookies: dict[str, str] = {}
    for cookie in data.get("cookies") or []:
        if cookie.get("name") and cookie.get("value"):
            cookies[cookie["name"]] = cookie["value"]
    user_agent = data.get("userAgent") or ""
    await _send_json(send, 200, {"cookies": cookies, "user_agent": user_agent})


async def _handle_html(client, trawl_url, backend, qs, headers, send) -> None:
    target = qs.get("url", [""])[0]
    if not target:
        await _send_json(send, 400, {"error": "缺少 url 参数"})
        return
    data = await _call_backend(
        client,
        backend=backend,
        base_url=trawl_url,
        url=target,
        proxy=qs.get("proxy", [""])[0],
    )
    if "error" in data:
        await _send_json(send, 502, {"error": data["error"]})
        return
    status_code = int(data.get("statusCode") or 200)
    html = data.get("html") or ""
    final_url = data.get("url") or target
    extra_headers: list[tuple[bytes, bytes]] = [
        (b"x-cf-bypasser-final-url", final_url.encode("utf-8")),
        (b"x-cf-bypasser-cookies", str(len(data.get("cookies") or [])).encode()),
        (b"x-cf-bypasser-user-agent", (data.get("userAgent") or "").encode("utf-8")),
    ]
    await _send_text(send, status_code, html.encode("utf-8"), extra_headers)


async def _handle_mirror(client, trawl_url, backend, scope, path, query_string, headers, receive, send) -> None:
    hostname = (headers.get(b"x-hostname") or b"").decode("latin-1").strip()
    if not hostname:
        await _send_json(send, 400, {"error": "缺少 x-hostname 头"})
        return

    target_url = _build_target_url(hostname, path, query_string)
    method = (scope.get("method") or "GET").upper()

    upstream_headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        name = raw_name.decode("latin-1").lower()
        if name in ("x-hostname", "x-proxy", "x-bypass-cache", "host", "content-length", "connection"):
            continue
        value = raw_value.decode("latin-1")
        upstream_headers[name] = upstream_headers.get(name, "") + (", " if name in upstream_headers else "") + value

    body_text = ""
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            body_received = await _read_body(scope, receive)
        except Exception:
            body_received = b""
        if body_received:
            body_text = body_received.decode("utf-8", errors="replace")

    data = await _call_backend(
        client,
        backend=backend,
        base_url=trawl_url,
        url=target_url,
        method=method,
        headers=upstream_headers or None,
        proxy=(headers.get(b"x-proxy") or b"").decode("latin-1").strip(),
        body=body_text,
    )
    if "error" in data:
        await _send_json(send, 502, {"error": data["error"]})
        return

    status_code = int(data.get("statusCode") or 200)
    response_headers: list[tuple[bytes, bytes]] = []
    upstream_response_headers = data.get("headers") or {}
    for name, value in upstream_response_headers.items():
        if name.lower() in ("content-length", "connection", "transfer-encoding"):
            continue
        response_headers.append((name.encode("latin-1"), str(value).encode("latin-1")))

    for cookie in data.get("cookies") or []:
        response_headers.append((b"set-cookie", _cookie_to_set_cookie(cookie).encode("latin-1")))

    final_url = data.get("url") or target_url
    response_headers.append((b"x-cf-bypasser-final-url", final_url.encode("utf-8")))

    body_bytes = data.get("body")
    if not body_bytes:
        body_bytes = (data.get("html") or "").encode("utf-8")

    await _send_text(send, status_code, body_bytes, response_headers)


async def _read_body(scope, receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body") or b"")
        if not message.get("more_body"):
            break
    return b"".join(chunks)


class TrawlAdapterServer:
    """本地外部 CF 服务适配层：把 cf_bypasser 协议翻译成 TRAWL /scrape 或 FlareSolverr /v1。

    随机空闲端口 + uvicorn 子进程/进程内线程。
    """

    def __init__(
        self,
        trawl_url: str,
        backend: str = BACKEND_TRAWL,
        log_fn: Callable[[str], None] | None = None,
    ):
        self._trawl_url = (trawl_url or "").strip().rstrip("/")
        self._backend = _normalize_backend(backend)
        self._process: asyncio.subprocess.Process | None = None
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self._in_process: bool = False
        self._port: int = 0
        self._url: str = ""
        self._started = False
        self._closing = False
        self._log_fn = log_fn or (lambda msg: logger.info(msg))
        self._atexit_registered = False

    def _log(self, msg: str) -> None:
        self._log_fn(f"[TRAWL适配] {msg}")

    @property
    def url(self) -> str:
        return self._url

    @property
    def is_running(self) -> bool:
        if self._in_process:
            return self._started and self._server is not None and not getattr(self._server, "should_exit", True)
        return self._started and self._process is not None and self._process.returncode is None

    def _check_dependencies(self) -> tuple[bool, str]:
        missing = []
        try:
            import uvicorn  # noqa: F401  # 探活
        except ImportError:
            missing.append("uvicorn")
        try:
            import httpx  # noqa: F401  # 探活
        except ImportError:
            missing.append("httpx")
        if missing:
            return False, f"缺少依赖: {', '.join(missing)}\n请运行: pip install {' '.join(missing)}"
        return True, ""

    async def start(self) -> tuple[bool, str]:
        if self.is_running:
            return True, self._url
        if not self._trawl_url:
            return False, "未配置 TRAWL 地址"

        deps_ok, deps_error = self._check_dependencies()
        if not deps_ok:
            return False, deps_error

        self._port = _find_free_port()
        self._url = f"http://{ADAPTER_HOST}:{self._port}"
        self._log(f"启动外部 CF 适配层 {self._url} -> {self._trawl_url} (backend={self._backend}) ...")

        if IS_PYINSTALLER:
            ok, err = await self._start_in_process()
        else:
            ok, err = await self._start_subprocess()
        if not ok:
            return False, err

        self._started = True
        self._log(f"外部 CF 适配层已就绪: {self._url}")
        return True, self._url

    async def _start_subprocess(self) -> tuple[bool, str]:
        import asyncio as _asyncio

        kwargs: dict = {}
        if os.name == "nt":
            # Windows: 抑制子进程弹出黑色控制台窗口
            import subprocess as _subprocess

            kwargs["creationflags"] = _subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        self._process = await _asyncio.create_subprocess_exec(
            __import__("sys").executable,
            "-m",
            "uvicorn",
            "mdcx.cf_bypass.trawl_adapter:create_trawl_adapter_factory",
            "--factory",
            "--host",
            ADAPTER_HOST,
            "--port",
            str(self._port),
            "--log-level",
            "warning",
            stdout=_asyncio.subprocess.DEVNULL,
            stderr=_asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, "MDCX_TRAWL_URL": self._trawl_url, "MDCX_BACKEND_TYPE": self._backend},
            **kwargs,
        )
        self._register_atexit()
        ready, error = await self._wait_ready()
        if not ready:
            await self.stop()
            return False, error
        return True, ""

    def _register_atexit(self) -> None:
        if self._atexit_registered:
            return
        self._atexit_registered = True
        atexit.register(self._atexit_cleanup)

    def _atexit_cleanup(self) -> None:
        proc = self._process
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass

    async def _start_in_process(self) -> tuple[bool, str]:
        import uvicorn

        try:
            config = uvicorn.Config(
                create_trawl_adapter_app(self._trawl_url, self._backend),
                host=ADAPTER_HOST,
                port=self._port,
                log_level="warning",
            )
            self._server = uvicorn.Server(config)  # type: ignore[assignment]
            assert self._server is not None
            self._thread = threading.Thread(target=self._server.run, daemon=True)
            self._thread.start()
        except Exception as e:
            return False, f"启动外部 CF 适配层线程失败: {e}"

        ready, error = await self._wait_ready()
        if not ready:
            await self.stop()
            return False, error
        self._in_process = True
        return True, ""

    async def _wait_ready(self, timeout: int = SERVER_START_TIMEOUT) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if self._in_process and self._thread is not None and not self._thread.is_alive():
                return False, "外部 CF 适配层线程已退出 (uvicorn 启动失败)"
            if not self._in_process and self._process and self._process.returncode is not None:
                return False, f"适配层进程异常退出 (code={self._process.returncode})"
            try:
                async with httpx.AsyncClient() as probe:
                    resp = await probe.get(f"{self._url}/cookies?url=http://example.com", timeout=5)
                    if resp.status_code == 200:
                        return True, ""
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
                last_error = str(e)
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        return False, f"外部 CF 适配层启动超时 ({SERVER_START_TIMEOUT}s): {last_error}"

    async def stop(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._in_process and self._server is not None:
            self._log("正在停止外部 CF 适配层(线程)...")
            try:
                self._server.should_exit = True
                if self._thread is not None:
                    self._thread.join(timeout=5)
            except Exception as e:
                self._log(f"停止服务异常: {e}")
            self._server = None
            self._thread = None
            self._in_process = False
        elif self._process is not None:
            self._log("正在停止外部 CF 适配层...")
            try:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except TimeoutError:
                    self._process.kill()
                    await asyncio.wait_for(self._process.wait(), timeout=3)
            except ProcessLookupError:
                pass
            except Exception as e:
                self._log(f"停止服务异常: {e}")
        self._process = None
        self._started = False
        self._url = ""
        self._port = 0
        self._log("外部 CF 适配层已停止")


def create_trawl_adapter_factory():
    """uvicorn --factory 入口：从环境变量读取外部 CF 服务地址与后端类型并创建适配层。"""
    trawl_url = os.environ.get("MDCX_TRAWL_URL", "")
    backend = os.environ.get("MDCX_BACKEND_TYPE", BACKEND_TRAWL)
    return create_trawl_adapter_app(trawl_url, backend)
