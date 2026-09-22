from pathlib import Path

import pytest
from PIL import Image

from mdcx.config.enums import FixedScrapingType
from mdcx.core.web import _maybe_right_crop_youma_poster
from mdcx.models.model_types import CrawlersResult, OtherInfo


def _result(**kwargs) -> CrawlersResult:
    result = CrawlersResult.empty()
    result.scraping_type = FixedScrapingType.YOUMA
    result.number = "ABP-622"
    result.image_download = True
    for key, value in kwargs.items():
        setattr(result, key, value)
    return result


def _other(thumb_path: Path | None, fanart_path: Path | None) -> OtherInfo:
    other = OtherInfo.empty()
    other.thumb_path = thumb_path
    other.fanart_path = fanart_path
    return other


@pytest.mark.asyncio
async def test_maybe_right_crop_yields_portrait_for_landscape_poster(tmp_path):
    poster = tmp_path / "poster.jpg"
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (800, 539), (200, 30, 30)).save(poster)
    Image.new("RGB", (800, 539), (30, 200, 30)).save(thumb)

    result = _result()
    other = _other(thumb, None)
    await _maybe_right_crop_youma_poster(result, other, poster)
    with Image.open(poster) as img:
        w, h = img.size
    assert h > w
    assert w <= 400


@pytest.mark.asyncio
async def test_maybe_right_crop_keeps_portrait_poster(tmp_path):
    poster = tmp_path / "poster.jpg"
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (400, 600), (200, 30, 30)).save(poster)
    Image.new("RGB", (800, 539), (30, 200, 30)).save(thumb)

    result = _result()
    other = _other(thumb, None)
    await _maybe_right_crop_youma_poster(result, other, poster)
    with Image.open(poster) as img:
        assert img.size == (400, 600)


@pytest.mark.asyncio
async def test_maybe_right_crop_ignores_wuma(tmp_path):
    poster = tmp_path / "poster.jpg"
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (800, 539), (200, 30, 30)).save(poster)
    Image.new("RGB", (800, 539), (30, 200, 30)).save(thumb)

    result = _result(scraping_type=FixedScrapingType.WUMA)
    other = _other(thumb, None)
    await _maybe_right_crop_youma_poster(result, other, poster)
    with Image.open(poster) as img:
        assert img.size == (800, 539)


@pytest.mark.asyncio
async def test_maybe_right_crop_noop_when_no_source(tmp_path):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (800, 539), (200, 30, 30)).save(poster)

    result = _result()
    other = _other(None, None)
    await _maybe_right_crop_youma_poster(result, other, poster)
    with Image.open(poster) as img:
        assert img.size == (800, 539)


@pytest.mark.asyncio
async def test_maybe_right_crop_vr_noop(tmp_path):
    poster = tmp_path / "poster.jpg"
    thumb = tmp_path / "thumb.jpg"
    Image.new("RGB", (800, 539), (200, 30, 30)).save(poster)
    Image.new("RGB", (800, 539), (30, 200, 30)).save(thumb)

    result = _result(number="VR-123", title="VR Test")
    other = _other(thumb, None)
    await _maybe_right_crop_youma_poster(result, other, poster)
    with Image.open(poster) as img:
        assert img.size == (800, 539)
