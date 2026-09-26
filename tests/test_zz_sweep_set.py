"""一次性 sweep：合集行(h114) vs 片商行(h138) 在各宽度下的 x/宽/间距/视口。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication, QCheckBox

_app = None


def _ensure_app():
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


def _goto(win, app, page_name):
    for i in range(win.Ui.stackedWidget.count()):
        if win.Ui.stackedWidget.widget(i).objectName() == page_name:
            win.Ui.stackedWidget.setCurrentIndex(i)
            app.processEvents()
            return win.Ui.stackedWidget.widget(i)
    raise AssertionError(f"page not found: {page_name}")


def _goto_nfo(win, app):
    _goto(win, app, "page_setting")
    for i in range(win.Ui.tabWidget.count()):
        if win.Ui.tabWidget.widget(i).findChild(QCheckBox, "checkBox_nfo_genre") is not None:
            win.Ui.tabWidget.setCurrentIndex(i)
            break
    app.processEvents()


def test_zz_sweep_set(win, app):
    ui = win.Ui
    genre = ui.checkBox_nfo_genre
    aset = ui.checkBox_nfo_actor_set
    sset = ui.checkBox_nfo_set
    studio = ui.checkBox_nfo_studio
    maker = ui.checkBox_nfo_maker
    publ = ui.checkBox_nfo_publisher
    lines = []
    for w in (1000, 1089, 1400, 1900):
        win.resize(w, 1050)
        win.show()
        _goto_nfo(win, app)
        app.processEvents()
        win._sync_page_layouts()
        app.processEvents()
        vp = ui.scrollArea_13.viewport().width()
        h114 = ui.horizontalLayout_114
        h138 = ui.horizontalLayout_138
        lines.append(
            f"W={w} vp={vp} sp114={h114.spacing()} sp138={h138.spacing()}\n"
            f"  genre.x={genre.x()} w={genre.width()} | "
            f"aset.x={aset.x()} w={aset.width()} | "
            f"sset.x={sset.x()} w={sset.width()}\n"
            f"  studio.x={studio.x()} w={studio.width()} | "
            f"maker.x={maker.x()} w={maker.width()} | "
            f"publ.x={publ.x()} w={publ.width()}\n"
            f"  d_aset_maker={aset.x()-maker.x()} d_set_publ={sset.x()-publ.x()}\n"
        )
    with open(
        "C:/Users/ZhouHan/AppData/Local/Temp/opencode/sweep_set.txt", "w", encoding="utf-8"
    ) as f:
        f.write("\n".join(lines))
    assert True
