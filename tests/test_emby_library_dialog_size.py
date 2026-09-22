"""议题 #146 回归: 选择媒体库对话框按库数自适应初始尺寸。

旧实现仅设最小尺寸 420x320, 从未 resize(), 25 个库只露出 ~7 行。
现初始高度按 min(库数, 20) 行计算, 宽按 16:9, 双向钳制到屏幕可用区 85%。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _make_libs(n: int) -> list[dict]:
    return [{"Id": f"lib-{i}", "Name": f"媒体库{i}", "CollectionType": "movies"} for i in range(n)]


def test_initial_size_20_rows_and_16_by_9():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    w, h = LibrarySelectDialog.initial_size(row_h=30, visible_rows=20, chrome_h=120, avail_w=1920, avail_h=1080)
    assert h == 120 + 20 * 30 + 12
    assert abs(w - round(h * 16 / 9)) <= 1


def test_initial_size_clamps_to_small_screen():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    w, h = LibrarySelectDialog.initial_size(row_h=30, visible_rows=20, chrome_h=120, avail_w=800, avail_h=450)
    assert w <= int(800 * 0.85)
    assert h <= int(450 * 0.85)
    assert w >= 420 and h >= 320


def test_initial_size_floors_to_minimum():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    w, h = LibrarySelectDialog.initial_size(row_h=10, visible_rows=1, chrome_h=40, avail_w=1920, avail_h=1080)
    assert (w, h) == (420, 320)


def test_initial_size_fewer_rows_shrinks_height():
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    _, h_big = LibrarySelectDialog.initial_size(row_h=30, visible_rows=20, chrome_h=120, avail_w=1920, avail_h=1080)
    _, h_small = LibrarySelectDialog.initial_size(row_h=30, visible_rows=5, chrome_h=120, avail_w=1920, avail_h=1080)
    assert h_small < h_big


def test_dialog_resizes_beyond_minimum_on_large_screen(monkeypatch):
    """集成: 25 库 + 1920x1080 屏 → 明显大于旧 420x320 最小尺寸。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(25))
    assert dlg.width() > 420, "宽应随 16:9 放宽"
    assert dlg.height() > 320
    # 全库上限场景: 不低于 20 行按实际行高(议题 #156 起取真实行高, 不再用 26px 估算下限)的高度
    assert dlg.height() >= 20 * dlg.list_widget.sizeHintForRow(0)


def test_dialog_clamps_on_small_screen(monkeypatch):
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 800, 450))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(25))
    assert dlg.width() <= int(800 * 0.85)
    assert dlg.height() <= int(450 * 0.85)
    assert dlg.width() >= 420 and dlg.height() >= 320


def test_dialog_few_libraries_not_taller(monkeypatch):
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    big = LibrarySelectDialog(_make_libs(24))
    small = LibrarySelectDialog(_make_libs(2))
    assert small.height() < big.height()


def _make_libs_mixed(n: int, boxsets: int) -> list[dict]:
    libs = _make_libs(n)
    libs += [{"Id": f"box-{i}", "Name": f"合集{i}", "CollectionType": "boxsets"} for i in range(boxsets)]
    return libs


def test_boxsets_hidden_by_default():
    """议题 #156: 合集(boxsets)是 Emby 自动创建的空壳库(无演员/标签), 默认不展示。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    dlg = LibrarySelectDialog(_make_libs_mixed(24, 1))
    assert dlg._hidden_boxsets == 1
    assert dlg.list_widget.count() == 24
    assert len(dlg.get_selected_ids()) == 24
    assert all(not lid.startswith("box-") for lid in dlg.get_selected_ids())


def test_boxsets_only_falls_back_to_original_list():
    """议题 #156: 极端情况——全部库都是合集时回退展示原始列表, 避免空对话框。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    dlg = LibrarySelectDialog(_make_libs_mixed(0, 3))
    assert dlg.list_widget.count() == 3


def test_row_height_pinned_to_checkbox():
    """议题 #156: 行高由 item 显式 sizeHint 钉死为复选框高度——此前从未设置 sizeHint,
    行高由默认代理字号决定、与预算行高无确定关系, Windows 上 20 行预算只容得下 19 行。"""
    _ensure_app()
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    dlg = LibrarySelectDialog(_make_libs(25))
    cb_h = dlg._checkboxes[0].sizeHint().height()
    assert dlg.list_widget.item(0).sizeHint().height() == cb_h
    assert dlg.list_widget.sizeHintForRow(0) == cb_h


def test_twenty_rows_fully_visible_on_large_screen(monkeypatch):
    """议题 #156 集成回归: 25 库 + 1920x1080 → 视口至少完整容纳 20 行。"""
    _ensure_app()
    from types import SimpleNamespace

    import mdcx.tools.emby_actor_manager_ui as ui_mod
    from mdcx.tools.emby_actor_manager_ui import LibrarySelectDialog

    fake_screen = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(ui_mod, "QGuiApplication", SimpleNamespace(primaryScreen=lambda: fake_screen))

    dlg = LibrarySelectDialog(_make_libs(25))
    dlg.show()
    row_h = dlg.list_widget.sizeHintForRow(0)
    assert row_h > 0
    assert dlg.list_widget.viewport().height() // row_h >= 20
