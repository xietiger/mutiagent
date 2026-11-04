from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from app.config import Settings
from app.db import connect, one
from app.presets import builtin_presets
from app.redact import redact
from app.timeutil import utc_now

BUILTIN_IDS = {preset["id"] for preset in builtin_presets()}
OBSOLETE_BUILTIN_IDS = {"claude-vscode", "claude-vscode-ide", "cursor"}


def _run(argv: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "probe timeout"
    except OSError as exc:
        return 127, exc.strerror or "os error"
    return completed.returncode, f"{completed.stdout or ''}\n{completed.stderr or ''}"


def count_vscode_windows() -> int | None:
    try:
        completed = subprocess.run(
            ["/bin/ps", "-ax", "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    count = 0
    for line in completed.stdout.splitlines():
        command = line.strip()
        if command == "Code" or command.endswith("/Code"):
            count += 1
    return count


def _json_object(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _auth_ok(kind: str, text: str, code: int) -> bool:
    lowered = text.lower()
    if kind == "codex":
        return code == 0 and ("logged in" in lowered or "api key configured" in lowered)
    if kind == "claude":
        payload = _json_object(text)
        return bool(payload and payload.get("loggedIn") is True)
    if kind == "grok":
        return code == 0 and "not authenticated" not in lowered and "login required" not in lowered
    if kind == "kimi":
        return code == 0 and any(name in lowered for name in ("moonshot", "kimi", "deepseek"))
    return False


def _version_of(text: str) -> str:
    match = re.search(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?)", text)
    if match:
        return match.group(1)[:80]
    line = next((item.strip() for item in text.splitlines() if item.strip()), "")
    return line[:80]


def probe_executable(driver: str, executable: str, config: dict, previous_version: str | None = None) -> dict:
    path = Path(executable)
    if not path.is_absolute():
        return _result("wrong_binary", "注册路径不是绝对路径", None, None, executable)
    if not path.exists():
        hint = config.get("install_hint") or "可执行文件不存在"
        return _result("not_installed", hint, None, None, executable)
    if not os.access(path, os.X_OK):
        return _result("not_installed", "路径存在但不可执行", None, None, executable)
    code, text = _run([str(path), "--version"])
    identity_ok = re.search(config.get("identity_regex") or r"$^", text, re.I) is not None
    if code != 0 or not identity_ok:
        return _result("wrong_binary", "版本输出与期望的程序身份不一致", _version_of(text) or None, None, str(path))
    version = _version_of(text)
    identity = config.get("expected_identity") or driver

    help_args = [str(path), *config.get("help_args", ["--help"])]
    help_code, help_text = _run(help_args)
    missing = [token for token in config.get("help_tokens", []) if token not in help_text]
    if help_code not in {0, 1} or missing:
        detail = "帮助信息缺少必需参数：" + ", ".join(missing or ["--help"])
        if previous_version and previous_version != version:
            detail = f"版本从 {previous_version} 变为 {version}。" + detail
        return _result("version_unsupported", detail, version, identity, str(path))

    auth_args = config.get("auth_args") or []
    if auth_args:
        auth_code, auth_text = _run([str(path), *auth_args])
        if not _auth_ok(config.get("auth_kind", ""), auth_text, auth_code):
            return _result("needs_login", "未登录或认证已失效。请使用该绝对路径登录，不要依赖 PATH 中的同名命令。", version, identity, str(path))

    if config.get("ide_mode"):
        windows = count_vscode_windows()
        if windows is None:
            return _result("error", "无法枚举 VS Code 进程", version, identity, str(path))
        if windows != 1:
            return _result("unavailable", "ide_target_ambiguous：需要恰好一个 VS Code 窗口", version, identity, str(path))

    detail = "已认证" if auth_args else "CLI 可用；认证状态将在运行时验证"
    if previous_version and previous_version != version:
        detail = f"版本已从 {previous_version} 更新为 {version}，参数检查通过"
    return _result("ready", detail, version, identity, str(path.resolve()))


def _result(status: str, detail: str, version: str | None, identity: str | None, executable: str) -> dict:
    return {
        "health_status": status,
        "health_detail": redact(detail, limit=500),
        "version": version,
        "executable_identity": identity,
        "executable_path": executable,
    }


def preset_config(preset: dict) -> dict:
    return {
        "timeout_seconds": preset["timeout_seconds"],
        "supported_modes": preset["supported_modes"],
        "auth_mode": "existing_login",
        "project_rules": preset["project_rules"],
        "mcp": preset["mcp"],
        "ide_mode": preset["ide_mode"],
        "profile": preset["profile"],
        "install_hint": preset["install_hint"],
        "expected_identity": preset["expected_identity"],
        "identity_regex": preset["identity_regex"],
        "help_args": preset["help_args"],
        "help_tokens": preset["help_tokens"],
        "auth_args": preset["auth_args"],
        "auth_kind": preset["auth_kind"],
        "http_url": "",
        "extra_args": [],
    }


def seed_builtins(settings: Settings) -> None:
    now = utc_now()
    with connect(settings.db_path) as conn:
        for preset in builtin_presets():
            discovered = preset["discover"]()
            path = str(discovered) if discovered else preset["placeholder"]
            existing = one(conn, "SELECT * FROM agents WHERE id = ?", (preset["id"],))
            config = json.dumps(preset_config(preset), ensure_ascii=False)
            capabilities = json.dumps(preset["supported_modes"] + (["ide_context"] if preset["ide_mode"] else []), ensure_ascii=False)
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO agents (
                      id, name, driver, config_json, executable_path, health_status,
                      capabilities, max_concurrency, enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'unchecked', ?, 1, ?, ?, ?)
                    """,
                    (preset["id"], preset["name"], preset["driver"], config, path, capabilities, preset["enabled"], now, now),
                )
                continue
            current = Path(existing["executable_path"])
            if discovered and not current.exists():
                conn.execute(
                    "UPDATE agents SET executable_path = ?, updated_at = ? WHERE id = ?",
                    (str(discovered), now, preset["id"]),
                )
            if preset["id"] == "claude-cli" and existing["name"] == "Claude Code CLI":
                conn.execute("UPDATE agents SET name = ?, updated_at = ? WHERE id = ?", (preset["name"], now, preset["id"]))
        for agent_id in OBSOLETE_BUILTIN_IDS:
            used = one(conn, "SELECT id FROM subtasks WHERE agent_id = ? LIMIT 1", (agent_id,))
            if used:
                conn.execute("UPDATE agents SET enabled = 0, updated_at = ? WHERE id = ?", (now, agent_id))
            else:
                conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))


def probe_agent_row(row: dict) -> dict:
    config = json.loads(row["config_json"])
    if row["driver"] == "custom_cli":
        return _probe_custom(row["executable_path"])
    if row["driver"] == "http":
        from app.urls import validate_loopback_url

        try:
            validate_loopback_url(config.get("http_url", ""))
        except Exception as exc:
            return _result("error", str(exc), None, "http", row["executable_path"])
        return _result("ready", "地址已接受，探测不会主动发请求", None, "http", row["executable_path"])
    return probe_executable(row["driver"], row["executable_path"], config, row.get("version"))


def _probe_custom(executable: str) -> dict:
    path = Path(executable)
    if not path.is_absolute():
        return _result("wrong_binary", "自定义命令必须是绝对路径", None, None, executable)
    if not path.exists():
        return _result("not_installed", "自定义命令不存在", None, None, executable)
    if not os.access(path, os.X_OK) or path.is_dir():
        return _result("not_installed", "自定义命令不可执行", None, None, executable)
    return _result("ready", "自定义命令可用；探测不会执行它", None, path.name, str(path.resolve()))


def apply_probe(settings: Settings, agent_id: str) -> dict:
    with connect(settings.db_path) as conn:
        row = one(conn, "SELECT * FROM agents WHERE id = ?", (agent_id,))
    if row is None:
        from app.errors import ConsoleError

        raise ConsoleError("Agent 不存在", 404, "agent_missing")
    result = probe_agent_row(row)
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            UPDATE agents
            SET executable_path = ?, executable_identity = ?, version = ?, health_status = ?,
                health_detail = ?, health_checked_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                result["executable_path"],
                result["executable_identity"],
                result["version"],
                result["health_status"],
                result["health_detail"],
                now,
                now,
                agent_id,
            ),
        )
        updated = one(conn, "SELECT * FROM agents WHERE id = ?", (agent_id,))
    return updated or row


def probe_all(settings: Settings) -> None:
    with connect(settings.db_path) as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM agents").fetchall()]
    for agent_id in ids:
        apply_probe(settings, agent_id)


