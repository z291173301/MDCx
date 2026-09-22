"""议题 #130 回归：cookie 检查失败只告警、不清空保存的 cookie；启动自检纳入 FC2PPVDB。

背景：javdb 检查在与已保存 cookie 相同的输入下，曾对「网络不可达」与「未检测到
登录态」两种非确凿情形直接清空保存的 cookie（并触发保存）。这会把用户的凭据
当作失败证据抹掉。现改为：一律只告警、保留 cookie，由用户手动替换。
另：启动自检由数据库/ThePornDB/JavDb/JavBus 扩展为包含 FC2PPVDB。
"""

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
    from mdcx.controllers.main_window import main_window as mw_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for t in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, t).stop()
    yield window, mw_mod
    window.close()
    window.deleteLater()
    app.processEvents()


def _set_saved_cookie(monkeypatch, cookie: str) -> None:
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "javdb", cookie, raising=False)


def test_javdb_cookie_not_cleared_on_network_error(win, monkeypatch):
    """网络/站点不可达（response is None 且 error 含 Cookie）：保留 cookie。"""
    from mdcx.config.manager import manager

    window, mw_mod = win
    saved = "locale=zh; _jdb_session=KEEP_ME"
    _set_saved_cookie(monkeypatch, saved)

    def fake_get_text_sync(url, headers=None, **kwargs):
        return None, "HTTP 403 Cookie Invalid"

    monkeypatch.setattr(mw_mod, "get_text_sync", fake_get_text_sync)

    window._check_javdb_cookie(saved)

    assert manager.config.javdb == saved, "网络不可达时不应清空已保存的 javdb cookie"


def test_javdb_cookie_not_cleared_when_logout_missing(win, monkeypatch):
    """页面无 /logout（可能维护页/拦截页）：只告警，保留 cookie。"""
    from mdcx.config.manager import manager

    window, mw_mod = win
    saved = "locale=zh; _jdb_session=KEEP_ME"
    _set_saved_cookie(monkeypatch, saved)

    def fake_get_text_sync(url, headers=None, **kwargs):
        return "<html>maintenance</html>", ""

    monkeypatch.setattr(mw_mod, "get_text_sync", fake_get_text_sync)

    window._check_javdb_cookie(saved)

    assert manager.config.javdb == saved, "未检测到登录态时不应清空已保存的 javdb cookie"


def test_javdb_check_no_longer_clears_cookie():
    """结构锁：_check_javdb_cookie 不得再清空 cookie（防回退）。

    注：成功分支仍会 emit `exec_save_config` 用于保存「新填入的有效 cookie」，
    这是允许的；被禁止的是把 cookie 置空的 `set_javdb_cookie.emit("")`。
    """
    import inspect

    from mdcx.controllers.main_window.main_window import MyMAinWindow

    src = inspect.getsource(MyMAinWindow._check_javdb_cookie)
    assert 'set_javdb_cookie.emit("")' not in src, "javdb 检查仍会清空 cookie"


def test_startup_selfcheck_includes_fc2ppvdb():
    """启动自检声明与实现都包含 FC2PPVDB。"""
    from pathlib import Path

    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window.main_window import MyMAinWindow

    # 实现：_on_version_check_done 调用了 fc2ppvdb 检测
    names = MyMAinWindow._on_version_check_done.__code__.co_names
    assert "pushButton_check_fc2ppvdb_cookie_clicked" in names, "启动自检未调用 fc2ppvdb cookie 检测"

    # 声明：启动自检文案包含 FC2PPVDB
    text = Path(mw_mod.__file__).read_text(encoding="utf-8")
    assert "启动自检：数据库 / ThePornDB / JavDb / JavBus / FC2PPVDB" in text, "启动自检文案未含 FC2PPVDB"


def test_fc2ppvdb_login_key_accepts_hyphenated_session():
    """fc2cmadb 实际下发的会话 cookie 名是 fc2cmadb-session（连字符），须被识别。"""
    from mdcx.crawlers.fc2ppvdb import cookie_has_login_key

    assert cookie_has_login_key("fc2cmadb-session=abc")
    assert cookie_has_login_key("XSRF-TOKEN=abc")
    assert not cookie_has_login_key("locale=zh")
    assert not cookie_has_login_key("")
