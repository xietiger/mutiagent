from __future__ import annotations

from app.drivers.base import Driver
from app.drivers.claude_print import ClaudePrintDriver
from app.drivers.codebuddy import CodeBuddyDriver
from app.drivers.codex_exec import CodexExecDriver
from app.drivers.custom_cli import CustomCLIDriver
from app.drivers.grok_build import GrokBuildDriver
from app.drivers.http import HTTPDriver
from app.drivers.kimi_code import KimiCodeDriver

DRIVERS: dict[str, Driver] = {
    "codex_exec": CodexExecDriver(),
    "claude_print": ClaudePrintDriver(),
    "codebuddy": CodeBuddyDriver(),
    "custom_cli": CustomCLIDriver(),
    "grok_build": GrokBuildDriver(),
    "http": HTTPDriver(),
    "kimi_code": KimiCodeDriver(),
}


def get_driver(name: str) -> Driver:
    try:
        return DRIVERS[name]
    except KeyError as exc:
        raise KeyError(f"unknown driver {name}") from exc
