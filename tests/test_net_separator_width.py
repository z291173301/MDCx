"""检测网络面板「=」分隔线：字符数按文本区可视宽算、铺满右边缘且不折行。

背景（用户诉求）：
- 还原态下顶/底两条分隔线右侧留一大段空白（截图实测约 170px），要求延伸到最右侧；
- 最大化时保持同样的字符数，即两态数量相同。

实现要点（main_window.py::_net_separator_chars）：
- 字符数 = 文本区可视宽 ÷ 等宽字宽（QSS 里 #textBrowser_net_main 为 Consolas 13px，
  实测单字宽 7px），只量一次并缓存，故最大化/还原两态数量一致；
- 量的时机是首帧之后（showEvent 里 singleShot(0)）。窗口在 __init__ 内即触发
  showEvent 并 resize 到自适应默认尺寸，但 resize 只把 resizeEvent 排进队列，
  文本区几何要等该事件派发（resizeEvent → _sync_page_layouts 同步 setGeometry）
  才落定；那一刻之前量到的仍是 .ui 设计宽，会多算字符导致默认态折行。

本文件锁定四件事：
1. 字符数恰好铺满可视宽（余量 < 单字宽）且渲染宽不超过可视宽（不折行）；
2. 多档窗口宽度下都成立（1030/1200/1600/1920）；
3. 缓存语义：已发出的字符数不随后续最大化/还原改变（两态数量相同）；
4. 首屏只发一次（托盘隐藏/再显示不重复），顶/底两条分隔线字符数一致。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtGui import QFontMetricsF
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
    # 本文件要验真实的 show_netstatus（顶/底两条分隔线由它生成），故不桩掉
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    # 加载真实主题资源，量到的字宽/可视宽才与用户实际运行环境一致
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


def _drain(app, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


def _settle(win, app, width: int) -> None:
    """把窗口摆到指定宽度并跑完布局，使文本区几何与 resizeEvent 后的终态一致。"""
    win.resize(width, 700)
    win._sync_page_layouts()
    _drain(app)


def _usable_width(win) -> int:
    """文本区可用文字宽：控件宽扣掉 QSS `padding: 2px, 2px`。"""
    from mdcx.controllers.main_window.main_window import _NET_SEP_TEXT_PADDING

    return max(win.Ui.textBrowser_net_main.width() - _NET_SEP_TEXT_PADDING, 0)


def _adv(win) -> float:
    return QFontMetricsF(win.Ui.textBrowser_net_main.font()).horizontalAdvance("=")


@pytest.mark.parametrize("width", [1030, 1200, 1600, 1920])
def test_separator_fills_width_without_wrapping(win, app, width):
    """各档宽度下：字符数铺满可视宽，且渲染宽不超过可视宽（不会折行）。"""
    from mdcx.controllers.main_window.main_window import _NET_SEP_MAX, _NET_SEP_MIN

    _settle(win, app, width)
    win._net_separator_chars_cache = 0  # 清缓存，量该宽度下的真实取值

    chars = win._net_separator_chars()
    adv = _adv(win)
    usable = _usable_width(win)

    assert usable > 0, "文本区宽度未落定，测试前提不成立"
    assert adv > 0
    # 不折行：渲染宽必须留在可视宽内
    assert chars * adv <= usable, f"{width} 宽下 {chars} 个={chars * adv}px 超出可视宽 {usable}px，会折行"
    # 铺到右边缘：余量必须小于一个字宽（否则右侧仍留可见空白）
    assert usable - chars * adv < adv, f"{width} 宽下右侧仍空 {usable - chars * adv}px，未延伸到最右侧"
    assert _NET_SEP_MIN <= chars <= _NET_SEP_MAX


def test_separator_count_is_stable_across_window_states(win, app):
    """最大化/还原不改变已缓存的字符数 —— 两态数量相同。"""
    _settle(win, app, 1030)
    win._net_separator_chars_cache = 0
    restored = win._net_separator_chars()

    # 最大化：几何大变，但字符数是缓存值，不重算
    _settle(win, app, 1920)
    assert win._net_separator_chars_cache == restored
    assert win._net_separator_chars() == restored

    # 再还原回来，仍是同一个值
    _settle(win, app, 1030)
    assert win._net_separator_chars() == restored


def test_both_separator_lines_use_the_same_width(win, app):
    """顶（时间戳居中）与底两条分隔线字符数一致，且都等于量出来的值。"""
    from mdcx.controllers.main_window import handlers as handlers_mod

    # 先把构造期排队的首屏发掉（_settle 里的事件泵会触发），
    # 再装桩，否则两轮分隔线都会被收进来
    _settle(win, app, 1030)
    win._net_separator_chars_cache = 0

    emitted: list[str] = []
    original = handlers_mod.signal_qt.show_net_info
    handlers_mod.signal_qt.show_net_info = lambda text: emitted.append(text)
    try:
        win._emit_net_startup_panel()
    finally:
        handlers_mod.signal_qt.show_net_info = original

    pure = [t for t in emitted if t and set(t.strip()) == {"="}]
    stamped = [t for t in emitted if t.startswith("=") and ":" in t]
    assert len(pure) == 1, f"底部分隔线应恰好一条，实际 {len(pure)} 条"
    assert len(stamped) == 1, f"顶部分隔线应恰好一条，实际 {len(stamped)} 条"

    chars = win._net_separator_chars_cache
    assert len(pure[0]) == chars
    assert len(stamped[0]) == chars
    # 时间戳居中：左右两段「=」长度差不超过 1（str.center 的取整规则）
    stamped_line = stamped[0]
    left = len(stamped_line) - len(stamped_line.lstrip("="))
    right = len(stamped_line) - len(stamped_line.rstrip("="))
    assert abs(left - right) <= 1, f"时间戳未居中：左 {left} 右 {right}"


def test_startup_panel_emitted_once_after_first_frame(win, app):
    """首屏只在首帧之后发一次；托盘隐藏/再显示不重复发。"""
    emitted: list[str] = []
    original = win.show_net_info
    win.show_net_info = lambda text: emitted.append(text)  # type: ignore[method-assign]
    try:
        win.show()
        _drain(app)
        first_round = len(emitted)
        assert win._net_startup_emitted is True
        assert win._net_separator_chars_cache > 0, "首帧后仍未量出分隔线字符数"

        # 托盘隐藏 → 再显示：showEvent 重复触发，首屏不应重发
        win.hide()
        _drain(app, 2)
        win.show()
        _drain(app)
        assert len(emitted) == first_round, "首屏被重复发送"
    finally:
        win.show_net_info = original  # type: ignore[method-assign]


def test_measurement_falls_back_when_viewport_not_settled(win, app):
    """可视宽还没随几何落定（与控件宽差超出合法范围）时，退回控件宽兜底不抛异常。"""
    _settle(win, app, 1030)
    win._net_separator_chars_cache = 0
    settled = win._net_separator_chars()

    # 模拟「viewport 尚未落定」：把可视宽撑到与控件宽差 > _NET_SEP_VIEWPORT_SLACK
    browser = win.Ui.textBrowser_net_main
    real_viewport = browser.viewport
    try:
        browser.viewport = lambda: type("_V", (), {"width": staticmethod(lambda: browser.width() + 500)})()  # type: ignore[method-assign]
        win._net_separator_chars_cache = 0
        fallback = win._net_separator_chars()
    finally:
        browser.viewport = real_viewport  # type: ignore[method-assign]

    assert fallback > 0
    assert fallback == settled, "兜底路径应给出与正常路径一致的结果（同一控件宽）"


def test_show_netstatus_accepts_sep_width():
    """handlers.show_netstatus(sep_width) 两条分隔线都按传入宽度生成。"""
    from mdcx.controllers.main_window import handlers as handlers_mod

    emitted: list[str] = []
    original = handlers_mod.signal_qt.show_net_info
    handlers_mod.signal_qt.show_net_info = lambda text: emitted.append(text)
    try:
        handlers_mod.show_netstatus(111)
    finally:
        handlers_mod.signal_qt.show_net_info = original

    pure = [t for t in emitted if t and set(t.strip()) == {"="}]
    stamped = [t for t in emitted if t.startswith("=") and ":" in t]
    assert len(pure) == 1 and len(pure[0]) == 111
    assert len(stamped) == 1 and len(stamped[0]) == 111


def test_show_netstatus_default_and_floor():
    """默认仍是 88（兼容旧调用）；非法宽度被夹到下限 8，不产生空行。"""
    from mdcx.controllers.main_window import handlers as handlers_mod

    emitted: list[str] = []
    original = handlers_mod.signal_qt.show_net_info
    handlers_mod.signal_qt.show_net_info = lambda text: emitted.append(text)
    try:
        handlers_mod.show_netstatus()
        handlers_mod.show_netstatus(0)
    finally:
        handlers_mod.signal_qt.show_net_info = original

    pure = [t for t in emitted if t and set(t.strip()) == {"="}]
    assert len(pure) == 2
    assert len(pure[0]) == 88
    assert len(pure[1]) == 8
