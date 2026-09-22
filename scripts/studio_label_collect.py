#!/usr/bin/env python3
"""
从 dmmsee（javbus 镜像）采集片商(studio)与发行商(label)。

详情页反查：
- 有码: /studio/{id}（片商）、/label/{id}（发行商）
- 无码: /uncensored/studio/{id}（片商），无 label（无码片商自制自发，无发行体系）

用法:
    uv run python scripts/studio_label_collect.py --out /tmp/opencode/studio_label_all.json
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


def _parse(text: str) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    """从详情页解析 (studio_id, studio_name) 与 (label_id, label_name)。"""
    if not text:
        return None, None
    tree = lxml_html.fromstring(text)
    studio = None
    label = None
    studio_nodes = tree.xpath('//a[contains(@href, "/studio/")]')
    if studio_nodes:
        href = studio_nodes[0].get("href") or ""
        studio = (href.rsplit("/", 1)[-1], (studio_nodes[0].text or "").strip())
    label_nodes = tree.xpath('//a[contains(@href, "/label/")]')
    if label_nodes:
        href = label_nodes[0].get("href") or ""
        label = (href.rsplit("/", 1)[-1], (label_nodes[0].text or "").strip())
    return studio, label


async def _collect_one(client: AsyncWebClient, detail_url: str, sem: asyncio.Semaphore):
    async with sem:
        try:
            text, _ = await client.get_text(detail_url)
        except Exception:
            return None
        return _parse(text)


async def _collect_pages(
    client: AsyncWebClient,
    base: str,
    max_pages: int,
    sem: asyncio.Semaphore,
    studios: dict[str, str],
    labels: dict[str, str],
) -> int:
    """采集一个分区，返回成功处理的详情页数。"""
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
            studio, label = res
            if studio:
                studios.setdefault(studio[0], studio[1])
            if label:
                labels.setdefault(label[0], label[1])
            handled += 1
        print(
            f"  {base} page {page}/{max_pages} 详情 {len(tasks)}，studio {len(studios)} label {len(labels)}", flush=True
        )
    return handled


async def _run(out: Path, concurrency: int, max_pages: int) -> tuple[int, int]:
    sem = asyncio.Semaphore(concurrency)
    studios: dict[str, str] = {}
    labels: dict[str, str] = {}
    client = AsyncWebClient(timeout=10)
    try:
        print("采集有码分区...", flush=True)
        await _collect_pages(client, BASE, min(max_pages, CENSORED_MAX_PAGES), sem, studios, labels)
        print("采集无码分区...", flush=True)
        await _collect_pages(client, f"{BASE}/uncensored", min(max_pages, UNCENSORED_MAX_PAGES), sem, studios, labels)
    finally:
        await client.close()
    out.write_text(json.dumps({"studios": studios, "labels": labels}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(studios), len(labels)


def main() -> int:
    parser = argparse.ArgumentParser(description="从 dmmsee 采集片商与发行商")
    parser.add_argument("--out", type=Path, default=Path("/tmp/opencode/studio_label_all.json"))
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--max-pages", type=int, default=10**9)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_studio, n_label = asyncio.run(_run(args.out, args.concurrency, args.max_pages))
    print(f"完成，共采集 {n_studio} 片商、{n_label} 发行商 -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
