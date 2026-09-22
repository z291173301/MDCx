#!/usr/bin/env python3
from typing import override

from ..config.models import Website
from .aio_site import AioSiteCrawler


class AvheatCrawler(AioSiteCrawler):
    description = "AVHEAT 欧美（欧美）"
    namespace = "wav"
    domain_site = "avheat"
    fallback_domain = "https://avheat.shop"
    mosaic = "欧美"
    with_outline = True
    probe_number = "Men.26.08.17"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.AVHEAT
