from __future__ import annotations

import os

BASE_ALLOW = {
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    "SSL_CERT_FILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
}

DRIVER_EXTRA = {
    "codex_exec": ("CODEX_HOME",),
    "claude_print": ("CLAUDE_CONFIG_DIR",),
    "custom_cli": (),
    "http": (),
}


def filtered_env(driver: str, *, pythonpath: str | None = None) -> dict[str, str]:
    """Return a whitelist environment. Secrets and .env values are not copied."""
    allowed = set(BASE_ALLOW)
    allowed.update(DRIVER_EXTRA.get(driver, ()))
    env = {key: value for key, value in os.environ.items() if key in allowed}
    env.setdefault("LANG", "C.UTF-8")
    if pythonpath:
        env["PYTHONPATH"] = pythonpath
    return env
