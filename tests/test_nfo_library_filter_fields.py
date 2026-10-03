"""信息管理页筛选框全字段搜索回归测试。

覆盖用户 8 项需求：时长 / 导演 / 片商 / 发行商 / 系列 / 评分 /
简介 / 标签，同时搜文件名与 NFO 内容；标签与演员支持逗号分隔多词
AND、乱序组合等价。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest

_app = None


def _ensure_app():
    global _app
    if _app is None:
        from PyQt6.QtWidgets import QApplication

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


def _write_nfo(folder, name, **fields):
    children = [f"<num>{fields.get('num', name)}</num>"]
    for key in ("title", "originaltitle", "director", "studio", "publisher", "series",
                "runtime", "rating", "plot", "outline", "release", "releasedate", "year"):
        if fields.get(key):
            children.append(f"<{key}>{fields[key]}</{key}>")
    for actor in fields.get("actors", []):
        children.append(f"<actor><name>{actor}</name></actor>")
    for tag in fields.get("tags", []):
        children.append(f"<tag>{tag}</tag>")
    (folder / f"{name}.nfo").write_text(
        "<movie>" + "".join(children) + "</movie>", encoding="utf-8"
    )


@pytest.fixture()
def library(win, app, tmp_path):
    folder = tmp_path / "nfo_filter"
    folder.mkdir()
    _write_nfo(
        folder, "SNOS-447",
        title="SNOS-447 电影女演员中村美雨",
        actors=["仲村美羽"],
        director="ザック荒井",
        studio="エスワン ナンバーワンスタイル",
        publisher="S1 NO.1 STYLE",
        series="",
        runtime="126",
        rating="3.0",
        plot="电影女演员中村美雨接受拍摄",
        tags=["SNOS", "仲村美羽", "単体作品", "美乳"],
        release="2026-09-03",
    )
    _write_nfo(
        folder, "MIBD-459",
        title="MIBD-459 手淫4小时",
        actors=["青木玲", "松嶋れいな"],
        director="",
        studio="ムーディーズ",
        publisher="MOODYZ Best",
        series="作品集",
        runtime="238",
        rating="5.0",
        plot="38位知名女演员用手指",
        tags=["打手枪", "系列：作品集", "MIBD"],
        release="2009-12-29",
        year="2009",
    )
    for i in range(win.Ui.stackedWidget.count()):
        if win.Ui.stackedWidget.widget(i).objectName() == "page_nfo_library":
            win.Ui.stackedWidget.setCurrentIndex(i)
            break
    app.processEvents()
    win.Ui.lineEdit_nfo_lib_dir.setText(str(folder))
    win.pushButton_nfo_lib_refresh_clicked()
    app.processEvents()
    assert win.Ui.listWidget_nfo_lib.count() == 2
    return folder


def _visible(win):
    lw = win.Ui.listWidget_nfo_lib
    return sorted(lw.item(i).text() for i in range(lw.count()) if not lw.item(i).isHidden())


def _search(win, app, keyword):
    win.Ui.lineEdit_nfo_lib_filter.setText(keyword)
    win.lineEdit_nfo_lib_filter_changed()
    app.processEvents()
    return _visible(win)


# ============= 8 项需求 =============


def test_filter_runtime(win, app, library):
    assert _search(win, app, "238") == ["MIBD-459"]
    assert _search(win, app, "126") == ["SNOS-447"]


def test_filter_director(win, app, library):
    assert _search(win, app, "ザック荒井") == ["SNOS-447"]


def test_filter_studio(win, app, library):
    assert _search(win, app, "ナンバーワンスタイル") == ["SNOS-447"]
    assert _search(win, app, "ムーディーズ") == ["MIBD-459"]


def test_filter_publisher(win, app, library):
    assert _search(win, app, "STYLE") == ["SNOS-447"]
    assert _search(win, app, "MOODYZ Best") == ["MIBD-459"]


def test_filter_series(win, app, library):
    assert _search(win, app, "作品集") == ["MIBD-459"]


def test_filter_rating(win, app, library):
    assert _search(win, app, "5.0") == ["MIBD-459"]
    assert _search(win, app, "3.0") == ["SNOS-447"]


def test_filter_outline(win, app, library):
    assert _search(win, app, "中村美雨接受拍摄") == ["SNOS-447"]
    assert _search(win, app, "38位知名女演员") == ["MIBD-459"]


def test_filter_tag_multi_and_reordered(win, app, library):
    assert _search(win, app, "単体作品") == ["SNOS-447"]
    # 多标签 AND：两个都在同一 NFO 内才命中
    assert _search(win, app, "単体作品,美乳") == ["SNOS-447"]
    # 乱序拆分组合等价
    assert _search(win, app, "美乳,単体作品") == ["SNOS-447"]
    # 分属两个 NFO 的标签 AND → 空
    assert _search(win, app, "単体作品,打手枪") == []


def test_filter_actor_multi_and_reordered(win, app, library):
    assert _search(win, app, "青木玲,松嶋れいな") == ["MIBD-459"]
    assert _search(win, app, "松嶋れいな,青木玲") == ["MIBD-459"]
    assert _search(win, app, "青木玲,仲村美羽") == []


def test_filter_filename_still_works(win, app, library):
    assert _search(win, app, "SNOS-447") == ["SNOS-447"]
    assert _search(win, app, "mibd") == ["MIBD-459"]
    assert _search(win, app, "") == ["MIBD-459", "SNOS-447"]


def test_filter_release_date_formats(win, app, library):
    # MIBD-459 发行日 2009-12-29：各种常见写法都要命中同一条
    for kw in (
        "2009-12-29",
        "09-12-29",
        "2009.12.29",
        "09.12.29",
        "2009·12·29",
        "09·12·29",
        "2009/12/29",
        "2009年12月29日",
        "2009年12月29",
        "20091229",
        "091229",
        "2009-12-29,MOODYZ",
    ):
        assert _search(win, app, kw) == ["MIBD-459"], kw
    # SNOS-447 发行日 2026-09-03
    assert _search(win, app, "2026.09.03") == ["SNOS-447"]
    assert _search(win, app, "26-09-03") == ["SNOS-447"]
    # 非日期数字不受归一化干扰
    assert _search(win, app, "238") == ["MIBD-459"]
    assert _search(win, app, "5.0") == ["MIBD-459"]


def test_filter_stray_commas_ignored(win, app, library):
    # 首尾多余逗号/连续逗号/全角逗号：空段不参与匹配
    assert _search(win, app, ",仲村美羽,SNOS，") == ["SNOS-447"]
    assert _search(win, app, "仲村美羽,,SNOS") == ["SNOS-447"]
    assert _search(win, app, "，，仲村美羽，SNOS，，") == ["SNOS-447"]
    # 全是逗号视为空搜索，显示全部
    assert _search(win, app, ",,,") == ["MIBD-459", "SNOS-447"]
    assert _search(win, app, "，") == ["MIBD-459", "SNOS-447"]
    # 用户截图模式：有效词全命中 + 首尾空段 → 命中（标签/演员同一套逻辑）
    assert _search(win, app, ",青木玲,MIBD，作品集，") == ["MIBD-459"]
    assert _search(win, app, "青木玲,MIBD,作品集,") == ["MIBD-459"]
    # 开头的 "1" 这类数字词只与数字字段精确比对（年份/时长/评分）
    # 或为发行日的开头——都不成立则整条落空
    assert _search(win, app, "1,青木玲,MIBD") == []


def test_filter_stray_digit_kills_match(win, app, library):
    # `1` 不在演员/标签里，也不精确等于任何数字字段 → 整条落空
    # （标签搜索与演员搜索同一套逻辑）
    assert _search(win, app, ",単体作品,美乳,1") == []
    assert _search(win, app, "1,単体作品,美乳") == []
    assert _search(win, app, "1,青木玲,打手枪") == []
    # 去掉 `1` 即命中（对照）
    assert _search(win, app, "単体作品,美乳") == ["SNOS-447"]
    assert _search(win, app, "青木玲,打手枪") == ["MIBD-459"]
    # 精确数字照样参与 AND：238 精确等于时长，2009 精确等于年份
    assert _search(win, app, "238,打手枪") == ["MIBD-459"]
    assert _search(win, app, "126,SNOS") == ["SNOS-447"]
    assert _search(win, app, "2009,打手枪") == ["MIBD-459"]
    # 半角冒号写法命中全角标签
    assert _search(win, app, "系列:作品集") == ["MIBD-459"]
