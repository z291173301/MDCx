import pytest

from mdcx.core.web import _should_skip_amazon_for_existing_poster
from mdcx.models.model_types import CrawlersResult

DMM_HD_PS = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg"
DMM_THUMB_PS = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipx00001/ipx00001ps.jpg"


def _make_result(poster: str, poster_from: str = "javbus") -> CrawlersResult:
    result = CrawlersResult.empty()
    result.poster = poster
    result.poster_from = poster_from
    return result


@pytest.mark.asyncio
async def test_skip_amazon_dmm_hd_poster_by_resolution(monkeypatch):
    async def _image_size(url, media_context=None):
        return 1032, 1469

    async def _should_not_called(url):
        raise AssertionError("DMM 高清图按分辨率放行，不应再查询字节大小")

    monkeypatch.setattr("mdcx.core.web._get_image_size", _image_size)
    monkeypatch.setattr("mdcx.core.web.get_url_content_length", _should_not_called)
    assert await _should_skip_amazon_for_existing_poster(_make_result(DMM_HD_PS), None) is True


@pytest.mark.asyncio
async def test_not_skip_amazon_dmm_thumbnail_poster(monkeypatch):
    async def _image_size(url, media_context=None):
        return 147, 200

    async def _small(url):
        return 14 * 1024

    monkeypatch.setattr("mdcx.core.web._get_image_size", _image_size)
    monkeypatch.setattr("mdcx.core.web.get_url_content_length", _small)
    assert await _should_skip_amazon_for_existing_poster(_make_result(DMM_THUMB_PS), None) is False


@pytest.mark.asyncio
async def test_skip_amazon_dmm_mid_size_poster(monkeypatch):
    async def _image_size(url, media_context=None):
        return 745, 1081

    monkeypatch.setattr("mdcx.core.web._get_image_size", _image_size)
    assert await _should_skip_amazon_for_existing_poster(_make_result(DMM_HD_PS), None) is True


@pytest.mark.asyncio
async def test_not_skip_amazon_dmm_narrow_poster(monkeypatch):
    async def _image_size(url, media_context=None):
        return 588, 800

    async def _mid(url):
        return 152 * 1024

    monkeypatch.setattr("mdcx.core.web._get_image_size", _image_size)
    monkeypatch.setattr("mdcx.core.web.get_url_content_length", _mid)
    assert await _should_skip_amazon_for_existing_poster(_make_result(DMM_HD_PS), None) is False


@pytest.mark.asyncio
async def test_skip_amazon_non_dmm_large_poster_keeps_byte_threshold(monkeypatch):
    async def _image_size(url, media_context=None):
        return 1000, 1500

    async def _large(url):
        return 500 * 1024

    monkeypatch.setattr("mdcx.core.web._get_image_size", _image_size)
    monkeypatch.setattr("mdcx.core.web.get_url_content_length", _large)
    assert await _should_skip_amazon_for_existing_poster(_make_result("https://img.javbus.com/x/abc.jpg"), None) is True


@pytest.mark.asyncio
async def test_not_skip_amazon_when_poster_from_amazon(monkeypatch):
    assert await _should_skip_amazon_for_existing_poster(_make_result(DMM_HD_PS, poster_from="Amazon"), None) is False
