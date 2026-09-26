"""一次性 instrument：NFO/水印两页注册 design_w、entry、视口、滚动条、组宽全打印。"""

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QGroupBox

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_window_state_matrix import _ensure_app, _goto  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod
    from mdcx.consts import MAIN_PATH

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


def _tab_by_text(win, app, text):
    tw = win.Ui.tabWidget
    for i in range(tw.count()):
        if tw.tabText(i).strip() == text:
            tw.setCurrentIndex(i)
            app.processEvents()
            return
    raise AssertionError(f"tab not found: {text}")


def _dump(app, win, sc, gb_name):
    ui = win.Ui
    gb = ui.__dict__[gb_name]
    content = sc.widget()
    lines = []
    lines.append(f"content={content.objectName()} live_w={content.width()}")
    lines.append(f"  reg_dw={getattr(content, '_wide_children_design_width', 'NONE')}")
    for e in getattr(content, "_wide_children_design", []) or []:
        if e.widget is gb:
            lines.append(f"  entry gb: {tuple(e.geometry)}")
    vp = sc.viewport()
    sb = sc.verticalScrollBar()
    lines.append(f"  vp_w={vp.width()} sb_vis={sb.isVisible()} sb_w={sb.width()}")
    g = gb.geometry()
    lines.append(f"  gb x={g.x()} w={g.width()} R={g.right() + 1}")
    return "\n".join(lines)


def test_zz_inst2(win, app, tmp_path):
    out = []
    win.resize(1089, 700)
    win.show()
    app.processEvents()
    _goto(win, app, "page_setting")
    ui = win.Ui
    _tab_by_text(win, app, "水印")
    for _ in range(3):
        win._sync_page_layouts()
        app.processEvents()
    out.append("== watermark ==")
    out.append(_dump(app, win, ui.scrollArea_4, "groupBox_31"))
    _tab_by_text(win, app, "NFO")
    for _ in range(3):
        win._sync_page_layouts()
        app.processEvents()
    out.append("== nfo ==")
    out.append(_dump(app, win, ui.scrollArea_13, "groupBox_81"))
    Path(r"C:\Users\ZhouHan\AppData\Local\Temp\opencode\\inst2.txt").write_text(
        "\n".join(out), encoding="utf-8"
    )
