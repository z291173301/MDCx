#!/usr/bin/env python3
import re
from typing import override

from lxml import etree
from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CrawlerData, CrawlerException


def _xpath_texts(html, xpath: str) -> list[str]:
    return [text.strip() for text in html.xpath(xpath) if text and text.strip()]


def _xpath_joined_text(html, xpath: str) -> str:
    return ",".join(_xpath_texts(html, xpath)).replace("/", ",").replace(" ", "").replace("\\n", "")


def getTitle(html):
    try:
        return ",".join(_xpath_texts(html, '//*[@id="center_column"]/div[1]/h1/text()')).replace("/", ",")
    except Exception:
        return ""


def getActor(html):
    result = _xpath_joined_text(html, '//th[contains(text(),"出演")]/../td/a/text()')
    if not result:
        result = _xpath_joined_text(html, '//th[contains(text(),"出演")]/../td/text()')
    return result


def getStudio(html):
    return _xpath_joined_text(html, '//th[contains(text(),"メーカー：")]/../td/a/text()') or _xpath_joined_text(
        html, '//th[contains(text(),"メーカー：")]/../td/text()'
    )


def getPublisher(html):
    return _xpath_joined_text(html, '//th[contains(text(),"レーベル：")]/../td/a/text()') or _xpath_joined_text(
        html, '//th[contains(text(),"レーベル：")]/../td/text()'
    )


def getRuntime(html):
    return _xpath_joined_text(html, '//th[contains(text(),"収録時間：")]/../td/a/text()').rstrip(
        "min"
    ) or _xpath_joined_text(html, '//th[contains(text(),"収録時間：")]/../td/text()').rstrip("min")


def getSeries(html):
    return _xpath_joined_text(html, '//th[contains(text(),"シリーズ：")]/../td/a/text()') or _xpath_joined_text(
        html, '//th[contains(text(),"シリーズ：")]/../td/text()'
    )


def getNum(html):
    return _xpath_joined_text(html, '//th[contains(text(),"品番：")]/../td/a/text()') or _xpath_joined_text(
        html, '//th[contains(text(),"品番：")]/../td/text()'
    )


def getYear(getRelease):
    try:
        result = str(re.search(r"\d{4}", getRelease).group())
        return result
    except Exception:
        return getRelease


def getRelease(html):
    return _xpath_joined_text(html, '//th[contains(text(),"配信開始日：")]/../td/a/text()') or _xpath_joined_text(
        html, '//th[contains(text(),"配信開始日：")]/../td/text()'
    )


def getTag(html):
    return _xpath_joined_text(html, '//th[contains(text(),"ジャンル：")]/../td/a/text()') or _xpath_joined_text(
        html, '//th[contains(text(),"ジャンル：")]/../td/text()'
    )


def getCoverSmall(cover_url):
    result = cover_url.replace("/pb_", "/pf_")
    return result


def getCover(html):
    return next(iter(_xpath_texts(html, '//a[@id="EnlargeImage"]/@href')), "")


def getExtraFanart(html):
    extrafanart_list = html.xpath("//dl[@id='sample-photo']/dd/ul/li/a[@class='sample_image']/@href")
    return extrafanart_list


async def get_trailer(client, html):
    trailer = ""
    play_url = html.xpath("//a[@class='review-btn']/@href")
    if play_url:
        play_url = play_url[0].replace("/mypage/review.php", "/sampleplayer/sampleRespons.php")
        htmlcode, error = await client.get_json(play_url, cookies={"adc": "1"})
        if htmlcode is not None:
            url_str = htmlcode.get("url")
            if url_str:
                url_temp = re.search(r"(https.+)ism/request", str(url_str))
                if url_temp:
                    trailer = url_temp.group(1) + "mp4"
    return trailer


def getOutline(html):
    result = next(iter(_xpath_texts(html, '//*[@id="introduction"]/dd/p[1]/text()')), "")
    if not result:
        temp = html.xpath('//*[@id="introduction"]/dd')
        result = temp[0].xpath("string(.)").replace(" ", "").strip() if temp else ""
    return result


def getScore(html):
    result = html.xpath('//td[@class="review"]/span/@class')
    if result:
        result = f"{int(result[0].replace('star_', '')[:2]) / 10:.1f}"
    return str(result)


def remove_number_leading_zero(number: str) -> str:
    if not number:
        return ""
    normalized = number.upper().strip()
    if not (matched := re.fullmatch(r"([A-Z0-9]+)-0+(\d+)", normalized)):
        return normalized
    return f"{matched[1]}-{matched[2]}"


def build_candidate_numbers(number: str, short_number: str) -> list[str]:
    candidates = []
    for each in [
        remove_number_leading_zero(number),
        remove_number_leading_zero(short_number),
        (number or "").upper().strip(),
        (short_number or "").upper().strip(),
    ]:
        if each and each not in candidates:
            candidates.append(each)
    return candidates


class MgstageCrawler(BaseCrawler):
    description = "MGStage 官网（仅能有码+素人）"
    # MGStage 主打素人系列（image.mgstage.com 直链已验证收录）；SSNI 等 S1 番号未收录
    probe_number = "259LUXU-1111"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.MGSTAGE

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.mgstage.com"

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        candidate_numbers = build_candidate_numbers(ctx.input.number.upper(), ctx.input.short_number.upper())
        if len(candidate_numbers) > 1:
            ctx.debug(f"候选番号: {', '.join(candidate_numbers)}")
        return [f"{self.base_url}/product/product_detail/{each}/" for each in candidate_numbers]

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        htmlcode = etree.fromstring(html.get(), etree.HTMLParser())
        web_number = getNum(htmlcode).strip(",")
        title = getTitle(htmlcode).replace("\\n", "").replace("        ", "").strip(",").strip()
        if title and web_number:
            return [search_url]
        ctx.debug("MGStage 候选详情页未获取到 title 或番号")
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        htmlcode = etree.fromstring(html.get(), etree.HTMLParser())
        number = getNum(htmlcode).strip(",") or ctx.input.number
        actor = getActor(htmlcode).replace(" ", "").strip(",")
        actors = [item.strip() for item in actor.split(",") if item.strip()]
        title = getTitle(htmlcode).replace("\\n", "").replace("        ", "").strip(",").strip()
        if not title or not number:
            raise CrawlerException("数据获取失败: 未获取到title或番号！")
        cover_url = getCover(htmlcode)
        release = getRelease(htmlcode).strip(",").replace("/", "-")
        tag = getTag(htmlcode).strip(",")
        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=getOutline(htmlcode).replace("\n", "").strip(","),
            originalplot=getOutline(htmlcode).replace("\n", "").strip(","),
            tags=[item.strip() for item in tag.split(",") if item.strip()],
            release=release,
            year=getYear(release).strip(","),
            runtime=getRuntime(htmlcode).strip(","),
            score=getScore(htmlcode).strip(","),
            series=getSeries(htmlcode).strip(","),
            studio=getStudio(htmlcode).strip(","),
            publisher=getPublisher(htmlcode).strip(","),
            thumb=cover_url,
            poster=getCoverSmall(cover_url),
            extrafanart=getExtraFanart(htmlcode),
            trailer=await get_trailer(self.async_client, htmlcode),
            image_download=True,
            mosaic="有码",
            external_id=detail_url,
        )

    @override
    async def _fetch_search(self, ctx: Context, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        return await self.async_client.get_text(url, cookies={"adc": "1"})

    @override
    async def _fetch_detail(self, ctx: Context, url: str, use_browser: bool | None = False) -> tuple[str | None, str]:
        return await self.async_client.get_text(url, cookies={"adc": "1"})
