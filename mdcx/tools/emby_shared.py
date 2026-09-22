"""Emby/Jellyfin API 共用工具函数。

供内置补全 (emby_actor_info/emby_actor_image) 和管理器工具 (emby_actor_manager) 共用。
"""

from __future__ import annotations

import base64
import traceback
from pathlib import Path
from urllib.parse import quote, urlencode

import aiofiles
import httpx

from ..config.manager import manager
from ..signals import signal

JELLYFIN_PERSON_FIELDS = (
    "Overview",
    "ProviderIds",
    "ProductionLocations",
    "Taglines",
    "Genres",
    "Tags",
)


def _is_jellyfin_server() -> bool:
    # server_type 配置为 Literal["emby", "ln"]，UI 用 "ln" 表示 Jellyfin
    return manager.config.server_type != "emby"


def _build_jellyfin_headers(headers: dict[str, str] | None = None, token: str | None = None) -> dict[str, str]:
    # Jellyfin 10.11(=12.x 之前的后端重写版)起 auth middleware 要求完整设备标识,
    # 只发 Token 的请求会被拒绝(议题 #32: 无法连接 Jellyfin 12 RC);完整字段向下兼容旧版。
    from ..consts import VERSION_NAME

    api_key = manager.config.api_key if token is None else token
    request_headers = dict(headers or {})
    request_headers["Authorization"] = (
        f'MediaBrowser Client="MDCx", Device="MDCx", DeviceId="MDCx", Version="{VERSION_NAME}", Token="{api_key}"'
    )
    return request_headers


def _append_query(url: str, params: dict[str, str | None]) -> str:
    query = urlencode({k: v for k, v in params.items() if v not in ("", None)})
    return f"{url}?{query}" if query else url


def _generate_server_url(actor: dict) -> tuple[str, str, str, str, str, str]:
    server_type = manager.config.server_type
    emby_url = str(manager.config.emby_url).rstrip("/")
    actor_name = quote(actor["Name"], safe="")
    actor_id = actor["Id"]
    server_id = actor.get("ServerId", "")

    if "emby" == server_type:
        actor_homepage = f"{emby_url}/web/index.html#!/item?id={actor_id}&serverId={server_id}"
        actor_person = f"{emby_url}/emby/Persons/{actor_name}"
        pic_url = f"{emby_url}/emby/Items/{actor_id}/Images/Primary"
        backdrop_url = f"{emby_url}/emby/Items/{actor_id}/Images/Backdrop"
        backdrop_url_0 = f"{emby_url}/emby/Items/{actor_id}/Images/Backdrop/0"
        update_url = f"{emby_url}/emby/Items/{actor_id}"
    else:
        actor_homepage = f"{emby_url}/web/index.html#!/details?id={actor_id}&serverId={server_id}"
        actor_person = _append_query(f"{emby_url}/Persons/{actor_name}", {"userId": manager.config.user_id})
        pic_url = f"{emby_url}/Items/{actor_id}/Images/Primary"
        backdrop_url = f"{emby_url}/Items/{actor_id}/Images/Backdrop"
        backdrop_url_0 = f"{emby_url}/Items/{actor_id}/Images/Backdrop/0"
        update_url = f"{emby_url}/Items/{actor_id}"
    return actor_homepage, actor_person, pic_url, backdrop_url, backdrop_url_0, update_url


_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _image_content_type(path: Path) -> str:
    """按文件实际格式返回 Content-Type（后缀识别不了时用 PIL 探测，兜底 jpeg）。"""
    from PIL import Image

    mime = _IMAGE_CONTENT_TYPES.get(path.suffix.lower())
    if mime:
        return mime
    try:
        with Image.open(path) as img:
            fmt = (img.format or "").lower()
            for suffix, candidate in _IMAGE_CONTENT_TYPES.items():
                if fmt == suffix.lstrip("."):
                    return candidate
    except Exception:
        pass
    return "image/jpeg"


_EMBY_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)


def _emby_base_url() -> str:
    return str(manager.config.emby_url).rstrip("/")


def _emby_api_prefix() -> str:
    # Emby 控制接口一律带 /emby 前缀；Jellyfin 不带
    return "/emby" if manager.config.server_type == "emby" else ""


async def _emby_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    data: str | None = None,
    token: str | None = None,
) -> tuple[httpx.Response | None, str]:
    """面向 Emby/Jellyfin 的轻量直连请求。

    议题 #133：Emby 是内网/自定义域名服务，不应复用为爬虫抗反爬设计的重型
    curl_cffi(impersonate 指纹) + 连接池 + 按 host 限流 + CF 预热栈——该栈对内网/
    真实 Emby host 的握手协商可能拖出分钟级延迟(第三方工具用普通 HTTP 秒连)。
    这里用 httpx 直连：无指纹、无池化、无按 host 限流、无 CF 预热；显式带回超时,
    卡住的服务器会快速失败而非拖分钟。verify 遵循全局 verify_ssl 配置。
    `token` 非空时用其覆盖全局配置 token(连接前校验用户输入场景)。
    `path` 可以是相对路径(会自动拼 base_url)或绝对 URL。
    """
    url = path if (path.startswith("http://") or path.startswith("https://")) else _emby_base_url() + path
    final_headers = _build_jellyfin_headers(headers, token=token)
    try:
        async with httpx.AsyncClient(timeout=_EMBY_TIMEOUT, verify=bool(manager.config.verify_ssl)) as client:
            resp = await client.request(method, url, headers=final_headers, content=data)
        if resp.status_code >= 400:
            body = resp.text[:500] if resp.text else ""
            return None, f"HTTP {resp.status_code}" + (f" {body}" if body else "")
        return resp, ""
    except httpx.HTTPError as e:
        return None, f"{type(e).__name__}: {e}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def _emby_get_json(
    path: str, *, headers: dict[str, str] | None = None, token: str | None = None
) -> tuple[dict | None, str]:
    resp, err = await _emby_request("GET", path, headers=headers, token=token)
    if resp is None:
        return None, err
    try:
        return resp.json(), ""
    except Exception as e:
        return None, f"JSON解析失败: {e!s}"


async def _upload_actor_photo(url: str, pic_path: Path) -> tuple[bool, str]:
    try:
        async with aiofiles.open(pic_path, "rb") as f:
            content = await f.read()
        # Emby/Jellyfin 的 Images/Primary、Images/Backdrop 等服务端会
        # 读取 body 为 Base64 格式，传原始二进制会导致服务端 Base64 解码失败 (500)。
        # 必须 Base64 编码后发送。
        b64_content = base64.b64encode(content).decode("ascii")
        header = _build_jellyfin_headers({"Content-Type": _image_content_type(pic_path)})
        # 议题 #133: 头像上传属同步批量路径(每演员一张), 同样走轻量直连
        resp, err = await _emby_request("POST", url, headers=header, data=b64_content)
        return resp is not None, err
    except Exception as e:
        signal.show_log_text(traceback.format_exc())
        return False, f"上传头像失败: {url} {pic_path} {e!s}"
