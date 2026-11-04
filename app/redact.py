from __future__ import annotations

import re

_SECRET = re.compile(
    r"(sk-[A-Za-z0-9*_\-]{6,})|((?i:api[_ ]?key|token|secret|password)\s*[:=]\s*\S+)|"
    r"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
)


def redact(text: str | None, limit: int | None = None) -> str:
    if not text:
        return ""
    cleaned = _SECRET.sub(
        lambda match: "sk-[redacted]" if match.group(1) else ("[redacted]" if match.group(2) else "[email]"),
        text,
    )
    if limit is not None and len(cleaned) > limit:
        return cleaned[:limit] + "\n…[truncated]"
    return cleaned
