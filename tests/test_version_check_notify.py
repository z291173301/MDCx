"""版本检查定时复查回归测试：timer_update 必须走完整提示链，且同一版本只提示一次。

回归背景：timer_update.timeout 曾直连裸 `check_version`——在主线程阻塞做网络，
返回值还被丢弃，12h 定时检查永远不产生任何提示，只有启动自检会提示。
修复：定时器改连 `show_version`（工作线程 + 比较 + 提示全链路），并用
`_notified_new_version` 做 transition 去重（同一版本重复检查不再刷屏，
出现更新的版本时自动再次提示）。

`check_version` 后续改为返回 `RemoteVersion(tag, name)`（tag 取列表中**最大**的
纯数字 tag 而非第一条，见 `tests/test_version_check_pick_latest.py`），比较改为
版本号 + 日期双维度（`is_remote_version_newer`），故本文件的桩与断言同步换成
`RemoteVersion`，提示文案断言也从裸数字 tag 改为 release 标题。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


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
    # 本文件测的是 _show_version_thread 本体：启动期 show_version 起的后台线程
    # 会跟测试抢读 check_version 桩，直接禁掉，测试内同步直调目标方法（确定性）。
    monkeypatch.setattr(mw_mod.MyMAinWindow, "show_version", lambda self: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    # 本测试不走真实网络：桩掉副作用线程与数据库初始化。
    monkeypatch.setattr(mw_mod, "check_theporndb_api_token", lambda: None)
    monkeypatch.setattr(mw_mod.ActressDB, "init_db", lambda: None)
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
    # _show_version_thread 尾部会调三个 cookie 检查（网络）：测试内全部桩掉。
    for name in (
        "pushButton_check_javdb_cookie_clicked",
        "pushButton_check_javbus_cookie_clicked",
        "pushButton_check_fc2ppvdb_cookie_clicked",
    ):
        monkeypatch.setattr(window, name, lambda: None)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _stub_version_path(monkeypatch, win):
    """桩掉提示链的日志出口，返回调用记录器。"""
    from mdcx import signals as signals_mod

    log_calls: list[str] = []
    monkeypatch.setattr(signals_mod.signal_qt, "show_log_text", lambda text: log_calls.append(text))
    monkeypatch.setattr(signals_mod.signal_qt, "show_scrape_info", lambda *a, **k: None)
    return log_calls


def _red_count(log_calls):
    return len([t for t in log_calls if "请及时更新" in t])


def _remote(tag: int, name: str = ""):
    from mdcx.base.web import RemoteVersion

    return RemoteVersion(tag=tag, name=name)


def test_periodic_recheck_notifies_once_per_version(win, app, monkeypatch):
    """同一版本重复检查只提示一次；出现更新的版本时再次提示；已是最新则绿色。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    log_calls = _stub_version_path(monkeypatch, win)
    local = int(win.localversion)
    assert win._notified_new_version is None

    # 第一次发现新版本：提示。
    monkeypatch.setattr(mw_mod, "check_version", lambda: _remote(local + 100, "v9.9.9 (99999999)"))
    win._show_version_thread()
    app.processEvents()
    assert win._notified_new_version == _remote(local + 100, "v9.9.9 (99999999)")
    assert "有新版本" in win.new_version
    assert _red_count(log_calls) == 1

    # 同一版本再查：不再刷屏。
    win._show_version_thread()
    app.processEvents()
    assert win._notified_new_version == _remote(local + 100, "v9.9.9 (99999999)")
    assert _red_count(log_calls) == 1

    # 出现更新的版本：再次提示。
    monkeypatch.setattr(mw_mod, "check_version", lambda: _remote(local + 101, "v9.9.10 (99999999)"))
    win._show_version_thread()
    app.processEvents()
    assert win._notified_new_version == _remote(local + 101, "v9.9.10 (99999999)")
    assert _red_count(log_calls) == 2

    # 已是最新：绿色日志，不登记。
    monkeypatch.setattr(mw_mod, "check_version", lambda: _remote(local, "v0.0.1 (19700101)"))
    win._show_version_thread()
    app.processEvents()
    assert win._notified_new_version == _remote(local + 101, "v9.9.10 (99999999)")
    assert any("最新版本" in t for t in log_calls)


def test_new_version_prompt_shows_release_display_name(win, app, monkeypatch):
    """红字与左下角提示都展示 release 标题（vX.Y.Z (tag)），不再只显示裸数字 tag。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    log_calls = _stub_version_path(monkeypatch, win)
    monkeypatch.setattr(mw_mod, "check_version", lambda: _remote(int(win.localversion) + 100, "v9.9.9 (99999999)"))

    win._show_version_thread()
    app.processEvents()

    assert "v9.9.9 (99999999)" in win.new_version
    assert any("v9.9.9 (99999999)" in t for t in log_calls if "请及时更新" in t)


def test_same_tag_higher_version_name_still_prompts(win, app, monkeypatch):
    """同一天发两版（tag 相同、版本号更高）也必须提示——纯日期比较认不出来。"""
    from mdcx.controllers.main_window import main_window as mw_mod

    log_calls = _stub_version_path(monkeypatch, win)
    local = int(win.localversion)
    # 远端 tag 与本地相同，但展示版本号更高（远端名比本地 v2.x.y 高即可）
    monkeypatch.setattr(mw_mod, "check_version", lambda: _remote(local, f"v99.0.0 ({local})"))

    win._show_version_thread()
    app.processEvents()

    assert _red_count(log_calls) == 1
    assert win._notified_new_version == _remote(local, f"v99.0.0 ({local})")


def test_timer_update_interval_unchanged(win):
    """定时器周期保持 12h（本修复只改连接目标与去重，不动周期）。"""
    assert win.timer_update.interval() == 43200000
