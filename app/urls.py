from __future__ import annotations

from urllib.parse import urlsplit

from app.errors import ConsoleError

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def validate_loopback_url(url: str) -> str:
    if not url or not isinstance(url, str):
        raise ConsoleError("HTTP driver 需要本机 URL", 422, "http_url_required")
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise ConsoleError("只允许 http 或 https", 422, "bad_url")
    if parts.username or parts.password:
        raise ConsoleError("URL 不能携带凭据", 422, "url_credentials")
    if parts.hostname not in LOOPBACK:
        raise ConsoleError("HTTP driver 只能访问本机回环地址", 422, "non_loopback")
    return url.strip()
