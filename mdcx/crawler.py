import asyncio
import contextlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, Protocol

from .config.enums import Website
from .crawlers.base import GenericBaseCrawler, get_crawler

if TYPE_CHECKING:
    from .config.models import Config
    from .web_async import AsyncWebClient


class CrawlerProviderProtocol(Protocol):
    client: Any

    async def get(self, site: Website) -> "GenericBaseCrawler[Never]": ...
    async def close(self) -> None: ...


class CrawlerProvider:
    def __init__(self, config: "Config", client: "AsyncWebClient", config_getter: Callable[[], "Config"] | None = None):
        self.instances: dict[Website, GenericBaseCrawler[Never]] = {}
        self.config = config
        self._config_getter = config_getter or (lambda: config)
        self.client = client
        self.lock = asyncio.Lock()
        self.client.retain()
        self._closed = False

    async def get(self, site: Website):
        if r := self.instances.get(site):
            return r
        async with self.lock:
            if site not in self.instances:
                crawler_cls = get_crawler(site)
                if crawler_cls is None:
                    raise ValueError(f"未找到 {site} 的刮削器")
                config = self._config_getter()
                self.instances[site] = crawler_cls(
                    client=self.client,
                    base_url=config.get_site_url(site),
                    browser=None,
                )
        return self.instances[site]

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            for instance in self.instances.values():
                # 逐实例收尾：单个实例的清理异常不得阻断其余实例与租约归还
                with contextlib.suppress(Exception):
                    await instance.close()
            self.instances.clear()
        finally:
            # client.release() 必须恒执行：漏掉即租永不归零，
            # close_when_idle 等满 300s 强制关闭（议题 #98 残留租约）
            with contextlib.suppress(Exception):
                await self.client.release()
