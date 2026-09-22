# ruff: noqa: E402
import argparse
import asyncio
import re
import sys
import warnings
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import aiofiles.os

from mdcx.base.web import download_file_with_filepath
from mdcx.config.enums import DownloadableFile, FixedScrapingType, HDPicSource, Website
from mdcx.config.manager import manager
from mdcx.core.file import get_file_info_v2, get_output_name
from mdcx.core.file_crawler import FileScraper, classify_scrape_task
from mdcx.core.image import add_mark, cut_thumb_to_poster
from mdcx.core.mosaic import is_censored_mosaic
from mdcx.core.web import poster_download
from mdcx.crawler import CrawlerProvider
from mdcx.models.enums import FileMode
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.model_types import CrawlersResult, FileInfo, OtherInfo
from mdcx.number import get_file_number, get_number_letters
from mdcx.utils.file import check_pic_async, copy_file_async, delete_file_async, move_file_async


@dataclass
class BackfillResult:
    number: str
    source: str
    scraping_type: FixedScrapingType
    mosaic: str
    folder: Path
    thumb_path: Path | None
    poster_path: Path | None


@dataclass(frozen=True)
class BackfillInput:
    raw: str
    number: str
    source_file: Path | None


def safe_print(message: Any = "") -> None:
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)


def _safe_basename(value: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n]+', "-", value).strip(" .")
    return name or "MDCx"


async def resolve_backfill_input(raw_value: str, source_file: Path | None = None) -> BackfillInput:
    raw = raw_value.strip().strip('"')
    if not raw:
        raise ValueError("input is empty")

    inferred_source = source_file
    raw_path = Path(raw)
    if inferred_source is None and raw_path.is_file():
        inferred_source = raw_path

    info_path = inferred_source if inferred_source is not None else raw_path
    info = await get_file_info_v2(info_path, copy_sub=False)
    raw_number = get_file_number(raw_path.name or raw, manager.computed.escape_string_list)
    number = raw_number or info.number or get_file_number(str(info_path), manager.computed.escape_string_list) or raw
    return BackfillInput(raw=raw, number=number, source_file=inferred_source)


def _dedupe_candidates(candidates: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for source, url in candidates:
        url = str(url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append((str(source or "image"), url))
    return deduped


async def _download_first_image(
    candidates: Iterable[tuple[str, str]],
    final_path: Path,
    folder_path: Path,
    *,
    label: str,
    overwrite: bool,
) -> tuple[bool, str]:
    if await aiofiles.os.path.exists(final_path):
        if not overwrite:
            safe_print(f"  {label}: exists, skip -> {final_path}")
            return True, "old"
        await delete_file_async(final_path)

    final_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = final_path.with_suffix(".[DOWNLOAD].jpg")
    if await aiofiles.os.path.exists(temp_path):
        await delete_file_async(temp_path)

    for source, url in _dedupe_candidates(candidates):
        safe_print(f"  {label}: download {source} -> {url}")
        if not await download_file_with_filepath(url, temp_path, folder_path):
            continue
        if await check_pic_async(temp_path):
            await move_file_async(temp_path, final_path)
            return True, source
        await delete_file_async(temp_path)

    safe_print(f"  {label}: failed")
    return False, ""


@contextmanager
def _cover_download_config():
    original_download_files = list(manager.config.download_files)
    original_hd_pics = list(manager.config.download_hd_pics)
    merged = list(
        dict.fromkeys(
            [
                *original_download_files,
                DownloadableFile.THUMB,
                DownloadableFile.POSTER,
                DownloadableFile.POSTER_AUTO_BEST,
            ]
        )
    )
    hd_pics = list(dict.fromkeys([*original_hd_pics, HDPicSource.AMAZON]))
    manager.config.download_files = merged
    manager.config.download_hd_pics = hd_pics
    try:
        yield
    finally:
        manager.config.download_files = original_download_files
        manager.config.download_hd_pics = original_hd_pics


@contextmanager
def _fast_cover_scrape_config():
    original_scrape_like = manager.config.scrape_like
    original_timeout = manager.config.timeout
    original_retry = manager.config.retry
    manager.config.scrape_like = "speed"
    manager.config.timeout = min(int(original_timeout or 10), 8)
    manager.config.retry = min(int(original_retry or 5), 1)
    try:
        yield
    finally:
        manager.config.scrape_like = original_scrape_like
        manager.config.timeout = original_timeout
        manager.config.retry = original_retry


async def _build_file_info(raw_value: str, number: str, output_dir: Path, source_file: Path | None) -> FileInfo:
    raw_path = source_file if source_file is not None else Path(raw_value)
    info = await get_file_info_v2(raw_path, copy_sub=False)
    info.number = number
    info.letters = get_number_letters(number)

    raw_name = raw_path.name or f"{_safe_basename(number)}.mp4"
    output_file_path = output_dir / raw_name
    info.file_path = output_file_path
    info.folder_path = output_dir
    info.file_name = info.file_name or Path(raw_name).stem or _safe_basename(number)
    info.file_ex = info.file_ex or Path(raw_name).suffix or ".mp4"
    info.file_show_name = info.file_show_name or number
    info.file_show_path = output_file_path
    return info


def _website_value(site: Website | str) -> str:
    return site.value if isinstance(site, Website) else str(site)


def _is_usable_dmm_portrait(size: tuple[int, int]) -> bool:
    width, height = size
    return width >= 500 and height > width


def _is_usable_dmm_landscape(size: tuple[int, int]) -> bool:
    width, height = size
    return width > height and width >= 1000


async def _try_dmm_direct_backfill(number: str, output_dir: Path, *, overwrite: bool) -> BackfillResult | None:
    from mdcx.core.image import cut_thumb_to_poster
    from mdcx.crawlers.dmm_direct import generate_image_candidates
    from mdcx.models.model_types import CrawlersResult

    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / _safe_basename(number)
    poster_target = base.with_name(base.name + "-poster.jpg")
    thumb_target = base.with_name(base.name + "-thumb.jpg")

    if not overwrite and await aiofiles.os.path.exists(poster_target) and await aiofiles.os.path.exists(thumb_target):
        safe_print("  dmm_direct: 封面已存在，跳过")
        return BackfillResult(
            number=number,
            source="dmm_direct",
            scraping_type=FixedScrapingType.AUTO,
            mosaic="",
            folder=output_dir,
            thumb_path=thumb_target,
            poster_path=poster_target,
        )

    candidates = list(generate_image_candidates(number))
    if not candidates:
        return None
    portrait_urls = [url for orient, url in candidates if orient == "portrait"]
    landscape_urls = [url for orient, url in candidates if orient == "landscape"]
    safe_print(f"DMM 官方直链候选: {len(candidates)} 个 URL (竖版 {len(portrait_urls)} / 横版 {len(landscape_urls)})")

    temp_path = poster_target.with_suffix(".[DMM].jpg")

    # 阶段一：优先竖版高清 ps（存在则直接作 poster，thumb 优先横版 pl）
    for url in portrait_urls:
        if await aiofiles.os.path.exists(temp_path):
            await delete_file_async(temp_path)
        safe_print(f"  dmm_direct: 尝试竖版 {url}")
        if not await download_file_with_filepath(url, temp_path, output_dir):
            continue
        size = await check_pic_async(temp_path)
        if not size or not _is_usable_dmm_portrait(size):
            safe_print(f"  dmm_direct: 竖版图无效或过小 {size}，跳过")
            await delete_file_async(temp_path)
            continue
        await move_file_async(temp_path, poster_target)
        thumb_saved = False
        for lurl in landscape_urls:
            if await aiofiles.os.path.exists(temp_path):
                await delete_file_async(temp_path)
            if not await download_file_with_filepath(lurl, temp_path, output_dir):
                continue
            lsize = await check_pic_async(temp_path)
            if not lsize or not _is_usable_dmm_landscape(lsize):
                await delete_file_async(temp_path)
                continue
            await move_file_async(temp_path, thumb_target)
            thumb_saved = True
            break
        if not thumb_saved:
            await copy_file_async(poster_target, thumb_target)
        safe_print(f"  dmm_direct: 竖版下载成功 {size} -> {poster_target}")
        return BackfillResult(
            number=number,
            source="dmm_direct",
            scraping_type=FixedScrapingType.AUTO,
            mosaic="",
            folder=output_dir,
            thumb_path=thumb_target,
            poster_path=poster_target,
        )

    # 阶段二：竖版全部失败，用横版 pl 作 thumb，poster 走 mdcx 裁剪逻辑
    for url in landscape_urls:
        if await aiofiles.os.path.exists(temp_path):
            await delete_file_async(temp_path)
        safe_print(f"  dmm_direct: 尝试横版 {url}")
        if not await download_file_with_filepath(url, temp_path, output_dir):
            continue
        size = await check_pic_async(temp_path)
        if not size or not _is_usable_dmm_landscape(size):
            safe_print(f"  dmm_direct: 横版图无效或过小 {size}，跳过")
            await delete_file_async(temp_path)
            continue
        await move_file_async(temp_path, thumb_target)
        result = CrawlersResult.empty()
        temp_cut = poster_target.with_suffix(".[CUT].jpg")
        if await aiofiles.os.path.exists(temp_cut):
            await delete_file_async(temp_cut)
        cut_ok = await asyncio.to_thread(
            cut_thumb_to_poster, result, thumb_target, temp_cut, result.scraping_type, safe_print
        )
        if cut_ok and await aiofiles.os.path.exists(temp_cut):
            await move_file_async(temp_cut, poster_target)
            safe_print(f"  dmm_direct: 横版 {size} 裁剪竖版成功 -> {poster_target}")
        else:
            safe_print("  dmm_direct: 横版裁剪失败，直接复制横版作 poster")
            await copy_file_async(thumb_target, poster_target)
        return BackfillResult(
            number=number,
            source="dmm_direct",
            scraping_type=FixedScrapingType.AUTO,
            mosaic="",
            folder=output_dir,
            thumb_path=thumb_target,
            poster_path=poster_target,
        )

    safe_print("  dmm_direct: 所有候选均失败")
    return None


def _cover_candidate_sites(file_info: FileInfo, forced_site: str | None) -> list[str]:
    if forced_site:
        return [forced_site]

    classification = classify_scrape_task(file_info.crawl_task(), manager.config)
    if classification.website:
        return [_website_value(classification.website)]

    sites = [_website_value(site) for site in classification.sites or []]
    priority = [Website.OFFICIAL.value, Website.MGSTAGE.value, Website.MISSAV.value]
    ordered = [site for site in priority if site in sites]
    ordered.extend(site for site in sites if site not in ordered)
    return ordered


async def _crawl_number(file_info: FileInfo, *, site: str, timeout: float | None) -> CrawlersResult:
    task = file_info.crawl_task()
    task.website_name = site

    async def run_crawler() -> CrawlersResult | None:
        async with manager.acquire_computed() as computed:
            provider = CrawlerProvider(manager.config, computed.async_client, config_getter=lambda: manager.config)
            try:
                scraper = FileScraper(manager.config, provider)
                return await scraper.run(task, FileMode.Again)
            finally:
                await provider.close()

    with _fast_cover_scrape_config():
        try:
            result = await asyncio.wait_for(run_crawler(), timeout=timeout) if timeout else await run_crawler()
        except TimeoutError as exc:
            raise TimeoutError(f"{file_info.number}: scraping timed out after {timeout:.0f}s") from exc

    if result is None:
        raise RuntimeError(f"no crawler result for {file_info.number}")
    return result


async def _download_uncropped_poster(
    result: CrawlersResult,
    other: OtherInfo,
    poster_final_path: Path,
    thumb_final_path: Path,
    folder_new_path: Path,
    *,
    overwrite: bool,
) -> bool:
    if await aiofiles.os.path.exists(poster_final_path):
        if not overwrite:
            other.poster_path = poster_final_path
            safe_print(f"  poster: exists, skip -> {poster_final_path}")
            return True
        await delete_file_async(poster_final_path)

    candidates = [(result.poster_from or "poster", result.poster)]
    candidates.extend((source, url) for source, url, _image_download in result.poster_list)
    ok, source = await _download_first_image(
        candidates,
        poster_final_path,
        folder_new_path,
        label="poster",
        overwrite=overwrite,
    )
    if ok:
        other.poster_path = poster_final_path
        other.poster_marked = False
        result.poster_from = source
        return True

    if other.thumb_path and await aiofiles.os.path.exists(thumb_final_path):
        safe_print("  poster: no direct poster, copy thumb without crop")
        await copy_file_async(thumb_final_path, poster_final_path)
        if await check_pic_async(poster_final_path):
            other.poster_path = poster_final_path
            other.poster_marked = other.thumb_marked
            result.poster_from = "copy thumb"
            return True

    return False


async def _download_censored_poster(
    result: CrawlersResult,
    other: OtherInfo,
    file_info: FileInfo,
    poster_final_path: Path,
    folder_new_path: Path,
    *,
    overwrite: bool,
) -> bool:
    if await aiofiles.os.path.exists(poster_final_path):
        if not overwrite:
            other.poster_path = poster_final_path
            safe_print(f"  poster: exists, skip -> {poster_final_path}")
            return True
        await delete_file_async(poster_final_path)

    with _cover_download_config():
        return await poster_download(result, other, file_info.cd_part, folder_new_path, poster_final_path)


async def _add_watermark(file_info: FileInfo, result: CrawlersResult, other: OtherInfo, *, enabled: bool) -> None:
    if not enabled:
        return
    with _cover_download_config():
        await add_mark(other, file_info, result.mosaic)


async def backfill_cover(
    item: str,
    *,
    output_dir: Path,
    source_file: Path | None = None,
    site: str | None = None,
    overwrite: bool = False,
    watermark: bool = True,
    crawl_timeout: float | None = 90,
) -> BackfillResult:
    LogBuffer.clear_task()
    safe_print("=" * 72)
    safe_print(f"开始处理: {item}")
    backfill_input = await resolve_backfill_input(item, source_file)
    number = backfill_input.number
    safe_print(f"解析番号: {number}")

    output_dir.mkdir(parents=True, exist_ok=True)
    file_info = await _build_file_info(backfill_input.raw, number, output_dir, backfill_input.source_file)
    if site:
        file_info.website_name = site
    timeout_text = f"{crawl_timeout:.0f}s" if crawl_timeout else "不限时"
    candidate_sites = _cover_candidate_sites(file_info, site)
    if not candidate_sites:
        raise RuntimeError(f"{number}: no candidate crawler sites")
    safe_print(f"候选站点: {' -> '.join(candidate_sites)}")

    result: CrawlersResult | None = None
    last_error: Exception | None = None
    for candidate_site in candidate_sites:
        safe_print(f"搜索元数据: {number} @ {candidate_site} (最多 {timeout_text})")
        try:
            result = await _crawl_number(file_info, site=candidate_site, timeout=crawl_timeout)
            break
        except Exception as exc:
            last_error = exc
            safe_print(f"  跳过 {candidate_site}: {exc}")

    if result is None:
        safe_print("所有爬虫站点失败，尝试 DMM 官方高清直链兜底...")
        direct_result = await _try_dmm_direct_backfill(number, output_dir, overwrite=overwrite)
        if direct_result is not None:
            return direct_result
        raise RuntimeError(f"{number}: no crawler result. last error: {last_error}")
    safe_print(f"搜索完成: {result.title or '(no title)'}")

    if file_info.mosaic and not result.mosaic:
        result.mosaic = file_info.mosaic

    (
        folder_new_path,
        _file_new_path,
        _nfo_new_path,
        _poster_new_path_with_filename,
        _thumb_new_path_with_filename,
        _fanart_new_path_with_filename,
        _naming_rule,
        poster_final_path,
        thumb_final_path,
        _fanart_final_path,
    ) = get_output_name(file_info, result, output_dir, file_info.file_ex or ".mp4")
    folder_new_path.mkdir(parents=True, exist_ok=True)

    safe_print("=" * 72)
    safe_print(f"{number}: {result.title or '(no title)'}")
    safe_print(f"  type: {result.scraping_type.value}, mosaic: {result.mosaic or '(empty)'}")
    safe_print(f"  folder: {folder_new_path}")

    other = OtherInfo.empty()
    other.thumb_marked = False
    other.poster_marked = False

    thumb_candidates = [(result.thumb_from or "thumb", result.thumb), *result.thumb_list]
    thumb_ok, thumb_source = await _download_first_image(
        thumb_candidates,
        thumb_final_path,
        folder_new_path,
        label="thumb",
        overwrite=overwrite,
    )
    if thumb_ok:
        other.thumb_path = thumb_final_path
        result.thumb_from = thumb_source

    should_use_censored_crop = result.scraping_type == FixedScrapingType.YOUMA or is_censored_mosaic(result.mosaic)
    if should_use_censored_crop:
        poster_ok = await _download_censored_poster(
            result,
            other,
            file_info,
            poster_final_path,
            folder_new_path,
            overwrite=overwrite,
        )
        if not poster_ok and other.thumb_path:
            cut_path = poster_final_path.with_suffix(".[CUT].jpg")
            safe_print("  poster: direct failed, cut from thumb with original logic")
            if await asyncio.to_thread(cut_thumb_to_poster, result, other.thumb_path, cut_path, result.scraping_type):
                await move_file_async(cut_path, poster_final_path)
                other.poster_path = poster_final_path
                other.poster_marked = False
                poster_ok = True
    else:
        poster_ok = await _download_uncropped_poster(
            result,
            other,
            poster_final_path,
            thumb_final_path,
            folder_new_path,
            overwrite=overwrite,
        )

    if not thumb_ok and not poster_ok:
        raise RuntimeError(f"{number}: no cover image downloaded")

    await _add_watermark(file_info, result, other, enabled=watermark)

    log_text = LogBuffer.log().get().strip()
    if log_text:
        safe_print("  log:")
        for line in log_text.splitlines():
            if line.strip():
                safe_print(f"    {line}")

    return BackfillResult(
        number=number,
        source=result.site_log.strip(),
        scraping_type=result.scraping_type,
        mosaic=result.mosaic,
        folder=folder_new_path,
        thumb_path=other.thumb_path,
        poster_path=other.poster_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill MDCx cover images by number. Uses current MDCx config, crawler priority, naming, crop, and watermark rules."
    )
    parser.add_argument("numbers", nargs="*", help="Numbers to scrape, for example SSIS-001 or 060626_001")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path.cwd(), help="Output directory")
    parser.add_argument(
        "--source-file",
        type=Path,
        help="Optional existing media file used only to parse suffixes such as subtitles, 4K, uncensored tags, and CD part",
    )
    parser.add_argument("--site", help="Optional crawler site to force, for example official, javdb, dmm")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing poster/thumb files")
    parser.add_argument("--no-watermark", action="store_true", help="Skip watermark step")
    parser.add_argument("--crawl-timeout", type=float, default=90, help="Metadata scraping timeout in seconds")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    numbers = [n.strip() for n in args.numbers if n.strip()]
    if not numbers:
        raw = input("Number: ").strip()
        numbers = [raw] if raw else []

    if not numbers:
        safe_print("No number provided.")
        return 2

    source_file = args.source_file
    if source_file is not None and not source_file.exists():
        safe_print(f"source file not found: {source_file}")
        return 2

    failed = 0
    for number in numbers:
        try:
            result = await backfill_cover(
                number,
                output_dir=args.output_dir.resolve(),
                source_file=source_file.resolve() if source_file else None,
                site=args.site,
                overwrite=args.overwrite,
                watermark=not args.no_watermark,
                crawl_timeout=args.crawl_timeout,
            )
            safe_print(f"done: {result.number}")
            if result.thumb_path:
                safe_print(f"  thumb : {result.thumb_path}")
            if result.poster_path:
                safe_print(f"  poster: {result.poster_path}")
        except Exception as exc:
            failed += 1
            safe_print(f"failed: {number}: {exc}")

    return 1 if failed else 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
