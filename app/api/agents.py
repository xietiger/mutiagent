from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Request

from app.db import connect, one, rows
from app.drivers.base import FORBIDDEN_FRAGMENTS
from app.errors import ConsoleError
from app.probe import BUILTIN_IDS, apply_probe
from app.tasks_service import review_profile
from app.timeutil import utc_now
from app.urls import validate_loopback_url

router = APIRouter()

ALLOWED_DRIVERS = {
    "codex_exec",
    "claude_print",
    "codebuddy",
    "grok_build",
    "kimi_code",
    "custom_cli",
    "http",
}


def _settings(request: Request):
    return request.app.state.settings


def public_agent(row: dict) -> dict:
    config = json.loads(row["config_json"])
    payload = {
        "id": row["id"],
        "name": row["name"],
        "driver": row["driver"],
        "executable_path": row["executable_path"],
        "version": row["version"],
        "identity": row["executable_identity"],
        "health_status": row["health_status"],
        "health_detail": row["health_detail"],
        "health_checked_at": row["health_checked_at"],
        "enabled": bool(row["enabled"]),
        "max_concurrency": row["max_concurrency"],
        "supported_modes": config.get("supported_modes") or [],
        "project_rules": config.get("project_rules"),
        "mcp": config.get("mcp"),
        "ide_mode": bool(config.get("ide_mode")),
        "profile": config.get("profile"),
        "install_hint": config.get("install_hint") or "",
        "review_profile": review_profile(config),
        "timeout_seconds": config.get("timeout_seconds"),
        "auth_mode": config.get("auth_mode") or "existing_login",
        "builtin": row["id"] in BUILTIN_IDS,
    }
    if row["driver"] == "custom_cli":
        payload["args"] = config.get("extra_args") or []
    if row["driver"] == "http":
        payload["http_url"] = config.get("http_url") or ""
    return payload


def _modes(values: list[str]) -> list[str]:
    if not values or any(item not in {"readonly", "worktree"} for item in values):
        raise ConsoleError("supported_modes 只能是 readonly 或 worktree", 422, "bad_mode")
    return list(dict.fromkeys(values))


def _rules(value: str, field: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise ConsoleError(f"{field} 不在允许范围内", 422, "bad_profile")
    return value


def _bounds(timeout: int, concurrency: int) -> tuple[int, int]:
    if not 10 <= int(timeout) <= 3600:
        raise ConsoleError("超时需要在 10 到 3600 秒之间", 422, "bad_timeout")
    if not 1 <= int(concurrency) <= 4:
        raise ConsoleError("单个 Agent 并发需要在 1 到 4 之间", 422, "bad_concurrency")
    return int(timeout), int(concurrency)


def _slug(name: str, conn) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"
    candidate = base
    number = 2
    while one(conn, "SELECT id FROM agents WHERE id = ?", (candidate,)):
        candidate = f"{base}-{number}"
        number += 1
    return candidate


@router.get("/agents")
def list_agents(request: Request):
    with connect(_settings(request).db_path) as conn:
        found = rows(conn, "SELECT * FROM agents ORDER BY name")
    return [public_agent(row) for row in found]


@router.post("/agents", status_code=201)
def create_agent(request: Request, body: dict):
    name = str(body.get("name") or "").strip()
    driver = str(body.get("driver") or "")
    if not name:
        raise ConsoleError("需要名称", 422, "name_required")
    if driver not in ALLOWED_DRIVERS:
        raise ConsoleError("不支持的 driver", 422, "bad_driver")
    timeout, concurrency = _bounds(int(body.get("timeout_seconds") or 900), int(body.get("max_concurrency") or 1))
    modes = _modes(list(body.get("supported_modes") or ["readonly", "worktree"]))
    project_rules = _rules(str(body.get("project_rules") or "off"), "project_rules", {"off", "on", "explicit"})
    mcp = _rules(str(body.get("mcp") or "off"), "mcp", {"off", "configured", "all"})
    extra_args = [str(item) for item in body.get("args") or []]
    for arg in extra_args:
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in arg:
                raise ConsoleError("参数包含被禁止的提权选项", 422, "unsafe_argv")
    http_url = ""
    if driver == "http":
        http_url = validate_loopback_url(str(body.get("http_url") or ""))
        executable = sys.executable
    else:
        executable = str(body.get("executable") or "")
        if not Path(executable).is_absolute():
            raise ConsoleError("可执行文件必须是绝对路径", 422, "relative_executable")
    config = {
        "timeout_seconds": timeout,
        "supported_modes": modes,
        "auth_mode": "existing_login",
        "project_rules": project_rules,
        "mcp": mcp,
        "ide_mode": False,
        "profile": "custom",
        "install_hint": "",
        "expected_identity": driver,
        "identity_regex": "codex-cli" if driver == "codex_exec" else "Claude Code" if "claude" in driver else r"\bgrok\b" if driver == "grok_build" else r"(CodeBuddy|\d+\.\d+\.\d+)" if driver == "codebuddy" else r"\d+\.\d+\.\d+" if driver == "kimi_code" else ".*",
        "help_args": ["exec", "--help"] if driver == "codex_exec" else ["--help"],
        "help_tokens": ["--json", "--sandbox", "--output-schema"] if driver == "codex_exec" else [],
        "auth_args": [],
        "auth_kind": "",
        "http_url": http_url,
        "extra_args": extra_args,
    }
    if driver == "claude_print":
        config["help_tokens"] = ["--restricted", "--json-schema", "--output-format"]
        config["auth_args"] = ["auth", "status"]
        config["auth_kind"] = "claude"
    elif driver == "codex_exec":
        config["auth_args"] = ["login", "status"]
        config["auth_kind"] = "codex"
    elif driver == "grok_build":
        config["help_tokens"] = ["--prompt-file", "--output-format", "--json-schema", "--sandbox"]
        config["auth_args"] = ["models"]
        config["auth_kind"] = "grok"
        config["expected_identity"] = "Grok Build"
    elif driver == "codebuddy":
        config["help_tokens"] = ["--output-format", "--json-schema", "--permission-mode", "--tools"]
        config["expected_identity"] = "CodeBuddy Code"
    elif driver == "kimi_code":
        config["help_tokens"] = ["--prompt", "--output-format", "--plan", "provider"]
        config["auth_args"] = ["provider", "list"]
        config["auth_kind"] = "kimi"
        config["expected_identity"] = "Kimi Code CLI"
    now = utc_now()
    settings = _settings(request)
    with connect(settings.db_path) as conn:
        agent_id = _slug(name, conn)
        conn.execute(
            """
            INSERT INTO agents (
              id, name, driver, config_json, executable_path, health_status, capabilities,
              max_concurrency, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'unchecked', ?, ?, 1, ?, ?)
            """,
            (
                agent_id,
                name,
                driver,
                json.dumps(config, ensure_ascii=False),
                executable,
                json.dumps(modes),
                concurrency,
                now,
                now,
            ),
        )
    updated = apply_probe(settings, agent_id)
    return public_agent(updated)


@router.patch("/agents/{agent_id}")
def patch_agent(agent_id: str, request: Request, body: dict):
    settings = _settings(request)
    with connect(settings.db_path) as conn:
        row = one(conn, "SELECT * FROM agents WHERE id = ?", (agent_id,))
        if row is None:
            raise ConsoleError("Agent 不存在", 404, "agent_missing")
        config = json.loads(row["config_json"])
        name = row["name"]
        enabled = row["enabled"]
        concurrency = row["max_concurrency"]
        if "name" in body and body["name"]:
            name = str(body["name"]).strip()
        if "enabled" in body:
            enabled = 1 if body["enabled"] else 0
        if "timeout_seconds" in body and body["timeout_seconds"] is not None:
            config["timeout_seconds"], _ = _bounds(int(body["timeout_seconds"]), concurrency)
        if "max_concurrency" in body and body["max_concurrency"] is not None:
            _, concurrency = _bounds(int(config.get("timeout_seconds") or 900), int(body["max_concurrency"]))
        if "project_rules" in body and body["project_rules"] is not None:
            config["project_rules"] = _rules(str(body["project_rules"]), "project_rules", {"off", "on", "explicit"})
        if "mcp" in body and body["mcp"] is not None:
            config["mcp"] = _rules(str(body["mcp"]), "mcp", {"off", "configured", "all"})
        conn.execute(
            """
            UPDATE agents
            SET name = ?, enabled = ?, max_concurrency = ?, config_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, enabled, concurrency, json.dumps(config, ensure_ascii=False), utc_now(), agent_id),
        )
    updated = apply_probe(settings, agent_id)
    return public_agent(updated)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, request: Request):
    if agent_id in BUILTIN_IDS:
        raise ConsoleError("内置 Agent 不能删除，可以停用", 403, "builtin_agent")
    settings = _settings(request)
    with connect(settings.db_path) as conn:
        used = one(conn, "SELECT id FROM subtasks WHERE agent_id = ? LIMIT 1", (agent_id,))
        if used:
            raise ConsoleError("已有任务引用该 Agent", 409, "agent_in_use")
        deleted = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        if deleted.rowcount == 0:
            raise ConsoleError("Agent 不存在", 404, "agent_missing")
    return {"deleted": agent_id}


@router.post("/agents/{agent_id}/probe")
def probe_agent(agent_id: str, request: Request):
    updated = apply_probe(_settings(request), agent_id)
    return public_agent(updated)
