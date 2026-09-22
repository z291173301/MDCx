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


async def _run_fetch(
    monkeypatch, persons: list[dict], lib_actor_names: set[str], *, filter_actor_only, deduplicate, parent_ids=None
):
    from mdcx.tools import emby_actor_manager as mgr_mod

    async def fake_list(filter_actor_only=True):
        return persons

    async def fake_stats(parent_ids=None, filter_actor_only=True, page_limit=500):
        counts = dict.fromkeys(lib_actor_names, 1)
        return counts, {n: ["[Movie] x"] for n in lib_actor_names}, lib_actor_names

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


# ==================== 统计栏「重复」分项 ====================


def _fake_self(show_unique: bool, raw_count: int):
    from types import SimpleNamespace

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    ns = SimpleNamespace(
        _show_unique=show_unique,
        _raw_count=raw_count,
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
    assert ns.lbl_total.text() == "总数: 5"

    ns2, _ = _fake_self(show_unique=True, raw_count=5)
    dialog_cls._update_statistics(ns2, actors)
    assert ns2.lbl_duplicate.text() == "重复: 1"
    assert ns2.lbl_total.text() == "总数: 4"


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
