"""AVEntertainments 爬虫

站点：aventertainments.com
类型：无码（DVD + PPV）
搜索：
  - PPV 番号（日期格式 YYMMDD_NNN）：/ppv/search → /ppv/detail?pro=ID
  - DVD 番号（字母-数字格式）：/dvd/search → /dvd/detail?pro=ID
"""

import re
from dataclasses import dataclass
from typing import override
from urllib.parse import urlencode

from parsel import Selector

from ..config.models import Website
from ..models.model_types import CrawlerInput
from .base import BaseCrawler, Context, CrawlerData
from .base.parser import get_year


@dataclass
class AventertainmentsContext(Context):
    """AVEntertainments 爬虫上下文"""

    is_ppv: bool = False  # 是否为 PPV 番号
    search_keyword: str = ""  # 搜索关键词


class AventertainmentsCrawler(BaseCrawler[AventertainmentsContext]):
    description = "AVENTERTAINMENTS 无码（DVD+PPV）"
    probe_number = "082226_001"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVENTERTAINMENTS

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.aventertainments.com"

    @override
    def new_context(self, input: CrawlerInput) -> AventertainmentsContext:
        return AventertainmentsContext(input=input)

    @override
    async def _generate_search_url(self, ctx: AventertainmentsContext) -> list[str] | str | None:
        number = ctx.input.number
        if not number:
            ctx.debug("番号为空")
            return None

        # 判断番号类型：日期格式 → PPV，其他 → DVD
        ctx.is_ppv = bool(re.match(r"^\d{6}[-_]?\d{1,3}$", number))
        ctx.search_keyword = number

        if ctx.is_ppv:
            search_url = f"{self.base_url}/ppv/search?{urlencode({'lang': '2', 'v': '1', 'culture': 'ja-JP', 'keyword': number})}"
            ctx.debug(f"PPV 搜索: {number}")
        else:
            search_url = f"{self.base_url}/dvd/search?{urlencode({'lang': '2', 'cat': '29', 'culture': 'ja-JP', 'keyword': number})}"
            ctx.debug(f"DVD 搜索: {number}")

        return search_url

    @override
    async def _parse_search_page(
        self, ctx: AventertainmentsContext, html: Selector, search_url: str
    ) -> list[str] | str | None:
        # 提取所有 pro= ID
        pro_ids = re.findall(r"pro=(\d+)", html.get())
        if not pro_ids:
            ctx.debug("搜索页未找到 pro ID")
            return None

        # 去重并构造详情页 URL
        unique_ids = list(dict.fromkeys(pro_ids))  # 保持顺序去重
        ctx.debug(f"找到 {len(unique_ids)} 个 pro ID")

        detail_urls = []
        for pro_id in unique_ids:
            if ctx.is_ppv:
                url = f"{self.base_url}/ppv/detail?{urlencode({'pro': pro_id, 'lang': '2', 'culture': 'ja-JP', 'v': '1'})}"
            else:
                url = f"{self.base_url}/dvd/detail?{urlencode({'pro': pro_id, 'lang': '2', 'cat': '29'})}"
            detail_urls.append(url)

        return detail_urls

    @override
    async def _parse_detail_page(
        self, ctx: AventertainmentsContext, html: Selector, detail_url: str
    ) -> CrawlerData | None:
        # 1. 番号（tag-title）
        raw_cid = html.xpath('//span[@class="tag-title"]/text()').get()
        if not raw_cid:
            ctx.debug("详情页未找到番号")
            return None

        raw_cid = raw_cid.strip()
        # 去除 DL 前缀（下载版标记）
        cid = re.sub(r"^DL", "", raw_cid, flags=re.IGNORECASE)
        ctx.debug(f"详情页番号: {cid}")

        # 验证番号匹配（考虑分隔符差异）
        if not self._match_number(ctx.search_keyword, cid):
            ctx.debug(f"番号不匹配: 搜索={ctx.search_keyword}, 详情={cid}")
            return None

        # 2. 标题
        title = html.xpath('//h1[@class="mb-10"]/text()').get()
        if not title:
            title = html.xpath("//h1/text()").get()
        if not title:
            title = html.xpath('//meta[@property="og:title"]/@content').get()
        title = (title or "").strip()

        # 3. 演员
        actresses = html.xpath('//a[contains(@href, "idol")]//text()').getall()
        actors = list(dict.fromkeys([a.strip() for a in actresses if a.strip()]))

        # 4. 简介
        plot_parts = html.xpath('//div[@class="product-description mt-20"]//text()').getall()
        outline = " ".join(plot_parts).strip()

        # 5. 标签/分类
        tags = html.xpath('//div[@class="value-category"]//a/text()').getall()
        tags = [t.strip() for t in tags if t.strip()]

        # 6. 系列
        series = ""
        series_link = html.xpath('//a[contains(@href, "series=")]/@href').get()
        if series_link:
            series_name = html.xpath('//a[contains(@href, "series=")]/text()').get()
            if series_name:
                series = series_name.strip()

        # 7. 发行日期
        release = ""
        release_raw = html.xpath(
            '//strong[contains(text(), "配信開始日") or contains(text(), "発売日")]/following-sibling::text()'
        ).get()
        if not release_raw:
            # 尝试从整段文本提取
            body_text = " ".join(html.xpath('//div[@class="product-info-detail"]//text()').getall())
            date_match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", body_text)
            if date_match:
                y, m, d = date_match.groups()
                release = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        elif release_raw:
            date_match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", release_raw)
            if date_match:
                y, m, d = date_match.groups()
                release = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

        # 8. 时长
        runtime = ""
        runtime_raw = html.xpath('//strong[contains(text(), "収録時間")]/following-sibling::text()').get()
        if runtime_raw:
            runtime_match = re.search(r"(\d+)", runtime_raw)
            if runtime_match:
                runtime = runtime_match.group(1)

        # 9. 封面
        cover = html.xpath('//img[contains(@src, "vodimages")]/@src').get()
        thumb = ""
        if cover:
            if cover.startswith("//"):
                thumb = "https:" + cover
            elif not cover.startswith("http"):
                thumb = self.base_url + cover
            else:
                thumb = cover

        # 10. 厂牌/制作商
        studio = ""
        studio_elem = html.xpath('//a[contains(@href, "studio=")]/text()').get()
        if studio_elem:
            studio = studio_elem.strip()

        return CrawlerData(
            number=cid,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            directors=[],
            extrafanart=[],
            originalplot=outline,
            outline=outline,
            tags=tags,
            release=release,
            year=get_year(release),
            runtime=runtime,
            series=series,
            studio=studio,
            publisher=studio,
            thumb=thumb,
            poster=thumb,
            image_download=False,
            mosaic="无码",
            external_id=detail_url,
        )

    def _match_number(self, search: str, detail: str) -> bool:
        """番号匹配验证（考虑分隔符差异）"""
        search_norm = search.lower()
        detail_norm = detail.lower()

        # 精确匹配（保留分隔符）
        if search_norm in detail_norm:
            return True

        # 模糊匹配（只比数字）
        search_digits = re.sub(r"[^0-9]", "", search)
        detail_digits = re.sub(r"[^0-9]", "", detail)

        if search_digits and search_digits in detail_digits:
            return True

        return False
