import pytest
from lxml import etree

from mdcx.crawlers.javbus import getRelease, getValidRelease, getYear


def _build_html(release: str):
    html = f"""
    <html>
      <body>
        <p><span class="header">發行日期:</span> {release}</p>
      </body>
    </html>
    """
    return etree.fromstring(html, etree.HTMLParser())


def test_get_valid_release_and_year():
    assert getValidRelease("2024-1-2") == "2024-01-02"
    assert getYear("2024-1-2") == "2024"


def test_get_release_placeholder_date_returns_invalid():
    html = _build_html("0000-00-00")
    release = getRelease(html)
    assert release == "0000-00-00"
    assert getValidRelease(release) == ""
    assert getYear(release) == ""


def test_should_skip_dmm_upgrade_uncensored():
    from mdcx.crawlers.javbus import _should_skip_dmm_upgrade

    assert _should_skip_dmm_upgrade("FC2-PPV-1234567")
    assert _should_skip_dmm_upgrade("HEYZO-0123")
    assert _should_skip_dmm_upgrade("CARIB_0421")
    assert not _should_skip_dmm_upgrade("SSIS-538")
    assert not _should_skip_dmm_upgrade("WANZ-100")


def test_is_match_tolerates_dmm_z_suffix():
    # 议题 #106：DMM `z` 尾缀番号应命中站点收录的基础番号
    from mdcx.crawlers.javbus import is_match

    assert is_match("/IBW-786", "IBW-786z")
    assert is_match("/IBW-786z", "IBW-786z")
    assert is_match("/IBW-786_1", "IBW-786z")
    assert not is_match("/IBW-7860", "IBW-786z")
    assert not is_match("/IBW-123", "IBW-786z")


def test_build_aws_cover_candidates_ssis():
    from mdcx.crawlers.javbus import _build_aws_cover_candidates

    assert _build_aws_cover_candidates("SSIS-001") == [
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/ssis00001/ssis00001pl.jpg"
    ]


def test_build_aws_poster_candidates_prefixed_series():
    from mdcx.crawlers.javbus import _build_aws_poster_candidates

    assert _build_aws_poster_candidates("WANZ-100")[0] == (
        "https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/3wanz00100/3wanz00100ps.jpg"
    )


class _FakeCtx:
    def __init__(self):
        self.logs = []

    def debug(self, message: str):
        self.logs.append(message)


async def _ok(url: str) -> str:
    return url


async def _fail(url: str) -> None:
    return None


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_success(monkeypatch):
    from mdcx.crawlers.javbus import _upgrade_dmm_cover

    async def _hd_size(url):
        return 1032, 1469

    monkeypatch.setattr("mdcx.base.web.check_url", _ok)
    monkeypatch.setattr("mdcx.base.web.get_imgsize", _hd_size)
    ctx = _FakeCtx()
    cover, poster = await _upgrade_dmm_cover(ctx, "SSIS-001", "old_cover.jpg", "old_poster.jpg")
    assert cover.endswith("ssis00001pl.jpg")
    assert poster.endswith("ssis00001ps.jpg")


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_fail_keeps_original(monkeypatch):
    from mdcx.crawlers.javbus import _upgrade_dmm_cover

    monkeypatch.setattr("mdcx.base.web.check_url", _fail)
    ctx = _FakeCtx()
    cover, poster = await _upgrade_dmm_cover(ctx, "SSIS-001", "old_cover.jpg", "old_poster.jpg")
    assert cover == "old_cover.jpg"
    assert poster == "old_poster.jpg"


@pytest.mark.asyncio
async def test_upgrade_dmm_cover_skips_uncensored(monkeypatch):
    from mdcx.crawlers.javbus import _upgrade_dmm_cover

    async def _should_not_be_called(url: str) -> str:
        raise AssertionError("无码番号不应发起候选请求")

    monkeypatch.setattr("mdcx.base.web.check_url", _should_not_be_called)
    ctx = _FakeCtx()
    cover, poster = await _upgrade_dmm_cover(ctx, "HEYZO-0123", "old_cover.jpg", "old_poster.jpg")
    assert cover == "old_cover.jpg"
    assert poster == "old_poster.jpg"
