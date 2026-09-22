import pytest

from mdcx.config.models import Language
from mdcx.crawlers.base import GenericBaseCrawler
from mdcx.crawlers.base.base_types import Context
from mdcx.crawlers.javlibrary import language_path, normalize_language


def test_normalize_language_keeps_language_enum():
    assert normalize_language(Language.ZH_CN) is Language.ZH_CN


def test_normalize_language_accepts_language_value():
    assert normalize_language("zh_tw") is Language.ZH_TW


def test_normalize_language_keeps_unknown_language_value():
    assert normalize_language("unknown") is Language.UNKNOWN


def test_language_path_maps_supported_javlibrary_languages():
    assert language_path(Language.ZH_CN) == "cn"
    assert language_path(Language.ZH_TW) == "tw"
    assert language_path(Language.JP) == "ja"


class _RotatingCrawler(GenericBaseCrawler):
    _skip_auto_register = True
    _domains = ["https://m1.test", "https://m2.test", "https://m3.test"]

    def __init__(self, client, base_url=""):
        super().__init__(client, base_url)
        self._init_rotator(self._domains, custom_url="")

    @classmethod
    def site(cls):
        from mdcx.config.models import Website

        return Website.JAVBUS

    @classmethod
    def base_url_(cls):
        return "https://m1.test"

    async def _generate_search_url(self, *args, **kwargs):
        return ""

    async def _parse_detail_page(self, *args, **kwargs):
        return None

    async def _parse_search_page(self, *args, **kwargs):
        return None

    def new_context(self, *args, **kwargs):
        return Context(input=None)


class _AlwaysFailClient:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    async def get_text(self, url, **kwargs):
        self.calls.append((url, kwargs.get("retry_count")))
        return None, "连接错误"


@pytest.mark.asyncio
async def test_rotate_requests_once_per_mirror():
    """每个镜像只请求一次（retry_count=1），镜像轮询不再与内部重试相乘放大。"""
    client = _AlwaysFailClient()
    crawler = _RotatingCrawler(client=client)
    ctx = Context(input=None)

    html, err = await crawler._get_text_with_rotate(ctx, "https://m1.test/page")

    assert html is None
    assert "所有镜像域名均失败" in err
    # 3 个镜像各请求 1 次，而不是 3 × 内部重试(3) = 9 次
    assert len(client.calls) == 3
    assert all(rc == 1 for _, rc in client.calls)
    # 每次请求切换了域名（轮询生效）
    urls = [u for u, _ in client.calls]
    assert len(set(urls)) == 3


@pytest.mark.asyncio
async def test_rotate_switches_mirror_on_failure():
    """首个镜像失败后立即切换下一个镜像并成功。"""

    class _PartialClient:
        def __init__(self):
            self.calls: list[str] = []

        async def get_text(self, url, **kwargs):
            self.calls.append(url)
            if "m1.test" in url:
                return None, "连接错误"
            return "<html>ok</html>", ""

    client = _PartialClient()
    crawler = _RotatingCrawler(client=client)
    ctx = Context(input=None)

    html, err = await crawler._get_text_with_rotate(ctx, "https://m1.test/page")

    assert html == "<html>ok</html>"
    assert err == ""
    assert len(client.calls) == 2
