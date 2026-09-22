"""评分字段回归测试（C5）：爬虫返回的评分必须能通过字段合并写入。

BaseCrawlerResult.empty() 曾把 score 初始化为 "0.0"（truthy），而
file_crawler 的字段合并判定是 `not getattr(reduced, field)`，导致任何
站点返回的真实评分都被当作"已有值"跳过——全库 NFO <rating> 恒 0.0。
"""

from mdcx.models.model_types import CrawlerResult


def test_empty_score_is_falsy():
    """empty() 的 score 必须是 falsy，否则字段合并永远跳过评分。"""
    empty = CrawlerResult.empty()
    assert not empty.score, (
        f"empty().score={empty.score!r} 为 truthy，"
        "`not getattr(reduced, 'score')` 恒 False，爬虫评分会被丢弃（C5 回归）"
    )


def test_crawler_score_survives_reduce_predicate():
    """复刻 file_crawler.py:511 的合并判定：真实评分必须能写入。"""
    reduced = CrawlerResult.empty()
    crawler_score = "8.5"

    is_primary_field_value = not getattr(reduced, "score", None)  # 原判定行
    if is_primary_field_value:
        reduced.score = crawler_score

    assert reduced.score == "8.5", f"爬虫评分 8.5 被丢弃，最终 score={reduced.score!r}（C5 回归）"


def test_zero_score_from_crawler_still_writable():
    """站点真实返回 "0.0" 时也应写入（区别于初始化占位）。"""
    reduced = CrawlerResult.empty()
    assert not reduced.score
    reduced.score = "0.0"  # 走到 setattr（is_primary 为 True 的真实写入）
    assert reduced.score == "0.0"
