#!/usr/bin/env python3
from typing import override

from ..config.models import Website
from .aio_site import AioSiteCrawler


class AvmooCrawler(AioSiteCrawler):
    description = "AVMOO 有码信息站（仅能有码）"
    namespace = "jav"
    domain_site = "avmoo"
    fallback_domain = "https://avmoo.shop"
    mosaic = "有码"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVMOO
