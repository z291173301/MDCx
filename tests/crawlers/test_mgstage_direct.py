import pytest

from mdcx.crawlers.mgstage_direct import (
    build_mgstage_cover_candidates,
    build_mgstage_poster_candidates,
    find_valid_mgstage_cover,
    find_valid_mgstage_poster,
)


def test_luxu_with_digit_prefix():
    candidates = build_mgstage_cover_candidates("259LUXU-1111")
    assert "https://image.mgstage.com/images/luxutv/259luxu/1111/pb_e_259luxu-1111.jpg" in candidates
    assert candidates[0].startswith("https://image.mgstage.com/images/luxutv/259luxu/")


def test_luxu_without_digit_prefix():
    assert build_mgstage_cover_candidates("LUXU-1111") == build_mgstage_cover_candidates("259LUXU-1111")


def test_known_series():
    assert build_mgstage_cover_candidates("OTIM-002")[0].startswith("https://image.mgstage.com/images/onetime/393otim/")
    assert build_mgstage_cover_candidates("CHUC-010")[0].startswith(
        "https://image.mgstage.com/images/firststar/201chuc/"
    )
    assert build_mgstage_cover_candidates("GERK-001")[0].startswith(
        "https://image.mgstage.com/images/guerrilla/302gerk/"
    )
    assert build_mgstage_cover_candidates("ONEZ-100")[0].startswith("https://image.mgstage.com/images/onemore/013onez/")


def test_num_leading_zero_variants():
    candidates = build_mgstage_cover_candidates("259LUXU-0001")
    assert "https://image.mgstage.com/images/luxutv/259luxu/0001/pb_e_259luxu-0001.jpg" in candidates
    assert "https://image.mgstage.com/images/luxutv/259luxu/1/pb_e_259luxu-1.jpg" in candidates


def test_poster_candidates():
    posters = build_mgstage_poster_candidates("259LUXU-1111")
    assert posters == ["https://image.mgstage.com/images/luxutv/259luxu/1111/pf_e_259luxu-1111.jpg"]


def test_dedup():
    candidates = build_mgstage_cover_candidates("259LUXU-1111")
    assert len(candidates) == len(set(candidates))


def test_unknown_series_returns_empty():
    assert build_mgstage_cover_candidates("SSIS-001") == []
    assert build_mgstage_cover_candidates("") == []
    assert build_mgstage_cover_candidates("ABC") == []
    assert build_mgstage_cover_candidates("LUXU") == []


@pytest.mark.asyncio
async def test_find_valid_mgstage_cover_hit(monkeypatch):
    async def _counting_ok(url):
        return url

    async def _big_size(url):
        return 960, 1348

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _big_size)
    url = await find_valid_mgstage_cover("259LUXU-1111")
    assert url is not None
    assert url.endswith("pb_e_259luxu-1111.jpg")


@pytest.mark.asyncio
async def test_find_valid_mgstage_cover_filters_small_image(monkeypatch):
    async def _counting_ok(url):
        return url

    async def _small_size(url):
        return 80, 120

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _small_size)
    assert await find_valid_mgstage_cover("259LUXU-1111") is None


@pytest.mark.asyncio
async def test_find_valid_mgstage_cover_no_hit_returns_none(monkeypatch):
    async def _fail(url):
        return None

    monkeypatch.setattr("mdcx.base.web.check_url", _fail)
    assert await find_valid_mgstage_cover("259LUXU-1111") is None


@pytest.mark.asyncio
async def test_find_valid_mgstage_cover_skips_uncensored(monkeypatch):
    async def _counting_ok(url):
        return url

    async def _big_size(url):
        return 960, 1348

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _big_size)
    assert await find_valid_mgstage_cover("FC2-PPV-1234567") is None
    assert await find_valid_mgstage_cover("HEYZO-0123") is None


@pytest.mark.asyncio
async def test_find_valid_mgstage_poster_hit(monkeypatch):
    async def _counting_ok(url):
        return url

    async def _big_size(url):
        return 422, 600

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _big_size)
    url = await find_valid_mgstage_poster("259LUXU-1111")
    assert url is not None
    assert url.endswith("pf_e_259luxu-1111.jpg")


@pytest.mark.asyncio
async def test_find_valid_mgstage_poster_no_hit_returns_none(monkeypatch):
    async def _fail(url):
        return None

    monkeypatch.setattr("mdcx.base.web.check_url", _fail)
    assert await find_valid_mgstage_poster("259LUXU-1111") is None
    assert await find_valid_mgstage_poster("FC2-PPV-1234567") is None
