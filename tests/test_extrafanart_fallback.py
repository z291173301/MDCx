"""议题 #131：剧照（extrafanart）下载失败后回退下一来源的回归测试。

现象：能刮到剧照 URL，但站点已删图导致下载 404，程序不再尝试其它剧照网站
（如 javdb 有、avbase 没有，或反之）。

修复：字段合并阶段按剧照字段优先级收集各来源的 URL 列表（extrafanart_list），
下载阶段按顺序尝试，任一来源整组下载成功即原子替换并结束；整组失败则换下一
来源；全部失败保持「沿用本地旧文件」行为。
"""

from pathlib import Path

import pytest

import mdcx.core.web as core_web
from mdcx.config.enums import DownloadableFile, Website
from mdcx.config.manager import manager
from mdcx.config.models import Config
from mdcx.core.file_crawler import FileScraper
from mdcx.gen.field_enums import CrawlerResultFields
from mdcx.manual import ManualConfig
from mdcx.models.model_types import CrawlerInput, CrawlerResult
from tests.test_file_crawler_runtime import _FakeCrawlerProvider

pytestmark = pytest.mark.asyncio


def _allow_extrafanart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager.config, "download_files", [DownloadableFile.EXTRAFANART])
    monkeypatch.setattr(manager.config, "keep_files", [])


def _install_fake_downloader(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    failing_urls: set[str],
) -> None:
    async def fake_task(task):
        url, file_path, _folder, _name = task
        calls.append(url)
        if url in failing_urls:
            return False
        file_path.write_bytes(b"x")
        return True

    monkeypatch.setattr(core_web, "download_extrafanart_task", fake_task)


async def test_extrafanart_falls_back_to_next_source_when_primary_urls_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """主来源整组 404 → 回退次来源；次来源完整下载后采用其剧照。"""
    _allow_extrafanart(monkeypatch)
    calls: list[str] = []
    _install_fake_downloader(monkeypatch, calls, failing_urls={"https://javdb.test/a1.jpg"})

    result = await core_web.extrafanart_download(
        ["https://javdb.test/a1.jpg"],
        Website.JAVDB.value,
        tmp_path,
        candidates=[(Website.AVBASE.value, ["https://avbase.test/b1.jpg", "https://avbase.test/b2.jpg"])],
    )

    assert result is True
    assert calls == ["https://javdb.test/a1.jpg", "https://avbase.test/b1.jpg", "https://avbase.test/b2.jpg"]
    folder = tmp_path / "extrafanart"
    assert sorted(p.name for p in folder.iterdir()) == ["fanart1.jpg", "fanart2.jpg"]
    assert not (tmp_path / "extrafanart[DOWNLOAD]").exists()


async def test_extrafanart_keeps_old_files_when_all_sources_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """所有来源均失败：不覆盖本地旧文件，返回 True（沿用旧文件）。"""
    _allow_extrafanart(monkeypatch)
    folder = tmp_path / "extrafanart"
    folder.mkdir()
    old_file = folder / "fanart1.jpg"
    old_file.write_bytes(b"old")

    calls: list[str] = []
    _install_fake_downloader(
        monkeypatch,
        calls,
        failing_urls={"https://javdb.test/a1.jpg", "https://avbase.test/b1.jpg"},
    )

    result = await core_web.extrafanart_download(
        ["https://javdb.test/a1.jpg"],
        Website.JAVDB.value,
        tmp_path,
        candidates=[(Website.AVBASE.value, ["https://avbase.test/b1.jpg"])],
    )

    assert result is True
    assert old_file.read_bytes() == b"old"
    assert calls == ["https://javdb.test/a1.jpg", "https://avbase.test/b1.jpg"]
    assert not (tmp_path / "extrafanart[DOWNLOAD]").exists()


async def test_extrafanart_all_sources_fail_without_old_files_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """无旧文件且所有来源失败 → 返回 False（计为下载失败）。"""
    _allow_extrafanart(monkeypatch)
    _install_fake_downloader(monkeypatch, [], failing_urls={"https://javdb.test/a1.jpg"})

    result = await core_web.extrafanart_download(
        ["https://javdb.test/a1.jpg"],
        Website.JAVDB.value,
        tmp_path,
    )

    assert result is False


async def test_extrafanart_dedupes_identical_candidate_urls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """候选与主来源 URL 完全相同时不重复请求。"""
    _allow_extrafanart(monkeypatch)
    calls: list[str] = []
    _install_fake_downloader(monkeypatch, calls, failing_urls={"https://javdb.test/a1.jpg"})

    result = await core_web.extrafanart_download(
        ["https://javdb.test/a1.jpg"],
        Website.JAVDB.value,
        tmp_path,
        candidates=[(Website.AVBASE.value, ["https://javdb.test/a1.jpg"])],
    )

    assert result is False
    assert calls == ["https://javdb.test/a1.jpg"]


def _build_extrafanart_result(site: Website, urls: list[str]) -> CrawlerResult:
    result = CrawlerResult.empty()
    result.source = site.value
    result.external_id = f"{site.value}:id"
    result.title = f"{site.value} title"
    result.extrafanart = list(urls)
    return result


async def test_call_crawlers_collects_extrafanart_candidates_in_priority_order(monkeypatch: pytest.MonkeyPatch):
    """合并阶段按剧照字段优先级收集各站 URL 列表，主来源排在最前。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.EXTRAFANART,),
    )

    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_extrafanart_result(Website.AVBASE, ["https://avbase.test/a1.jpg"]),
            Website.JAVDB: _build_extrafanart_result(
                Website.JAVDB, ["https://javdb.test/j1.jpg", "https://javdb.test/j2.jpg"]
            ),
        }
    )
    config = Config(website_youma=[Website.AVBASE, Website.JAVDB])
    config.set_field_sites(CrawlerResultFields.EXTRAFANART, [Website.AVBASE, Website.JAVDB])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-131"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.extrafanart_from == Website.AVBASE.value
    assert result.extrafanart == ["https://avbase.test/a1.jpg"]
    assert result.extrafanart_list == [
        (Website.AVBASE.value, ["https://avbase.test/a1.jpg"]),
        (Website.JAVDB.value, ["https://javdb.test/j1.jpg", "https://javdb.test/j2.jpg"]),
    ]


async def test_call_crawlers_skips_duplicate_extrafanart_url_lists(monkeypatch: pytest.MonkeyPatch):
    """两个来源返回完全相同的剧照列表时，候选去重只保留一个。"""
    monkeypatch.setattr(
        ManualConfig,
        "REDUCED_FIELDS",
        (CrawlerResultFields.EXTRAFANART,),
    )
    shared = ["https://cdn.test/s1.jpg", "https://cdn.test/s2.jpg"]
    provider = _FakeCrawlerProvider(
        {
            Website.AVBASE: _build_extrafanart_result(Website.AVBASE, shared),
            Website.JAVDB: _build_extrafanart_result(Website.JAVDB, shared),
        }
    )
    config = Config(website_youma=[Website.AVBASE, Website.JAVDB])
    config.set_field_sites(CrawlerResultFields.EXTRAFANART, [Website.AVBASE, Website.JAVDB])
    scraper = FileScraper(config, provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-132"

    result = await scraper._call_crawlers(task_input, {Website.AVBASE, Website.JAVDB})

    assert result is not None
    assert result.extrafanart_list == [(Website.AVBASE.value, shared)]


async def test_specific_crawler_populates_extrafanart_list():
    """指定单站模式只有一个来源，也填充 extrafanart_list 供下载层消费。"""
    provider = _FakeCrawlerProvider(
        {
            Website.JAVDB: _build_extrafanart_result(Website.JAVDB, ["https://javdb.test/j1.jpg"]),
        }
    )
    scraper = FileScraper(Config(), provider)
    task_input = CrawlerInput.empty()
    task_input.number = "TEST-133"

    result = await scraper._call_specific_crawler(task_input, Website.JAVDB)

    assert result is not None
    assert result.extrafanart_list == [(Website.JAVDB.value, ["https://javdb.test/j1.jpg"])]
