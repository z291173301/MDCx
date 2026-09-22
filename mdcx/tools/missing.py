"""
查找指定演员缺少作品
"""

import json
import re
import time
from pathlib import Path
from typing import cast

import aiofiles
import aiofiles.os

from ..base.file import movie_lists
from ..config.manager import manager
from ..config.resources import resources
from ..core.file import get_file_info_v2
from ..models.flags import Flags
from ..signals import signal
from ..utils import get_used_time
from ..utils.file import write_file_atomic_async
from .actor_sources import (
    _JavbusRotator,
    fetch_censored,
    fetch_guochan,
    fetch_uncensored,
    fetch_western,
)

_ACTOR_TYPE_PATTERN = re.compile(r"[（(]\s*(有码|无码|欧美|国产)\s*[)）]")


def _parse_actor_entry(entry: str) -> tuple[str, str]:
    """解析演员名条目，提取类型标注。返回 (演员名, 类型)。

    格式: "波多野結衣" 或 "水菜麗(无码)" 或 "Angela White(欧美)"。
    不标注的默认有码。
    """
    entry = entry.strip()
    m = _ACTOR_TYPE_PATTERN.search(entry)
    if m:
        actor_type = m.group(1)
        name = _ACTOR_TYPE_PATTERN.sub("", entry).strip()
        return name, actor_type
    return entry, "有码"


async def _fetch_actor_numbers(name: str, actor_type: str, rotator: _JavbusRotator) -> set[str] | None:
    """按演员类型调用对应数据源拉取全部番号。"""
    if actor_type == "无码":
        return await fetch_uncensored(name, rotator)
    if actor_type == "欧美":
        return await fetch_western(name, rotator)
    if actor_type == "国产":
        return await fetch_guochan(name, rotator)
    return await fetch_censored(name, rotator)


async def _show_actor_missing_numbers(actor_name: str, actor_type: str, net_numbers: set[str]) -> None:
    """对比网络番号与本地库，输出缺失列表。"""
    local_set = Flags.local_number_set
    cnword_set = Flags.local_number_cnword_set

    missing = sorted(n for n in net_numbers if n not in local_set)
    missing_cnword = sorted(n for n in missing if n in cnword_set)

    type_tag = f"[{actor_type}]" if actor_type != "有码" else ""
    _log = signal.show_log_text
    _log(f"\n{'=' * 97}\n👩 {type_tag} {actor_name} 的全部网络番号({len(net_numbers)})...\n{'=' * 97}")
    if net_numbers:
        for each in sorted(net_numbers, reverse=True):
            mark = "✓" if each in local_set else "✗"
            sub = "🀄️" if each in cnword_set else ""
            _log(f"   {each:<20} {mark} {sub}")
    else:
        _log("   没有找到任何番号...")

    _log(f"\n{'=' * 97}\n🔍 {type_tag} {actor_name} 本地缺失的番号({len(missing)})...\n{'=' * 97}")
    if missing:
        for each in missing:
            sub = "🀄️" if each in cnword_set else ""
            _log(f"   {each:<20} {sub}")
    else:
        _log("   没有缺失的番号，已全部收集！")

    if missing_cnword:
        _log(f"\n{'=' * 97}\n🀄️ {type_tag} {actor_name} 本地缺失的有字幕番号({len(missing_cnword)})...\n{'=' * 97}")
        for each in missing_cnword:
            _log(f"   {each}")


async def _try_write_cache_async(p: str | Path, content: str, start_time: float) -> None:
    """写缓存文件，失败只记录日志，不让整个查询任务中断。

    缺失番号查询已耗时遍历整个资源库，若结尾写缓存失败（磁盘满、
    目录只读、文件被占用等）导致任务中断，之前的查询结果全部白费。
    """
    try:
        await write_file_atomic_async(p, content)
    except Exception as e:
        signal.show_log_text(f"   ⚠️ 缓存文件写入失败（不影响本次查询结果，但下次会重新扫描）：{e}")


async def check_missing_number(actor_flag):
    """
    检查缺失番号
    """
    signal.change_buttons_status.emit()
    start_time = time.time()
    local_movies: dict[str, tuple[str, bool]] = {}

    # 获取资源库配置
    movie_type = manager.config.media_type
    libraries = manager.config.local_library  # 用户设置的扫描媒体路径
    libraries = {Path(p) for p in libraries if p.strip()}

    # 遍历本地资源库
    signal.show_log_text("")
    library_lines = "\n   ".join(str(p) for p in libraries)
    signal.show_log_text(
        f"\n本地资源库地址:\n   {library_lines}\n\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n⏳ 开始遍历本地资源库，以获取本地视频的最新列表...\n   提示：每次启动第一次查询将更新本地视频数据。（大概1000个/30秒，如果视频较多，请耐心等待。）"
    )
    all_movies: list[Path] = []
    for p in libraries:
        movies = await movie_lists([], movie_type, p)  # 获取所有需要刮削的影片列表
        all_movies.extend(movies)
    signal.show_log_text(f"🎉 获取完毕！共找到视频数量（{len(all_movies)}）({get_used_time(start_time)}s)")

    # 获取本地番号
    start_time_local = time.time()
    signal.show_log_text("\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n⏳ 开始获取本地视频的番号信息...")
    local_number_list = resources.u("number_list.json")
    if not await aiofiles.os.path.exists(local_number_list):
        signal.show_log_text(
            "   提示：正在生成本地视频的番号信息数据...（第一次较慢，请耐心等待，以后只需要查找新视频，速度很快）"
        )
        await _try_write_cache_async(local_number_list, "{}", start_time)
    async with aiofiles.open(local_number_list, encoding="utf-8") as data:
        json_data = json.loads(await data.read())
        json_data = cast("dict[str, tuple[str, bool]]", json_data)
    for movie in all_movies:
        nfo_path = movie.with_suffix(".nfo")
        number = ""
        has_sub = False
        if r := json_data.get(movie.as_posix()):
            number, has_sub = r
        else:
            if await aiofiles.os.path.exists(nfo_path):
                async with aiofiles.open(nfo_path, encoding="utf-8") as f:
                    nfo_content = await f.read()
                number_result = re.findall(r"<num>(.+)</num>", nfo_content)
                if number_result:
                    number = number_result[0]

                    if "<genre>中文字幕</genre>" in nfo_content or "<tag>中文字幕</tag>" in nfo_content:
                        has_sub = True
                    else:
                        has_sub = False
            if not number:
                file_info = await get_file_info_v2(movie, copy_sub=False)
                has_sub = file_info.has_sub
                number = file_info.number
            cn_word_icon = "🀄️" if has_sub else ""
            signal.show_log_text(f"   发现新番号：{number:<10} {cn_word_icon}")
        temp_number = re.findall(r"\d{3,}([a-zA-Z]+-\d+)", number)  # 去除前缀，因为 javdb 不带前缀
        number = temp_number[0] if temp_number else number
        local_movies[movie.as_posix()] = (number, has_sub)  # 用新表，更新完重新写入到本地文件中
        Flags.local_number_set.add(number)  # 添加到本地番号集合
        if has_sub:
            Flags.local_number_cnword_set.add(number)  # 添加到本地有字幕的番号集合

        await _try_write_cache_async(
            local_number_list,
            json.dumps(
                local_movies,
                ensure_ascii=False,
                sort_keys=True,
                indent=4,
                separators=(",", ": "),
            ),
            start_time,
        )
    signal.show_log_text(f"🎉 获取完毕！共获取番号数量（{len(local_movies)}）({get_used_time(start_time_local)}s)")

    # 查询演员番号
    if manager.config.actors_name:
        raw_list = re.split(r"[,，]", manager.config.actors_name)
        actor_entries = [_parse_actor_entry(e) for e in raw_list if e.strip()]
        summary = ", ".join(f"{n}({t})" if t != "有码" else n for n, t in actor_entries)
        signal.show_log_text(
            f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n🔍 需要查询的演员：\n   {summary}"
        )
        rotator = _JavbusRotator()
        for actor_name, actor_type in actor_entries:
            signal.show_log_text(
                f"\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n⏳ 查询 [ {actor_name} ]({actor_type}) 的所有番号列表..."
            )
            try:
                net_numbers = await _fetch_actor_numbers(actor_name, actor_type, rotator)
            except Exception as e:
                signal.show_log_text(f"   查询出错: {e}")
                continue
            if net_numbers:
                await _show_actor_missing_numbers(actor_name, actor_type, net_numbers)
            else:
                signal.show_log_text(f"\n🔴 未找到 [ {actor_name} ] 的作品，请检查演员名或类型标注是否正确")
    else:
        signal.show_log_text("\n🔴 没有要查询的演员！")

    signal.show_log_text(f"\n🎉 查询完毕！共用时({get_used_time(start_time)}s)")
    signal.reset_buttons_status.emit()
