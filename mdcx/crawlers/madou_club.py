#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from typing import override
from urllib.parse import urlencode, urljoin

from parsel import Selector

from ..config.models import Website
from ..models.model_types import CrawlerInput
from .base import BaseCrawler, Context, CrawlerData, CrawlerException
from .guochan import get_number_list


def _dedupe(items: list[str]) -> list[str]:
    result = []
    for item in items:
        item = str(item or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _no_sep(text: str) -> str:
    return re.sub(r"[\W_]", "", text or "").upper()


def normalize_cover_url(cover_url: str) -> str:
    cover_url = (cover_url or "").strip()
    if not cover_url:
        return ""
    # 搜索页缩略图形如 .../covers/2022/02/xxx-240x180.jpg，去掉尺寸后缀拿原图
    return re.sub(r"-\d+x\d+(\.\w+)$", r"\1", cover_url)


def _extract_number_candidates(number: str, appoint_number: str = "", file_path: str = "") -> list[str]:
    values = [appoint_number, number]
    if file_path:
        filename = re.split(r"[\\/]", file_path)[-1]
        values.append(re.sub(r"\.[^.]+$", "", filename))

    candidates: list[str] = []
    for value in values:
        text = str(value or "").upper()
        for match in re.finditer(r"(?<![A-Z0-9])([A-Z]{2,5})[-_ ]?(\d{3,5})(?!\d)", text):
            prefix, digits = match.groups()
            candidates.extend([f"{prefix}{digits}", f"{prefix}-{digits}"])
    return _dedupe(candidates)


def parse_title(title: str) -> tuple[str, str]:
    """详情页标题形如 'MDX0236-01 / 淫荡静香的偷腥体验'，返回 (番号, 标题)。"""
    title = (title or "").strip()
    if " / " in title:
        number, real_title = title.split(" / ", 1)
        return number.strip(), real_title.strip()
    if "/" in title:
        number, real_title = title.split("/", 1)
        return number.strip(), real_title.strip()
    return "", title


@dataclass
class MadouClubContext(Context):
    number_candidates: list[str] = field(default_factory=list)
    search_cover_url: str = ""


class MadouClubCrawler(BaseCrawler[MadouClubContext]):
    description = "麻豆社 国产（国产）"
    # madou.club 收录麻豆系 MDX 等番号，搜索需无横杠关键词（MDX-0236 无结果，MDX0236 命中，2026-08 实测）
    probe_number = "MDX0236"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MADOUCLUB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://madou.club"

    @override
    def new_context(self, input: CrawlerInput) -> MadouClubContext:
        return MadouClubContext(input=input)

    @override
    async def _generate_search_url(self, ctx: MadouClubContext) -> list[str] | str | None:
        file_path = str(ctx.input.file_path or "")
        number_list, _filename_list = get_number_list(ctx.input.number, ctx.input.appoint_number, file_path)
        ctx.number_candidates = _dedupe(
            _extract_number_candidates(ctx.input.number, ctx.input.appoint_number, file_path) + number_list
        )
        # madou.club 搜索须无横杠关键词
        keywords = [n.replace("-", "").replace(" ", "") for n in ctx.number_candidates]
        # get_number_list 会同时产出 MDX0236 与补零版 MDX00236，同一前缀分组内保留最短
        groups: dict[str, list[str]] = {}
        for k in keywords:
            m = re.search(r"([A-Z]{2,})\d+", k)
            if not m:
                groups.setdefault(k, []).append(k)
                continue
            groups.setdefault(m.group(1), []).append(k)
        ctx.number_candidates = _dedupe([min(v, key=len) for v in groups.values()])
        return [f"{self.base_url}/?{urlencode({'s': keyword})}" for keyword in ctx.number_candidates]

    @override
    async def _parse_search_page(
        self, ctx: MadouClubContext, html: Selector, search_url: str
    ) -> list[str] | str | None:
        candidates = {_no_sep(n) for n in ctx.number_candidates}
        detail_urls: list[str] = []
        for article in html.xpath('//article[contains(concat(" ", normalize-space(@class), " "), " excerpt ")]'):
            title = article.xpath(".//h2//text()").get()
            href = article.xpath(".//h2//a/@href").get()
            cover = article.xpath(".//img/@data-src").get() or article.xpath(".//img/@src").get()
            if not title or not href:
                continue
            if not candidates or any(c in _no_sep(title) for c in candidates):
                detail_urls.append(urljoin(search_url, href))
                if cover and not ctx.search_cover_url:
                    ctx.search_cover_url = normalize_cover_url(cover)
        if not detail_urls:
            ctx.debug("MadouClub 搜索页没有匹配结果")
            return None
        ctx.debug(f"MadouClub 搜索命中: {detail_urls}")
        return detail_urls

    @override
    async def _parse_detail_page(self, ctx: MadouClubContext, html: Selector, detail_url: str) -> CrawlerData | None:
        title = html.xpath("//h1[contains(@class,'article-title')]/text()").get()
        if not title:
            raise CrawlerException("数据获取失败: 未获取到标题")
        number, title = parse_title(title)
        if not number:
            number = ctx.input.number
        studio = html.xpath(
            '//div[contains(@class,"article-meta")]//a[contains(concat(" ", normalize-space(@rel), " "), " category ")]/text()'
        ).get()
        tags = html.xpath(
            '//div[contains(@class,"article-tags")]//a[contains(concat(" ", normalize-space(@rel), " "), " tag ")]/text()'
        ).getall()
        thumb = ctx.search_cover_url
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=[],
            all_actors=[],
            tags=_dedupe(tags),
            studio=studio or "",
            publisher=studio or "",
            thumb=thumb,
            poster=thumb,
            extrafanart=[],
            image_download=False,
            mosaic="国产",
            external_id=detail_url,
        )
