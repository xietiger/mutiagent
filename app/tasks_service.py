from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from app.compare import compare_cards
from app.config import Settings
from app.db import connect, one, rows
from app.drivers.base import UnsafeArgv
from app.drivers.registry import get_driver
from app.errors import ConsoleError
from app.paths import atomic_write_text, resolve_context, subtask_dir, task_dir
from app.process_util import read_json
from app.snapshots import prepare_baseline, worktree_destination
from app.summarizer import summarize
from app.timeutil import utc_now

TERMINAL = {"succeeded", "degraded", "failed", "timeout", "cancelled", "unavailable"}


def review_profile(config: dict) -> str:
    if config.get("ide_mode") or config.get("project_rules") not in {None, "off"} or config.get("mcp") not in {None, "off"}:
        return "项目感知评审"
    return "隔离评审"


def aggregate(statuses: list[str]) -> str:
    if not statuses or all(item == "queued" for item in statuses):
        return "pending"
    if any(item in {"queued", "running"} for item in statuses):
        return "running"
    if all(item == "cancelled" for item in statuses):
        return "cancelled"
    if all(item == "succeeded" for item in statuses):
        return "succeeded"
    if all(item in {"succeeded", "degraded"} for item in statuses):
        return "degraded"
    if any(item in {"succeeded", "degraded"} for item in statuses):
        return "mixed"
    if any(item in {"failed", "timeout", "unavailable"} for item in statuses):
        return "failed"
    return "mixed"


def _load_config(agent: dict) -> dict:
    try:
        return json.loads(agent["config_json"])
    except json.JSONDecodeError:
        return {}


def _request_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _select_agents(conn, body: dict, context_ready: bool) -> tuple[list[dict], list[dict]]:
    mode = body["execution_mode"]
    strategy = body["strategy"]
    if strategy == "fanout":
        found = rows(conn, "SELECT * FROM agents WHERE enabled = 1 ORDER BY name")
        chosen = []
        skipped = []
        for agent in found:
            config = _load_config(agent)
            reason = _agent_block_reason(agent, config, mode)
            if reason:
                skipped.append({"agent_id": agent["id"], "included": False, "reason": reason, "health": agent["health_status"]})
                continue
            chosen.append(agent)
        if not chosen:
            raise ConsoleError("没有可运行的 Agent", 422, "no_ready_agent")
        return chosen, skipped
    if strategy != "selected":
        raise ConsoleError("未知策略", 422, "bad_strategy")
    ids = []
    for agent_id in body.get("agent_ids") or []:
        if agent_id not in ids:
            ids.append(agent_id)
    if not ids:
        raise ConsoleError("至少选择一个 Agent", 422, "agent_required")
    chosen = []
    skipped = []
    for agent_id in ids:
        agent = one(conn, "SELECT * FROM agents WHERE id = ?", (agent_id,))
        if agent is None:
            raise ConsoleError(f"Agent 不存在：{agent_id}", 422, "agent_missing")
        config = _load_config(agent)
        reason = _agent_block_reason(agent, config, mode)
        if reason:
            raise ConsoleError(f"{agent['name']}：{reason}", 422, "agent_not_ready")
        chosen.append(agent)
    return chosen, skipped


def _agent_block_reason(agent: dict, config: dict, mode: str) -> str | None:
    if not agent["enabled"]:
        return "Agent 已停用"
    if agent["health_status"] != "ready":
        return agent.get("health_detail") or f"健康状态为 {agent['health_status']}"
    modes = config.get("supported_modes") or []
    if mode not in modes:
        return f"不支持 {mode}"
    return None


def create_task(settings: Settings, body: dict) -> tuple[dict, int]:
    mode = body.get("execution_mode") or "readonly"
    strategy = body.get("strategy") or "selected"
    if mode == "existing_workspace":
        raise ConsoleError("首版不实现直接修改当前工作区", 422, "mode_not_supported")
    if mode not in {"readonly", "worktree"}:
        raise ConsoleError("不支持的执行模式", 422, "bad_mode")
    title = str(body.get("title") or "").strip()
    prompt = str(body.get("prompt") or "")
    if not title or not prompt.strip():
        raise ConsoleError("标题和任务内容不能为空", 422, "empty_task")
    if len(prompt) > 100_000:
        raise ConsoleError("任务内容过长", 422, "prompt_too_long")
    context = resolve_context(settings, body.get("context_path") or "")
    key = (body.get("idempotency_key") or "").strip() or None
    digest_payload = {
        "title": title,
        "prompt": prompt,
        "agent_ids": body.get("agent_ids") or [],
        "context_path": str(context),
        "execution_mode": mode,
        "strategy": strategy,
    }
    request_hash = _request_hash(digest_payload)
    with connect(settings.db_path) as conn:
        if key:
            existing = one(conn, "SELECT * FROM tasks WHERE idempotency_key = ?", (key,))
            if existing:
                if existing.get("request_hash") != request_hash:
                    raise ConsoleError("幂等键已用于不同的任务内容", 409, "idempotency_conflict")
                return task_detail(settings, existing["id"]), 200
        chosen, skipped = _select_agents(conn, {**body, "execution_mode": mode, "strategy": strategy}, True)
    task_id = str(uuid.uuid4())
    directory = task_dir(settings, task_id)
    try:
        baseline = prepare_baseline(settings, context, task_id, mode)
        plans = []
        for agent in chosen:
            subtask_id = str(uuid.uuid4())
            artifact = subtask_dir(settings, task_id, subtask_id)
            artifact.mkdir(parents=True, exist_ok=True)
            if mode == "readonly":
                workspace = Path(baseline["snapshot_path"])
            else:
                workspace = worktree_destination(settings, context, task_id, subtask_id)
            from app.worker import make_context

            try:
                argv = get_driver(agent["driver"]).build_argv(make_context(agent, workspace, artifact, mode))
            except UnsafeArgv as exc:
                raise ConsoleError(str(exc), 422, "unsafe_argv") from exc
            atomic_write_text(artifact / "command.json", json.dumps({"argv": argv, "cwd": str(workspace)}, ensure_ascii=False, indent=2))
            plans.append((agent, subtask_id, artifact, workspace, argv))
    except Exception:
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
        raise
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO tasks (
                  id, title, prompt, context_path, execution_mode, strategy, base_commit,
                  input_digest, status, idempotency_key, request_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    task_id,
                    title,
                    prompt,
                    str(context),
                    mode,
                    strategy,
                    baseline.get("base_commit"),
                    baseline.get("input_digest"),
                    key,
                    request_hash,
                    now,
                    now,
                ),
            )
            for agent, subtask_id, artifact, workspace, _argv in plans:
                conn.execute(
                    """
                    INSERT INTO subtasks (
                      id, task_id, agent_id, attempt, execution_mode, workspace_path, base_commit,
                      payload_path, status, created_at, phase, input_digest
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'queued', ?, 'queued', ?)
                    """,
                    (
                        subtask_id,
                        task_id,
                        agent["id"],
                        mode,
                        str(workspace),
                        baseline.get("base_commit"),
                        str(artifact),
                        now,
                        baseline.get("input_digest"),
                    ),
                )
                conn.execute(
                    "INSERT INTO events (task_id, subtask_id, type, payload, created_at) VALUES (?, ?, 'subtask_update', ?, ?)",
                    (
                        task_id,
                        subtask_id,
                        json.dumps({"subtask_id": subtask_id, "status": "queued", "phase": "queued"}, ensure_ascii=False),
                        now,
                    ),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            shutil.rmtree(directory, ignore_errors=True)
            raise
    detail = task_detail(settings, task_id)
    detail["preflight"] = [
        {
            "agent_id": agent["id"],
            "name": agent["name"],
            "included": True,
            "health": agent["health_status"],
            "command": argv,
            "review_profile": review_profile(_load_config(agent)),
        }
        for agent, _subtask_id, _artifact, _workspace, argv in plans
    ] + skipped
    return detail, 201


def task_detail(settings: Settings, task_id: str) -> dict:
    with connect(settings.db_path) as conn:
        task = one(conn, "SELECT * FROM tasks WHERE id = ?", (task_id,))
        if task is None:
            raise ConsoleError("任务不存在", 404, "task_missing")
        subtasks = rows(
            conn,
            """
            SELECT s.*, a.name AS agent_name, a.version AS agent_version, a.driver, a.config_json
            FROM subtasks s JOIN agents a ON a.id = s.agent_id
            WHERE s.task_id = ?
            ORDER BY s.created_at, s.rowid
            """,
            (task_id,),
        )
    cards = []
    public_subtasks = []
    for subtask in subtasks:
        config = _load_config(subtask)
        normalized = read_json(Path(subtask["normalized_result_path"]) if subtask.get("normalized_result_path") else Path(subtask["payload_path"]) / "normalized.json")
        if normalized is None:
            normalized = {}
        command = read_json(Path(subtask["payload_path"]) / "command.json") or {}
        stats = read_json(Path(subtask["payload_path"]) / "patch-stats.json") or {}
        card = {
            "agent_id": subtask["agent_id"],
            "agent_name": subtask["agent_name"],
            "status": subtask["status"],
            "category": normalized.get("category"),
            "summary": normalized.get("summary"),
            "findings": normalized.get("findings") or [],
            "notes": normalized.get("notes") or "",
            "version": subtask.get("agent_version"),
            "execution_mode": subtask["execution_mode"],
            "review_profile": review_profile(config),
        }
        if subtask["status"] in TERMINAL or normalized:
            cards.append(card)
        public_subtasks.append(
            {
                "id": subtask["id"],
                "agent_id": subtask["agent_id"],
                "agent_name": subtask["agent_name"],
                "driver": subtask["driver"],
                "version": subtask.get("agent_version"),
                "attempt": subtask["attempt"],
                "status": subtask["status"],
                "phase": subtask.get("phase"),
                "execution_mode": subtask["execution_mode"],
                "review_profile": card["review_profile"],
                "started_at": subtask.get("started_at"),
                "finished_at": subtask.get("finished_at"),
                "heartbeat_at": subtask.get("heartbeat_at"),
                "exit_code": subtask.get("exit_code"),
                "error_code": subtask.get("error_code"),
                "error": subtask.get("error"),
                "input_drift": bool(subtask.get("input_drift")),
                "session_id": subtask.get("agent_session_id"),
                "command": command.get("argv") or [],
                "normalized": normalized or None,
                "patch": stats or None,
                "has_patch": bool(subtask.get("patch_path")),
            }
        )
    baseline = read_json(task_dir(settings, task_id) / "base.json") or {}
    return {
        "id": task["id"],
        "title": task["title"],
        "prompt": task["prompt"],
        "context_path": task["context_path"],
        "execution_mode": task["execution_mode"],
        "strategy": task["strategy"],
        "status": task["status"],
        "summary": task.get("summary"),
        "summary_source": task.get("summary_source"),
        "base_commit": task.get("base_commit"),
        "input_digest": task.get("input_digest"),
        "baseline_dirty": bool(baseline.get("dirty")),
        "baseline_branch": baseline.get("branch"),
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "subtasks": public_subtasks,
        "comparison": compare_cards(cards),
    }


def list_tasks(settings: Settings) -> list[dict]:
    with connect(settings.db_path) as conn:
        found = rows(conn, "SELECT id, title, status, execution_mode, strategy, created_at, updated_at FROM tasks ORDER BY created_at DESC LIMIT 50")
    return found


def refresh_task(settings: Settings, task_id: str) -> None:
    with connect(settings.db_path) as conn:
        subtasks = rows(conn, "SELECT status FROM subtasks WHERE task_id = ?", (task_id,))
    status = aggregate([item["status"] for item in subtasks])
    summary = None
    source = None
    if status not in {"pending", "running"}:
        try:
            detail = task_detail(settings, task_id)
            cards = []
            for subtask in detail["subtasks"]:
                normalized = subtask.get("normalized") or {}
                cards.append(
                    {
                        "agent_id": subtask["agent_id"],
                        "agent_name": subtask["agent_name"],
                        "summary": normalized.get("summary"),
                        "notes": normalized.get("notes"),
                        "findings": normalized.get("findings") or [],
                    }
                )
            summary, source = summarize(cards, summary_url=settings.summary_url)
        except Exception:
            summary, source = None, "rule"
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, summary = ?, summary_source = ?, updated_at = ? WHERE id = ?",
            (status, summary, source, now, task_id),
        )
        conn.execute(
            "INSERT INTO events (task_id, subtask_id, type, payload, created_at) VALUES (?, NULL, 'task_update', ?, ?)",
            (task_id, json.dumps({"task_id": task_id, "status": status, "summary_source": source}, ensure_ascii=False), now),
        )


def cancel_task(settings: Settings, task_id: str) -> dict:
    now = utc_now()
    with connect(settings.db_path) as conn:
        task = one(conn, "SELECT * FROM tasks WHERE id = ?", (task_id,))
        if task is None:
            raise ConsoleError("任务不存在", 404, "task_missing")
        conn.execute("BEGIN IMMEDIATE")
        try:
            found = rows(conn, "SELECT * FROM subtasks WHERE task_id = ?", (task_id,))
            for subtask in found:
                if subtask["status"] == "queued":
                    conn.execute(
                        """
                        UPDATE subtasks
                        SET status = 'cancelled', error_code = 'cancelled', finished_at = ?, phase = 'done'
                        WHERE id = ? AND status = 'queued'
                        """,
                        (now, subtask["id"]),
                    )
                elif subtask["status"] == "running":
                    path = Path(subtask["payload_path"])
                    path.mkdir(parents=True, exist_ok=True)
                    (path / "cancel.requested").write_text(now, encoding="utf-8")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    refresh_task(settings, task_id)
    return task_detail(settings, task_id)


def retry_subtask(settings: Settings, subtask_id: str) -> dict:
    with connect(settings.db_path) as conn:
        current = one(
            conn,
            """
            SELECT s.*, a.config_json, a.health_status, a.enabled, a.name
            FROM subtasks s JOIN agents a ON a.id = s.agent_id
            WHERE s.id = ?
            """,
            (subtask_id,),
        )
        if current is None:
            raise ConsoleError("子任务不存在", 404, "subtask_missing")
        if current["status"] not in TERMINAL:
            raise ConsoleError("只能重试已经结束的子任务", 409, "still_running")
        config = _load_config(current)
        reason = _agent_block_reason(current, config, current["execution_mode"])
        if reason:
            raise ConsoleError(reason, 422, "agent_not_ready")
        task = one(conn, "SELECT * FROM tasks WHERE id = ?", (current["task_id"],))
        attempt = conn.execute("SELECT COALESCE(MAX(attempt), 0) AS n FROM subtasks WHERE task_id = ? AND agent_id = ?", (current["task_id"], current["agent_id"])).fetchone()["n"]
    new_id = str(uuid.uuid4())
    artifact = subtask_dir(settings, current["task_id"], new_id)
    artifact.mkdir(parents=True, exist_ok=True)
    context = Path(task["context_path"])
    if current["execution_mode"] == "worktree":
        workspace = worktree_destination(settings, context, current["task_id"], new_id)
    else:
        workspace = Path(current["workspace_path"])
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO subtasks (
              id, task_id, agent_id, attempt, retry_of, execution_mode, workspace_path, base_commit,
              payload_path, status, created_at, phase, input_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 'queued', ?)
            """,
            (
                new_id,
                current["task_id"],
                current["agent_id"],
                int(attempt) + 1,
                current["id"],
                current["execution_mode"],
                str(workspace),
                current.get("base_commit"),
                str(artifact),
                now,
                current.get("input_digest"),
            ),
        )
        conn.execute(
            "UPDATE tasks SET summary = NULL, summary_source = NULL, updated_at = ? WHERE id = ?",
            (now, current["task_id"]),
        )
    refresh_task(settings, current["task_id"])
    return task_detail(settings, current["task_id"])
