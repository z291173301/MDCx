from mdcx.web_async import AsyncWebClient


def _client(trusted: str = "") -> AsyncWebClient:
    return AsyncWebClient(timeout=1, cf_bypass_trusted_hosts=trusted)


def test_empty_allowlist_skips_check():
    client = _client("")
    assert client._is_trusted_bypass_landing("https://any.example.com/path") is True
    assert client._is_trusted_bypass_landing("") is True


def test_exact_host_match():
    client = _client("javbus.com,javdb.com")
    assert client._is_trusted_bypass_landing("https://javbus.com/en/1") is True
    assert client._is_trusted_bypass_landing("http://javdb.com/a") is True
    assert client._is_trusted_bypass_landing("https://evil.com/javbus.com") is False


def test_wildcard_subdomain_match():
    client = _client("*.javdb.com")
    assert client._is_trusted_bypass_landing("https://www.javdb.com/x") is True
    assert client._is_trusted_bypass_landing("https://api.javdb.com/x") is True
    # 通配符不匹配裸域名本身
    assert client._is_trusted_bypass_landing("https://javdb.com/x") is False


def test_host_case_insensitive():
    client = _client("JAVBUS.COM")
    assert client._is_trusted_bypass_landing("https://javbus.com/x") is True


def test_invalid_url_rejected_when_allowlist_configured():
    client = _client("javbus.com")
    assert client._is_trusted_bypass_landing("not-a-url") is False
    assert client._is_trusted_bypass_landing("") is False


def test_port_and_scheme_ignored():
    client = _client("javbus.com")
    assert client._is_trusted_bypass_landing("https://javbus.com:8443/x") is True
