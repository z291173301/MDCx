"""议题 #127 回归: 演员管理器「获取数据」按模式筛子集, 不再逐人遍历全库。

验证两层:
1. PreparePreviewThread.select_targets 纯函数——各模式下子集成员正确
   (「缺失」类只挑缺失字段者, 占位简介按缺简介处理, force 类取全量)。
2. _try_fetch_info 不再对已有简介的演员发 fetch_actor_detail 网络核对,
   判定全部基于列表阶段带回的 have/existing 数据。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _make_actor(name: str, *, image: bool, overview: str = ""):
    from mdcx.tools.emby_actor_manager import ActorInfo

    return ActorInfo(
        name=name,
        actor_id=f"id-{name}",
        server_id="srv",
        has_image=image,
        has_overview=bool(overview),
        existing_overview=overview,
    )


@pytest.fixture
def actors():
    return [
        _make_actor("完整", image=True, overview="正常简介"),
        _make_actor("缺头像", image=False, overview="正常简介"),
        _make_actor("缺简介", image=True, overview=""),
        _make_actor("都缺", image=False, overview=""),
        _make_actor("占位简介", image=True, overview="无维基百科信息"),
        _make_actor("占位简介缺图", image=False, overview="无维基百科信息"),
    ]


def _names(result):
    return sorted(a.name for a in result)


def test_missing_image_only_actors_without_image(actors):
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    got = PreparePreviewThread.select_targets(actors, "missing_image")
    assert _names(got) == ["占位简介缺图", "缺头像", "都缺"]


def test_missing_info_includes_placeholder_overview(actors):
    """占位简介（无维基百科信息）按缺简介处理; 正常简介永不重查。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    got = PreparePreviewThread.select_targets(actors, "missing_info")
    assert _names(got) == ["占位简介", "占位简介缺图", "缺简介", "都缺"]


def test_missing_all_is_union_not_intersection(actors):
    """「缺失头像或缺失简介」的语义 = 缺任一字段者都处理, 完整者除外。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    got = PreparePreviewThread.select_targets(actors, "missing_all")
    assert _names(got) == ["占位简介", "占位简介缺图", "缺头像", "缺简介", "都缺"]


def test_force_modes_take_everyone(actors):
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    for mode in ("force_all", "force_image", "force_info"):
        got = PreparePreviewThread.select_targets(actors, mode)
        assert _names(got) == _names(actors), mode


def test_select_targets_returns_new_list_for_force(actors):
    """force 模式返回副本, 调用方增删不影响原表。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    got = PreparePreviewThread.select_targets(actors, "force_all")
    assert got is not actors


async def _call_try_fetch_info(actor, *, force, search_mock):
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    fake_self = SimpleNamespace(_INFO_PLACEHOLDER=PreparePreviewThread._INFO_PLACEHOLDER)
    with patch("mdcx.tools.emby_actor_manager_ui.search_actor_info", search_mock):
        await PreparePreviewThread._try_fetch_info(fake_self, actor, force)


async def test_try_fetch_info_skips_actor_with_normal_overview():
    """已有正常简介: 直接跳过, 不搜源、不核对服务器。"""
    search_mock = AsyncMock(return_value=False)
    actor = _make_actor("完整", image=True, overview="正常简介")
    await _call_try_fetch_info(actor, force=False, search_mock=search_mock)
    assert search_mock.await_count == 0


def test_try_fetch_info_no_longer_requeries_server():
    """回归 #127: _try_fetch_info 源码中不得再出现 fetch_actor_detail 逐人网络核对,
    且 ui 模块整体不再导入该符号 (判定已前移到 select_targets)。"""
    import ast
    import inspect

    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    src = inspect.getsource(PreparePreviewThread._try_fetch_info)
    body = ast.parse(src.replace("    async def", "async def", 1))
    called = {n.func.id for n in ast.walk(body) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "fetch_actor_detail" not in called, "_try_fetch_info 不得再核对服务器"

    import mdcx.tools.emby_actor_manager_ui as ui_mod

    assert not hasattr(ui_mod, "fetch_actor_detail"), "ui 模块整体不应再导入 fetch_actor_detail"


async def test_try_fetch_info_requeries_placeholder_overview():
    """占位简介: 视为缺失继续搜源 (重补全是既有有意设计)。"""
    search_mock = AsyncMock(return_value=True)
    actor = _make_actor("占位简介", image=True, overview="无维基百科信息")
    await _call_try_fetch_info(actor, force=False, search_mock=search_mock)
    assert search_mock.await_count == 1
    assert actor.need_update_info


async def test_try_fetch_info_force_ignores_existing(actors):
    """force 模式无视已有简介照常重查 (用户显式重新获取)。"""
    search_mock = AsyncMock(return_value=False)
    complete = actors[0]
    await _call_try_fetch_info(complete, force=True, search_mock=search_mock)
    assert search_mock.await_count == 1


def test_statistics_classes_share_missing_predicates(actors):
    """议题 #147: 统计栏分项与「获取数据」模式用同一缺失判定, 避免计数漂移。

    占位简介(「无维基百科信息」)必须计入「缺简介」而非「完整」, 否则统计栏
    与 missing_all 并集(select_targets)口径不一致 —— 用户截图"统计 7404 vs 并集 7257"即此根因。
    """
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    is_mi, is_mn = PreparePreviewThread._is_missing_image, PreparePreviewThread._is_missing_info
    has_both = [a for a in actors if not is_mn(a) and not is_mi(a)]
    has_image_only = [a for a in actors if is_mi(a) and not is_mn(a)]  # 有简介、缺头像
    has_info_only = [a for a in actors if not is_mi(a) and is_mn(a)]  # 有头像、缺简介
    has_none = [a for a in actors if is_mi(a) and is_mn(a)]  # 都缺

    # 四类互斥且完整覆盖全体(合计 == 总数)
    assert sum(len(x) for x in (has_both, has_image_only, has_info_only, has_none)) == len(actors)
    assert sorted(a.name for a in has_both) == ["完整"]
    assert sorted(a.name for a in has_image_only) == ["缺头像"]
    assert sorted(a.name for a in has_info_only) == ["占位简介", "缺简介"]
    assert sorted(a.name for a in has_none) == ["占位简介缺图", "都缺"]

    # 统计的「缺失」分项并集 == missing_all 取数候选: 二者都来自 _is_missing_info/_is_missing_image,
    # 保证用户在统计栏看到的分项之和 = 选「缺失头像或缺失简介」时实际取出的人数。
    union = PreparePreviewThread.select_targets(actors, "missing_all")
    assert sorted(a.name for a in has_image_only + has_info_only + has_none) == _names(union)


# ==================== 议题 #155: 「且都缺(交集)」独立入口 ====================


def test_missing_both_is_intersection(actors):
    """交集模式只取「头像和简介都缺」者, 含占位简介缺图者; 单缺/完整一律排除。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    got = PreparePreviewThread.select_targets(actors, "missing_both")
    assert _names(got) == ["占位简介缺图", "都缺"]


def test_missing_both_equals_statistics_all_missing_class(actors):
    """交集候选必然等于统计栏「全缺」分项——同一对判定函数, 口径一致 (#147 延续)。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    is_mi, is_mn = PreparePreviewThread._is_missing_image, PreparePreviewThread._is_missing_info
    all_missing = [a for a in actors if is_mi(a) and is_mn(a)]
    assert _names(PreparePreviewThread.select_targets(actors, "missing_both")) == _names(all_missing)


def test_missing_both_thread_fetches_both_fields():
    """交集模式的取数线程必须同时开头像与简介两路 (need_image/need_info 都含 missing_both)。"""
    import ast
    import inspect

    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    fn = next(
        n
        for n in ast.walk(ast.parse(inspect.getsource(PreparePreviewThread)))
        if isinstance(n, ast.FunctionDef) and n.name == "run"
    )
    flags: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if target in ("need_image", "need_info") and isinstance(node.value, ast.Compare):
                comps = node.value.comparators
                if len(comps) == 1 and isinstance(comps[0], ast.Tuple):
                    flags[target] = {e.value for e in comps[0].elts if isinstance(e, ast.Constant)}
    assert "missing_both" in flags.get("need_image", set()), "交集模式须取头像"
    assert "missing_both" in flags.get("need_info", set()), "交集模式须取简介"


def test_fetch_mode_dropdown_map_tooltip_in_sync():
    """下拉项、mode_map、tooltip 三处一一对账: 新增/改名模式漏任何一处即红。"""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "mdcx" / "tools" / "emby_actor_manager_ui.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    items: list[str] = []
    tooltip_indexes: set[int] = set()
    mode_map_keys: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "addItems" and node.args:
                for arg in node.args:
                    if isinstance(arg, ast.List) and any(
                        isinstance(e, ast.Constant) and e.value == "缺失头像或缺失简介" for e in arg.elts
                    ):
                        items = [e.value for e in arg.elts if isinstance(e, ast.Constant)]
            # 只统计获取模式下拉的 tooltip: setItemData 的 receiver 为 self.cmb_fetch_mode
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "setItemData"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "cmb_fetch_mode"
            ):
                tooltip_indexes.add(node.args[0].value)
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "mode_map"
            and isinstance(node.value, ast.Dict)
        ):
            mode_map_keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]

    assert "头像和简介都缺" in items
    assert items == mode_map_keys, "下拉项与 mode_map 必须一一对应且同序"
    assert tooltip_indexes == set(range(len(items))), "每个下拉项都必须有 tooltip"


# ==================== 议题 #164: 重排/默认锚定/仅简介重新获取模式 ====================


def test_force_overview_takes_everyone(actors):
    """「重新获取所有演员简介」(force_overview) 不筛缺失, 取全量。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    got = PreparePreviewThread.select_targets(actors, "force_overview")
    assert _names(got) == _names(actors)


async def test_force_overview_clears_non_overview_fields():
    """force_overview 取数后清空其余 new_* 字段——同步出口按真值写入, 只回写简介。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    actor = _make_actor("完整", image=True, overview="正常简介")

    async def _fake_search(a, wiki_intro=""):
        a.new_overview = "新简介"
        a.new_taglines = ["t"]
        a.new_premiere_date = "1990-01-01"
        a.new_production_year = 1990
        a.new_production_locations = ["jp"]
        a.new_provider_ids = {"imdb": "x"}
        return True

    from types import SimpleNamespace

    with patch("mdcx.tools.emby_actor_manager_ui.search_actor_info", _fake_search):
        fake_self = SimpleNamespace(_INFO_PLACEHOLDER=PreparePreviewThread._INFO_PLACEHOLDER, mode="force_overview")
        await PreparePreviewThread._try_fetch_info(fake_self, actor, True)

    assert actor.new_overview == "新简介"
    assert actor.new_taglines == []
    assert actor.new_premiere_date == ""
    assert actor.new_production_year is None
    assert actor.new_production_locations == []
    assert actor.new_provider_ids == {}
    assert actor.need_update_info is True


async def test_force_overview_no_overview_found_not_marked():
    """force_overview 下简介没取到: 不标记待同步(避免空简介覆盖服务器)。"""
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    actor = _make_actor("完整", image=True, overview="正常简介")

    async def _fake_search(a, wiki_intro=""):
        return False

    from types import SimpleNamespace

    with patch("mdcx.tools.emby_actor_manager_ui.search_actor_info", _fake_search):
        fake_self = SimpleNamespace(_INFO_PLACEHOLDER=PreparePreviewThread._INFO_PLACEHOLDER, mode="force_overview")
        await PreparePreviewThread._try_fetch_info(fake_self, actor, True)

    assert actor.need_update_info is False


def test_default_fetch_mode_is_union_after_reorder():
    """#164 重排后默认项显式锚定「缺失头像或缺失简介」(index 3), 不改默认行为。"""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "mdcx/tools/emby_actor_manager_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    items: list[str] = []
    set_current: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        f = node.func
        if f.attr == "addItems" and node.args and isinstance(node.args[0], ast.List):
            elts = [e.value for e in node.args[0].elts if isinstance(e, ast.Constant)]
            if "缺失头像或缺失简介" in elts:
                items = elts
        if (
            f.attr == "setCurrentIndex"
            and isinstance(f.value, ast.Attribute)
            and f.value.attr == "cmb_fetch_mode"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            set_current.append(node.args[0].value)
    assert items[3] == "缺失头像或缺失简介"
    assert set_current == [3], f"默认项须锚定并集 index 3, 实际: {set_current}"
