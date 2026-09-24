"""站点名单归一化（使用代理网站 / 直连白名单）：去 scheme、尾斜杠，中文逗号转英文。"""

from mdcx.config.models import Config, normalize_site_list


def test_strip_scheme_and_trailing_slash():
    assert normalize_site_list("https://missav.ws/") == "missav.ws"
    assert normalize_site_list("http://example.com/a?b=1#c") == "example.com"
    assert normalize_site_list("HTTPS://AVSEX.CC") == "AVSEX.CC"


def test_chinese_comma_and_dedupe():
    assert normalize_site_list("a.com，b.com、c.com") == "a.com,b.com,c.com"
    assert normalize_site_list("a.com, a.com,, ,b.com") == "a.com,b.com"
    assert normalize_site_list("") == ""
    assert normalize_site_list(None) == ""


def test_preserve_site_values_wildcard_and_port():
    assert normalize_site_list("javdb,*,example.com:8080") == "javdb,*,example.com:8080"


def test_config_validator_normalizes_on_load():
    cfg = Config(proxy_sites="https://a.com/，b.com", direct_sites="http://c.com/d，")
    assert cfg.proxy_sites == "a.com,b.com"
    assert cfg.direct_sites == "c.com"
