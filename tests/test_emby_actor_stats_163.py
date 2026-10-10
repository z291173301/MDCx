"""议题 #163: 演员管理器统计栏 8 个计数器(总数/演员/重复/完整/缺头像/缺简介/全缺/有背景图)的回归测试。

真实 Emby 服务器(192.168.0.101:8096)全量审查结论见 docs/Changelog.md:
  - 已修 bug: is_missing_overview / _fill / _on_clean_actor_done 未 strip, 纯空白简介被算成「有简介」;
             ActorSourceTestDialog._do_update_async 不回填 has_image/has_overview;
             首次打开对话框 8 个标签没有任何数字; _update_statistics 有重复的 _show_unique 分支;
             「有背景图」提示文案对基数的描述与实际不符。
  - 已证伪(非 bug): 演员/重复/四项分拆的算术在「勾选/不勾选仅演员」×「去重/不去重」×
    「原始条目数/唯一名字数」共 8 种组合下都与服务器 ground-truth 完全一致。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_app = None


def _ensure_app():
    """QApplication 必须存进模块级强引用。

    只 `return QApplication.instance() or QApplication([])` 的话, 返回瞬间引用计数归零,
    PyQt 会连带析构 C++ 侧的 QApplication, 紧接着创建的 QLabel 直接触发原生崩溃
    (pytest 下表现为无堆栈的 STATUS_STACK_BUFFER_OVERRUN)。
    """
    global _app
    if _app is None:
        from PyQt6.QtWidgets import QApplication

        _app = QApplication.instance() or QApplication([])
    return _app


def _actor(name, *, image=True, overview="简介", backdrop=False, actor_id=None, server_id="srv"):
    from mdcx.tools.emby_actor_manager import ActorInfo

    return ActorInfo(
        name=name,
        actor_id=actor_id or f"id-{name}",
        server_id=server_id,
        has_image=image,
        has_overview=bool(overview),
        existing_overview=overview,
        has_backdrop=backdrop,
    )


def _fake_self(show_unique: bool, raw_count: int, all_staff_count: int = 0, actors=None):
    from PyQt6.QtWidgets import QLabel

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    ns = SimpleNamespace(
        _show_unique=show_unique,
        _raw_count=raw_count,
        _all_staff_count=all_staff_count,
        _actors=actors if actors is not None else [],
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


def _stats(ns):
    """把 8 个标签还原成 {名称: 数字}。"""
    out = {}
    for key in (
        "lbl_all_staff",
        "lbl_total",
        "lbl_duplicate",
        "lbl_has_both",
        "lbl_missing_image",
        "lbl_missing_info",
        "lbl_missing_all",
        "lbl_backdrop",
    ):
        label = getattr(ns, key).text()
        name, _, value = label.rpartition(":")
        out[name] = int(value.strip())
    return out


# --------------------------------------------------------------------------
# is_missing_overview: 纯空白简介必须按「缺简介」处理
# --------------------------------------------------------------------------


def test_whitespace_only_overview_counts_as_missing():
    """纯空白简介(空格/换行/制表/全角空格)等价于没有简介, 不得算进「完整」。"""
    from mdcx.tools.emby_actor_manager import is_missing_overview

    for blank in ("   ", "\n", "\t\n ", "\r\n", "　", " \n\t "):
        info = _actor("A", overview=blank)
        info.has_overview = True  # 权威位为真, 但正文全是空白
        assert is_missing_overview(info) is True, blank
        assert is_missing_overview({"Overview": blank}) is True, blank


def test_empty_overview_text_without_flag_still_missing():
    """正文为空(非空白串)且权威位为真时仍信权威位; 权威位为假则一律按缺处理。"""
    from mdcx.tools.emby_actor_manager import ActorInfo, is_missing_overview

    assert is_missing_overview({"Overview": ""}) is True
    assert is_missing_overview({"Overview": None}) is True
    assert is_missing_overview(ActorInfo(name="A", actor_id="i", server_id="s")) is True


def test_placeholder_overview_counts_as_missing():
    from mdcx.tools.emby_actor_manager import INFO_PLACEHOLDER, is_missing_overview

    info = _actor("A", overview=f"前言\n{INFO_PLACEHOLDER}")
    assert is_missing_overview(info) is True
    assert is_missing_overview({"Overview": INFO_PLACEHOLDER}) is True


def test_real_overview_counts_as_present():
    from mdcx.tools.emby_actor_manager import is_missing_overview

    assert is_missing_overview(_actor("A", overview="真实简介")) is False
    assert is_missing_overview({"Overview": "真实简介"}) is False


def test_has_overview_flag_stays_authoritative():
    """has_overview 是抓取/清洗/同步三处成对维护的权威位, 不因正文为空而改判为缺。

    `ActorInfo(has_overview=True)` 的 existing_overview 允许为空(详情接口可能只回布尔位),
    这是既有契约; 清洗出空简介时由 has_overview=False 表达, 不是靠正文长度。
    """
    from mdcx.tools.emby_actor_manager import ActorInfo, is_missing_overview

    info = ActorInfo(name="A", actor_id="i", server_id="s", has_overview=True)
    assert info.existing_overview == ""
    assert is_missing_overview(info) is False

    assert is_missing_overview(ActorInfo(name="A", actor_id="i", server_id="s")) is True


def test_missing_info_predicate_agrees_with_model_helper():
    """UI 的 _is_missing_info 必须与模型层 is_missing_overview 同口径。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager import is_missing_overview
    from mdcx.tools.emby_actor_manager_ui import PreparePreviewThread

    for overview in ("", "   ", "真实简介", "无维基百科信息"):
        info = _actor("A", overview=overview)
        info.has_overview = bool(overview.strip())
        assert PreparePreviewThread._is_missing_info(info) == is_missing_overview(info)


# --------------------------------------------------------------------------
# _fill: 抓到纯空白简介时不置 has_overview
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_all_actors_does_not_mark_blank_overview_as_present(monkeypatch):
    from mdcx.tools import emby_actor_manager as eam

    monkeypatch.setattr(
        eam,
        "get_emby_actor_list",
        _async_return([{"Name": "空白君", "Id": "p1", "ServerId": "s", "Type": "Person", "Overview": "   \n "}]),
    )
    monkeypatch.setattr(eam, "fetch_person_item_stats", _async_return(({}, {}, {"空白君"})))
    monkeypatch.setattr(eam, "fetch_actor_detail", _async_return(None))

    actors, _raw = await eam.fetch_all_actors(filter_actor_only=True)
    assert len(actors) == 1
    assert actors[0].has_overview is False
    assert eam.is_missing_overview(actors[0]) is True


# --------------------------------------------------------------------------
# 统计栏: 纯空白简介被算进 缺简介 / 全缺, 不进 完整
# --------------------------------------------------------------------------


def test_statistics_treats_blank_overview_as_missing():
    _ensure_app()
    actors = [
        _actor("完整君", image=True, overview="简介"),
        _actor("空白君", image=True, overview="   "),
        _actor("缺图君", image=False, overview="简介"),
        _actor("全缺君", image=False, overview="  \n"),
    ]
    for a in actors:
        a.has_overview = bool(a.existing_overview.strip())
    ns, dialog_cls = _fake_self(show_unique=True, raw_count=4, all_staff_count=9, actors=actors)
    dialog_cls._update_statistics(ns, actors)

    s = _stats(ns)
    assert s == {
        "总数": 9,
        "演员": 4,
        "重复": 0,
        "完整": 1,
        "缺头像": 1,
        "缺简介": 1,  # 空白君
        "全缺": 1,  # 全缺君(空白简介)
        "有背景图": 0,
    }


def test_statistics_partition_is_exhaustive_and_backdrop_within_base():
    """四项分拆必须是 base 的一个划分, 且有背景图不超过基数。"""
    _ensure_app()
    actors = []
    for i in range(30):
        actors.append(
            _actor(
                f"A{i}",
                image=bool(i % 2),
                overview=("简介" if i % 3 else "   "),
                backdrop=bool(i % 5),
            )
        )
    for a in actors:
        a.has_overview = bool(a.existing_overview.strip())

    for show_unique in (False, True):
        raw = len(actors) + 4 if not show_unique else len(actors)
        ns, dialog_cls = _fake_self(show_unique=show_unique, raw_count=raw, actors=actors)
        dialog_cls._update_statistics(ns, actors)
        s = _stats(ns)
        base = len(actors)
        assert s["完整"] + s["缺头像"] + s["缺简介"] + s["全缺"] == base
        assert s["有背景图"] <= base
        assert s["重复"] == max(raw - len({a.name for a in actors}), 0)


def test_statistics_empty_list_is_all_zero_and_survives_none():
    _ensure_app()
    ns, dialog_cls = _fake_self(show_unique=False, raw_count=0, all_staff_count=0)
    dialog_cls._update_statistics(ns, None)
    assert _stats(ns) == {
        "总数": 0,
        "演员": 0,
        "重复": 0,
        "完整": 0,
        "缺头像": 0,
        "缺简介": 0,
        "全缺": 0,
        "有背景图": 0,
    }


def test_statistics_duplicate_count_matches_tooltip_invariant():
    """原始条目数 + 去重抓取: 四项之和 + 重复 == 演员 (标签提示里写明的恒等式)。

    fetch_all_actors 去重后交给统计栏的列表本身已无同名重复, 故 base 大小 == 唯一名字数。
    """
    _ensure_app()
    actors = [_actor("A"), _actor("B"), _actor("C")]
    ns, dialog_cls = _fake_self(show_unique=False, raw_count=7, all_staff_count=7)
    dialog_cls._update_statistics(ns, actors)
    s = _stats(ns)
    assert s["演员"] == 7
    assert s["重复"] == 7 - 3
    assert s["完整"] + s["缺头像"] + s["缺简介"] + s["全缺"] + s["重复"] == s["演员"]


def test_statistics_backdrop_tooltip_does_not_claim_per_mode_rebase():
    """提示文案不得声称「唯一名字数模式按名字去重计数」—— 抓取已去重时两种模式同基数。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    source = _read_source()
    assert "唯一名字数模式按名字去重计数" not in source
    assert "与「完整/缺头像/缺简介/全缺」四项同基数统计" in source
    assert EmbyActorManagerDialog is not None


def _read_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "mdcx" / "tools" / "emby_actor_manager_ui.py").read_text(
        encoding="utf-8"
    )


def test_update_statistics_has_single_show_unique_branch():
    """去重后的实现只应有一个 `if self._show_unique:` 分支。"""
    source = _read_source()
    start = source.index("    def _update_statistics(self, actors: list[ActorInfo]):")
    end = source.index("    def _update_sync_button(self):", start)
    body = source[start:end]
    assert body.count("if self._show_unique:") == 1
    assert "total = unique_count" in body
    assert "total = self._raw_count if self._raw_count > 0 else len(actors)" in body


# --------------------------------------------------------------------------
# 清洗: 不允许「越清洗缺得越少」
# --------------------------------------------------------------------------


def test_clean_done_does_not_turn_blank_into_present():
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog, PreparePreviewThread

    actor = _actor("清洗君", overview="旧简介")
    ns = SimpleNamespace(
        _is_stale_session=lambda: False,
        _clean_failed=[],
        _clean_items={"id-清洗君": ("   \n", False)},
        _actors=[actor],
        log=lambda *_a, **_k: None,
    )
    EmbyActorManagerDialog._on_clean_actor_done(ns, "id-清洗君", True, "ok")
    assert actor.has_overview is False
    assert PreparePreviewThread._is_missing_info(actor) is True


def test_clean_done_marks_real_overview_present():
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog, PreparePreviewThread

    actor = _actor("清洗君", overview="")
    ns = SimpleNamespace(
        _is_stale_session=lambda: False,
        _clean_failed=[],
        _clean_items={"id-清洗君": ("新简介", False)},
        _actors=[actor],
        log=lambda *_a, **_k: None,
    )
    EmbyActorManagerDialog._on_clean_actor_done(ns, "id-清洗君", True, "ok")
    assert actor.has_overview is True
    assert PreparePreviewThread._is_missing_info(actor) is False


# --------------------------------------------------------------------------
# 数据源测试弹窗的单演员更新: 必须回填 has_image / has_overview
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_test_update_fills_has_flags_from_server_detail(monkeypatch):
    """服务器明明有简介, 却因为 has_overview 留空而被算成「缺简介」。"""
    from mdcx.tools import emby_actor_manager as eam
    from mdcx.tools import emby_actor_manager_ui as ui
    from mdcx.tools import emby_shared as es

    captured = {}

    async def fake_sync(actor, sync_type):
        captured["actor"] = actor
        return True, "ok"

    async def fake_detail(name):
        return {
            "Id": "p1",
            "ServerId": "s",
            "Name": "已有简介君",
            "Overview": "服务器上真实存在的简介",
            "ImageTags": {"Primary": "abc"},
        }

    async def fake_ping(*_a, **_k):
        return SimpleNamespace(status_code=200), ""

    monkeypatch.setattr(eam, "_sync_actor_async", fake_sync)
    monkeypatch.setattr(eam, "fetch_actor_detail", fake_detail)
    monkeypatch.setattr(es, "_emby_get_json", fake_ping)

    dialog = ui.ActorSourceTestDialog.__new__(ui.ActorSourceTestDialog)
    # overview 传空 => 本次不写简介; 用 taglines 满足「有内容才写」的前置条件。
    ok, msg = await ui.ActorSourceTestDialog._do_update_async(dialog, "已有简介君", None, "", "", "", [], ["新标签"])
    assert ok is True, msg
    actor = captured["actor"]
    assert actor.existing_overview == "服务器上真实存在的简介"
    assert actor.has_overview is True, "服务器已有简介却因 has_overview 留空被算成「缺简介」"
    assert actor.has_image is True
    assert ui.PreparePreviewThread._is_missing_info(actor) is False
    assert ui.PreparePreviewThread._is_missing_image(actor) is False


@pytest.mark.asyncio
async def test_source_test_update_blank_server_overview_is_missing(monkeypatch):
    from mdcx.tools import emby_actor_manager as eam
    from mdcx.tools import emby_actor_manager_ui as ui
    from mdcx.tools import emby_shared as es

    captured = {}

    async def fake_sync(actor, sync_type):
        captured["actor"] = actor
        return True, "ok"

    async def fake_detail(name):
        return {"Id": "p1", "ServerId": "s", "Name": "空白简介君", "Overview": "  ", "ImageTags": {}}

    async def fake_ping(*_a, **_k):
        return SimpleNamespace(status_code=200), ""

    monkeypatch.setattr(eam, "_sync_actor_async", fake_sync)
    monkeypatch.setattr(eam, "fetch_actor_detail", fake_detail)
    monkeypatch.setattr(es, "_emby_get_json", fake_ping)

    dialog = ui.ActorSourceTestDialog.__new__(ui.ActorSourceTestDialog)
    ok, msg = await ui.ActorSourceTestDialog._do_update_async(dialog, "空白简介君", None, "", "", "", [], ["新标签"])
    assert ok is True, msg
    actor = captured["actor"]
    # has_overview 描述「服务器当前有没有简介」, 纯空白 = 没有
    assert actor.has_overview is False
    assert ui.PreparePreviewThread._is_missing_info(actor) is True
    assert ui.PreparePreviewThread._is_missing_image(actor) is True


# --------------------------------------------------------------------------
# 首次打开: 8 个标签必须已经有数字
# --------------------------------------------------------------------------


def test_init_ui_populates_statistics_labels():
    """未抓取数据时 8 个标签必须已是「…: 0」, 而不是裸的「总数: 」。

    走真实构造(与 test_actor_manager_font_size 同路径), 因此顺带覆盖「打开即崩」。
    """
    app = _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    dialog = EmbyActorManagerDialog()
    try:
        app.processEvents()
        labels = {
            "总数": dialog.lbl_all_staff,
            "演员": dialog.lbl_total,
            "重复": dialog.lbl_duplicate,
            "完整": dialog.lbl_has_both,
            "缺头像": dialog.lbl_missing_image,
            "缺简介": dialog.lbl_missing_info,
            "全缺": dialog.lbl_missing_all,
            "有背景图": dialog.lbl_backdrop,
        }
        for name, label in labels.items():
            assert label.text() == f"{name}: 0", f"{name} 标签初始文本异常: {label.text()!r}"
    finally:
        dialog.close()
        app.processEvents()


def test_init_ui_populates_statistics_labels_in_unique_mode(monkeypatch):
    """「唯一名字数」档位下首次打开也必须填好数字, 不依赖用户先点一次下拉框。"""
    app = _ensure_app()
    from mdcx.config.manager import manager
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    monkeypatch.setattr(manager.config, "actor_count_mode", 1, raising=False)
    dialog = EmbyActorManagerDialog()
    try:
        app.processEvents()
        assert dialog._show_unique is True
        assert dialog.lbl_total.text() == "演员: 0"
        assert dialog.lbl_duplicate.text() == "重复: 0"
    finally:
        dialog.close()
        app.processEvents()


def _async_return(value):
    async def _fn(*_a, **_k):
        return value

    return _fn
