from mdcx.crawlers.libredmm import _build_aws_cover_candidates, _build_aws_poster_candidates


def test_cover_candidates_ssis_no_prefix():
    assert _build_aws_cover_candidates("SSIS-001") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg"
    ]


def test_poster_candidates_ssis_no_prefix():
    assert _build_aws_poster_candidates("SSIS-001", "") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001ps.jpg"
    ]


def test_poster_candidates_prefixed_series():
    assert _build_aws_poster_candidates("WANZ-100", "")[0] == (
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/3wanz00100/3wanz00100ps.jpg"
    )
    assert _build_aws_poster_candidates("SW-123", "") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/1sw00123/1sw00123ps.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sw00123/sw00123ps.jpg",
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/h_113sw00123/h_113sw00123ps.jpg",
    ]


def test_poster_candidates_thumb_suffix_fallback():
    thumb = "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipx00535/ipx00535pl.jpg"
    candidates = _build_aws_poster_candidates("IPX-535", thumb)
    assert "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ipx00535/ipx00535ps.jpg" in candidates


def test_cover_candidates_only_landscape():
    for url in _build_aws_cover_candidates("IPX-535"):
        assert url.endswith("pl.jpg")


def test_poster_candidates_only_portrait():
    for url in _build_aws_poster_candidates("IPX-535", ""):
        assert url.endswith("ps.jpg")
