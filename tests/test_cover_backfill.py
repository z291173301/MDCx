import asyncio
from pathlib import Path

import pytest

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.core import file_crawler
from mdcx.models.model_types import FileInfo
from scripts import cover_backfill as cb


def test_dedupe_candidates_filters_empty_urls_and_keeps_order():
    candidates = [
        ("poster", "https://a.com/1.jpg"),
        ("poster", ""),
        ("thumb", "https://a.com/1.jpg"),
        ("thumb", "https://b.com/2.jpg"),
        ("fanart", None),
    ]
    assert cb._dedupe_candidates(candidates) == [
        ("poster", "https://a.com/1.jpg"),
        ("thumb", "https://b.com/2.jpg"),
    ]


def test_dedupe_candidates_returns_empty_for_no_valid_candidates():
    assert cb._dedupe_candidates([("poster", ""), ("thumb", None)]) == []


def _build_file_info(tmp_path: Path, number: str = "ABC-123") -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = number
    file_info.file_path = tmp_path / f"{number}.mp4"
    file_info.folder_path = tmp_path
    file_info.file_name = number
    return file_info


def test_cover_candidate_sites_forced_site_wins(tmp_path: Path):
    file_info = _build_file_info(tmp_path)
    assert cb._cover_candidate_sites(file_info, forced_site="r18dev") == ["r18dev"]


def test_cover_candidate_sites_uses_single_website(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    file_info = _build_file_info(tmp_path)

    classification = file_crawler.ScrapeClassification(FixedScrapingType.AUTO, "auto", website=Website.MYWIFE)
    monkeypatch.setattr(cb, "classify_scrape_task", lambda task, config: classification)

    assert cb._cover_candidate_sites(file_info, forced_site=None) == ["mywife"]


def test_cover_candidate_sites_orders_priority_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    file_info = _build_file_info(tmp_path)

    classification = file_crawler.ScrapeClassification(
        FixedScrapingType.AUTO,
        "auto",
        sites=[Website.MISSAV, Website.R18DEV, Website.OFFICIAL, Website.MGSTAGE],
    )
    monkeypatch.setattr(cb, "classify_scrape_task", lambda task, config: classification)

    assert cb._cover_candidate_sites(file_info, forced_site=None) == [
        "official",
        "mgstage",
        "missav",
        "r18dev",
    ]


def test_resolve_backfill_input_empty_raises():
    with pytest.raises(ValueError, match="input is empty"):
        asyncio.run(cb.resolve_backfill_input("   "))


def test_resolve_backfill_input_parses_number_from_raw(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    async def _fake_get_file_info_v2(info_path, copy_sub=False):
        file_info = _build_file_info(tmp_path, number="ABC-123")
        return file_info

    monkeypatch.setattr(cb, "get_file_info_v2", _fake_get_file_info_v2)

    result = asyncio.run(cb.resolve_backfill_input("ABC-123"))

    assert result.number == "ABC-123"
    assert result.source_file is None


def test_resolve_backfill_input_falls_back_to_file_info_number(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    async def _fake_get_file_info_v2(info_path, copy_sub=False):
        file_info = _build_file_info(tmp_path, number="XYZ-999")
        return file_info

    monkeypatch.setattr(cb, "get_file_info_v2", _fake_get_file_info_v2)
    monkeypatch.setattr(cb, "get_file_number", lambda filepath, escape_list: "")

    result = asyncio.run(cb.resolve_backfill_input("some-random-string"))

    assert result.number == "XYZ-999"


def test_dmm_direct_backfill_downloads_portrait_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    async def _fake_download(url, temp_path, folder_path):
        temp_path.write_bytes(b"fake-jpeg")
        return True

    async def _fake_check_pic(path):
        return (1032, 1469)

    async def _fake_move(src, dst):
        dst.write_bytes(src.read_bytes())

    async def _fake_copy(src, dst):
        dst.write_bytes(src.read_bytes())

    monkeypatch.setattr(cb, "download_file_with_filepath", _fake_download)
    monkeypatch.setattr(cb, "check_pic_async", _fake_check_pic)
    monkeypatch.setattr(cb, "move_file_async", _fake_move)
    monkeypatch.setattr(cb, "copy_file_async", _fake_copy)

    result = asyncio.run(cb._try_dmm_direct_backfill("IPX-535", tmp_path, overwrite=False))

    assert result is not None
    assert result.source == "dmm_direct"
    assert result.thumb_path == tmp_path / "IPX-535-thumb.jpg"
    assert result.poster_path == tmp_path / "IPX-535-poster.jpg"
    assert result.poster_path.exists()
    assert result.thumb_path.exists()


def test_dmm_direct_backfill_rejects_small_or_invalid_images(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    async def _fake_download(url, temp_path, folder_path):
        temp_path.write_bytes(b"fake-jpeg")
        return True

    async def _fake_check_pic(path):
        return (120, 160)

    async def _fake_move(src, dst):
        dst.write_bytes(src.read_bytes())

    async def _fake_copy(src, dst):
        dst.write_bytes(src.read_bytes())

    async def _fake_delete(path):
        path.unlink(missing_ok=True)

    monkeypatch.setattr(cb, "download_file_with_filepath", _fake_download)
    monkeypatch.setattr(cb, "check_pic_async", _fake_check_pic)
    monkeypatch.setattr(cb, "move_file_async", _fake_move)
    monkeypatch.setattr(cb, "copy_file_async", _fake_copy)
    monkeypatch.setattr(cb, "delete_file_async", _fake_delete)

    result = asyncio.run(cb._try_dmm_direct_backfill("IPX-535", tmp_path, overwrite=False))

    assert result is None
    assert not (tmp_path / "IPX-535-poster.jpg").exists()


def test_dmm_direct_backfill_invalid_number_returns_none(tmp_path: Path):
    assert asyncio.run(cb._try_dmm_direct_backfill("xyzzy", tmp_path, overwrite=False)) is None


def test_dmm_direct_backfill_falls_back_to_landscape_crop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    async def _fake_download(url, temp_path, folder_path):
        if "ps.jpg" in url:
            return False
        temp_path.write_bytes(b"fake-jpeg")
        return True

    async def _fake_check_pic(path):
        return (2184, 1469)

    async def _fake_move(src, dst):
        dst.write_bytes(src.read_bytes())

    async def _fake_copy(src, dst):
        dst.write_bytes(src.read_bytes())

    async def _fake_delete(path):
        path.unlink(missing_ok=True)

    def _fake_cut_thumb_to_poster(json_data, thumb_path, poster_path, scraping_type, log_fn=None):
        poster_path.write_bytes(thumb_path.read_bytes())
        json_data.poster_from = "cut"
        return True

    monkeypatch.setattr(cb, "download_file_with_filepath", _fake_download)
    monkeypatch.setattr(cb, "check_pic_async", _fake_check_pic)
    monkeypatch.setattr(cb, "move_file_async", _fake_move)
    monkeypatch.setattr(cb, "copy_file_async", _fake_copy)
    monkeypatch.setattr(cb, "delete_file_async", _fake_delete)
    monkeypatch.setattr("mdcx.core.image.cut_thumb_to_poster", _fake_cut_thumb_to_poster)

    result = asyncio.run(cb._try_dmm_direct_backfill("IPX-535", tmp_path, overwrite=False))

    assert result is not None
    assert result.thumb_path == tmp_path / "IPX-535-thumb.jpg"
    assert result.poster_path == tmp_path / "IPX-535-poster.jpg"
    assert result.thumb_path.exists()
    assert result.poster_path.exists()
