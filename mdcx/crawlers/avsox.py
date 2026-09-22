#!/usr/bin/env python3
from typing import override

from ..config.models import Website
from .aio_site import AioSiteCrawler


class AvsoxCrawler(AioSiteCrawler):
    description = "AVSOX 无码（无码专属）"
    """
    avsox（无码）爬虫.

    avsox 与 avmoo/avheat 同属 tellme.pw AIO 平台（命名空间 javu），已改为 Vue SPA + JSON API，
    旧的 HTML 解析方式（#waterfall）已失效，故改用与 AioSiteCrawler 一致的 API 流程。
    """

    namespace = "javu"
    domain_site = "avsox"
    fallback_domain = "https://avsox.click"
    mosaic = "无码"
    with_outline = True
    probe_number = "081826_100"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVSOX
