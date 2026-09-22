"""DMM 图源前缀路由学习。

DMM CDN（awsimgsrc）不同厂牌番号的 cid 前缀不同（如 ABF=436、MILK=h_1240），
静态前缀表（dmm_direct._PREFIX_GROUPS）无法覆盖新厂牌。刮削过程中观察到的
真实 DMM 图片 URL 是权威证据，本模块从这些证据学习 series -> prefix 映射，
按状态机管理可靠性，供 dmm_direct 生成候选时优先使用。

状态机（简化版，参照 AVACA work_image_learned_route 的 provisional/verified/
degraded/quarantined 思想）：
- provisional：首次观察到证据，验证成功 >= 2 个不同番号后转正
- verified：verified 规则被使用但连续失败 >= 3 次后隔离
- quarantined：隔离停用；被新的成功证据重新观察到后重置为 provisional

存储：userdata/dmm_prefix_learned.json，原子写（临时文件 + os.replace）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_VERSION = 1
_PREFIX_RE = None  # 惰性编译，避免导入开销

_VERIFIED_THRESHOLD = 2  # 至少 2 个不同番号验证成功才转正
_QUARANTINE_FAILURE_THRESHOLD = 3  # verified 规则连续失败次数达到即隔离

_lock = threading.Lock()
_learned: dict[str, dict[str, Any]] = {}
_loaded = False
_load_failed = False


def _cache_path() -> Path | None:
    from mdcx.config.resources import Resources

    try:
        resources = Resources()
    except Exception:
        return None
    userdata = getattr(resources, "_userdata_base", None)
    if not isinstance(userdata, Path) or str(userdata) in (".", "./"):
        return None
    return userdata / "dmm_prefix_learned.json"


def _prefix_regex():
    global _PREFIX_RE
    if _PREFIX_RE is None:
        import re

        _PREFIX_RE = re.compile(r"^([a-z0-9_]{0,8})$")
    return _PREFIX_RE


def _load() -> None:
    global _loaded, _load_failed
    with _lock:
        if _loaded:
            return
        path = _cache_path()
        if path is None or not path.exists():
            _loaded = True
            return
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            if isinstance(data, dict) and data.get("version") == _VERSION:
                series = data.get("series")
                if isinstance(series, dict):
                    for key, value in series.items():
                        if isinstance(key, str) and isinstance(value, dict):
                            _learned[key] = value
        except Exception:
            _load_failed = True
        finally:
            _loaded = True


def _sanitize_series(value: Any) -> dict[str, Any] | None:
    """校验并规范化一个 series 条目，非法返回 None。"""
    if not isinstance(value, dict):
        return None
    verified = value.get("verified")
    quarantined = value.get("quarantined")
    if not isinstance(verified, dict) or not isinstance(quarantined, dict):
        return None
    cleaned_verified: dict[str, int] = {}
    for prefix, count in verified.items():
        if _prefix_regex().match(prefix) and isinstance(count, int) and count > 0:
            cleaned_verified[prefix] = count
    cleaned_quarantined: dict[str, int] = {}
    for prefix, count in quarantined.items():
        if _prefix_regex().match(prefix) and isinstance(count, int) and count > 0:
            cleaned_quarantined[prefix] = count
    return {"verified": cleaned_verified, "quarantined": cleaned_quarantined}


def _persist() -> None:
    if _load_failed:
        # 历史学习表加载失败时 _learned 为空，若继续写会把"空表+新记录"覆盖回去，
        # 丢失全部历史学习结果。加载失败期间禁止落盘。
        return
    path = _cache_path()
    if path is None:
        return
    try:
        payload = {"version": _VERSION, "series": _learned}
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception:
        # 学习表写入失败不影响刮削主流程
        return


def _series_entry(series: str) -> dict[str, Any]:
    entry = _learned.get(series)
    if entry is None:
        entry = {"verified": {}, "quarantined": {}}
        _learned[series] = entry
    return entry


def _record_success(series: str, prefix: str, code: str) -> None:
    """记录一次成功证据。prefix 验证成功 >= 2 个不同番号后转正。"""
    if not _prefix_regex().match(prefix) or not series:
        return
    with _lock:
        entry = _series_entry(series)
        # 被新证据重新观察到：解除隔离
        entry["quarantined"].pop(prefix, None)
        verified = entry["verified"]
        if prefix in verified:
            return  # 已转正，成功证据不再重复累加
        # provisional：记录验证过的番号，达到阈值转正
        proven_codes = entry.setdefault("proven_codes", {}).get(prefix, [])
        if code not in proven_codes:
            proven_codes.append(code)
            entry["proven_codes"][prefix] = proven_codes[-_VERIFIED_THRESHOLD:]
        if len(proven_codes) >= _VERIFIED_THRESHOLD:
            entry["verified"][prefix] = len(proven_codes)
            entry["proven_codes"].pop(prefix, None)
            _persist()


def _record_failure(series: str, prefix: str) -> None:
    """记录一次失败。仅对已 verified 的规则计数，连续失败达到阈值则隔离。"""
    if prefix is None or not series:
        return
    with _lock:
        entry = _learned.get(series)
        if entry is None or prefix not in entry.get("verified", {}):
            return
        failures = entry.setdefault("consecutive_failures", {}).get(prefix, 0) + 1
        entry["consecutive_failures"][prefix] = failures
        if failures >= _QUARANTINE_FAILURE_THRESHOLD:
            count = entry["verified"].pop(prefix, 0)
            entry["quarantined"][prefix] = count
            entry["consecutive_failures"].pop(prefix, None)
            _persist()


def record_success(number: str, cid: str) -> None:
    """刮削流程观察到真实 DMM URL 时的证据入口。

    Args:
        number: 规范化番号（如 sone-833）
        cid: 真实观察到的 cid（URL 路径 /video/{cid}/{cid}ps.jpg 中的 {cid}）

    从 cid 与番号反推 series + prefix 并记录成功证据。
    """
    _load()
    series, prefix = _split_cid(number, cid)
    if not series:
        return
    code = _canonical_code(number)
    _record_success(series, prefix, code)


def record_failure(number: str, cid: str) -> None:
    """verify 候选失败时调用（仅对 verified 规则生效，provisional 不因失败被隔离）。"""
    _load()
    series, prefix = _split_cid(number, cid)
    if not series:
        return
    _record_failure(series, prefix)


def get_learned_prefixes(series: str) -> tuple[list[str], list[str]]:
    """返回 (verified_prefixes, provisional_prefixes)。

    仅返回学习表中与 series 相关的规则；调用方负责与静态表合并排序。
    """
    _load()
    with _lock:
        entry = _learned.get(series)
        if entry is None:
            return [], []
        verified = [p for p in entry.get("verified", {}) if _prefix_regex().match(p)]
        proven_codes = entry.get("proven_codes", {})
        provisional = [p for p in proven_codes if _prefix_regex().match(p)]
        return verified, provisional


def _split_cid(number: str, cid: str) -> tuple[str, str]:
    """从番号与 cid 反推 (series, prefix)。

    cid = {prefix}{series}{编号5位补零}，prefix 可能是空串。
    策略：把 cid 中的数字段拆出后，剩余字母部分按已知 series 最长匹配，
    匹配失败则把剩余全部当作 series（prefix 为空），交给后续验证过滤。
    """
    from mdcx.crawlers.dmm_direct import _parse_number

    parsed = _parse_number(number)
    if not parsed:
        return "", ""
    series, _num, padded = parsed[0]
    if not cid.endswith(padded):
        return "", ""
    prefix = cid[: -len(series) - len(padded)]
    return series, prefix


def _canonical_code(number: str) -> str:
    return (number or "").lower().replace("-", "").replace(" ", "")


def reset_for_testing() -> None:
    """测试复位：清空学习表与状态。"""
    global _loaded, _load_failed
    with _lock:
        _learned.clear()
        _loaded = False
        _load_failed = False
