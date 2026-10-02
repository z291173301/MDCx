"""信息管理页列表右键菜单文案回归测试。

需求：`NFO 列表右键菜单：重新刮削 / 打开所在目录 / 删除 NFO` 改为
`NFO 列表右键菜单：重新刮削番号 / 打开所在目录 / 删除nfo文件`。

本文件锁死三项菜单文案（含多选时「删除nfo文件（N 个）」的后缀拼接），改回旧措辞
即报红。相关文案同步范围见 `docs/Changelog.md` v2.2.0「界面调整」。

刻意不锁的三处（均非本菜单）：删除确认框标题「删除 NFO」、重新刮削输入框标题
「输入番号重新刮削」、刮削结果树右键菜单「  重新刮削\tN」。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QMenu

_app: QApplication | None = None

# 三个菜单项的期望文案（顺序即菜单中的顺序：标题行 → 重新刮削番号 → 打开所在目录 → 删除nfo文件）
_EXPECTED_TEXTS = ("重新刮削番号", "打开所在目录", "删除nfo文件")
# 本次改名前的旧文案（只有前两项改名，「打开所在目录」始终未变）
_OLD_TEXTS = ("重新刮削", "删除 NFO")


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.fixture()
def library(win, app, tmp_path):
    """两个 NFO 已加载进信息管理列表，并选中第一个（右键菜单的前置条件）。"""
    folder = tmp_path / "nfo_lib"
    folder.mkdir()
    for name in ("ABC-001", "ABC-002"):
        # 必须带 <title>：core/nfo.py 在缺 title 时返回 (None, None)
        (folder / f"{name}.nfo").write_text("<movie><title>T</title></movie>", encoding="utf-8")
        Image.new("RGB", (300, 420), (12, 34, 56)).save(folder / f"{name}-poster.jpg", quality=90)

    for index in range(win.Ui.stackedWidget.count()):
        page = win.Ui.stackedWidget.widget(index)
        if page.objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(index)
            break
    app.processEvents()

    win.Ui.lineEdit_nfo_lib_dir.setText(str(folder))
    win.pushButton_nfo_lib_refresh_clicked()
    deadline = time.time() + 10
    while time.time() < deadline and win.Ui.listWidget_nfo_lib.count() < 2:
        app.processEvents()
        time.sleep(0.02)
    assert win.Ui.listWidget_nfo_lib.count() == 2

    win.Ui.listWidget_nfo_lib.setCurrentRow(0)
    app.processEvents()
    assert win.Ui.listWidget_nfo_lib.selectedItems()
    return folder


def _context_menu(win, monkeypatch, app) -> QMenu:
    """调真实入口并截获弹出的菜单（exec 会阻塞，离屏直接替换掉）。"""
    from mdcx.controllers.main_window.nfo_library import listWidget_nfo_lib_context_menu

    captured: list[QMenu] = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *args, **kwargs: captured.append(self) or None)
    listWidget_nfo_lib_context_menu(win, QPoint(5, 5))
    app.processEvents()
    assert len(captured) == 1
    return captured[0]


def test_menu_item_texts(library, win, app, monkeypatch):
    """三个菜单项文案：重新刮削番号 / 打开所在目录 / 删除nfo文件。"""
    menu = _context_menu(win, monkeypatch, app)
    # 末尾两项是分隔线（空文本），首个是标题行（番号 / 已选择 N 项）
    texts = [action.text() for action in menu.actions() if action.text()]
    assert tuple(texts[1:]) == _EXPECTED_TEXTS
    assert texts[0] == "ABC-001"
    # 列表成员判定为精确匹配：「重新刮削」不会误判成「重新刮削番号」的前缀
    for old in _OLD_TEXTS:
        assert old not in texts


def test_delete_text_keeps_count_suffix(library, win, app, monkeypatch):
    """多选时删除项仍是「删除nfo文件（N 个）」。"""
    win.Ui.listWidget_nfo_lib.selectAll()
    app.processEvents()
    menu = _context_menu(win, monkeypatch, app)
    texts = [action.text() for action in menu.actions() if action.text()]
    assert texts[0] == "已选择 2 项"
    assert "删除nfo文件（2 个）" in texts


def test_menu_docstring_matches_texts():
    """函数 docstring 与实际菜单文案一致（文档不会与实现脱节）。"""
    import inspect

    from mdcx.controllers.main_window.nfo_library import listWidget_nfo_lib_context_menu

    doc = inspect.getdoc(listWidget_nfo_lib_context_menu) or ""
    for text in _EXPECTED_TEXTS:
        assert text in doc
    # 「重新刮削」是新文案「重新刮削番号」的前缀，子串判定会误报，故只判「删除 NFO」
    assert "删除 NFO" not in doc
