from __future__ import annotations

import os
from pathlib import Path


CODEX_CANDIDATES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
)


def discover_codex() -> Path | None:
    for path in CODEX_CANDIDATES:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def discover_claude_cli(home: Path | None = None) -> Path | None:
    path = (home or Path.home()) / ".local" / "bin" / "claude"
    if path.is_file() and os.access(path, os.X_OK) and "anthropic.claude-code-" not in str(path):
        return path
    return None


def discover_grok_build(home: Path | None = None) -> Path | None:
    path = (home or Path.home()) / ".grok" / "bin" / "grok"
    if path.is_file() and os.access(path, os.X_OK):
        return path
    return None


def discover_codebuddy(home: Path | None = None) -> Path | None:
    home = home or Path.home()
    candidates = [
        home / ".npm-global" / "bin" / "codebuddy",
        home / ".local" / "bin" / "codebuddy",
        Path("/opt/homebrew/bin/codebuddy"),
        Path("/usr/local/bin/codebuddy"),
    ]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def discover_kimi_code(home: Path | None = None) -> Path | None:
    path = (home or Path.home()) / ".kimi-code" / "bin" / "kimi"
    if path.is_file() and os.access(path, os.X_OK):
        return path
    return None


def builtin_presets(home: Path | None = None) -> list[dict]:
    home = home or Path.home()
    return [
        {
            "id": "codex",
            "name": "Codex",
            "driver": "codex_exec",
            "discover": discover_codex,
            "placeholder": str(CODEX_CANDIDATES[0]),
            "identity_regex": r"codex-cli",
            "help_args": ["exec", "--help"],
            "help_tokens": ["--json", "--sandbox", "--output-schema", "--output-last-message"],
            "auth_args": ["login", "status"],
            "auth_kind": "codex",
            "project_rules": "on",
            "mcp": "off",
            "ide_mode": False,
            "enabled": 1,
            "profile": "project-aware",
            "install_hint": "使用 ChatGPT.app 内置 Codex CLI，并在该绝对路径上完成登录。",
            "supported_modes": ["readonly", "worktree"],
            "timeout_seconds": 900,
            "expected_identity": "codex-cli",
        },
        {
            "id": "claude-cli",
            "name": "Claude Code",
            "driver": "claude_print",
            "discover": discover_claude_cli,
            "placeholder": str(home / ".local" / "bin" / "claude"),
            "identity_regex": r"Claude Code",
            "help_args": ["--help"],
            "help_tokens": ["--restricted", "--json-schema", "--output-format", "--permission-mode", "--no-session-persistence"],
            "auth_args": ["auth", "status"],
            "auth_kind": "claude",
            "project_rules": "off",
            "mcp": "off",
            "ide_mode": False,
            "enabled": 1,
            "profile": "isolated",
            "install_hint": "确认 ~/.local/bin/claude 已安装并完成登录。",
            "supported_modes": ["readonly", "worktree"],
            "timeout_seconds": 900,
            "expected_identity": "Claude Code",
        },
        {
            "id": "grok-build",
            "name": "Grok Build",
            "driver": "grok_build",
            "discover": discover_grok_build,
            "placeholder": str(home / ".grok" / "bin" / "grok"),
            "identity_regex": r"\bgrok\b",
            "help_args": ["--help"],
            "help_tokens": ["--prompt-file", "--output-format", "--json-schema", "--sandbox", "--permission-mode"],
            "auth_args": ["models"],
            "auth_kind": "grok",
            "project_rules": "off",
            "mcp": "off",
            "ide_mode": False,
            "enabled": 1,
            "profile": "isolated",
            "install_hint": f"运行 {home / '.grok' / 'bin' / 'grok'} login 完成登录。",
            "supported_modes": ["readonly", "worktree"],
            "timeout_seconds": 900,
            "expected_identity": "Grok Build",
        },
        {
            "id": "codebuddy",
            "name": "CodeBuddy",
            "driver": "codebuddy",
            "discover": discover_codebuddy,
            "placeholder": str(home / ".npm-global" / "bin" / "codebuddy"),
            "identity_regex": r"(CodeBuddy|\d+\.\d+\.\d+)",
            "help_args": ["--help"],
            "help_tokens": ["--output-format", "--json-schema", "--permission-mode", "--tools"],
            "auth_args": [],
            "auth_kind": "",
            "project_rules": "off",
            "mcp": "off",
            "ide_mode": False,
            "enabled": 1,
            "profile": "isolated",
            "install_hint": f"运行 {home / '.npm-global' / 'bin' / 'codebuddy'} 完成登录。",
            "supported_modes": ["readonly", "worktree"],
            "timeout_seconds": 900,
            "expected_identity": "CodeBuddy Code",
        },
        {
            "id": "kimi-code",
            "name": "Kimi Code",
            "driver": "kimi_code",
            "discover": discover_kimi_code,
            "placeholder": str(home / ".kimi-code" / "bin" / "kimi"),
            "identity_regex": r"\d+\.\d+\.\d+",
            "help_args": ["--help"],
            "help_tokens": ["--prompt", "--output-format", "--plan", "provider"],
            "auth_args": ["provider", "list"],
            "auth_kind": "kimi",
            "project_rules": "off",
            "mcp": "off",
            "ide_mode": False,
            "enabled": 1,
            "profile": "isolated",
            "install_hint": f"在 {home / '.kimi-code' / 'config.toml'} 中配置 API Provider，或运行 {home / '.kimi-code' / 'bin' / 'kimi'} login。",
            "supported_modes": ["readonly", "worktree"],
            "timeout_seconds": 900,
            "expected_identity": "Kimi Code CLI",
        },
    ]
