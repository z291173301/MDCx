#!/usr/bin/env python3
import re
from dataclasses import dataclass, field
from typing import override
from urllib.parse import urlencode, urljoin

from parsel import Selector

from ..config.models import Website
from ..models.model_types import CrawlerInput
from .base import BaseCrawler, Context, CrawlerData, CrawlerException
from .base.parser import get_year, parse_runtime


def _dedupe(items: list[str]) -> list[str]:
    result = []
    for item in items:
        item = str(item or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _no_sep(text: str) -> str:
    return re.sub(r"[\W_]+", "", text or "").upper()


def extract_number_candidates(number: str, appoint_number: str = "", file_path: str = "") -> list[str]:
    """生成搜索关键词候选。

    javfree.me 搜索实测（2026-08）：
    - 标准番号带横杠形态命中（SSNI-647 命中，纯数字 4965111 无结果）
    - FC2 番号需 FC2-PPV-{digits} 形态（FC2-4965111 与纯数字均无结果）
    """
    values = [appoint_number, number]
    if file_path:
        filename = re.split(r"[\\/]", file_path)[-1]
        values.append(re.sub(r"\.[^.]+$", "", filename))

    candidates: list[str] = []
    for value in values:
        text = str(value or "").upper().replace("_", "-")
        fc2 = re.search(r"FC2(?:-?PPV)?-(\d{5,})", text)
        if fc2:
            candidates.append(f"FC2-PPV-{fc2.group(1)}")
            continue
        m = re.search(r"(?<![A-Z])([A-Z]{2,7})-?(\d{2,6})(?!\d)", text)
        if m:
            candidates.append(f"{m.group(1)}-{m.group(2)}")
    return _dedupe(candidates)


def parse_title(title: str) -> tuple[str, str]:
    """标题解析 (番号, 片名)。

    站内三种形态：
    - [SSNI-647] 一ヶ月間の禁欲の果てに... 橋本ありな
    - FC2 PPV 4965111 30%OFF! ...
    - Heyzo 3924 敏感フリーター娘 ...
    """
    title = re.sub(r"\s+", " ", (title or "").strip())
    m = re.match(r"\[([^\[\]]+)\]\s*(.*)", title)
    if m:
        return m.group(1).strip().upper(), m.group(2).strip()
    m = re.match(r"FC2\s*PPV\s*(\d{5,})\s*(.*)", title, re.I)
    if m:
        return f"FC2-{m.group(1)}", m.group(2).strip()
    m = re.match(r"(HEYZO)\s*[_\-]?(?:HD\s*[_\-]?)?(\d{3,6})(?:_full)?\s*(.*)", title, re.I)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}", m.group(3).strip()
    return "", title


def _match_number(no_sep_title: str, candidate: str) -> bool:
    """无分隔符番号匹配。

    标准番号要求命中位置后一位不是数字（避免 SSNI-647 误中 SSNI-6470）。
    FC2 候选跳过边界检查：FC2 编号长（≥6 位），且标题形如 "FC2 PPV 4965111 30%OFF"
    归一化后番号后紧跟计数数字 30，边界检查会误杀精确命中。
    """
    idx = no_sep_title.find(candidate)
    if idx < 0:
        return False
    if "FC2PPV" in candidate:
        return True
    while idx >= 0:
        end = idx + len(candidate)
        if end >= len(no_sep_title) or not no_sep_title[end].isdigit():
            return True
        idx = no_sep_title.find(candidate, idx + 1)
    return False


def category_from_url(url: str) -> str:
    """从 /category/mosaic/s1 提取分类路径 mosaic/s1。"""
    m = re.search(r"/category/([^?#]+)", url or "")
    return m.group(1) if m else ""


def classify_mosaic(category_path: str) -> str:
    """按站点分类判定有码/无码：mosaic/*=有码；avi/*（含 fc2）与 demosaic=无码。"""
    path = (category_path or "").strip("/").lower()
    if path.startswith("mosaic"):
        return "有码"
    return "无码"


def parse_metadata_lines(blockquote_html: str) -> tuple[dict[str, str], str]:
    """详情页 blockquote 按行解析元数据字段，品番之后的行拼接为剧情简介。"""
    lines = re.split(r"<br\s*/?>", blockquote_html or "")
    fields: dict[str, str] = {}
    outline_parts: list[str] = []
    for line in lines:
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", line)).strip()
        if not plain:
            continue
        m = re.match(r"(発売日|収録時間|出演者|監督|シリーズ|メーカー|レーベル|ジャンル|品番)[：:]\s*(.+)", plain)
        if m and not outline_parts:
            fields[m.group(1)] = m.group(2).strip()
        else:
            outline_parts.append(plain)
    return fields, "\n".join(outline_parts)


@dataclass
class JavfreeContext(Context):
    number_candidates: list[str] = field(default_factory=list)
    search_cover_url: str = ""
    category_path: str = ""


class JavfreeCrawler(BaseCrawler[JavfreeContext]):
    description = "JAVFREE 综合（有码+FC2）"
    probe_number = "SSNI-647"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVFREE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://javfree.me"

    @override
    def new_context(self, input: CrawlerInput) -> JavfreeContext:
        return JavfreeContext(input=input)

    @override
    async def _generate_search_url(self, ctx: JavfreeContext) -> list[str] | str | None:
        ctx.number_candidates = extract_number_candidates(
            ctx.input.number, ctx.input.appoint_number, str(ctx.input.file_path or "")
        )
        if not ctx.number_candidates:
            ctx.debug("JAVFREE 未识别出可搜索的番号")
            return None
        return [f"{self.base_url}/?{urlencode({'s': keyword})}" for keyword in ctx.number_candidates]

    @override
    async def _parse_search_page(self, ctx: JavfreeContext, html: Selector, search_url: str) -> list[str] | str | None:
        candidates = [_no_sep(n) for n in ctx.number_candidates]
        detail_urls: list[str] = []
        for article in html.xpath('//article[contains(concat(" ", normalize-space(@class), " "), " hentry ")]'):
            title = article.xpath('.//h2[contains(@class,"entry-title")]//text()').get()
            href = article.xpath('.//a[contains(@class,"thumbnail-link")]/@href').get()
            if not title or not href:
                continue
            no_sep_title = _no_sep(title)
            if not any(_match_number(no_sep_title, c) for c in candidates):
                continue
            detail_urls.append(urljoin(search_url, href))
            cover = article.xpath(".//img/@src").get()
            if cover and not ctx.search_cover_url:
                ctx.search_cover_url = urljoin(search_url, cover)
            cat_href = article.xpath(
                './/span[contains(@class,"entry-category")]/a[contains(@href,"/category/")]/@href'
            ).get()
            if cat_href and not ctx.category_path:
                ctx.category_path = category_from_url(cat_href)
        if not detail_urls:
            ctx.debug("JAVFREE 搜索页没有匹配结果")
            return None
        ctx.debug(f"JAVFREE 搜索命中: {detail_urls}")
        return detail_urls

    @override
    async def _parse_detail_page(self, ctx: JavfreeContext, html: Selector, detail_url: str) -> CrawlerData | None:
        raw_title = html.xpath('//h1[contains(@class,"entry-title")]//text()').get()
        if not raw_title:
            raise CrawlerException("数据获取失败: 未获取到标题")
        web_number, title = parse_title(raw_title)

        blockquote = html.xpath('//div[contains(@class,"entry-content")]//blockquote').get() or ""
        fields, outline = parse_metadata_lines(blockquote)

        release_raw = fields.get("発売日", "")
        # FC2 详情页无 blockquote 元数据，改用独立行 販売日/商品ID
        if not release_raw:
            body_text = re.sub(r"<[^>]+>", " ", html.get())
            fc2_release = re.search(r"販売日\s*[：:]\s*(\d{4}/\d{2}/\d{2})", body_text)
            if fc2_release:
                release_raw = fc2_release.group(1)
            fc2_id = re.search(r"商品ID\s*[：:]\s*FC2\s*PPV\s*(\d{5,})", body_text)
            if fc2_id:
                web_number = f"FC2-{fc2_id.group(1)}"
        release = release_raw.replace("/", "-")

        actors_line = fields.get("出演者", "")
        tags_line = fields.get("ジャンル", "")

        thumb = ""
        extrafanart: list[str] = []
        hlic_urls = [urljoin(detail_url, src) for src in html.xpath('//img[contains(@src,"/HLIC/")]/@src').getall()]
        # 站点封面即第一张非去码的 HLIC 图；数字后缀（-N.jpg）为剧照
        thumb = next((u for u in hlic_urls if "-demosaic" not in u.rsplit("/", 1)[-1]), "")
        for url in hlic_urls:
            if url == thumb:
                continue
            if re.search(r"-\d+\.(jpe?g|png)$", url.rsplit("/", 1)[-1], re.I):
                extrafanart.append(url)

        if not ctx.category_path:
            paths = [
                category_from_url(h)
                for h in html.xpath(
                    '//li[contains(@class,"current-post-parent")]//a[contains(@href,"/category/")]/@href'
                ).getall()
            ]
            # 同一条目可能挂多个分类（如去码版），取路径最深的作为主分类
            if paths:
                ctx.category_path = max(set(paths), key=lambda p: p.count("/") + len(p))
        mosaic = classify_mosaic(ctx.category_path)

        number = web_number or (ctx.number_candidates[0] if ctx.number_candidates else "")
        # DMM 高清直链升级（横版+竖版，无码番号内部跳过）
        from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

        if number:
            thumb, upgraded_poster = await upgrade_dmm_cover(ctx, number, thumb, "")
        else:
            upgraded_poster = ""
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=[a.strip() for a in re.split(r"[、\s]", actors_line) if a.strip()],
            all_actors=[a.strip() for a in re.split(r"[、\s]", actors_line) if a.strip()],
            directors=[fields["監督"]] if fields.get("監督") else [],
            extrafanart=extrafanart,
            originalplot=outline,
            outline=outline,
            tags=_dedupe(tags_line.split()),
            release=release,
            year=get_year(release),
            runtime=parse_runtime(fields.get("収録時間", "")),
            series=fields.get("シリーズ", ""),
            studio=fields.get("メーカー", ""),
            publisher=fields.get("レーベル", "") or fields.get("メーカー", ""),
            thumb=thumb,
            poster=upgraded_poster or thumb or ctx.search_cover_url,
            image_download=False,
            mosaic=mosaic,
            external_id=detail_url,
        )
