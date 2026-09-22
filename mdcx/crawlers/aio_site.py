#!/usr/bin/env python3
import json
from typing import override

from ..base.web import get_aio_domain
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year
from .base.base_types import NOT_SUPPORT


class AioSiteCrawler(BaseCrawler):
    """
    tellme.pw AIO 系列站点（avmoo/avsox/avheat）爬虫基类.

    这些站点是 Vue SPA，页面 HTML 只是壳，数据全部走 JSON API:

      - search:    POST {base}/{namespace}/data/api/search
                   body 为 JSON 数组 `[{"search": 番号, "lang": lang}, 60, 1]`
                   返回 `{"code": 200, "data": [{movieId, movieFanHao, title, ...}]}`
      - getMovie:  POST {base}/{namespace}/data/api/getMovie
                   body 为表单 `{"movieId": "..."}`
                   返回完整影片详情(嵌套 star/studio/genre/series/label/director 等)

    站点入口域名为动态地址，通过 tellme.pw 导航页实时获取（见 base/web.get_aio_domain）。
    子类只需指定命名空间、动态域名键、马赛克类型与语言即可。
    """

    namespace: str = ""
    domain_site: str = ""
    mosaic: str = ""

    # 默认域名（动态获取失败时回退）
    fallback_domain: str = ""

    @classmethod
    def supports_custom_url(cls) -> bool:
        return True

    @classmethod
    def _default_url(cls) -> str:
        return cls.fallback_domain or f"https://{cls.domain_site}.shop"

    @classmethod
    @override
    def base_url_(cls) -> str:
        return cls._default_url()

    @classmethod
    @override
    async def check_urls(cls) -> list[str]:
        """网络检测用动态地址（含默认 fallback）."""
        try:
            domain = await get_aio_domain(cls.domain_site)
            return [domain, cls._default_url()]
        except Exception:
            return [cls._default_url()]

    async def _resolve_domain(self, ctx: Context) -> str:
        """解析站点入口域名：优先用户自定义 URL，其次动态获取，最后回退默认域名。"""
        if self.base_url:
            return self.base_url.rstrip("/")
        try:
            domain = await get_aio_domain(self.domain_site)
            ctx.debug(f"动态域名: {domain}")
            return domain
        except Exception as e:
            ctx.debug(f"动态域名获取失败, 使用默认域名: {e}")
            return self._default_url()

    async def _api_search(self, ctx: Context, base: str, number: str) -> dict | None:
        url = f"{base}/{self.namespace}/data/api/search"
        body = json.dumps([{"search": number, "lang": "cn"}, 60, 1])
        json_data, error = await self.async_client.post_json(
            url,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if error or json_data is None:
            ctx.debug(f"搜索请求失败: {error}")
            return None
        items = json_data.get("data") or []
        if not items:
            ctx.debug("搜索结果为空")
            return None
        return items[0]

    async def _api_get_movie(self, ctx: Context, base: str, movie_id: str) -> dict | None:
        url = f"{base}/{self.namespace}/data/api/getMovie"
        json_data, error = await self.async_client.post_json(
            url,
            data={"movieId": movie_id},
            headers={"Accept": "application/json"},
        )
        if error or json_data is None:
            ctx.debug(f"详情请求失败: {error}")
            return None
        data = json_data.get("data")
        return data if isinstance(data, dict) else None

    def _build_data(self, movie: dict, input_number: str) -> CrawlerData:
        title = str(movie.get("title") or "").strip()
        if not title:
            title = str(movie.get("title_ja") or "").strip()
        fanhao = str(movie.get("movieFanHao") or input_number or "").strip()

        actors = [
            str((star.get("starName_en") or star.get("starName_ja") or "").strip())
            for star in (movie.get("star") or [])
            if (star.get("starName_en") or star.get("starName_ja"))
        ]
        actors = list(dict.fromkeys(actors))

        tags = [
            str(genre.get("genreName") or "").strip() for genre in (movie.get("genre") or []) if genre.get("genreName")
        ]

        studio = str((movie.get("studio") or {}).get("studioName") or "").strip()
        series = str((movie.get("series") or {}).get("seriesName") or "").strip()
        label = str((movie.get("label") or {}).get("labelName") or "").strip()
        director = str((movie.get("director") or {}).get("directorName") or "").strip()

        release = str(movie.get("releaseDate") or "").strip()
        length = str(movie.get("length") or "").strip()

        outline = (
            str(movie.get("description_cn") or movie.get("description_zh") or movie.get("description_en") or "").strip()
            if self.with_outline
            else ""
        )

        return CrawlerData(
            title=title,
            originaltitle=title,
            outline=outline or NOT_SUPPORT,
            originalplot=outline or NOT_SUPPORT,
            number=fanhao or input_number,
            release=release,
            year=get_year(release),
            runtime=length,
            studio=studio,
            publisher=label or studio,
            series=series,
            directors=[director] if director else NOT_SUPPORT,
            actors=actors,
            all_actors=actors,
            tags=tags,
            thumb=str(movie.get("posterLarge") or "").strip() or NOT_SUPPORT,
            poster=str(movie.get("posterSmall") or "").strip() or NOT_SUPPORT,
            extrafanart=[str(url or "").strip() for url in (movie.get("sampleLarge") or []) if url and str(url).strip()]
            or NOT_SUPPORT,
            image_download=bool(movie.get("posterSmall") or movie.get("posterLarge")),
            mosaic=self.mosaic,
            external_id=fanhao,
        )

    with_outline: bool = False

    @override
    async def _run(self, ctx: Context):
        number = (ctx.input.number or "").strip()
        if not number:
            raise CrawlerException("番号为空")

        base = await self._resolve_domain(ctx)
        ctx.debug(f"API 基础地址: {base}")

        movie = await self._api_search(ctx, base, number)
        if not movie:
            raise CrawlerException(f"未找到匹配: {number}")

        movie_id = str(movie.get("movieId") or "").strip()
        ctx.debug(f"搜索命中 movieId: {movie_id}")
        detail = await self._api_get_movie(ctx, base, movie_id)
        if not detail:
            raise CrawlerException("获取详情失败")

        data = self._build_data(detail, number)
        data.source = self.site().value
        result = data.to_result()
        return await self.post_process(ctx, result)

    # 三个抽象方法本爬虫用不到（已重写 _run 完全自定义流程），仅需提供实现方可实例化。
    @override
    async def _generate_search_url(self, ctx: Context):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str):
        raise NotImplementedError
