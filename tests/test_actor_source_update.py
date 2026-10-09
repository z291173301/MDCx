"""数据源测试「更新数据」按钮回归。

需求：获取头像/简介完成后，点更新数据把数据写回 Emby/Jellyfin 对应演员；
空字段保留服务器原数据，只有有具体值/图像的字段才更新；未连接时提示去
演员管理器主页面连接；未获取到数据时不执行。
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys  # noqa: E402

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing or QApplication(sys.argv)


@pytest.fixture
def dlg(app):
    from mdcx.tools.emby_actor_manager_ui import ActorSourceTestDialog

    dialog = ActorSourceTestDialog()
    dialog.show()
    app.processEvents()
    try:
        yield dialog
    finally:
        dialog.close()
        app.processEvents()


def _fake_info(**kw):
    from mdcx.models.emby import EMbyActressInfo

    base = dict(name="测试演员", server_id="s", id="i")
    base.update(kw)
    return EMbyActressInfo(**base)


def test_update_button_next_to_fetch_button(dlg):
    """更新数据按钮与获取头像和简介按钮在同一行，紧邻右侧。"""
    assert isinstance(dlg.btn_update, QPushButton)
    assert dlg.btn_update.text() == "更新数据"
    assert dlg.btn_update.parent() is dlg.btn_both.parent()


def test_is_blank(dlg):
    blank = dlg._is_blank
    assert blank(None) and blank("") and blank("   ")
    assert blank("0000-00-00") and blank("0000")
    assert blank([]) and blank({})
    assert not blank("三上悠亚")
    assert not blank("1993-08-16") and not blank("2015")
    assert not blank(["东京"])


def test_no_snapshot_no_update(dlg):
    """无任何已获取数据时门控为 False，更新不会执行。"""
    dlg._fetched_name = ""
    dlg._fetched_avatar = None
    dlg._fetched_info = None
    assert dlg._has_fetched_data() is False


def test_only_avatar_counts(dlg):
    """只有头像文件也算拿到数据（可单独更新头像）。"""
    dlg._fetched_avatar = __file__  # 本文件一定存在，仅借 path 存在性
    assert dlg._has_fetched_data() is True
    dlg._fetched_avatar = None


def test_empty_info_does_not_count(dlg):
    """信息对象全空（占位零值）不算拿到数据。"""
    dlg._fetched_avatar = None
    dlg._fetched_info = _fake_info()
    assert dlg._has_fetched_data() is False


def test_partial_info_counts(dlg):
    """任一字段有具体值即算拿到数据。"""
    dlg._fetched_avatar = None
    dlg._fetched_info = _fake_info(birthday="0000-00-00", year="0000", overview="一行简介")
    assert dlg._has_fetched_data() is True
    dlg._fetched_info = None


def _patch_server(monkeypatch, probe_ok=True, detail=None):
    import mdcx.tools.emby_actor_manager as mgr
    import mdcx.tools.emby_shared as shared

    async def _probe(url, headers=None):
        return ({"ServerName": "Emby"}, "") if probe_ok else (None, "conn refused")

    async def _detail(name):
        return detail

    captured = {}

    async def _sync(actor, sync_type="both"):
        captured["actor"] = actor
        captured["sync_type"] = sync_type
        return True, "✅ ok"

    monkeypatch.setattr(shared, "_emby_get_json", _probe)
    monkeypatch.setattr(mgr, "fetch_actor_detail", _detail)
    monkeypatch.setattr(mgr, "_sync_actor_async", _sync)
    return captured


def test_update_writes_only_nonempty(dlg, monkeypatch):
    """空字段不写入、保留服务器原数据；非空字段写入；现有值回填防 400。"""
    detail = {
        "Name": "测试演员",
        "Id": "a1",
        "ServerId": "s1",
        "Overview": "服务器旧简介",
        "Taglines": ["旧标签"],
        "ProductionYear": 2010,
        "PremiereDate": "2000-01-01T00:00:00.0000000Z",
        "ProductionLocations": ["旧出生地"],
        "ProviderIds": {"imdb": "nm1"},
        "Genres": ["g"],
        "Tags": ["t"],
    }
    captured = _patch_server(monkeypatch, probe_ok=True, detail=detail)
    ok, _msg = asyncio.run(
        dlg._do_update_async(
            "测试演员", None, "新简介", "0000-00-00", "0000", [], ["新标签"]
        )
    )
    assert ok is True
    actor = captured["actor"]
    assert captured["sync_type"] == "info"
    assert actor.new_overview == "新简介"
    assert actor.new_taglines == ["新标签"]
    # 空字段保持缺省，不覆盖服务器原数据
    assert actor.new_premiere_date == ""
    assert actor.new_production_year is None
    assert actor.new_production_locations == []
    assert actor.new_image_path is None
    assert actor.need_update_info is True
    assert actor.need_update_image is False
    # 服务器现有值必须回填（Genres/Tags/ProviderIds 空引用会导致 400）
    assert actor.existing_overview == "服务器旧简介"
    assert actor.existing_genres == ["g"]
    assert actor.existing_provider_ids == {"imdb": "nm1"}


def test_update_probe_fail_prompts_connect(dlg, monkeypatch):
    """连不上服务器时返回连接提示，不执行写入。"""
    captured = _patch_server(monkeypatch, probe_ok=False, detail=None)
    ok, msg = asyncio.run(dlg._do_update_async("测试演员", None, "新简介", "", "", [], []))
    assert ok is False
    assert "演员管理器主页面" in msg
    assert captured == {}


def test_update_actor_missing(dlg, monkeypatch):
    """服务器中没有该演员时明确提示，不执行写入。"""
    captured = _patch_server(monkeypatch, probe_ok=True, detail=None)
    ok, msg = asyncio.run(dlg._do_update_async("测试演员", None, "新简介", "", "", [], []))
    assert ok is False
    assert "未找到" in msg
    assert captured == {}
