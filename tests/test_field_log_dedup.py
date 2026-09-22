"""同番号失败级联的日志降噪回归测试（field_log 站点级去重）。

背景（议题 #55 报告人日志实证，2026-08-29）：字段循环里对每个已失败
站点按【字段×站点】重复追加 "(已失败, 跳过)"——66 个失败文件的会话
产生 9400 行重复标记（每文件平均 142 行，"dmm 已失败"在同一文件内
重复 20+ 次，信息量趋近零），单次会话 5.5 万行日志中约 1.7 万行是
此类噪声 + 优先级装饰行。

修复：file_crawler 字段循环里失败站点标记改为站点级去重——每站点
的失败信息只记一次，后续字段静默跳过。
"""

import pytest

from mdcx.config.enums import Website
from mdcx.config.models import FieldConfig
from mdcx.core.file_crawler import FileScraper
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.model_types import (
    CrawlerInput,
    CrawlerResult,
)
from tests.test_file_crawler_runtime import (
    _build_result,
    _FakeConfig,
    _FakeCrawlerProvider,
)

pytestmark = pytest.mark.asyncio


class _MixedFieldConfig(_FakeConfig):
    """title/outline/series/studio 四字段都有 [javdb(成功), javbus(失败)] 优先级。"""

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field in (
            CrawlerResultFields.TITLE,
            CrawlerResultFields.OUTLINE,
            CrawlerResultFields.SERIES,
            CrawlerResultFields.STUDIO,
        ):
            return FieldConfig(site_prority=[Website.JAVDB, Website.JAVBUS])
        return FieldConfig(site_prority=[])


async def test_failed_site_marked_once_across_fields(monkeypatch: pytest.MonkeyPatch):
    """核心断言：javbus 失败后，4 个字段的循环里失败标记只出现 1 次。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (
            CrawlerResultFields.TITLE,
            CrawlerResultFields.OUTLINE,
            CrawlerResultFields.SERIES,
            CrawlerResultFields.STUDIO,
        ),
    )

    # javdb 只有 title/outline；series/studio 无值——这两个字段会轮询到
    # javbus 并触发"已失败跳过"路径（这正是噪声场景：字段轮到失败站点）
    javdb_data = CrawlerResult.empty()
    javdb_data.source = "javdb"
    javdb_data.title = "标题"
    javdb_data.outline = "简介"

    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: javdb_data,
            Website.JAVBUS: (None, RuntimeError("搜索结果: 未匹配到番号！")),
        }
    )
    scraper = FileScraper(_MixedFieldConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-55"

    result = await scraper._call_crawlers(task_input, {Website.JAVDB, Website.JAVBUS})

    assert result is not None, "javdb 成功提供 4 字段，应部分成功"
    # 数失败标记行（"(已失败" 行），非字符串总出现——优先级行也含站名
    marks = result.field_log.count("(已失败")
    assert marks == 1, f"javbus 的失败标记应只记 1 次（站点级去重），实际 {marks} 次。\nfield_log:\n{result.field_log}"


async def test_failed_site_dedup_still_names_every_site(monkeypatch: pytest.MonkeyPatch):
    """去重不丢信息：两个失败站点各记一次，且新文案点明『后续字段将跳过』。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE),
    )

    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: _build_result(Website.JAVDB, "成功标题"),
            Website.JAVBUS: (None, RuntimeError("javbus 失败原因A")),
            Website.AVBASE: (None, RuntimeError("avbase 失败原因B")),
        }
    )

    class _ThreeSiteConfig(_MixedFieldConfig):
        def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
            if field in (CrawlerResultFields.TITLE, CrawlerResultFields.OUTLINE):
                return FieldConfig(site_prority=[Website.JAVDB, Website.JAVBUS, Website.AVBASE])
            return FieldConfig(site_prority=[])

    scraper = FileScraper(_ThreeSiteConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-56"

    result = await scraper._call_crawlers(task_input, {Website.JAVDB, Website.JAVBUS, Website.AVBASE})

    assert result is not None
    # 每个失败站点恰好各 1 行，且带后续跳过说明
    assert result.field_log.count("(已失败") == 2
    assert "javbus" in result.field_log and "avbase" in result.field_log
    assert "后续字段将跳过" in result.field_log


async def test_failed_site_mark_includes_cause(monkeypatch: pytest.MonkeyPatch):
    """议题 #101：失败标记必须区分失败类因——「请求超时/被拦截/解析失败/请求异常」。

    用户把「avbase/thejavdb_api/javdb_app 已失败，后续字段将跳过该站」误解为
    逻辑 bug，实际是这些站在其网络下请求级失败。标注原因后一眼可分辨。
    """
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (
            CrawlerResultFields.TITLE,
            CrawlerResultFields.OUTLINE,
        ),
    )

    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: (None, TimeoutError("read timed out")),
            Website.JAVBUS: (None, RuntimeError("cloudflare 403 blocked")),
            Website.AVBASE: _build_result(Website.AVBASE, "成功标题"),
        }
    )

    class _TimeoutConfig(_MixedFieldConfig):
        def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
            return FieldConfig(site_prority=[Website.AVBASE, Website.JAVDB, Website.JAVBUS])

    scraper = FileScraper(_TimeoutConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-101"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB, Website.JAVBUS})
    assert result is not None
    assert result.field_log.count("(已失败") == 2
    # 两个失败的类因明确标注
    assert "原因: 请求超时" in result.field_log
    assert "原因: 被站点拦截" in result.field_log
