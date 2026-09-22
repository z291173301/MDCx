import re
from typing import Any, override
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict

from mdcx.config.enums import DownloadableFile
from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.models.model_types import CrawlerResult
from mdcx.signals import signal

from .base import CrawlerData, CrawlerException
from .dmm import DMMContext, DmmCrawler

_DEFAULT_API_ID = "UrwskPfkqQ0DuVry2gYL"
_DEFAULT_AFFILIATE_ID = "10278-996"
_API_PATH = "/affiliate/v3/ItemList"


class _DmmApiItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service_code: str | None = None
    content_id: str | None = None
    product_id: str | None = None
    title: str | None = None
    date: str | None = None
    volume: int | str | None = None
    review: dict[str, Any] | None = None
    imageURL: dict[str, str] | None = None
    sampleImageURL: dict | None = None
    # DMM 真实响应的 iteminfo 条目除 name 外还含 int 型 id 等字段，
    # 值类型须用 Any，声明 dict[str, str] 会让所有真实响应校验失败。
    iteminfo: dict[str, list[dict[str, Any]]] | None = None
    URL: str | None = None
    affiliateURL: str | None = None

    def _info_names(self, key: str) -> list[str]:
        entries = (self.iteminfo or {}).get(key, []) or []
        return [str(e.get("name", "")).strip() for e in entries if e.get("name")]

    @property
    def actresses(self) -> list[str]:
        return self._info_names("actress")

    @property
    def directors(self) -> list[str]:
        return self._info_names("director")

    @property
    def genres(self) -> list[str]:
        return self._info_names("genre")

    @property
    def makers(self) -> list[str]:
        return self._info_names("maker")

    @property
    def labels(self) -> list[str]:
        return self._info_names("label")

    @property
    def series(self) -> list[str]:
        return self._info_names("series")

    @property
    def thumb_urls(self) -> list[str]:
        """返回缩略图候选 URL，优先竖幅大图(pl→ps)再横幅(pt)。"""
        urls: list[str] = []
        img = self.imageURL or {}
        for key in ("large", "small", "list"):
            if url := img.get(key):
                urls.append(url)
        return urls

    @property
    def sample_images(self) -> list[str]:
        for key in ("sample_l", "sample_s"):
            block = (self.sampleImageURL or {}).get(key)
            if isinstance(block, dict):
                imgs = block.get("image", [])
                if imgs:
                    return list(imgs)
        return []

    @property
    def digital_cid(self) -> str:
        for url in self.sample_images:
            if m := re.search(r"/digital/video/([^/]+)/", url):
                return m.group(1)
        for url in self.thumb_urls:
            if m := re.search(r"/digital/video/([^/]+)/", url):
                return m.group(1)
        return ""


class DmmApiCrawler(DmmCrawler):
    description = "DMM 官方 Affiliate API（仅能有码）"

    @staticmethod
    def _log(message: str):
        signal.add_log(f"[DmmApi] {message}")

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.DMM_API

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://api.dmm.com"

    @classmethod
    @override
    def supports_custom_url(cls) -> bool:
        return False

    @classmethod
    def _api_id(cls) -> str:
        return str(getattr(manager.config, "dmm_api_id", "") or "").strip() or _DEFAULT_API_ID

    @classmethod
    def _affiliate_id(cls) -> str:
        return str(getattr(manager.config, "dmm_affiliate_id", "") or "").strip() or _DEFAULT_AFFILIATE_ID

    @classmethod
    def _build_api_url(cls, **params: str) -> str:
        query = urlencode(
            {
                "api_id": cls._api_id(),
                "affiliate_id": cls._affiliate_id(),
                "output": "json",
                **params,
            }
        )
        return f"{cls.base_url_()}{_API_PATH}?{query}"

    @staticmethod
    def _search_keywords(number: str) -> list[str]:
        """DMM keyword 全文检索的候选序列.

        带横杠格式（SSIS-200）实测返回 0 结果；content_id 形态
        （小写前缀 + 编号补零到 5 位，如 ssis00200）可精确命中。
        特殊站内前缀番号（如 T28 系列 cid=55t2800645）转换后可能落空，
        回退小写厂牌词模糊搜索，交由 _find_best_item 打分挑选。
        """
        stripped = number.strip()
        m = re.fullmatch(r"([A-Za-z0-9]+)-(\d{1,5})", stripped)
        if not m:
            return [stripped]
        prefix, digits = m.group(1).lower(), m.group(2)
        return [f"{prefix}{digits.zfill(5)}", prefix]

    @staticmethod
    def _match_score(item: _DmmApiItem, number_clean: str) -> int:
        """按匹配质量打分，数字段忽略前导零。

        DMM content_id 的编号段 5 位补零（如 sone00244），直接与去横杠后的番号
        （sone244）比较永远不等，导致 90/80 分分支形同虚设、全部落入包含匹配。
        """
        cid = (item.content_id or "").lower()
        pid = (item.product_id or "").lower()
        ncid = re.sub(r"[^a-z0-9]", "", cid)
        npid = re.sub(r"[^a-z0-9]", "", pid)
        nnum = re.sub(r"[^a-z0-9]", "", number_clean)

        if ncid == nnum:
            return 100
        m = re.search(r"([a-z]+)(?:\.)?(\d+)$", cid)
        num_m = re.search(r"([a-z]+)(\d+)$", number_clean)
        if m and num_m and m.group(1) == num_m.group(1) and int(m.group(2)) == int(num_m.group(2)):
            return 90
        if nnum in ncid:
            score = 50
            if ncid.startswith("9"):
                score -= 10
            return score
        if npid == nnum:
            return 80
        return -1

    def _find_best_item(self, items: list[_DmmApiItem], number: str) -> _DmmApiItem | None:
        number_clean = number.replace("-", "").lower()
        best: _DmmApiItem | None = None
        best_score = -1
        for item in items:
            score = self._match_score(item, number_clean)
            if score > best_score:
                best_score = score
                best = item
        return best if best_score >= 0 else None

    def _set_number_context(self, ctx: DMMContext, number: str) -> None:
        number_lower = number.lower()
        if x := re.findall(r"[A-Za-z]+-?(\d+)", number_lower):
            digits = x[0]
            if len(digits) >= 5 and digits.startswith("00"):
                number_lower = number_lower.replace(digits, digits[2:])
            elif len(digits) == 4:
                number_lower = number_lower.replace("-", "0")
        ctx.number_00 = number_lower.replace("-", "00")
        ctx.number_no_00 = number_lower.replace("-", "")

    @override
    async def _run(self, ctx: DMMContext) -> CrawlerResult:
        number = ctx.input.number.strip()
        if not number:
            raise CrawlerException("番号为空")

        self._set_number_context(ctx, number)

        items: list[_DmmApiItem] = []
        search_urls: list[str] = []
        for keyword in self._search_keywords(number):
            api_url = self._build_api_url(keyword=keyword, sort="match", hits="20")
            search_urls.append(api_url)
            ctx.debug(f"API URL: {api_url}")
            ctx.debug_info.search_urls = list(search_urls)

            response, error = await self.async_client.get_json(api_url, headers={"Accept": "application/json"})
            if response is None:
                raise CrawlerException(f"API 请求失败: {error}")

            result = response.get("result", {}) or {}
            status_code = result.get("status")
            if status_code != 200:
                raise CrawlerException(f"API 返回错误: status={status_code}, message={result.get('message', '')}")

            raw_items = result.get("items", []) or []
            if raw_items:
                items = [_DmmApiItem.model_validate(item) for item in raw_items]
                break

        if not items:
            raise CrawlerException(f"API 无搜索结果: {number}")
        best = self._find_best_item(items, number)
        if not best:
            ctx.debug(f"未找到匹配项，共 {len(items)} 条结果")
            raise CrawlerException(f"API 搜索无精确匹配: {number}")

        ctx.debug(f"匹配: content_id={best.content_id} title={best.title!r}")

        data = self._to_crawler_data(best, fallback_number=number)
        if not data.title and not data.thumb:
            raise CrawlerException("API 返回空内容")

        ctx.debug_info.detail_urls = [str(best.affiliateURL or best.URL or data.external_id)]

        trailer = await self._fetch_trailer(ctx, best)
        if trailer:
            data.trailer = trailer
            ctx.debug(f"预告片: {trailer}")

        data.source = self.site().value
        result_data = data.to_result()
        return await self.post_process(ctx, result_data)

    async def _fetch_trailer(self, ctx: DMMContext, item: _DmmApiItem) -> str:
        digital_cid = item.digital_cid
        if not digital_cid or not self._is_valid_dmm_cid(digital_cid):
            ctx.debug("无法提取 digital cid，跳过预告片")
            return ""

        player_url = (
            f"https://www.dmm.co.jp/service/digitalapi/-/html5_player/"
            f"=/cid={digital_cid}/mtype=AhRVShI_/service=digital/floor=videoa/mode=/"
        )
        player_html, error = await self._http_request_with_retry(
            "GET",
            player_url,
            headers={"User-Agent": "Mozilla/5.0"},
            cookies={"age_check_done": "1"},
            encoding="euc-jp",
        )
        if player_html is None:
            ctx.debug(f"HTML5 player 请求失败: {digital_cid=} {error=}")
            return ""

        candidates = self._extract_litevideo_trailer_candidates(player_html)
        if not candidates:
            ctx.debug(f"HTML5 player 未找到预告片: {digital_cid=}")
            return ""

        best = self._pick_best_unvalidated_trailer("", candidates)
        if not best:
            ctx.debug(f"预告片候选无可选: {digital_cid=}")
            return ""

        validated = await self._validate_trailer_url(ctx, best)
        if validated:
            best = validated
        ctx.debug(f"预告片候选: {len(candidates)} 个，最优 rank={self._trailer_quality_rank(best)}: {best}")
        return best

    def _to_crawler_data(self, item: _DmmApiItem, *, fallback_number: str) -> CrawlerData:
        title = str(item.title or "").strip()
        thumb_urls = [self._with_https(u) for u in item.thumb_urls if u]
        thumb = thumb_urls[0] if thumb_urls else ""
        # poster 留空，由 post_process 的 _finalize_result_images 从 thumb 派生（pl→ps）

        samples = [self._with_https(u) for u in item.sample_images if u]
        # 升级剧照到高清版: -N.jpg -> jp-N.jpg（与 DmmCrawler DigitalParser 一致）
        samples = [re.sub(r"-(\d+)\.jpg", r"jp-\1.jpg", u) for u in samples]

        release_raw = str(item.date or "").strip()
        release = release_raw.split(" ")[0] if release_raw else ""

        return CrawlerData(
            title=title,
            originaltitle=title,
            outline="",
            originalplot="",
            number=fallback_number,
            thumb=thumb,
            poster="",
            trailer="",
            release=release,
            runtime=self._runtime(item.volume),
            score=self._score(item.review),
            studio=self._first(item.makers),
            publisher=self._first(item.labels),
            series=self._first(item.series),
            actors=item.actresses,
            all_actors=item.actresses,
            directors=item.directors,
            tags=item.genres,
            extrafanart=samples,
            external_id=str(item.affiliateURL or item.URL or fallback_number),
            mosaic="有码",
        )

    @staticmethod
    def _first(values: list[str]) -> str:
        return values[0] if values else ""

    @staticmethod
    def _runtime(value: int | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, int):
            return str(value) if value > 0 else ""
        if m := re.search(r"\d+", str(value)):
            return m.group()
        return ""

    @staticmethod
    def _score(review: dict[str, Any] | None) -> str:
        if not review:
            return ""
        average = str(review.get("average", "") or "").strip()
        if average:
            return average
        if m := re.search(r"[\d.]+", str(review)):
            return m.group()
        return ""

    @override
    async def post_process(self, ctx: DMMContext, res: CrawlerResult) -> CrawlerResult:
        if not res.publisher:
            res.publisher = res.studio
        if res.extrafanart and DownloadableFile.EXTRAFANART not in manager.config.download_files:
            res.extrafanart = self._dedupe_urls(res.extrafanart)
        return await super().post_process(ctx, res)
