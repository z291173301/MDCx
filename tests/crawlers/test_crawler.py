import pytest

from mdcx.config.enums import Website
from mdcx.config.models import Config, SiteConfig
from mdcx.crawler import CrawlerProvider
from mdcx.crawlers.base import crawler_registry, get_crawler, validate_crawler_registry
from mdcx.web_async import AsyncWebClient


def test_crawler_classes():
    """测试所有注册的爬虫类可正常初始化."""
    async_client = AsyncWebClient(timeout=1)
    for site in crawler_registry:
        crawler_class = get_crawler(site)
        assert crawler_class is not None, f"未找到 {site} 的爬虫"
        # assert crawler_class.site() == site, f"{crawler_class} 的 site 方法返回值不正确"
        crawler_class(client=async_client)


def test_validate_crawler_registry_no_missing():
    """所有 Website 枚举值都应有所属爬虫，除已废弃的兼容值外。

    已废弃的 Website.AIRAV 仅用于兼容旧配置（无爬虫，见 migrations.py
    的 _is_removed_airav_site 与 manual.py 的 SUPPORTED_WEBSITES 排除），
    不应算作缺失。若新增 Website 枚举值却漏注册爬虫，此测试应失败。
    """
    missing = validate_crawler_registry()
    assert missing == [], f"存在未注册爬虫的 Website 枚举值: {missing}"
    # 明确断言 AIRAV 是"有意废弃、无爬虫"，防止误加回爬虫。
    assert get_crawler(Website.AIRAV) is None, "Website.AIRAV 是废弃值，不应有爬虫"
    assert get_crawler(Website.AIRAV_CC) is not None, "Website.AIRAV_CC 应有爬虫"


@pytest.mark.asyncio
async def test_crawler_provider_always_uses_http_only():
    config = Config()
    config.site_configs[Website.DMM] = SiteConfig()
    provider = CrawlerProvider(config=config, client=AsyncWebClient(timeout=1))

    crawler = await provider.get(Website.DMM)

    assert crawler is not None
    assert crawler.browser is None
    await provider.close()
