from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit


class DomainRotator:
    """站点域名轮询器：主域名失败时自动切换备用域名重试。

    用于部分站点（javbus 等）存在多个镜像域名，某个域名不可达/被 CF 拦截时
    可换备用域名继续抓取。请求失败时调用 next() 切换，返回新 base_url。
    """

    def __init__(self, domains: Iterable[str], custom_url: str = ""):
        self._domains: list[str] = []
        for d in domains:
            d = str(d or "").strip().rstrip("/")
            if d and d not in self._domains:
                self._domains.append(d)
        # 用户自定义 URL 优先，单独作为一个域名（不参与轮询列表去重）
        self._custom = str(custom_url or "").strip().rstrip("/")
        if self._custom and self._custom not in self._domains:
            self._domains.insert(0, self._custom)
        self._index = 0

    @property
    def current(self) -> str:
        if not self._domains:
            return ""
        return self._domains[self._index % len(self._domains)]

    def rotate(self) -> str:
        """切换到下一个域名并返回新的 base_url。"""
        if len(self._domains) <= 1:
            return self.current
        self._index = (self._index + 1) % len(self._domains)
        return self.current

    @property
    def domains(self) -> list[str]:
        return list(self._domains)

    def reset(self) -> None:
        self._index = 0

    def current_is_custom(self) -> bool:
        """当前使用的域名是否来自用户自定义 URL。"""
        return bool(self._custom) and self.current == self._custom

    def rebuild_url(self, url: str, new_base: str | None = None) -> str:
        """把 url 的 host 替换为指定 base_url（默认当前域名）。"""
        parts = urlsplit(url)
        base = urlsplit(new_base or self.current)
        return urlunsplit((base.scheme, base.netloc, parts.path, parts.query, parts.fragment))
