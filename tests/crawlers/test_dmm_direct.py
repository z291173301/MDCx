import pytest

from mdcx.crawlers.dmm_direct import generate_cid_candidates, generate_image_candidates


def test_ipx_no_prefix_first():
    candidates = generate_cid_candidates("IPX-535")
    assert candidates[0] == "ipx00535"
    assert "ipx00535" in candidates


def test_abf_prefixed_candidate():
    candidates = generate_cid_candidates("ABF-042")
    assert "436abf00042" in candidates
    assert "abf00042" in candidates


def test_common_series_padded_five():
    candidates = generate_cid_candidates("SSIS-001")
    assert candidates == ["ssis00001"]
    assert generate_cid_candidates("MIDV-100") == ["midv00100"]


def test_special_threshold_small():
    assert "avop00100" in generate_cid_candidates("AVOP-100")
    assert "avop00001" in generate_cid_candidates("AVOP-1")


def test_special_threshold_large():
    assert "1avop00200" in generate_cid_candidates("AVOP-200")
    assert "h_860gigl00643" in generate_cid_candidates("GIGL-643")
    assert "gigl00644" in generate_cid_candidates("GIGL-644")


def test_special_threshold_avop_boundary():
    # ≤168 无前缀，>168 前缀 1（avbase 实测 avop00168 / 1avop00604）
    assert generate_cid_candidates("AVOP-168")[0] == "avop00168"
    assert generate_cid_candidates("AVOP-169")[0] == "1avop00169"
    assert "59avop00168" not in generate_cid_candidates("AVOP-168")


def test_prefix_group_members():
    candidates = generate_cid_candidates("DISM-123")
    assert candidates[0] == "1dism00123"
    candidates = generate_cid_candidates("HODV-001")
    assert "5642hodv00001" in candidates


def test_real_verified_prefixes():
    assert generate_cid_candidates("SW-123") == ["1sw00123", "sw00123", "h_113sw00123"]
    assert generate_cid_candidates("WANZ-100")[0] == "3wanz00100"
    assert generate_cid_candidates("NTRD-100")[0] == "18ntrd00100"
    assert generate_cid_candidates("PPD-100")[0] == "143ppd00100"
    assert generate_cid_candidates("UMD-100")[0] == "143umd00100"
    assert generate_cid_candidates("MBD-100")[0] == "433mbd00100"
    assert generate_cid_candidates("SIN-100")[0] == "sin00100"
    assert generate_cid_candidates("YMD-100")[0] == "h_189ymd00100"
    assert generate_cid_candidates("MADM-100")[0] == "49madm00100"


def test_digit_series():
    candidates = generate_cid_candidates("T28-123")
    assert "55t2800123" in candidates
    assert "t2800123" in candidates
    assert generate_cid_candidates("T-2828") == generate_cid_candidates("T28-028")


def test_dedup_and_order():
    candidates = generate_cid_candidates("IPX-535")
    assert len(candidates) == len(set(candidates))


def test_invalid_number_returns_empty():
    assert generate_cid_candidates("") == []
    assert generate_cid_candidates("abc") == []
    assert generate_cid_candidates("12345") == []


def test_image_candidates_pairing():
    images = generate_image_candidates("IPX-535")
    assert len(images) == len(generate_cid_candidates("IPX-535")) * 2
    portrait = [o for o, _ in images if o == "portrait"]
    landscape = [o for o, _ in images if o == "landscape"]
    assert len(portrait) == len(landscape)
    for orient, url in images[:2]:
        assert url.startswith("https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/")
        assert url.endswith(".jpg")
        if orient == "portrait":
            assert "ps.jpg" in url
        else:
            assert "pl.jpg" in url


def test_is_uncensored_number():
    from mdcx.crawlers.dmm_direct import is_uncensored_number

    assert is_uncensored_number("FC2-PPV-1234567")
    assert is_uncensored_number("HEYZO-0123")
    assert is_uncensored_number("CARIB_0421")
    assert not is_uncensored_number("SSIS-538")
    assert not is_uncensored_number("WANZ-100")
    assert not is_uncensored_number("")


def test_probe_discovered_prefixed_series():
    from mdcx.crawlers.dmm_direct import generate_cid_candidates

    expected = {
        "MILK-100": "h_1240milk00100",
        "HZGD-100": "h_1100hzgd00100",
        "FONE-100": "h_491fone00100",
        "BKD-100": "17bkd00100",
        "ONEZ-100": "118onez00100",
        "MADM-100": "49madm00100",
        "ABF-030": "436abf00030",
        "GG-100": "13gg00100",
        "GVG-100": "13gvg00100",
        "OVG-100": "13ovg00100",
    }
    for number, first_cid in expected.items():
        candidates = generate_cid_candidates(number)
        assert candidates[0] == first_cid, f"{number}: 首个候选 {candidates[0]} != {first_cid}"
        assert first_cid in candidates


def test_probe_discovered_prefix1_series():
    from mdcx.crawlers.dmm_direct import generate_cid_candidates

    for series in ["STARS", "START", "SDJS", "SDMT", "RCTD", "RCT", "FSDSS", "MMGH", "GS"]:
        candidates = generate_cid_candidates(f"{series}-100")
        assert candidates[0] == f"1{series.lower()}00100", f"{series}: {candidates[0]}"
        assert f"1{series.lower()}00100" in candidates


def test_probe2_discovered_series():
    from mdcx.crawlers.dmm_direct import generate_cid_candidates

    expected = {
        # 无前缀
        "SSNI-100": "ssni00100",
        "SONE-100": "sone00100",
        "OFJE-100": "ofje00100",
        "MIAB-100": "miab00100",
        "IPVR-100": "ipvr00100",
        "IPIT-100": "ipit00100",
        "JUL-100": "jul00100",
        "JUFD-100": "jufd00100",
        "JUK-100": "juk00100",
        "JUX-100": "jux00100",
        "WAAA-100": "waaa00100",
        "HNTD-100": "hntd00100",
        "JUE-100": "jue00100",
        "EBOD-100": "ebod00100",
        # 前缀 1
        "SDNM-100": "1sdnm00100",
        "SDMS-100": "1sdms00100",
        "SDMM-100": "1sdmm00100",
        "SDMF-100": "1sdmf00100",
        "FSET-100": "1fset00100",
        # 前缀 13 / 18 / h_113 / h_068
        "GVH-100": "13gvh00100",
        "MOMJ-100": "18momj00100",
        "GGG-100": "h_113ggg00100",
        "MXGS-100": "h_068mxgs00100",
    }
    for number, first_cid in expected.items():
        candidates = generate_cid_candidates(number)
        assert candidates[0] == first_cid, f"{number}: 首个候选 {candidates[0]} != {first_cid}"
        assert first_cid in candidates


def test_probe3_discovered_series():
    from mdcx.crawlers.dmm_direct import generate_cid_candidates

    assert generate_cid_candidates("SDAM-100")[0] == "1sdam00100"
    assert generate_cid_candidates("SSND-100")[0] == "h_205ssnd00100"
    assert generate_cid_candidates("ONSD-100")[0] == "onsd00100"


def test_probe4_discovered_series():
    from mdcx.crawlers.dmm_direct import generate_cid_candidates

    expected = {
        "KMHRS-100": "1kmhrs00100",
        "DLDSS-100": "1dldss00100",
        "HUNT-100": "1hunt00100",
        "DOK-100": "41dok00100",
        "HUSR-100": "h_1454husr00100",
        "CRE-100": "77cre00100",
        "MUKD-100": "mukd00100",
        "DASD-100": "dasd00100",
        "MYMD-100": "mymd00100",
        "KAWD-100": "kawd00100",
        "MUDR-100": "mudr00100",
        "BF-100": "bf00100",
        "CND-100": "cnd00100",
        "DVDMS-100": "dvdms00100",
        "EYAN-100": "eyan00100",
    }
    for number, first_cid in expected.items():
        candidates = generate_cid_candidates(number)
        assert candidates[0] == first_cid, f"{number}: 首个候选 {candidates[0]} != {first_cid}"
        assert first_cid in candidates


class _FakeCtx:
    def __init__(self):
        self.logs = []

    def debug(self, message):
        self.logs.append(message)


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_cache_hit_skips_probe(monkeypatch):
    from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

    calls = []

    async def _counting_ok(url):
        calls.append(url)
        return url

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    ctx = _FakeCtx()
    cover1, poster1 = await upgrade_dmm_cover(ctx, "SSIS-001", "old_cover.jpg", "old_poster.jpg")
    assert cover1.endswith("ssis00001pl.jpg")
    assert poster1.endswith("ssis00001ps.jpg")
    first_calls = len(calls)
    cover2, poster2 = await upgrade_dmm_cover(ctx, "SSIS-001", "old_cover2.jpg", "old_poster2.jpg")
    assert cover2 == cover1
    assert poster2 == poster1
    assert len(calls) == first_calls


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_cache_failure_keeps_original(monkeypatch):
    from mdcx.crawlers.dmm_direct import upgrade_dmm_cover

    async def _fail(url):
        return None

    monkeypatch.setattr("mdcx.base.web.check_url", _fail)
    ctx = _FakeCtx()
    cover, poster = await upgrade_dmm_cover(ctx, "SSIS-001", "site_a_cover.jpg", "site_a_poster.jpg")
    assert cover == "site_a_cover.jpg"
    assert poster == "site_a_poster.jpg"
    cover2, poster2 = await upgrade_dmm_cover(ctx, "SSIS-001", "site_b_cover.jpg", "site_b_poster.jpg")
    assert cover2 == "site_b_cover.jpg"
    assert poster2 == "site_b_poster.jpg"


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_inflight_dedup(monkeypatch):
    import asyncio

    from mdcx.crawlers.dmm_direct import (
        build_aws_cover_candidates,
        build_aws_poster_candidates,
        upgrade_dmm_cover,
    )

    calls = []

    async def _counting_ok(url):
        calls.append(url)
        return url

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    ctx = _FakeCtx()
    expected = len(build_aws_cover_candidates("SSIS-001")) + len(build_aws_poster_candidates("SSIS-001"))
    results = await asyncio.gather(
        upgrade_dmm_cover(ctx, "SSIS-001", "a_cover.jpg", "a_poster.jpg"),
        upgrade_dmm_cover(ctx, "SSIS-001", "b_cover.jpg", "b_poster.jpg"),
    )
    assert len(calls) == expected
    assert results[0][0] == results[1][0]


@pytest.mark.asyncio
async def test_find_valid_dmm_cover_hit(monkeypatch):
    from mdcx.crawlers.dmm_direct import find_valid_dmm_cover

    async def _counting_ok(url):
        return url

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    url = await find_valid_dmm_cover("SSIS-001")
    assert url is not None
    assert url.endswith("pl.jpg")


@pytest.mark.asyncio
async def test_find_valid_dmm_cover_no_hit_returns_none(monkeypatch):
    from mdcx.crawlers.dmm_direct import find_valid_dmm_cover

    async def _fail(url):
        return None

    monkeypatch.setattr("mdcx.base.web.check_url", _fail)
    assert await find_valid_dmm_cover("SSIS-001") is None


@pytest.mark.asyncio
async def test_find_valid_dmm_cover_skips_uncensored(monkeypatch):
    from mdcx.crawlers.dmm_direct import find_valid_dmm_cover

    async def _counting_ok(url):
        return url

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _counting_ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    assert await find_valid_dmm_cover("FC2-PPV-1234567") is None
