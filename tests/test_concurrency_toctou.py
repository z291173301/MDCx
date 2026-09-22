"""并发场景下 Flags 共享集合的 TOCTOU 修复验证。"""

import asyncio
from pathlib import Path

import pytest

from mdcx.core import file_crawler as _fc
from mdcx.models.flags import FileDoneDict, Flags


async def _concurrent_set_add(lock_attr: str, set_attr: str, values: list[Path]) -> None:
    """模拟多个协程同时对同一个 set 做 check-then-add。"""
    obj = getattr(Flags, set_attr)
    lock = getattr(Flags, lock_attr)

    async def _add_one(val: Path) -> None:
        if val not in obj:
            async with lock:
                if val not in obj:
                    obj.add(val)

    await asyncio.gather(*[_add_one(v) for v in values])


@pytest.mark.asyncio
async def test_pic_catch_set_concurrent_dedup():
    """多协程并发抢占 pic_catch_set 时，每个路径只被 add 一次。"""
    Flags.reset()
    paths = [Path(f"/mnt/media/vol{i}.mp4") for i in range(50)]
    duplicates = paths + paths  # 100 个协程，50 个重复

    await _concurrent_set_add("_pic_catch_lock", "pic_catch_set", duplicates)
    assert len(Flags.pic_catch_set) == 50


@pytest.mark.asyncio
async def test_extrafanart_deal_set_concurrent_dedup():
    """多协程并发抢占 extrafanart_deal_set 时，每个路径只被 add 一次。"""
    Flags.reset()
    paths = [Path(f"/mnt/media/extra{i}") for i in range(50)]
    duplicates = paths + paths

    await _concurrent_set_add("_extrafanart_lock", "extrafanart_deal_set", duplicates)
    assert len(Flags.extrafanart_deal_set) == 50


@pytest.mark.asyncio
async def test_trailer_deal_set_concurrent_dedup():
    """多协程并发抢占 trailer_deal_set 时，每个路径只被 add 一次。"""
    Flags.reset()
    paths = [Path(f"/mnt/media/trailers/vol{i}") for i in range(50)]
    duplicates = paths + paths

    await _concurrent_set_add("_trailer_lock", "trailer_deal_set", duplicates)
    assert len(Flags.trailer_deal_set) == 50


@pytest.mark.asyncio
async def test_file_done_dic_concurrent_init_dedup():
    """多协程并发初始化 file_done_dic 时，每个 number 只写入一次。"""
    Flags.reset()
    numbers = [f"ABC-{i:03d}" for i in range(50)]
    entries = [
        (
            n,
            FileDoneDict(
                poster=None,
                thumb=None,
                fanart=None,
                trailer=None,
                local_poster=None,
                local_thumb=None,
                local_fanart=None,
                local_trailer=None,
            ),
        )
        for n in numbers
    ]

    obj = Flags.file_done_dic
    lock = Flags._file_done_lock

    async def _update_one(key: str, val: FileDoneDict) -> None:
        if key not in obj:
            async with lock:
                if key not in obj:
                    obj[key] = val

    await asyncio.gather(*[_update_one(k, v) for k, v in entries + entries])
    assert len(Flags.file_done_dic) == 50


@pytest.mark.asyncio
async def test_file_done_dic_trailer_check_then_set():
    """模拟 web.py 中 trailer 字段的 check-then-set 模式。"""
    Flags.reset()

    async def _set_trailer_if_missing(number: str, path: Path) -> None:
        if not Flags.file_done_dic.get(number, {}).get("trailer"):
            async with Flags._file_done_lock:
                if not Flags.file_done_dic.get(number, {}).get("trailer"):
                    if number not in Flags.file_done_dic:
                        Flags.file_done_dic[number] = FileDoneDict(
                            poster=None,
                            thumb=None,
                            fanart=None,
                            trailer=None,
                            local_poster=None,
                            local_thumb=None,
                            local_fanart=None,
                            local_trailer=None,
                        )
                    Flags.file_done_dic[number].update({"trailer": path})

    tasks = [_set_trailer_if_missing("VOL-001", Path(f"/mnt/trailer/vol001_{i}.mp4")) for i in range(100)]
    await asyncio.gather(*tasks)
    assert Flags.file_done_dic["VOL-001"]["trailer"] is not None


@pytest.mark.asyncio
async def test_next_start_time_concurrent_increment():
    """多协程并发执行 next_start_time += thread_time 时，增量不丢失。"""
    Flags.reset()
    Flags.next_start_time = 100.0
    thread_time = 5.0
    n = 50

    async def _increment() -> None:
        async with Flags._counter_lock:
            Flags.next_start_time += thread_time

    await asyncio.gather(*[_increment() for _ in range(n)])
    assert Flags.next_start_time == 100.0 + thread_time * n


@pytest.mark.asyncio
async def test_counting_order_concurrent_increment():
    """多协程并发执行 counting_order += 1 时，每个协程获得唯一序号。"""
    Flags.reset()
    n = 50

    async def _get_order() -> int:
        async with Flags._counter_lock:
            Flags.counting_order += 1
            return Flags.counting_order

    results = await asyncio.gather(*[_get_order() for _ in range(n)])
    assert sorted(results) == list(range(1, n + 1))


@pytest.mark.asyncio
async def test_json_get_status_concurrent_update():
    """模拟 scraper.py 中 json_get_status 的并发更新。"""
    Flags.reset()
    numbers = [f"ABC-{i:03d}" for i in range(50)]

    async def _check_and_set(num: str) -> bool:
        async with Flags._json_get_lock:
            if Flags.json_get_status.get(num) is None:
                Flags.json_get_status[num] = True
                return True
        return False

    for n in numbers:
        Flags.json_get_status[n] = None

    await asyncio.gather(*[_check_and_set(n) for n in numbers + numbers])
    true_count = sum(1 for n in numbers if Flags.json_get_status.get(n) is True)
    assert true_count == 50


def test_flags_reset_keeps_async_locks_stable():
    locks_before = {
        attr: getattr(Flags, attr)
        for attr in (
            "_counter_lock",
            "_json_get_lock",
            "_file_path_lock",
            "_file_done_lock",
            "_pic_catch_lock",
            "_extrafanart_lock",
            "_trailer_lock",
        )
    }

    Flags.reset()

    assert {attr: getattr(Flags, attr) for attr in locks_before} == locks_before


@pytest.mark.asyncio
async def test_crawl_cache_concurrent_put_eviction():
    """并发写入 _crawl_cache 触发淘汰逻辑时不触发 RuntimeError。"""
    from mdcx.models.model_types import CrawlersResult

    cache = _fc._crawl_cache
    cache.clear()

    original_max = _fc._CRAWL_CACHE_MAX_ENTRIES
    _fc._CRAWL_CACHE_MAX_ENTRIES = 10

    try:
        empty_result = CrawlersResult.empty()
        n = 50

        async def _put_one(i: int) -> None:
            await _fc._crawl_cache_put((f"/path/vol{i}.mp4", f"ABC-{i:03d}"), empty_result)

        await asyncio.gather(*[_put_one(i) for i in range(n)])
        assert len(cache) == _fc._CRAWL_CACHE_MAX_ENTRIES
    finally:
        _fc._CRAWL_CACHE_MAX_ENTRIES = original_max
        cache.clear()
