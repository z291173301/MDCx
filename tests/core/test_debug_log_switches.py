"""议题 #98-1 回归：调试日志三开关互相独立。

开关语义（设置 → 调试模式）：
- show_web_log：控制爬虫/图片/TMDB 等「过程明细」（LogBuffer.web 通道），
  逐字段来源排障块（📒 字段来源）也归该通道（#98-3）
- show_from_log：「显示字段来源信息」——开时输出保持 [website] 站点摘要精简形态，
  不再触发逐字段展开（逐字段排障需开 show_web_log）
- show_data_log：控制「字段内容」块（show_movie_info 写入 log 通道）

核心回归：关掉 show_web_log 不再连带吞掉字段内容（旧实现读取端
只有 show_web_log 一个闸门，关闭时整段丢弃）。
"""

from pathlib import Path

import pytest

from mdcx.core.scraper import compose_scrape_log_output
from mdcx.core.utils import show_movie_info, show_result
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.model_types import CrawlersResult, FileInfo


def _fresh_root():
    """新开任务组并清干净三个通道，返回写入用的 buffer。"""
    LogBuffer.new_root()
    LogBuffer.clear_task()
    LogBuffer.new_root()
    log = LogBuffer.log()
    web = LogBuffer.web()
    err = LogBuffer.error()
    log.clear()
    web.clear()
    err.clear()
    return log, web, err


def test_web_channel_is_independent_buffer():
    """web 通道与 log 通道是独立 buffer，写入互不混入。"""
    log, web, _ = _fresh_root()
    log.write("\n [log] key line")
    web.write("\n [web] detail line")
    assert "[log] key line" in log.get(only_self=True)
    assert "[web]" not in log.get(only_self=True)
    assert "[web] detail line" in web.get(only_self=True)
    assert "[log]" not in web.get(only_self=True)


@pytest.mark.parametrize(
    ("web_log", "from_log", "data_log"),
    [
        (False, True, True),  # 用户报告的组合：精简 + 字段来源 + 字段内容
        (False, True, False),
        (False, False, True),
        (False, False, False),
        (True, True, True),
        (True, False, False),
    ],
)
def test_three_debug_switches_are_independent(monkeypatch, web_log, from_log, data_log):
    """任一开关组合下，其余开关的行为不受 show_web_log 影响。"""
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "show_web_log", web_log)
    monkeypatch.setattr(manager.config, "show_from_log", from_log)
    monkeypatch.setattr(manager.config, "show_data_log", data_log)

    log, web, _ = _fresh_root()
    # 关键节点行（恒出）
    log.write("\n 🙈 [file] /lib/SSIS-001.mp4")
    log.write("\n 🍀 Data done!(1.0s)")
    # 过程明细（show_web_log 控制）
    web.write("\n 🖼 Poster选优: 使用 thumb 右裁剪 (0,0)")

    # 字段来源块（show_from_log 控制）—— show_result 的写入行为
    res = CrawlersResult.empty()
    res.field_log = " 📌 title\n ====================\n 🟢 javdb\n  ↳ xxx"
    res.site_log = "\n 🌐 [website] javdb (1.0s)-> javbus (2.0s)"
    show_result(res, start_time=0.0)

    # 字段内容块（show_data_log 控制）—— show_movie_info 的写入行为
    file_info = FileInfo.empty()
    file_info.file_path = Path("/lib/SSIS-001.mp4")
    res.number = "SSIS-001"
    res.title = "测试标题"
    show_movie_info(file_info, res)

    text = compose_scrape_log_output("BEGIN", "END")

    # 关键节点行恒出
    assert "[file] /lib/SSIS-001.mp4" in text
    assert "Data done!" in text
    # 站点耗时行恒出（用户期望的精简输出里保留）
    assert "website] javdb (1.0s)" in text
    # 过程明细只受 show_web_log 控制
    if web_log:
        assert "Poster选优" in text
    else:
        assert "Poster选优" not in text
    # 逐字段来源排障块归过程明细通道：只受 show_web_log 控制（议题 #98-3），
    # show_from_log 不再触发逐字段展开，开启时输出保持 [website] 站点摘要精简形态
    if web_log:
        assert "字段来源" in text
        assert "↳ xxx" in text
    else:
        assert "字段来源" not in text
        assert "↳ xxx" not in text
    # 字段内容块只受 show_data_log 控制
    if data_log:
        assert "number" in text and "SSIS-001" in text
        assert "title" in text and "测试标题" in text
    else:
        assert "测试标题" not in text


def test_show_web_log_off_keeps_field_content_block(monkeypatch):
    """关过程明细时字段内容块仍输出；逐字段排障块归过程明细通道，随之隐藏（#98-3）。"""
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "show_web_log", False)
    monkeypatch.setattr(manager.config, "show_from_log", True)
    monkeypatch.setattr(manager.config, "show_data_log", True)

    log, web, _ = _fresh_root()
    log.write("\n 🙈 [file] /lib/SSIS-002.mp4")
    web.write("\n 🟡 图片读取失败: timeout")
    res = CrawlersResult.empty()
    res.field_log = " 📌 outline\n 🟢 thejavdb_api"
    res.site_log = "\n 🌐 [website] javdb (1.0s)"
    show_result(res, start_time=0.0)
    file_info = FileInfo.empty()
    file_info.file_path = Path("/lib/SSIS-002.mp4")
    res.number = "SSIS-002"
    res.outline = "测试简介"
    show_movie_info(file_info, res)

    text = compose_scrape_log_output("BEGIN", "END")
    assert "[file] /lib/SSIS-002.mp4" in text
    # 字段内容块（show_data_log）恒出
    assert "outline" in text
    assert "测试简介" in text
    # 逐字段排障块归过程明细通道：关 show_web_log 时不输出（#98-3）
    assert "字段来源" not in text
    assert "📌 outline" not in text
    # 过程明细被隐藏
    assert "图片读取失败" not in text


def test_migrated_detail_writers_use_web_channel(monkeypatch):
    """已迁移的过程明细写点走 web 通道（抽测 _tmdb_log_line）。"""
    from mdcx.core import tmdb_actor

    _, web, _ = _fresh_root()
    monkeypatch.setattr(tmdb_actor.manager.config, "show_data_log", True)
    tmdb_actor._tmdb_log_line("  ℹ️ [TMDB] actor matched tmdbid=123")
    assert "actor matched" in web.get(only_self=True)
    assert "actor matched" not in LogBuffer.log().get(only_self=True)
