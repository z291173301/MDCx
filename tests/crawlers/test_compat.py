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


@pytest.mark.asyncio
async def test_rotate_not_fooled_by_404_inside_url():
    """URL/番号含 404（如 FC2-PPV-404xxxx）遇传输失败时不得误判为真 404，必须继续轮询其余镜像。"""

    class _Number404Client:
        def __init__(self):
            self.calls: list[str] = []

        async def get_text(self, url, **kwargs):
            self.calls.append(url)
            if "m1.test" in url:
                # 传输层失败，但 error 内嵌的 URL 含 404 子串
                return None, "GET https://m1.test/dm285/FC2-PPV-4041234 失败: 连接错误: Recv failure"
            return "<html>ok</html>", ""

    client = _Number404Client()
    crawler = _RotatingCrawler(client=client)
    ctx = Context(input=None)

    html, err = await crawler._get_text_with_rotate(ctx, "https://m1.test/dm285/FC2-PPV-4041234")

    assert html == "<html>ok</html>"
    assert err == ""
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_rotate_stops_on_real_http_404():
    """真 HTTP 404 仍视为页面不存在，首个镜像即停、不轮询。"""

    class _Http404Client:
        def __init__(self):
            self.calls: list[str] = []

        async def get_text(self, url, **kwargs):
            self.calls.append(url)
            return None, f"GET {url} 失败: HTTP 404 body=<html>not found</html>"

    client = _Http404Client()
    crawler = _RotatingCrawler(client=client)
    ctx = Context(input=None)

    html, err = await crawler._get_text_with_rotate(ctx, "https://m1.test/dm285/SSNI-647")

    assert html is None
    assert "HTTP 404" in err
    assert len(client.calls) == 1
