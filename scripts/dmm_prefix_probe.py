"""番号系列 → DMM cid 前缀探测工具（维护 dmm_direct 前缀表用）.

用途:
    批量校验/发现番号系列在 awsimgsrc CDN 的真实 cid 前缀，辅助维护
    ``mdcx/crawlers/dmm_direct.py`` 的 ``_PREFIX_GROUPS`` / ``_SPECIAL_THRESHOLDS``。

流程:
    1. dmmapi（thejavdb API）按番号反推真实 cid（快）
    2. dmmapi 查不到时用 avbase 搜系列名拿 product_id（兜底）
    3. 反推的前缀最终以 awsimgsrc 直连多编号验证为准（唯一采信标准）

用法:
    # 校验指定系列（逗号分隔）
    uv run python -m scripts.dmm_prefix_probe ssis,mide,wanz

    # 校验文件中的系列清单（每行一个）
    uv run python -m scripts.dmm_prefix_probe @series.txt

    # 输出推荐补表代码片段
    uv run python -m scripts.dmm_prefix_probe ssis,mide --emit-code
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import warnings

warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

from curl_cffi import requests
from lxml import html as lxml_html
from PIL import Image

_TRIAL_NUMS = [100, 300, 500, 30, 60, 80, 200, 150]
# 尺寸验证探测的编号段（不同系列编号分布差异大，多段探测取最佳）
_SIZE_PROBE_NUMS = [100, 300, 538, 600, 800, 900]
_DMMAPI = "https://api.thejavdb.net/v1/movies"
_AVBASE = "https://www.avbase.net/works"
_CDN = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video"


def _extract_cid_from_url(url: str) -> str | None:
    """从 DMM 图 URL 提取 cid（兼容 awsimgsrc digital 与 pics.dmm.co.jp mono）."""
    for pattern in (r"/digital/video/([^/]+)/", r"/mono/movie/adult/([^/]+)/"):
        m = re.search(pattern, url or "")
        if m:
            return m.group(1)
    return None


def _split_prefix(series: str, cid: str) -> tuple[str, int | None]:
    """从 cid 反推前缀与编号. 如 h_1240milk00100 -> ('h_1240', 100)."""
    lower = (cid or "").lower()
    if series not in lower:
        return "", None
    head, tail = lower.split(series, 1)
    if tail.isdigit():
        return head, int(tail)
    return head, None


def _probe_size(url: str, *, attempts: int = 4) -> tuple[int, int] | None:
    """awsimgsrc 直连下载并读取实际尺寸（BoringSSL 间歇抖动，多次重试）."""
    for _ in range(attempts):
        try:
            r = requests.get(url, impersonate="chrome", timeout=20)
            if r.status_code != 200 or not r.content:
                return None
            try:
                img = Image.open(io.BytesIO(r.content))
                return img.size
            except Exception:
                return None
        except Exception:
            continue
    return None


def _is_usable_portrait(size: tuple[int, int]) -> bool:
    """竖版可用：宽≥500 且 高>宽（过滤 147x200 占位图）."""
    w, h = size
    return w >= 500 and h > w


def _image_area(size: tuple[int, int]) -> int:
    return size[0] * size[1]


async def _probe_dmmapi(number: str) -> str | None:
    try:
        r = requests.get(f"{_DMMAPI}?q={number}", impersonate="chrome", timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
        if isinstance(d, dict) and "frontcover_url" in d:
            return _extract_cid_from_url(d.get("frontcover_url") or "")
    except Exception:
        pass
    return None


async def _probe_avbase(series: str) -> str | None:
    """avbase 搜系列名，返回首个匹配 product_id（完整 DMM cid）."""
    try:
        r = requests.get(f"{_AVBASE}?q={series}", impersonate="chrome", timeout=25)
        tree = lxml_html.fromstring(r.text)
        hrefs = [
            h for h in tree.xpath('//a[starts-with(@href, "/works/")]/@href') if "/date" not in h and "/recent" not in h
        ]
        for href in hrefs[:5]:
            r2 = requests.get(f"https://www.avbase.net{href}", impersonate="chrome", timeout=25)
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r2.text, re.S)
            if not m:
                continue
            try:
                nd = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            work = ((nd.get("props") or {}).get("pageProps") or {}).get("work") or {}
            for p in work.get("products") or []:
                if isinstance(p, dict):
                    pid = p.get("product_id") or ""
                    if series in pid.lower():
                        return pid
    except Exception:
        pass
    return None


async def probe_series(series: str, *, verify: bool = True) -> dict:
    from mdcx.crawlers.dmm_direct import is_uncensored_number

    series = series.strip().lower()
    result: dict = {
        "series": series,
        "source": None,
        "cid": None,
        "prefix": None,
        "verified": False,
    }
    if not series or is_uncensored_number(series):
        return result
    cid = None
    for trial in _TRIAL_NUMS:
        cid = await _probe_dmmapi(f"{series}-{trial}")
        if cid:
            result["source"] = "dmmapi"
            break
    if not cid:
        cid = await _probe_avbase(series)
        if cid:
            result["source"] = "avbase"
    if not cid:
        return result
    result["cid"] = cid
    prefix, num = _split_prefix(series, cid)
    result["prefix"] = prefix
    if verify and prefix is not None:
        best_size = None
        for probe_num in _SIZE_PROBE_NUMS:
            cid5 = f"{prefix}{series}{probe_num:05d}"
            size = _probe_size(f"{_CDN}/{cid5}/{cid5}ps.jpg")
            if size and (best_size is None or _image_area(size) > _image_area(best_size)):
                best_size = size
        result["size"] = best_size
        result["verified"] = bool(best_size and _is_usable_portrait(best_size))
    return result


def _action(result: dict) -> str:
    prefix = result.get("prefix")
    if not result.get("source"):
        return "跳过（查不到）"
    if prefix is None:
        return "需复核"
    if not prefix:
        return "无前缀"
    return "新增" if result.get("verified") else "需复核"


def _emit_code(rows: list[dict]) -> str:
    """生成推荐补表代码片段."""
    no_prefix: list[str] = []
    by_prefix: dict[str, list[str]] = {}
    for r in rows:
        if not r.get("source") or not r.get("verified"):
            continue
        prefix = r.get("prefix") or ""
        if not prefix:
            no_prefix.append(r["series"])
        else:
            by_prefix.setdefault(prefix, []).append(r["series"])
    lines: list[str] = []
    if no_prefix:
        lines.append(f'    "": [\n{chr(10).join(f"        {chr(34)}{s}{chr(34)}," for s in sorted(no_prefix))}\n    ],')
    for prefix in sorted(by_prefix):
        members = by_prefix[prefix]
        lines.append(f'    "{prefix}": [{", ".join(chr(34) + s + chr(34) for s in sorted(members))}],')
    return chr(10).join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DMM cid 前缀探测（dmmapi + avbase + awsimgsrc 验证）")
    parser.add_argument("series", nargs="*", help="系列名（逗号分隔），或 @文件路径（每行一个）")
    parser.add_argument("--no-verify", action="store_true", help="跳过 awsimgsrc 验证（只反推前缀）")
    parser.add_argument("--emit-code", action="store_true", help="输出推荐补表代码片段")
    parser.add_argument("--attempts", type=int, default=4, help="awsimgsrc 验证重试次数（默认 4）")
    return parser.parse_args()


def _expand_series_args(args_series: list[str]) -> list[str]:
    series: list[str] = []
    for item in args_series:
        if item.startswith("@"):
            path = item[1:]
            with open(path, encoding="utf-8") as f:
                series.extend(line.strip().lower() for line in f if line.strip())
        else:
            series.extend(s.strip().lower() for s in item.split(",") if s.strip())
    return series


async def _run(series: list[str], *, verify: bool, attempts: int) -> list[dict]:
    rows = []
    for i, s in enumerate(series, 1):
        row = await probe_series(s, verify=verify)
        if verify and not row.get("verified"):
            row = await probe_series(s, verify=False)  # 反推保留
        row["verified"] = row.get("verified", False)
        rows.append(row)
        print(f"\r进度 {i}/{len(series)}", end="", flush=True)
    print()
    return rows


def main() -> None:
    args = parse_args()
    series = _expand_series_args(args.series)
    if not series:
        print("未提供系列。用法: uv run python -m scripts.dmm_prefix_probe ssis,mide [--emit-code]")
        return

    rows = asyncio.run(_run(series, verify=not args.no_verify, attempts=args.attempts))

    print(f"\n{'系列':<8} {'来源':<7} {'反推cid':<22} {'前缀':<12} {'尺寸':<12} 建议")
    print("-" * 80)
    for r in rows:
        src = r.get("source") or "-"
        cid = r.get("cid") or "未查到"
        prefix = r.get("prefix") or "无"
        size = r.get("size")
        size_str = f"{size[0]}x{size[1]}" if size else "-"
        print(f"{r['series']:<8} {src:<7} {cid:<22} {prefix:<12} {size_str:<12} {_action(r)}")

    if args.emit_code:
        print("\n推荐补表片段:")
        print(_emit_code(rows))


if __name__ == "__main__":
    main()
