"""番号 -> MGStage 官方图源直链构造。

MGStage 官方图片托管在 image.mgstage.com，URL 规律:
    https://image.mgstage.com/images/{folder}/{cid}/{num}/pb_e_{cid}-{num}.jpg   (大封面)
    https://image.mgstage.com/images/{folder}/{cid}/{num}/pf_e_{cid}-{num}.jpg   (小封面)

cid = {id}{series}（如 LUXU 系列 cid=259luxu），id/folder 由品牌(series)决定。
系列映射表来自 JavDB 高清图替换油猴脚本的实测数据，与 MgstageCrawler 网页抓取互为补充，
用于站点图源全部失败时的直构兜底（尤其 DMM 不收录的素人番号）。
"""

from __future__ import annotations

import re

_MGSTAGE_IMG_BASE = "https://image.mgstage.com/images"

# series -> (id, folder)
_MGSTAGE_SERIES_MAP: dict[str, tuple[str, str]] = {
    "otim": ("393", "onetime"),
    "chuc": ("201", "firststar"),
    "gerk": ("302", "guerrilla"),
    "luxu": ("259", "luxutv"),
    "onez": ("013", "onemore"),
    "onex": ("013", "onemore"),
    "mfc": ("435", "doc"),
    "ara": ("261", "ara"),
}

_MGSTAGE_HD_MIN_WIDTH = 300


def _parse_mgstage_number(number: str) -> list[tuple[str, str, str]]:
    """返回 [(series, id, folder)]，从番号解析出命中的 MGStage 系列。

    支持 259LUXU-1111（mdcx 素人番号带数字前缀）与 LUXU-1111 两种写法。
    """
    cleaned = (number or "").upper().strip().replace(" ", "")
    if "-" not in cleaned:
        return []
    head, _, raw_num = cleaned.rpartition("-")
    if not raw_num.isdigit():
        return []
    candidates_head = [head.lower()]
    m = re.fullmatch(r"(\d+)([a-z]+)", head.lower())
    if m:
        candidates_head.append(m.group(2))
    results: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for series in candidates_head:
        entry = _MGSTAGE_SERIES_MAP.get(series)
        if entry and entry not in seen:
            seen.add(entry)
            results.append((series, entry[0], entry[1]))
    return results


def _num_variants(raw_num: str) -> list[str]:
    variants = [raw_num]
    stripped = str(int(raw_num))
    if stripped not in variants:
        variants.append(stripped)
    return variants


def _build_mgstage_candidates(number: str, kind: str) -> list[str]:
    urls: list[str] = []
    _, _, raw_num = (number or "").upper().strip().rpartition("-")
    for series, sid, folder in _parse_mgstage_number(number):
        cid = f"{sid}{series}"
        for num in _num_variants(raw_num):
            if kind == "cover":
                url = f"{_MGSTAGE_IMG_BASE}/{folder}/{cid}/{num}/pb_e_{cid}-{num}.jpg"
            else:
                url = f"{_MGSTAGE_IMG_BASE}/{folder}/{cid}/{num}/pf_e_{cid}-{num}.jpg"
            if url not in urls:
                urls.append(url)
    return urls


def build_mgstage_cover_candidates(number: str) -> list[str]:
    """从番号构造 MGStage 大封面（pb_e）候选 URL 列表。"""
    return _build_mgstage_candidates(number, "cover")


def build_mgstage_poster_candidates(number: str) -> list[str]:
    """从番号构造 MGStage 小封面（pf_e）候选 URL 列表。"""
    return _build_mgstage_candidates(number, "poster")


async def find_valid_mgstage_cover(number: str) -> str | None:
    """尝试为番号找到一张可用的 MGStage 横版大图（pb_e）.

    站点图源全部失败时作兜底：按番号直构 MGStage 候选，逐个校验存在且非小图。
    未知系列或无码番号返回 None。
    """
    return await _find_valid_mgstage_image(number, "cover")


async def find_valid_mgstage_poster(number: str) -> str | None:
    """尝试为番号找到一张可用的 MGStage 竖版小图（pf_e）.

    Poster 候选全部失败时作兜底：按番号直构 MGStage 竖版海报候选，
    逐个校验存在且非小图。未知系列或无码番号返回 None。
    """
    return await _find_valid_mgstage_image(number, "poster")


async def _find_valid_mgstage_image(number: str, kind: str) -> str | None:
    from mdcx.base.web import check_url, get_imgsize
    from mdcx.crawlers.dmm_direct import is_uncensored_number

    if not number or is_uncensored_number(number):
        return None
    builders = {"cover": build_mgstage_cover_candidates, "poster": build_mgstage_poster_candidates}
    for url in builders[kind](number):
        if await check_url(url):
            width, _height = await get_imgsize(url)
            if width >= _MGSTAGE_HD_MIN_WIDTH:
                return url
    return None
