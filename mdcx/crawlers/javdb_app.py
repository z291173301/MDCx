import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import override

from pydantic import BaseModel, ConfigDict
from zhconv import convert as zhconv_convert

from ..base.web import learn_spfcas_image_segment
from ..config.manager import manager
from ..config.models import Website
from ..models.model_types import CrawlerResult
from ..number import match_number, number_search_variants
from .base import BaseCrawler, Context, CrawlerData, CrawlerException

logger = logging.getLogger(__name__)

# ============================================================
# 签名算法 - 基于 JavDB 移动端 APK 逆向
# jdsignature = "{ts}.{suffix}.{md5(ts + prefix)}"
# prefix/suffix 由 APK 解密得到，值已验证与 javdb-cli 项目一致
# ============================================================

_SIG_PREFIX = "71cf27bb3c0bcdf207b64abecddc970098c7421ee7203b9cdae54478478a199e7d5a6e1a57691123c1a931c057842fb73ba3b3c83bcd69c17ccf174081e3d8aa"
_SIG_SUFFIX = "lpw6vgqzsp"

_API_BASE = "https://apidd.czssdgz.com"
_API_FALLBACKS = ["https://apidd.spthgb.com", "https://jdforrepam.com"]
# App CDN（spfcas）返回加密流，下载层统一解密后为无水印原图（见 base/web.py decode_spfcas_image_content）
_IMAGE_HOST_LEGACY = "https://tp.cmastd.com/"
_IMAGE_HOST_APP = "https://tp.spfcas.com/"

_PLATFORM = "android"
_APP_CHANNEL = "official"
_APP_VERSION = "official"
_APP_VERSION_NUMBER = "1.9.35"
_SYSTEM_VERSION = "13"
_DEVICE_MODEL = "Pixel 6"
_DEVICE_NAME = "Pixel"

# 每个 JavDB App 实例对应一个稳定的 device_uuid，模拟真实设备标识
_DEVICE_UUID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "mdcx-javdb-app"))

# 签名常量环境变量覆盖：JavDB App 更新轮换签名常量时免改代码
_ENV_SIG_PREFIX = "MDCX_JAVDB_APP_SIG_PREFIX"
_ENV_SIG_SUFFIX = "MDCX_JAVDB_APP_SIG_SUFFIX"
_ENV_APP_VERSION_NUMBER = "MDCX_JAVDB_APP_VERSION_NUMBER"

# 服务器对签名/参数校验失败的响应特征（200 错误体或 HTTP 状态码）
# 错误 action 值见统一响应包裹：InvalidSignature(HTTP 400) / ParameterInvalid / ResourceNotFound
_SIGNATURE_ERROR_MARKERS = ("parameterinvalid", "invalidsignature", "unauthorized")
_SIGNATURE_HTTP_STATUSES = ("HTTP 400", "HTTP 401", "HTTP 403")


def _env_override(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _signature_prefix() -> str:
    return _env_override(_ENV_SIG_PREFIX, _SIG_PREFIX)


def _signature_suffix() -> str:
    return _env_override(_ENV_SIG_SUFFIX, _SIG_SUFFIX)


def _app_version_number() -> str:
    return _env_override(_ENV_APP_VERSION_NUMBER, _APP_VERSION_NUMBER)


def make_signature() -> str:
    ts = int(time.time())
    md5_hash = hashlib.md5(f"{ts}{_signature_prefix()}".encode()).hexdigest()
    return f"{ts}.{_signature_suffix()}.{md5_hash}"


def _build_api_params() -> dict:
    return {
        "platform": _PLATFORM,
        "app_channel": _APP_CHANNEL,
        "app_version": _APP_VERSION,
        "app_version_number": _app_version_number(),
        "system_version": _SYSTEM_VERSION,
        "device_model": _DEVICE_MODEL,
        "device_name": _DEVICE_NAME,
        "device_uuid": _DEVICE_UUID,
    }


def _get_api_url(host: str, path: str, params: dict | None = None) -> str:
    from urllib.parse import urlencode

    query = _build_api_params()
    if params:
        query.update(params)
    return f"{host}{path}?{urlencode(query)}"


def _is_signature_http_error(error: str) -> bool:
    return any(status in error for status in _SIGNATURE_HTTP_STATUSES)


def _is_signature_error_payload(payload) -> bool:
    try:
        text = json.dumps(payload, ensure_ascii=False).lower()
    except Exception:
        text = str(payload).lower()
    return any(marker in text for marker in _SIGNATURE_ERROR_MARKERS)


class MovieSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    number: str | None = None
    title: str | None = None
    origin_title: str | None = None
    thumb_url: str | None = None
    cover_url: str | None = None
    duration: int | None = None
    release_date: str | None = None
    has_cnsub: bool | None = None


class MovieDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    number: str | None = None
    title: str | None = None
    origin_title: str | None = None
    summary: str | None = None
    thumb_url: str | None = None
    cover_url: str | None = None
    duration: int | None = None
    score: str | None = None
    release_date: str | None = None
    maker_name: str | None = None
    director_name: str | None = None
    publisher_name: str | None = None
    series_name: str | None = None
    tags: list | None = None
    actors: list | None = None
    preview_images: list | None = None
    preview_video_url: str | None = None
    share_info: str | None = None


# ============================================================
# 爬虫实现
# ============================================================


class JavdbAppCrawler(BaseCrawler):
    description = "JavDB 移动端 API 直连（综合：有码+无码）"

    def __init__(self, client, base_url="", browser=None):
        super().__init__(client, base_url, browser)
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    @staticmethod
    def _log(message: str) -> None:
        from ..signals import signal

        signal.add_log(f"[JavdbAPI] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVDB_APP

    @classmethod
    @override
    def base_url_(cls) -> str:
        return manager.config.get_site_url(Website.JAVDB_APP, _API_BASE)

    @staticmethod
    def _ensure_https(url: str) -> str:
        if url and not url.startswith("http"):
            return "https:" + url
        return url or ""

    @classmethod
    def _normalize_image_url(cls, url: str) -> str:
        normalized = cls._ensure_https(url)
        # 老 App CDN 域名归一到当前 App CDN（路径保持原样，spfcas 自用 small_covers 路径体系）
        if normalized.startswith(_IMAGE_HOST_LEGACY):
            normalized = _IMAGE_HOST_APP + normalized[len(_IMAGE_HOST_LEGACY) :]
        if normalized.startswith(_IMAGE_HOST_APP):
            # App CDN 响应持续携带当前路径中段，学习后供网页版 URL 无水印变换自愈
            learn_spfcas_image_segment(normalized)
        return normalized

    @staticmethod
    def _clean_str(value: str | None) -> str:
        if not value:
            return ""
        return value.strip()

    @staticmethod
    def _clean_int(value: int | None) -> str:
        if value is None or value <= 0:
            return ""
        return str(value)

    @staticmethod
    def _is_female(actor: dict) -> bool:
        gender = actor.get("gender")
        if gender is not None:
            if isinstance(gender, str):
                return gender.lower() in ("female", "女", "女优", "女優")
            if isinstance(gender, bool):
                return gender
            if isinstance(gender, int):
                return gender == 1
        return True

    @staticmethod
    def _number_key(value: str) -> str:
        key = value.upper().strip()
        key = re.sub(r"[\s_\-]+", "", key)
        return key.replace("FC2PPV", "FC2")

    @classmethod
    def _search_candidates(cls, number: str) -> list[str]:
        cleaned = number.strip()
        candidates = list(number_search_variants(cleaned))
        key = cls._number_key(cleaned)
        if key.startswith("FC2"):
            digits = re.sub(r"\D", "", key[3:])
            if digits:
                candidates.extend([f"FC2-{digits}", digits])
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    async def _request_api(self, path: str, params: dict | None = None) -> dict | None:
        hosts = [_API_BASE] + _API_FALLBACKS
        signature = make_signature()
        headers = {
            "jdsignature": signature,
            "accept-language": "zh",
            "User-Agent": "Dart/3.5 (dart:io)",
        }

        async with self._request_lock:
            if self._last_request_at > 0:
                elapsed = time.monotonic() - self._last_request_at
                delay = random.uniform(3.0, 8.0)
                if elapsed < delay:
                    await asyncio.sleep(delay - elapsed)
            self._last_request_at = time.monotonic()

        last_error = None
        signature_failures: list[str] = []
        for host in hosts:
            url = _get_api_url(host, path, params)
            try:
                resp, error = await self.async_client.get_json(url, headers=headers)
            except Exception as e:
                last_error = str(e)
                continue

            if resp is not None:
                if _is_signature_error_payload(resp):
                    signature_failures.append(f"{host}: 响应含签名/参数校验错误")
                    continue
                return resp

            if error:
                if _is_signature_http_error(error):
                    signature_failures.append(f"{host}: {error}")
                last_error = error

        if signature_failures:
            detail = "; ".join(signature_failures)
            self._log(f"签名校验失败: {detail}")
            raise CrawlerException(
                f"jdsignature 签名校验失败（{detail}）。签名常量可能已随 JavDB App 更新轮换，"
                f"请升级 mdcx，或设置环境变量 {_ENV_SIG_PREFIX} / {_ENV_SIG_SUFFIX} / "
                f"{_ENV_APP_VERSION_NUMBER} 覆盖签名参数后重试"
            )

        self._log(f"API 请求失败: {last_error}")
        return None

    @override
    async def _run(self, ctx: Context) -> CrawlerResult:
        number = self._clean_str(ctx.input.number)
        if not number:
            raise CrawlerException("番号为空")

        # Step 1: Search for the movie by number (依次尝试候选番号)
        movie_id = None
        last_error = ""
        for candidate in self._search_candidates(number):
            # type=movie 过滤非影片噪声；limit=50 为服务器上限，提高首页精确命中率
            search_resp = await self._request_api(
                "/api/v2/search", {"q": candidate, "page": "1", "type": "movie", "limit": "50"}
            )
            if not search_resp:
                last_error = f"{candidate}: 搜索请求失败"
                continue

            # API response wraps data in "data" key
            search_data_raw = search_resp.get("data", {})
            movies_raw = search_data_raw.get("movies", [])
            if not movies_raw:
                last_error = f"{candidate}: 未找到匹配的影片"
                continue

            movies = [MovieSummary(**m) for m in movies_raw]

            # Find exact match by number (normalized, case-insensitive)
            for summary_movie in movies:
                if summary_movie.number and self._number_key(summary_movie.number) == self._number_key(number):
                    movie_id = summary_movie.id
                    break

            if not movie_id:
                # 无精确匹配时按严格前缀规则匹配，避免 BF-002 误用 ABF-002 等更长前缀的结果
                for summary_movie in movies:
                    if summary_movie.number and match_number(summary_movie.number, number):
                        movie_id = summary_movie.id
                        break

            if movie_id:
                ctx.debug(f"候选番号 {candidate} 命中影片 ID: {movie_id}")
                break
            last_error = f"{candidate}: 未找到严格匹配的影片"

        if not movie_id:
            raise CrawlerException(f"搜索失败: {last_error}")

        ctx.debug(f"找到影片 ID: {movie_id}")

        # Step 2: Get movie detail
        detail_resp = await self._request_api(f"/api/v4/movies/{movie_id}")
        if not detail_resp:
            raise CrawlerException("详情请求失败")

        # API response wraps data in "data" key
        detail_data_raw = detail_resp.get("data", {})
        movie_raw = detail_data_raw.get("movie", {})
        if not movie_raw:
            raise CrawlerException("详情数据为空")

        try:
            movie = MovieDetail(**movie_raw)
        except Exception as e:
            ctx.debug(f"详情响应解析失败: {e} {movie_raw=}")
            raise CrawlerException("详情响应解析失败") from e

        self._log(
            "图片字段: "
            f"cover_url={self._normalize_image_url(self._clean_str(movie.cover_url))} "
            f"thumb_url={self._normalize_image_url(self._clean_str(movie.thumb_url))}"
        )

        # Step 3: Build CrawlerData
        data = CrawlerData(
            number=self._clean_str(movie.number),
            title=self._clean_str(movie.title),
            originaltitle=self._clean_str(movie.origin_title),
            outline=self._clean_str(movie.summary),
            thumb=self._normalize_image_url(self._clean_str(movie.cover_url)),
            poster=self._normalize_image_url(self._clean_str(movie.thumb_url)),
            release=self._clean_str(movie.release_date),
            runtime=self._clean_int(movie.duration),
            score=self._clean_str(movie.score),
            studio=self._clean_str(movie.maker_name),
            directors=[self._clean_str(movie.director_name)] if movie.director_name else [],
            publisher=self._clean_str(movie.publisher_name),
            series=self._clean_str(movie.series_name),
            tags=(
                [
                    self._clean_str(tag.get("name"))
                    for tag in (movie.tags or [])
                    if tag and self._clean_str(tag.get("name"))
                ]
                if movie.tags
                else []
            ),
            actors=(
                [
                    self._clean_str(actor.get("name"))
                    for actor in (movie.actors or [])
                    if actor and self._clean_str(actor.get("name")) and self._is_female(actor)
                ]
                if movie.actors
                else []
            ),
            all_actors=(
                [
                    self._clean_str(actor.get("name"))
                    for actor in (movie.actors or [])
                    if actor and self._clean_str(actor.get("name"))
                ]
                if movie.actors
                else []
            ),
            extrafanart=[
                self._normalize_image_url(img.get("thumb_url") or img.get("large_url", ""))
                for img in (movie.preview_images or [])
                if img
            ],
            trailer=self._ensure_https(self._clean_str(movie.preview_video_url)),
            external_id=f"https://javdb573.com/v/{movie_id}",
        )

        # Set image_download to True if we have cover/thumb URLs
        if data.thumb or data.poster:
            data.image_download = True

        data.source = self.site().value
        result = data.to_result()
        return await self.post_process(ctx, result)

    @override
    async def _generate_search_url(self, ctx: Context):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str):
        raise NotImplementedError

    @override
    async def post_process(self, ctx: Context, res: CrawlerResult) -> CrawlerResult:
        if not res.originaltitle:
            res.originaltitle = res.title
        if res.release:
            res.year = res.release[:4]
        res.mosaic = "无码" if self._number_key(res.number or "").startswith("FC2") else "有码"
        if res.mosaic != "无码":
            from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

            thumb, poster = await upgrade_dmm_cover(ctx, str(res.number or ""), res.thumb, res.poster)
            res.thumb = thumb
            res.poster = poster
        return res


# ============================================================
# 演员别名查询 — 供演员数据管理工具调用
# ============================================================

_JP_VARIANT_MAP: dict[str, str] = {
    "亜": "亞",
    "亞": "亞",
    "凉": "涼",
    "涼": "涼",
    "高": "髙",
    "髙": "髙",
    "斎": "齋",
    "齋": "齋",
    "沢": "澤",
    "澤": "澤",
    "桜": "櫻",
    "櫻": "櫻",
    "垅": "壟",
    "壮": "壯",
    "壯": "壯",
    "屿": "嶼",
    "嶼": "嶼",
    "栗": "慄",
    "慄": "慄",
    "岬": "岬",
}


def _normalize_actor_name(name: str) -> str:
    """归一化演员名用于匹配：NFKC + zhconv 繁体 + 日文异体字统一 + 去标点 + 小写"""
    name = unicodedata.normalize("NFKC", name)
    name = zhconv_convert(name, "zh-hant")
    name = "".join(_JP_VARIANT_MAP.get(c, c) for c in name)
    name = re.sub(r"[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]", "", name)
    return name.lower()


def _is_pure_kana(name: str) -> bool:
    """判断归一化后的名字是否纯假名（无汉字）"""
    return bool(name) and all("\u3040" <= c <= "\u30ff" for c in name)


def _actor_name_matches(target: str, candidate: str) -> bool:
    """宽松匹配演员名：归一化后完全一致、包含、或去掉末字后一致。

    纯假名短名（归一化后 ≤2 字）只允许精确匹配，不做子串包含——
    2 字假名作为子串极易误命中（如 "りな" 出现在 "新ありな" 中）。
    含汉字的名字不受此限制（如 "田中檸檬" 包含 "檸檬" 是安全的）。
    """
    t = _normalize_actor_name(target)
    c = _normalize_actor_name(candidate)
    if not t or not c:
        return False
    if t == c:
        return True
    # 纯假名短名（≤2字）不做子串包含，避免误匹配
    short_side = t if len(t) <= len(c) else c
    if _is_pure_kana(short_side) and len(short_side) <= 2:
        # 但允许去掉末字后一致（处理异体字差异）
        if len(t) >= 3 and len(c) >= 3 and t[:-1] == c[:-1]:
            return True
        return False
    if t in c or c in t:
        return True
    if len(t) >= 3 and len(c) >= 3 and t[:-1] == c[:-1]:
        return True
    return False


@dataclass
class JavdbActorInfo:
    """JavDB 演员详情（仅包含可用的名字相关字段）."""

    name: str = ""  # JavDB 数据库里的 name 字段（可能是日文原名或正式中文名）
    name_zht: str = ""  # 繁体名（可能为空）
    other_name: str = ""  # 别名字段（逗号分隔，可能含日文原名与其他别名）


async def fetch_javdb_actor_info(actor_name: str) -> JavdbActorInfo | None:
    """从 JavDB 移动端 API 查询演员的完整名字信息。

    流程: 搜索演员名 → 取前 5 部影片详情 → 匹配演员 → 取演员详情。
    返回 JavdbActorInfo（含 name/name_zht/other_name）或 None（未匹配）。
    """
    if not actor_name or not actor_name.strip():
        return None

    target = actor_name.strip()
    try:
        from urllib.parse import urlencode

        sig = make_signature()
        headers = {"jdsignature": sig, "accept-language": "zh", "User-Agent": "Dart/3.5 (dart:io)"}
        base_params = _build_api_params()

        params = dict(base_params)
        params["q"] = target
        params["page"] = "1"
        url = f"{_API_BASE}/api/v2/search?{urlencode(params)}"

        async with manager.acquire_computed() as computed:
            response, error = await computed.async_client.get_json(url, headers=headers, retry_count=1)
        if response is None:
            logger.debug("[javdb-actor] 搜索失败: %s", error)
            return None

        movies = (response.get("data") or {}).get("movies") or []
        if not movies:
            return None

        # 并发拉取前 5 部影片详情（原串行 for 循环是主要瓶颈）
        async with manager.acquire_computed() as computed:

            async def _fetch_movie_detail(movie_id: str) -> list[dict]:
                detail_params = dict(base_params)
                detail_url = f"{_API_BASE}/api/v4/movies/{movie_id}?{urlencode(detail_params)}"
                detail_resp, detail_err = await computed.async_client.get_json(
                    detail_url, headers=headers, retry_count=1
                )
                if detail_resp is None:
                    return []
                actors = ((detail_resp.get("data") or {}).get("movie") or {}).get("actors")
                return actors if isinstance(actors, list) else []

            movie_ids = [m.get("id") for m in movies[:5] if m.get("id")]
            actors_lists = await asyncio.gather(*[_fetch_movie_detail(mid) for mid in movie_ids])

        # 在所有影片的演员列表中找匹配者，取其 actor_id 查演员详情
        matched_actor_ids: list[str] = []
        for actors in actors_lists:
            for actor in actors:
                if not isinstance(actor, dict):
                    continue
                cand_name = (actor.get("name") or "").strip()
                if not cand_name or not _actor_name_matches(target, cand_name):
                    continue
                actor_id = actor.get("id")
                if actor_id and actor_id not in matched_actor_ids:
                    matched_actor_ids.append(actor_id)

        if not matched_actor_ids:
            return None

        async with manager.acquire_computed() as computed:
            for actor_id in matched_actor_ids:
                actor_params = dict(base_params)
                actor_url = f"{_API_BASE}/api/v1/actors/{actor_id}?{urlencode(actor_params)}"
                actor_resp, actor_err = await computed.async_client.get_json(actor_url, headers=headers, retry_count=1)
                if actor_resp is None:
                    continue
                actor_data = (actor_resp.get("data") or {}).get("actor") or {}
                return JavdbActorInfo(
                    name=(actor_data.get("name") or "").strip(),
                    name_zht=(actor_data.get("name_zht") or "").strip(),
                    other_name=(actor_data.get("other_name") or "").strip(),
                )
        return None
    except Exception:
        logger.debug("[javdb-actor] 查询失败: %s", target, exc_info=True)
        return None


async def fetch_javdb_aliases(actor_name: str) -> list[str]:
    """从 JavDB 移动端 API 查询演员别名。

    流程: 搜索演员名 → 取前 5 部影片详情 → 匹配演员 → 取演员详情的 other_name 字段
    → 拆分逗号 + 去重 + 排除原名 → 返回别名列表。

    搜索无结果、未匹配到演员、无别名均返回空列表，由调用方决定如何降级。
    """
    info = await fetch_javdb_actor_info(actor_name)
    if info is None:
        return []
    return _split_aliases(info.other_name, info.name_zht, actor_name.strip(), info.name)


def _is_combo_name(alias: str) -> bool:
    """判断别名是否为组合名（A・B 格式，两边各自像完整的日本人姓名）。

    判断标准：去掉括号后，・ 两边各为 2-5 字的纯汉字/含假名姓名段。
    外国人名（含片假名外来语）、罗马音间隔、括号内标签不受影响。
    例: 朝比奈菜々子・水原麗子 -> True（双人名组合）
        アンジェラ・ホワイト   -> False（片假名外来语）
        岸畑孝美(人妻斬り・...)  -> False（括号内）
    """
    import re

    # 去掉括号内容后再判断
    clean = re.sub(r"\(.*?\)|【.*?】|\[.*?\]", "", alias).strip()
    if "・" not in clean:
        return False
    parts = [p.strip() for p in clean.split("・") if p.strip()]
    if len(parts) != 2:
        return False

    def _looks_like_jp_name(s: str) -> bool:
        """2-6 字，含汉字或平假名（非片假名外来语），像日本人姓名"""
        if not (2 <= len(s) <= 6):
            return False
        has_kanji = any("\u4e00" <= c <= "\u9fff" for c in s)
        has_hira = any("\u3040" <= c <= "\u309f" for c in s)
        # 片假名为主（外来语）不算日本人姓名
        has_kata = any("\u30a0" <= c <= "\u30ff" for c in s)
        if has_kata and not has_kanji:
            return False
        return has_kanji or has_hira

    return _looks_like_jp_name(parts[0]) and _looks_like_jp_name(parts[1])


def _split_aliases(other_name: str, name_zht: str, search_name: str, db_name: str) -> list[str]:
    """拆分 other_name 字段为别名列表，排除原名和搜索名，过滤组合名"""
    seen = {_normalize_actor_name(search_name), _normalize_actor_name(db_name)}
    aliases: list[str] = []
    for part in other_name.split(","):
        part = part.strip()
        if not part or _normalize_actor_name(part) in seen:
            continue
        if _is_combo_name(part):
            continue
        seen.add(_normalize_actor_name(part))
        aliases.append(part)
    if name_zht and _normalize_actor_name(name_zht) not in seen:
        aliases.append(name_zht)
    return aliases
