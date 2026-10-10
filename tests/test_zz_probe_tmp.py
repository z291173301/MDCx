import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PyQt6.QtWidgets import QApplication

_app = None


def _ensure_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture(scope="module")
def win(app, tmp_path_factory):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    orig_cwd = os.getcwd()
    tmp = str(tmp_path_factory.mktemp("probe"))
    os.chdir(tmp)
    orig = {}
    for name, fn in (
        ("run_startup_health_checks", lambda: None),
        ("show_netstatus", lambda *_a, **_k: None),
        ("check_version", lambda *_a, **_k: None),
        ("save_remain_list", lambda *_a, **_k: None),
        ("apply_site_priority_theme", lambda *_a, **_k: None),
    ):
        orig[name] = getattr(mw_mod, name)
        setattr(mw_mod, name, fn)
    orig_style = mw_mod.MyMAinWindow.set_style
    mw_mod.MyMAinWindow.set_style = lambda self: None
    orig_qtr = style_mod.resources.qtr
    style_mod.resources.qtr = lambda path: str(MAIN_PATH / "resources" / path)
    window = mw_mod.MyMAinWindow()
    for t in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        try:
            getattr(window, t).stop()
        except Exception:
            pass
    window.Ui.stackedWidget.setCurrentIndex(3)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()
    for name, fn in orig.items():
        setattr(mw_mod, name, fn)
    mw_mod.MyMAinWindow.set_style = orig_style
    style_mod.resources.qtr = orig_qtr
    os.chdir(orig_cwd)


def _resize(win, app, width, height=800):
    win.showNormal()
    win.resize(width, height)
    win.show()
    app.processEvents()
    win._sync_page_layouts()
    app.processEvents()


ROW = [
    "checkBox_actor_db_alias_all",
    "label_actor_db_sync_offset",
    "spinBox_actor_db_sync_offset",
    "label_actor_db_sync_limit",
    "spinBox_actor_db_sync_limit",
    "label_actor_db_sync_slice_hint",
]


def test_probe(win, app):
    from PyQt6.QtGui import QFontMetrics, QTextDocument

    ui = win.Ui
    for width in (760, 900, 1080, 1400, 1920):
        _resize(win, app, width)
        box = ui.groupBox_actor_db_maintenance
        row = [getattr(ui, n) for n in ROW]
        print(f"\n=== win {width} ===")
        print("  box geom:", box.geometry(), "boxW:", box.width())
        print("  row:", [(w.x(), w.width()) for w in row], "right:", row[-1].x() + row[-1].width())
        print("  overwrite x:", ui.checkBox_cover_backfill_overwrite.x())
    _resize(win, app, 1920)
    box = ui.groupBox_actor_db_maintenance
    print("wide boxW", box.width(), "group siblings right edges:")
    for c in box.children():
        if hasattr(c, "geometry") and c.geometry().x() + c.geometry().width() > 620:
            print("   ", c.objectName(), c.geometry())
    hint = ui.label_actor_db_sync_slice_hint
    f = hint.font()
    print("hint font", f.family(), f.pixelSize())
    fm = QFontMetrics(f)
    old = "起始行数0+单次限制5000=默认更新值"
    new = "起始行数0+单次限制5000=默认更新数据表行数"
    print("old adv", fm.horizontalAdvance(old), "new adv", fm.horizontalAdvance(new))
    d = QTextDocument()
    d.setDefaultFont(f)
    d.setPlainText(new)
    for wdt in (240, 245, 250, 252, 254, 256, 258, 259, 260, 261, 262, 265):
        d.setTextWidth(wdt)
        print("   new text at width", wdt, "height", d.size().height())
    print("sizes under live style:")
    for n in ROW:
        w = getattr(ui, n)
        print("   ", n, "sizeHint", w.sizeHint().width(), "minSizeHint", w.minimumSizeHint().width(), "curW", w.width())
