"""
演员作品数据源：为「检查演员缺失番号」提供按演员拉取全部番号的能力。

支持四类数据源（有码/无码/欧美/国产），每类有主源 + 兜底源：

  有码: libredmm(xlsx href → fuzzy 搜索) → javbus searchstar 兜底
  无码: avsox(getFilterMovies) → javbus uncensored searchstar 兜底
  欧美: avheat(getFilterMovies)
  国产: iqqtv(search.php?s_type=actor 演员页 num 分页)

javbus 使用 12 镜像轮询（与 JavbusCrawler 一致），不写死单域名。
"""

import json
import re
from urllib.parse import quote

from lxml import etree

from ..base.web import get_aio_domain
from ..config.manager import manager
from ..config.resources import resources
from ..signals import signal
from ..utils.domain_rotate import DomainRotator

_LIBREDMM = "https://www.libredmm.com"
_IQQTV_DOMAINS = ["https://iqq5.xyz", "https://iqqk4.quest"]
_JAVBUS_DOMAINS = [
    "https://www.dmmsee.cyou",
    "https://www.busjav.bond",
    "https://www.cdnbus.bond",
    "https://www.seejav.cyou",
    "https://www.buscdn.bond",
    "https://www.javsee.cyou",
    "https://www.fanbus.bond",
    "https://www.busdmm.bond",
    "https://www.cdnbus.cyou",
    "https://www.dmmbus.bond",
    "https://www.javbus.bond",
    "https://www.javbus.com",
]
_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6"}


def _log(msg: str) -> None:
    signal.show_log_text(msg)


# ---------------------------------------------------------------------------
# javbus 镜像轮询封装
# ---------------------------------------------------------------------------


class _JavbusRotator:
    """javbus 12 镜像轮询，连接失败自动切下一个域名。"""

    def __init__(self) -> None:
        custom = manager.config.get_site_url(  # type: ignore[attr-defined]
            __import__("mdcx.config.enums", fromlist=["Website"]).Website.JAVBUS, ""
        )
        self._rotator = DomainRotator(_JAVBUS_DOMAINS, custom_url=custom)

    @property
    def base(self) -> str:
        return self._rotator.current

    async def get_text(self, url: str) -> str | None:
        """带镜像轮询的 GET 请求，连接级失败切镜像，返回 HTML 或 None。"""
        for _ in range(len(self._rotator.domains)):
            async with manager.acquire_computed() as computed:
                html, error = await computed.async_client.get_text(url, headers=_HEADERS)
            if html is not None:
                return html
            # 404 是业务级错误（演员不存在），不轮询
            if "404" in str(error):
                return None
            # 连接级失败：切镜像
            self._rotator.rotate()
            url = self._rotator.rebuild_url(url)
            _log(f"   javbus 镜像请求失败，切换: {self._rotator.current} ({error})")
        return None


# ---------------------------------------------------------------------------
# 番号归一化
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 有码：libredmm → javbus 兜底
# ---------------------------------------------------------------------------


async def fetch_censored(name: str, rotator: _JavbusRotator) -> set[str] | None:
    """有码演员番号：libredmm(xlsx href → fuzzy) → javbus 兜底。"""
    # 1. libredmm: xlsx href
    href = resources.get_actor_data(name).get("href") or ""
    if href and "libredmm.com" in href:
        nums = await _libredmm_fetch_numbers(href)
        if nums:
            _log(f"   [libredmm] {name} 找到 {len(nums)} 部 (xlsx href)")
            return nums

    # 2. libredmm: fuzzy 搜索
    rel = await _libredmm_fuzzy_search(name)
    if rel:
        nums = await _libredmm_fetch_numbers(rel)
        if nums:
            _log(f"   [libredmm] {name} 找到 {len(nums)} 部 (fuzzy 搜索)")
            return nums

    # 3. javbus 兜底
    star_url = await _javbus_searchstar(rotator, name, uncensored=False)
    if star_url:
        nums = await _javbus_star_numbers(rotator, star_url)
        if nums:
            _log(f"   [javbus] {name} 找到 {len(nums)} 部 (兜底)")
            return nums

    _log(f"   {name} 未在任一有码数据源找到")
    return None


async def _libredmm_fuzzy_search(name: str) -> str | None:
    """libredmm 演员模糊搜索，返回相对路径 /actresses/{id} 或 None。"""
    url = f"{_LIBREDMM}/actresses?order=New&fuzzy={quote(name)}&commit=Filter+by+name"
    async with manager.acquire_computed() as computed:
        html, error = await computed.async_client.get_text(url, headers=_HEADERS)
    if not html:
        return None
    root = etree.fromstring(html, etree.HTMLParser())
    anchors = root.xpath('//a[contains(@href,"/actresses/")]')
    # 逐 <a> 成对取 href 与完整文本，避免跨 xpath 的 links/names zip 数量不等导致错位配对
    for a in anchors:
        link = str(a.get("href") or "")
        nm = "".join(a.xpath(".//text()")).strip()
        if nm == name or name in nm or nm in name:
            return link
    return str(anchors[0].get("href") or "") if anchors else None


async def _libredmm_fetch_numbers(rel_or_url: str) -> set[str]:
    """拉取 libredmm 演员页全部作品番号，支持分页。"""
    href = rel_or_url if rel_or_url.startswith("http") else f"{_LIBREDMM}{rel_or_url}"
    all_nums: set[str] = set()
    page = 1
    while True:
        url = href if page == 1 else f"{href}?page={page}"
        async with manager.acquire_computed() as computed:
            html, error = await computed.async_client.get_text(url, headers=_HEADERS)
        if not html:
            break
        root = etree.fromstring(html, etree.HTMLParser())
        movies = root.xpath('//a[contains(@href,"/movies/")]/@href')
        for m in movies:
            num = m.split("/movies/")[-1]
            if num:
                all_nums.add(num)
        next_p = root.xpath('//a[contains(@href,"?page=")]/text()')
        joined = "".join(next_p)
        has_next = "Next" in joined or "下一頁" in joined or "下一页" in joined
        if not has_next or len(movies) < 60:
            break
        page += 1
        if page > 60:
            break
    return all_nums


# ---------------------------------------------------------------------------
# 无码：avsox → javbus 兜底
# ---------------------------------------------------------------------------


async def fetch_uncensored(name: str, rotator: _JavbusRotator) -> set[str] | None:
    """无码演员番号：avsox(getFilterMovies) → javbus uncensored 兜底。"""
    # 1. avsox
    nums = await _avmoo_fetch_numbers("avsox", "javu", name)
    if nums:
        _log(f"   [avsox] {name} 找到 {len(nums)} 部")
        return nums

    # 2. javbus uncensored 兜底
    star_url = await _javbus_searchstar(rotator, name, uncensored=True)
    if star_url:
        nums = await _javbus_star_numbers(rotator, star_url)
        if nums:
            _log(f"   [javbus] {name} 找到 {len(nums)} 部 (无码兜底)")
            return nums

    _log(f"   {name} 未在任一无码数据源找到")
    return None


# ---------------------------------------------------------------------------
# 欧美：avheat
# ---------------------------------------------------------------------------


async def fetch_western(name: str, rotator: _JavbusRotator) -> set[str] | None:
    """欧美演员番号：avheat(getFilterMovies)。"""
    nums = await _avmoo_fetch_numbers("avheat", "wav", name)
    if nums:
        _log(f"   [avheat] {name} 找到 {len(nums)} 部")
        return nums
    _log(f"   {name} 未在 avheat 找到")
    return None


# ---------------------------------------------------------------------------
# avmoo 系通用（avsox/avheat）：搜索影片定位 starId → getFilterMovies
# ---------------------------------------------------------------------------


async def _avmoo_fetch_numbers(domain_site: str, namespace: str, name: str) -> set[str]:
    """avmoo 系站点：搜索演员名 → 从影片 star 拿 starId → getFilterMovies 全部分页。"""
    try:
        base = await get_aio_domain(domain_site)
    except Exception:
        base = f"https://{domain_site}.shop"
    all_nums: set[str] = set()
    star_id = await _avmoo_locate_star_id(base, namespace, name)
    if not star_id:
        return all_nums
    page = 1
    while True:
        async with manager.acquire_computed() as computed:
            json_data, error = await computed.async_client.post_json(
                f"{base}/{namespace}/data/api/getFilterMovies",
                data=json.dumps(["star", star_id, "cn", 60, page]),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        if error or json_data is None:
            break
        arr = json_data.get("data") or []
        if not isinstance(arr, list):
            break
        for m in arr:
            num = m.get("movieFanHao")
            if num:
                all_nums.add(num)
        if len(arr) < 60:
            break
        page += 1
        if page > 30:
            break
    return all_nums


async def _avmoo_locate_star_id(base: str, namespace: str, name: str) -> str | None:
    """通过搜索演员名 → 影片详情 → star 字段定位 starId。"""
    for _ in range(3):
        async with manager.acquire_computed() as computed:
            json_data, error = await computed.async_client.post_json(
                f"{base}/{namespace}/data/api/search",
                data=json.dumps([{"search": name, "lang": "cn"}, 20, 1]),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
        if error or json_data is None:
            continue
        items = json_data.get("data") or []
        for it in items[:8]:
            mid = it.get("movieId")
            if not mid:
                continue
            async with manager.acquire_computed() as computed:
                detail, derr = await computed.async_client.post_json(
                    f"{base}/{namespace}/data/api/getMovie",
                    data=json.dumps({"movieId": mid}),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
            if derr or detail is None:
                continue
            stars = (detail.get("data") or {}).get("star") or []
            for st in stars:
                sn = (st.get("starName_ja") or st.get("starName_en") or "").strip()
                if sn and (sn == name or name in sn or sn in name):
                    return st.get("starId")
        # 无匹配：继续下一次 attempt（原实现在此 return None，使重试只对网络错误生效）
    return None


# ---------------------------------------------------------------------------
# 国产：iqqtv
# ---------------------------------------------------------------------------

_IQQTV_NUMBER_PAT = re.compile(
    r"([A-Z]{2,8}[-]?\d{2,6}[A-Z]?(?:-\d+)?|1pondo[-_]?\d+[-_]?\d+|caribbeancom[-_]?\d+[-_]?\d+|10musume[-_]?\d+[-_]?\d+|pacopacomama[-_]?\d+[-_]?\d+|heyzo[-_]?\d+|heydouga[-_]?\d+[-_]?\d+)"
)


async def fetch_guochan(name: str, rotator: _JavbusRotator) -> set[str] | None:
    """国产演员番号：iqqtv 搜索演员 → num 分页 → title 提取番号。"""
    tid = await _iqqtv_search_actor(name)
    if not tid:
        _log(f"   {name} 未在 iqqtv 找到")
        return None
    all_nums: set[str] = set()
    page = 1
    while True:
        html = await _iqqtv_get_page(tid, page)
        if not html:
            break
        root = etree.fromstring(html, etree.HTMLParser())
        titles = root.xpath('//a[contains(@href,"player.php")]//@title')
        for t in titles:
            nums = _IQQTV_NUMBER_PAT.findall(t)
            for n in nums:
                all_nums.add(n.upper())
        # iqqtv 每页约 48 个作品
        cards = root.xpath('//a[contains(@href,"player.php")]/@href')
        if len(cards) < 48:
            break
        page += 1
        if page > 30:
            break
    if all_nums:
        _log(f"   [iqqtv] {name} 找到 {len(all_nums)} 部")
    return all_nums if all_nums else None


async def _iqqtv_search_actor(name: str) -> str | None:
    """iqqtv 搜索演员名，返回匹配的 s_tid。"""
    for base in _IQQTV_DOMAINS:
        url = f"{base}/cn/search.php?kw={quote(name)}"
        async with manager.acquire_computed() as computed:
            html, error = await computed.async_client.get_text(url, headers=_HEADERS)
        if not html:
            continue
        root = etree.fromstring(html, etree.HTMLParser())
        for a in root.xpath("//a[contains(@href,'s_type=actor')]"):
            nm = "".join(a.xpath(".//text()")).strip()
            if not nm or "すべて" in nm or "全部" in nm or "表示" in nm:
                continue
            if nm == name or name in nm or nm in name:
                return a.get("href", "").split("s_tid=")[-1].split("&")[0]
        # 首个域名成功但未匹配，不再试第二个
        return None
    return None


async def _iqqtv_get_page(tid: str, page: int) -> str | None:
    """iqqtv 演员作品分页，使用 num 参数。"""
    for base in _IQQTV_DOMAINS:
        url = f"{base}/cn/search.php?s_type=actor&s_tid={tid}&num={page}"
        async with manager.acquire_computed() as computed:
            html, error = await computed.async_client.get_text(url, headers=_HEADERS)
        if html:
            return html
    return None


# ---------------------------------------------------------------------------
# javbus 通用：searchstar 定位 + star 页拉番号
# ---------------------------------------------------------------------------


async def _javbus_searchstar(rotator: _JavbusRotator, name: str, uncensored: bool) -> str | None:
    """javbus 按演员名搜索，返回 star 页 URL 或 None。"""
    prefix = "/uncensored" if uncensored else ""
    url = f"{rotator.base}{prefix}/searchstar/{quote(name)}"
    html = await rotator.get_text(url)
    if not html:
        return None
    root = etree.fromstring(html, etree.HTMLParser())
    all_hrefs = root.xpath("//a[contains(@href,'/star/')]/@href")
    star_hrefs: list[str] = []
    for href in all_hrefs:
        if "/searchstar/" in href:
            continue
        if uncensored:
            if "/uncensored/star/" in href:
                star_hrefs.append(href)
        else:
            if "/uncensored/" not in href:
                star_hrefs.append(href)
    if star_hrefs:
        href = star_hrefs[0]
        # 页面返回的 href 可能是根相对路径（/star/xxx），补全为绝对 URL 供后续请求
        return href if href.startswith("http") else f"{rotator.base}{href}"
    return None


async def _javbus_star_numbers(rotator: _JavbusRotator, star_url: str) -> set[str]:
    """javbus 演员页分页拉全部番号（每页 30 个，番号在 date 标签）。"""
    all_nums: set[str] = set()
    page = 1
    while True:
        url = star_url if page == 1 else f"{star_url}/{page}"
        html = await rotator.get_text(url)
        if not html:
            break
        root = etree.fromstring(html, etree.HTMLParser())
        boxes = root.xpath('//a[@class="movie-box"]')
        nums = [b.xpath(".//date/text()")[0] for b in boxes if b.xpath(".//date/text()")]
        all_nums |= set(nums)
        next_p = root.xpath(
            '//a[contains(text(),"下一頁") or contains(text(),"下一页") or contains(text(),"Next")]/@href'
        )
        if not next_p or len(nums) < 30:
            break
        page += 1
        if page > 60:
            break
    return all_nums
