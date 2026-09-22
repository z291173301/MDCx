"""字段 skip 哨兵测试：验证字段配置 skip=True 时不从任何来源抓取。"""

import pytest

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.config.models import Config, FieldConfig, FieldPriorityConfig
from mdcx.core.file_crawler import FileScraper
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.model_types import (
    CrawlerInput,
)
from tests.test_file_crawler_runtime import (
    _RecordingCrawler,
    _RecordingCrawlerProvider,
)


class _SkipFieldConfig:
    """模拟 config，RUNTIME 字段 skip=True，TITLE 字段正常。"""

    fixed_scraping_type = FixedScrapingType.AUTO
    website_youma = {Website.DMM}
    website_wuma = set()
    website_suren = set()
    website_fc2 = set()
    website_oumei = set()
    website_guochan = set()
    scrape_like = "info"
    field_priority_try_all_images = False

    def get_field_config(self, field: CrawlerResultFields) -> FieldConfig:
        if field == CrawlerResultFields.RUNTIME:
            return FieldConfig(site_prority=[Website.DMM], skip=True)
        if field == CrawlerResultFields.TITLE:
            return FieldConfig(site_prority=[Website.DMM])
        return FieldConfig(site_prority=[])

    def get_type_field_config(
        self, scraping_type: FixedScrapingType, field: CrawlerResultFields
    ) -> FieldPriorityConfig:
        if field == CrawlerResultFields.RUNTIME:
            return FieldPriorityConfig(skip=True)
        if field == CrawlerResultFields.TITLE:
            return FieldPriorityConfig(site_prority=[Website.DMM])
        return FieldPriorityConfig()

    def get_type_sites(self, scraping_type: FixedScrapingType) -> list[Website]:
        return [Website.DMM]

    def get_site_url(self, site: Website, default: str = "") -> str:
        return default

    def get_site_config(self, site: Website):
        from mdcx.config.models import SiteConfig

        return SiteConfig()


@pytest.mark.asyncio
async def test_skip_field_does_not_fetch(monkeypatch: pytest.MonkeyPatch):
    """skip=True 的字段不会触发任何网络请求。"""
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.TITLE, CrawlerResultFields.RUNTIME))

    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider({Website.DMM: _RecordingCrawler(Website.DMM, records)})
    scraper = FileScraper(_SkipFieldConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "ABF-001"

    result = await scraper._call_crawlers(task_input, {Website.DMM})

    assert result is not None
    # TITLE 字段应该正常抓取到值
    assert result.title == "ok"
    # RUNTIME 字段应该为空（被跳过）
    assert result.runtime == ""
    # 只请求了 1 次（TITLE），RUNTIME 被跳过不请求
    assert len(records) == 1
    assert records[0] == ("dmm", "ABF-001")


@pytest.mark.asyncio
async def test_skip_field_logged_in_field_log(monkeypatch: pytest.MonkeyPatch):
    """skip=True 的字段在 field_log 中记录跳过信息，且不触发网络请求。"""
    monkeypatch.setattr(ManualConfig, "REDUCED_FIELDS", (CrawlerResultFields.RUNTIME, CrawlerResultFields.TITLE))

    records: list[tuple[str, str]] = []
    provider = _RecordingCrawlerProvider({Website.DMM: _RecordingCrawler(Website.DMM, records)})
    scraper = FileScraper(_SkipFieldConfig(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "ABF-001"

    result = await scraper._call_crawlers(task_input, {Website.DMM})

    assert result is not None
    # TITLE 正常抓取
    assert result.title == "ok"
    # RUNTIME 被跳过
    assert result.runtime == ""
    assert "已跳过" in result.field_log or "skip" in result.field_log.lower()
    # 只请求了 1 次（TITLE），RUNTIME 被跳过不请求
    assert len(records) == 1


def test_field_config_skip_default_false():
    """FieldConfig.skip 默认为 False。"""
    fc = FieldConfig()
    assert fc.skip is False


def test_field_priority_config_skip_default_false():
    """FieldPriorityConfig.skip 默认为 False。"""
    fpc = FieldPriorityConfig()
    assert fpc.skip is False


def test_field_config_skip_serialization():
    """FieldConfig.skip 可以序列化和反序列化。"""
    fc = FieldConfig(skip=True)
    data = fc.model_dump()
    assert data["skip"] is True

    fc2 = FieldConfig.model_validate(data)
    assert fc2.skip is True


def test_config_build_type_field_configs_respects_skip():
    """Config.build_type_field_configs 在 skip=True 时不回退到全局网站列表。"""
    config = Config()
    config.set_field_skip(CrawlerResultFields.RUNTIME, True)

    configs = config.build_type_field_configs(FixedScrapingType.YOUMA)

    # skip=True 的字段应该返回空 site_prority 且 skip=True
    runtime_config = configs[CrawlerResultFields.RUNTIME]
    assert runtime_config.skip is True
    assert runtime_config.site_prority == []

    # 未 skip 的字段应该正常回退到全局网站列表
    title_config = configs[CrawlerResultFields.TITLE]
    assert title_config.skip is False
    assert len(title_config.site_prority) > 0


def test_config_normalize_preserves_skip():
    """_normalize_type_field_config 保留 skip=True 配置。"""
    config = Config()
    config.set_field_skip(CrawlerResultFields.SCORE, True)
    config.ensure_type_field_configs()

    score_config = config.get_type_field_config(FixedScrapingType.YOUMA, CrawlerResultFields.SCORE)
    assert score_config.skip is True
    assert score_config.site_prority == []


def test_config_set_field_skip():
    """set_field_skip 可以设置字段 skip。"""
    config = Config()
    assert config.get_field_config(CrawlerResultFields.TITLE).skip is False

    config.set_field_skip(CrawlerResultFields.TITLE, True)
    assert config.get_field_config(CrawlerResultFields.TITLE).skip is True

    config.set_field_skip(CrawlerResultFields.TITLE, False)
    assert config.get_field_config(CrawlerResultFields.TITLE).skip is False
