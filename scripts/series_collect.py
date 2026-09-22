#!/usr/bin/env python3
"""
从 javbus 镜像站（dmmsee）批量采集系列名。

遍历有码/无码列表页 -> 作品详情页，反查 series 链接与系列名（日文），去重保存为 json。

用法:
    uv run python scripts/series_collect.py [--out OUT.json] [--concurrency N] [--max-pages N]

采集结果为日文系列名，后续需要翻译成中文再并入 info_database.xlsx。
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from lxml import html as lxml_html

from mdcx.web_async import AsyncWebClient

BASE = "https://www.dmmsee.cyou"

CENSORED_MAX_PAGES = 196
UNCENSORED_MAX_PAGES = 23


def _parse_series(text: str) -> tuple[str, str] | None:
    """从详情页解析 series 链接与名称，返回 (series_id, series_name)。"""
    if not text:
        return None
    tree = lxml_html.fromstring(text)
    nodes = tree.xpath('//a[contains(@href, "/series/")]')
    for node in nodes:
        href = node.get("href") or ""
        name = (node.text or "").strip()
        if not name:
            continue
        if "/uncensored/series/" in href:
            series_id = href.rsplit("/", 1)[-1]
        elif "/series/" in href:
            series_id = href.rsplit("/", 1)[-1]
        else:
            continue
        return series_id, name
    return None


async def _collect_one(client: AsyncWebClient, detail_url: str, sem: asyncio.Semaphore) -> tuple[str, str] | None:
    async with sem:
        try:
            text, _ = await client.get_text(detail_url)
        except Exception:
            return None
        return _parse_series(text)


async def _collect_pages(
    client: AsyncWebClient,
    base: str,
    max_pages: int,
    sem: asyncio.Semaphore,
    results: dict[str, str],
) -> int:
    """采集一个分区（有码/无码），返回成功处理的详情页数。"""
    seen_details: set[str] = set()
    handled = 0
    for page in range(1, max_pages + 1):
        page_url = f"{base}/page/{page}"
        try:
            text, _ = await client.get_text(page_url)
        except Exception:
            continue
        if not text:
            continue
        links = re.findall(r'class="movie-box"[^>]*href="([^"]+)"', text)
        tasks = []
        for link in links:
            if link in seen_details:
                continue
            seen_details.add(link)
            tasks.append(_collect_one(client, link, sem))
        if not tasks:
            continue
        for res in await asyncio.gather(*tasks):
            if res is None:
                continue
            series_id, series_name = res
            if series_name not in results:
                results[series_name] = series_id
            handled += 1
        print(f"  page {page}/{max_pages} 处理详情 {len(tasks)}，当前系列 {len(results)}", flush=True)
    return handled


async def _run(out: Path, concurrency: int, max_pages: int) -> int:
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, str] = {}
    client = AsyncWebClient(timeout=10)
    try:
        print("采集有码分区...", flush=True)
        await _collect_pages(client, BASE, min(max_pages, CENSORED_MAX_PAGES), sem, results)
        print("采集无码分区...", flush=True)
        await _collect_pages(client, f"{BASE}/uncensored", min(max_pages, UNCENSORED_MAX_PAGES), sem, results)
    finally:
        await client.close()
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(results)


def main() -> int:
    parser = argparse.ArgumentParser(description="从 dmmsee 采集系列名")
    parser.add_argument("--out", type=Path, default=Path("/tmp/opencode/series_raw.json"))
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=10**9)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    total = asyncio.run(_run(args.out, args.concurrency, args.max_pages))
    print(f"完成，共采集 {total} 个系列 -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
