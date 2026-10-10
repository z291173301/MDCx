"""议题 #157 回归: 演员列表角色过滤 + 统计栏「重复」分项。

根因背景: Emby /Persons 端点不支持按角色类型过滤 (官方 API 参考: personTypes 仅在
配合 Person 参数时生效), 服务端把导演/编剧/制片等非演出角色一并返回——此前软件
"只看演员"开关对 Emby 从未生效 (用户拿 PersonType=Actor 的 14519 对比软件 13569
暴露此问题, 且两边其实都没过滤成功)。修复: 与「所选库(缺省全库)影片 People 中
角色=Actor 的人名集合」交集过滤; 出演统计失败 (集合为空) 时不过滤兜底。

同时 raw_count 语义修正为「过滤后、去重前」条目数, 统计栏新增「重复」分项
= raw_count − 唯一名字数 (议题 #157 诉求 1)。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

pytestmark = pytest.mark.asyncio

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _person(name: str) -> dict:
    # 带 Overview 键 → fetch_all_actors 复用列表字段, 不发逐人详情请求 (测试免网络)
    return {"Name": name, "Id": f"id-{name}", "ServerId": "srv", "Overview": "简介"}


def _key(name: str) -> str:
    """fetch_person_item_stats 返回的三个映射现在以去重键为键(议题 #164)。"""
    from mdcx.tools.emby_actor_manager import _actor_dedup_key

    return _actor_dedup_key(name)


async def _run_fetch(
    monkeypatch, persons: list[dict], lib_actor_names: set[str], *, filter_actor_only, deduplicate, parent_ids=None
):
    from mdcx.tools import emby_actor_manager as mgr_mod

    async def fake_list(filter_actor_only=True):
        return persons

    async def fake_stats(parent_ids=None, filter_actor_only=True, page_limit=500):
        keys = {_key(n) for n in lib_actor_names}
        counts = dict.fromkeys(keys, 1)
        return counts, {n: ["[Movie] x"] for n in keys}, keys

    monkeypatch.setattr(mgr_mod, "get_emby_actor_list", fake_list)
    monkeypatch.setattr(mgr_mod, "fetch_person_item_stats", fake_stats)
    return await mgr_mod.fetch_all_actors(
        filter_actor_only=filter_actor_only, deduplicate=deduplicate, parent_ids=parent_ids
    )


async def test_role_filter_applies_without_parent_ids(monkeypatch):
    """Emby 服务端没过滤角色 → 客户端必须用 Actor 人名集合剔除导演/编剧。"""
    persons = [_person("演员A"), _person("导演B"), _person("编剧C"), _person("演员A")]
    actors, raw = await _run_fetch(monkeypatch, persons, {"演员A"}, filter_actor_only=True, deduplicate=True)
    assert [a.name for a in actors] == ["演员A"]
    assert raw == 2, "raw_count = 过滤后(剔导演/编剧)、去重前条目数"


async def test_empty_actor_name_set_skips_filtering(monkeypatch):
    """出演统计整体失败(集合为空)时不得过滤——兜底防误删 (#32 教训)。"""
    persons = [_person("演员A"), _person("导演B")]
    actors, raw = await _run_fetch(monkeypatch, persons, set(), filter_actor_only=True, deduplicate=True)
    assert {a.name for a in actors} == {"演员A", "导演B"}
    assert raw == 2


async def test_no_filter_when_both_switches_off(monkeypatch):
    """filter_actor_only=False 且未指定库 → 保持全量 (用户显式要所有 Person)。"""
    persons = [_person("演员A"), _person("导演B")]
    actors, raw = await _run_fetch(monkeypatch, persons, {"演员A"}, filter_actor_only=False, deduplicate=True)
    assert {a.name for a in actors} == {"演员A", "导演B"}
    assert raw == 2


async def test_library_filter_regression_kept(monkeypatch):
    """指定媒体库过滤的既有行为不回退: 不在所选库影片出演者被剔除。"""
    persons = [_person("演员A"), _person("库外演员B")]
    actors, raw = await _run_fetch(
        monkeypatch, persons, {"演员A"}, filter_actor_only=True, deduplicate=False, parent_ids=["lib1"]
    )
    assert [a.name for a in actors] == ["演员A"]
    assert raw == 1


async def test_deduplicate_off_keeps_duplicates_in_raw(monkeypatch):
    """去重开关关闭: 列表含同名条目, raw 与列表长度一致。"""
    persons = [_person("演员A"), _person("演员A")]
    actors, raw = await _run_fetch(monkeypatch, persons, {"演员A"}, filter_actor_only=True, deduplicate=False)
    assert [a.name for a in actors] == ["演员A", "演员A"]
    assert raw == 2


async def test_filter_off_with_library_subset_keeps_all_roles_in_lib(monkeypatch):
    """不勾选「仅演员」+ 子集库: 保留所选库内所有角色(含导演), 剔除库外人员。"""
    persons = [_person("演员A"), _person("导演B"), _person("库外演员C")]
    actors, raw = await _run_fetch(
        monkeypatch,
        persons,
        {"演员A", "导演B"},
        filter_actor_only=False,
        deduplicate=True,
        parent_ids=["lib1"],
    )
    assert {a.name for a in actors} == {"演员A", "导演B"}
    assert raw == 2


async def test_empty_stats_with_library_subset_warns_and_skips_filter(monkeypatch):
    """出演统计为空 + 子集库: 防误删兜底保留全量, 并发出警告(此前静默导致库过滤看似无效)。"""
    import mdcx.tools.emby_actor_manager as mgr_mod

    logs: list[str] = []
    monkeypatch.setattr(mgr_mod.signal, "show_log_text", logs.append)
    persons = [_person("演员A"), _person("库外演员B")]
    actors, raw = await _run_fetch(
        monkeypatch, persons, set(), filter_actor_only=True, deduplicate=True, parent_ids=["lib1"]
    )
    assert {a.name for a in actors} == {"演员A", "库外演员B"}
    assert raw == 2
    assert any("跳过" in msg and "过滤" in msg for msg in logs), f"兜底时必须警告, 实际日志: {logs}"


async def test_duplicate_gap_between_filter_modes_is_explained_by_removed_dupes(monkeypatch):
    """复现「不勾选重复41、勾选重复40」机理: 被角色过滤剔除的条目里含1条重复,
    则两档重复数差=剔除条目数−剔除唯一名数=1, 差值可逐项对账, 不是 bug。"""
    import mdcx.tools.emby_actor_manager as mgr_mod

    logs: list[str] = []
    monkeypatch.setattr(mgr_mod.signal, "show_log_text", logs.append)
    # 演员A×3(出演) + 导演B×2(未出演, 且B自身重名): 勾选剔除B的2条(R=2,U=1), 重复数差1
    persons = [_person("演员A"), _person("演员A"), _person("演员A"), _person("导演B"), _person("导演B")]
    actors_on, raw_on = await _run_fetch(
        monkeypatch, persons, {"演员A"}, filter_actor_only=True, deduplicate=True
    )
    assert raw_on == 3
    assert raw_on - len({a.name for a in actors_on}) == 2
    detail_on = next((m for m in logs if "重复明细" in m), None)
    assert detail_on is not None and "演员A(×3)" in detail_on and "重复条目=2" in detail_on
    skip = next((m for m in logs if "跳过" in m and "导演B" in m), None)
    assert skip is not None and "重复条目1条" in skip, f"剔除日志须点出被剔重名, 实际: {logs}"

    logs.clear()
    actors_off, raw_off = await _run_fetch(
        monkeypatch, persons, {"演员A", "导演B"}, filter_actor_only=False, deduplicate=True
    )
    assert raw_off == 5
    assert raw_off - len({a.name for a in actors_off}) == 3
    detail_off = next((m for m in logs if "重复明细" in m), None)
    assert detail_off is not None and "重复条目=3" in detail_off
    # 两档差 = 3 − 2 = 1 = 剔除2条 − 剔除1个名, 对账成立


# ==================== 统计栏「重复」分项 ====================


# ==================== 出演统计 Type 过滤门 + 脏数据容错 ====================


def _fake_items_response(items: list) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(json=lambda: {"Items": items, "TotalRecordCount": len(items)})


async def _run_stats(monkeypatch, items_pages: list[list], *, filter_actor_only, parent_ids=None):
    """直测 fetch_person_item_stats 的 Type 过滤门（_run_fetch 把它整个 mock 掉，盖不住这里）。"""
    import mdcx.tools.emby_actor_manager as mgr_mod

    pages = [_fake_items_response(p) for p in items_pages]
    calls = {"n": 0}

    async def fake_request(method, url, headers=None, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        if idx < len(pages):
            return pages[idx], ""
        return _fake_items_response([]), ""

    monkeypatch.setattr(mgr_mod, "_emby_request", fake_request)
    return await mgr_mod.fetch_person_item_stats(parent_ids=parent_ids, filter_actor_only=filter_actor_only)


def _people_item(name: str, people: list) -> dict:
    return {"Name": name, "Type": "Movie", "People": people}


async def test_actor_filter_keeps_guest_star_and_unknown_type(monkeypatch):
    """客串(GuestStar)是表演者必须保留；Type 缺失按 fail-open 保留；导演/编剧/制片剔除。"""
    items = [
        _people_item(
            "剧集S",
            [
                {"Name": "主演A", "Type": "Actor"},
                {"Name": "客串G", "Type": "GuestStar"},
                {"Name": "无类型N"},
                {"Name": "导演D", "Type": "Director"},
                {"Name": "编剧W", "Type": "Writer"},
                {"Name": "制片P", "Type": "Producer"},
            ],
        )
    ]
    counts, _titles, names = await _run_stats(monkeypatch, [items], filter_actor_only=True)
    assert names == {_key("主演A"), _key("客串G"), _key("无类型N")}
    assert set(counts) == {_key("主演A"), _key("客串G"), _key("无类型N")}


async def test_actor_filter_off_keeps_all_roles(monkeypatch):
    """不勾选时全部角色都进集合（含导演），供所选库交集使用。"""
    items = [
        _people_item(
            "电影M",
            [
                {"Name": "主演A", "Type": "Actor"},
                {"Name": "导演D", "Type": "Director"},
            ],
        )
    ]
    _counts, _titles, names = await _run_stats(monkeypatch, [items], filter_actor_only=False)
    assert names == {_key("主演A"), _key("导演D")}


async def test_malformed_entries_do_not_abort_stats(monkeypatch):
    """People 里的 null/非字典/空名脏条目只跳过，不能抛错中止整库统计。"""
    items = [
        _people_item(
            "电影M",
            [
                None,
                "junk",
                {"Type": "Actor"},
                {"Name": "", "Type": "Actor"},
                {"Name": "主演A", "Type": "Actor"},
            ],
        ),
        None,
        "junk-item",
        {"Name": "无People键"},
    ]
    counts, _titles, names = await _run_stats(monkeypatch, [items], filter_actor_only=True)
    assert names == {_key("主演A")}
    assert counts == {_key("主演A"): 1}


async def test_non_dict_json_body_treated_as_empty_page(monkeypatch):
    """服务端返回 JSON null/数组等非对象时当空页收尾，不抛 AttributeError。"""
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager as mgr_mod

    async def fake_request(method, url, headers=None, **kwargs):
        return SimpleNamespace(json=lambda: None), ""

    monkeypatch.setattr(mgr_mod, "_emby_request", fake_request)
    counts, _titles, names = await mgr_mod.fetch_person_item_stats(filter_actor_only=True)
    assert names == set()
    assert counts == {}


def _fake_self(show_unique: bool, raw_count: int, all_staff_count: int = 0):
    from types import SimpleNamespace

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    ns = SimpleNamespace(
        _show_unique=show_unique,
        _raw_count=raw_count,
        _all_staff_count=all_staff_count,
        lbl_all_staff=QLabel(),
        lbl_total=QLabel(),
        lbl_duplicate=QLabel(),
        lbl_has_both=QLabel(),
        lbl_missing_image=QLabel(),
        lbl_missing_info=QLabel(),
        lbl_missing_all=QLabel(),
        lbl_backdrop=QLabel(),
    )
    return ns, EmbyActorManagerDialog


def _make_actor(name: str, *, image: bool = True, overview: str = "简介"):
    from mdcx.tools.emby_actor_manager import ActorInfo

    return ActorInfo(
        name=name,
        actor_id=f"id-{name}",
        server_id="srv",
        has_image=image,
        has_overview=bool(overview),
        existing_overview=overview,
    )


def test_duplicate_stat_shows_raw_minus_unique():
    """重复数 = 过滤后条目数 − 唯一名字数; 与计数方式切换无关。"""
    _ensure_app()
    ns, dialog_cls = _fake_self(show_unique=False, raw_count=5)
    actors = [_make_actor("A"), _make_actor("A"), _make_actor("B"), _make_actor("C"), _make_actor("D")]
    dialog_cls._update_statistics(ns, actors)
    assert ns.lbl_duplicate.text() == "重复: 1"
    assert ns.lbl_total.text() == "演员: 5"
    assert ns.lbl_all_staff.text() == "总数: 0"

    ns2, _ = _fake_self(show_unique=True, raw_count=5)
    dialog_cls._update_statistics(ns2, actors)
    assert ns2.lbl_duplicate.text() == "重复: 1"
    assert ns2.lbl_total.text() == "演员: 4"


def test_duplicate_stat_zero_when_no_duplicates():
    _ensure_app()
    ns, dialog_cls = _fake_self(show_unique=False, raw_count=3)
    actors = [_make_actor(n) for n in "ABC"]
    dialog_cls._update_statistics(ns, actors)
    assert ns.lbl_duplicate.text() == "重复: 0"


def test_statistics_labels_include_duplicate_between_total_and_complete():
    """布局顺序锚定 (#157 诉求 1: 「总数 后面 完整 前面」)。"""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "mdcx/tools/emby_actor_manager_ui.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_build_actor_list")
    # ast.walk 不保证源码顺序, 按行号还原创建次序; 目标是 self.lbl_x (Attribute)
    labeled = sorted(
        (node.lineno, node.targets[0].attr)
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Attribute)
        and node.targets[0].attr.startswith("lbl_")
    )
    creation_order = [name for _, name in labeled]
    assert creation_order.index("lbl_duplicate") == creation_order.index("lbl_total") + 1
