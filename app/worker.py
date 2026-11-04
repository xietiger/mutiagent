from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.db import connect, one
from app.drivers.base import RunContext, UnsafeArgv
from app.drivers.registry import get_driver
from app.environment import filtered_env
from app.errors import ConsoleError
from app.output.parse import read_text, write_native_events
from app.output.validate import fallback_result
from app.paths import atomic_write_text, task_dir
from app.process_util import process_info, process_matches, read_json, reap_if_child, signal_group, stage_name, stop_sequence
from app.prompt import build_prompt
from app.redact import redact
from app.snapshots import (
    collect_patch,
    create_worktree,
    digest_tree,
    is_git_repo,
    repo_baseline,
)
from app.timeutil import utc_now

SCHEMA_PATH = Path(__file__).resolve().parent / "output" / "schema.json"
TERMINAL = {"succeeded", "degraded", "failed", "timeout", "cancelled", "unavailable"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _config(agent: dict) -> dict:
    try:
        return json.loads(agent["config_json"])
    except json.JSONDecodeError:
        return {}


def make_context(agent: dict, workspace: Path, artifact: Path, mode: str) -> RunContext:
    config = _config(agent)
    return RunContext(
        executable=agent["executable_path"],
        workspace=str(workspace),
        schema_path=artifact / "schema.json",
        artifact_dir=artifact,
        execution_mode=mode,
        project_rules=config.get("project_rules") or "off",
        mcp=config.get("mcp") or "off",
        ide_mode=bool(config.get("ide_mode")),
        extra_args=tuple(config.get("extra_args") or []),
        http_url=config.get("http_url") or "",
    )


def decide_status(*, exit_code, strict: bool, timed_out: bool, cancelled: bool, exit_known: bool, native_nonempty: bool) -> tuple[str, str | None]:
    if cancelled:
        return "cancelled", "cancelled"
    if timed_out:
        return "timeout", "timeout"
    if not exit_known:
        if native_nonempty:
            return "degraded", "missing_exit"
        return "failed", "orphaned_runner"
    if exit_code != 0:
        return "failed", "nonzero_exit"
    if strict:
        return "succeeded", None
    return "degraded", "invalid_output"


def _event(conn, task_id: str, subtask_id: str | None, event_type: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO events (task_id, subtask_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, subtask_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
    )


def _timeout_seconds(agent: dict) -> int:
    raw = _config(agent).get("timeout_seconds") or 900
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 900
    return max(10, min(value, 3600))


def _busy_agents(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT a.id
        FROM agents a
        LEFT JOIN subtasks s ON s.agent_id = a.id AND s.status = 'running'
        GROUP BY a.id
        HAVING a.enabled = 0 OR COUNT(s.id) >= a.max_concurrency
        """
    ).fetchall()
    return [row["id"] for row in rows]


def claim_and_start(settings: Settings) -> bool:
    with connect(settings.db_path) as conn:
        running = conn.execute("SELECT COUNT(*) AS n FROM subtasks WHERE status = 'running'").fetchone()["n"]
        if running >= settings.global_max_concurrency:
            return False
        busy = _busy_agents(conn)
        now = utc_now()
        if busy:
            marks = ",".join("?" for _ in busy)
            sql = f"""
                UPDATE subtasks
                SET status = 'running', started_at = ?, heartbeat_at = ?, phase = 'preparing'
                WHERE id = (
                  SELECT id FROM subtasks
                  WHERE status = 'queued' AND agent_id NOT IN ({marks})
                  ORDER BY created_at, rowid
                  LIMIT 1
                )
                AND status = 'queued'
                RETURNING *
            """
            params: list = [now, now, *busy]
        else:
            sql = """
                UPDATE subtasks
                SET status = 'running', started_at = ?, heartbeat_at = ?, phase = 'preparing'
                WHERE id = (
                  SELECT id FROM subtasks
                  WHERE status = 'queued'
                  ORDER BY created_at, rowid
                  LIMIT 1
                )
                AND status = 'queued'
                RETURNING *
            """
            params = [now, now]
        claimed = conn.execute(sql, params).fetchone()
    if claimed is None:
        return False
    row = dict(claimed)
    try:
        _start(settings, row)
    except Exception as exc:
        code = getattr(exc, "code", "start_failed")
        status = "unavailable" if code in {"unsafe_argv", "wrong_binary", "not_installed"} else "failed"
        _abort(settings, row, status, code, str(exc))
    return True


def _abort(settings: Settings, row: dict, status: str, code: str, message: str) -> None:
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            UPDATE subtasks
            SET status = ?, error_code = ?, error = ?, finished_at = ?, phase = 'done'
            WHERE id = ? AND status = 'running'
            """,
            (status, code, redact(message, 500), now, row["id"]),
        )
        _event(conn, row["task_id"], row["id"], "subtask_update", {"subtask_id": row["id"], "status": status, "phase": "done", "error_code": code})
    from app.tasks_service import refresh_task

    refresh_task(settings, row["task_id"])


def _phase(settings: Settings, row: dict, phase: str) -> None:
    with connect(settings.db_path) as conn:
        conn.execute("UPDATE subtasks SET phase = ?, heartbeat_at = ? WHERE id = ?", (phase, utc_now(), row["id"]))
        _event(
            conn,
            row["task_id"],
            row["id"],
            "subtask_update",
            {"subtask_id": row["id"], "status": "running", "phase": phase},
        )


def _start(settings: Settings, row: dict) -> None:
    with connect(settings.db_path) as conn:
        agent = one(conn, "SELECT * FROM agents WHERE id = ?", (row["agent_id"],))
        task = one(conn, "SELECT * FROM tasks WHERE id = ?", (row["task_id"],))
    if agent is None or task is None:
        raise ConsoleError("任务或 Agent 缺失", 500, "missing_row")
    executable = Path(agent["executable_path"])
    if agent["driver"] != "http":
        if not executable.is_absolute():
            raise ConsoleError("程序身份不匹配", 422, "wrong_binary")
        if not executable.exists():
            raise ConsoleError("可执行文件不存在", 422, "not_installed")
    artifact = Path(row["payload_path"])
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "tmp").mkdir(exist_ok=True)
    workspace = Path(row["workspace_path"])
    mode = row["execution_mode"]
    if mode == "worktree":
        _phase(settings, row, "creating_worktree")
        create_worktree(Path(task["context_path"]), workspace, row["base_commit"])
    elif mode == "readonly":
        _phase(settings, row, "preparing_snapshot")
        if not workspace.is_dir():
            raise ConsoleError("只读快照不存在", 500, "snapshot_missing")
    else:
        raise ConsoleError("不支持的执行模式", 422, "mode_not_supported")
    shutil.copyfile(SCHEMA_PATH, artifact / "schema.json")
    atomic_write_text(
        artifact / "prompt.txt",
        build_prompt(user_prompt=task["prompt"], execution_mode=mode, workspace=str(workspace)),
    )
    try:
        argv = get_driver(agent["driver"]).build_argv(make_context(agent, workspace, artifact, mode))
    except UnsafeArgv as exc:
        raise ConsoleError(str(exc), 422, "unsafe_argv") from exc
    atomic_write_text(artifact / "command.json", json.dumps({"argv": argv, "cwd": str(workspace)}, ensure_ascii=False, indent=2))
    internal = len(argv) >= 3 and argv[1] == "-m" and str(argv[2]).startswith("app.")
    spec = {
        "argv": argv,
        "cwd": str(workspace),
        "stdin_path": str(artifact / "prompt.txt"),
        "stdout_path": str(artifact / "stdout.log"),
        "stderr_path": str(artifact / "stderr.log"),
        "exit_path": str(artifact / "exit.json"),
        "heartbeat_path": str(artifact / "heartbeat"),
        "env": filtered_env(agent["driver"], pythonpath=str(settings.project_root) if internal else None) | {"TMPDIR": str(artifact / "tmp")},
        "timeout_seconds": _timeout_seconds(agent),
        "grace_seconds": settings.stop_grace_seconds,
        "internal": internal,
        "allow_force": "--force" in argv,
        "driver": agent["driver"],
    }
    spec_path = artifact / "spec.json"
    atomic_write_text(spec_path, json.dumps(spec, ensure_ascii=False))
    log_handle = open(artifact / "runner.log", "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.runner", "--spec", str(spec_path)],
        cwd=str(settings.project_root),
        env=filtered_env(agent["driver"], pythonpath=str(settings.project_root)),
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    lstart = None
    for _ in range(20):
        info = process_info(proc.pid)
        if info:
            lstart = info["lstart"]
            break
        time.sleep(0.05)
    atomic_write_text(
        artifact / "runner-meta.json",
        json.dumps({"pid": proc.pid, "pgid": pgid, "lstart": lstart, "spec_path": str(spec_path)}, ensure_ascii=False),
    )
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            UPDATE subtasks
            SET runner_pid = ?, runner_pgid = ?, runner_started_at = ?, runner_exit_path = ?,
                phase = 'agent_running', heartbeat_at = ?, workspace_path = ?
            WHERE id = ?
            """,
            (proc.pid, pgid, now, str(artifact / "exit.json"), now, str(workspace), row["id"]),
        )
        _event(
            conn,
            row["task_id"],
            row["id"],
            "subtask_update",
            {"subtask_id": row["id"], "status": "running", "phase": "agent_running"},
        )


def _timed_out(row: dict, agent: dict | None) -> bool:
    started = _parse_time(row.get("started_at"))
    if started is None or agent is None:
        return False
    limit = _timeout_seconds(agent)
    return (datetime.now(timezone.utc) - started).total_seconds() > limit


def _escalate(settings: Settings, row: dict, artifact: Path, reason: str) -> None:
    state_path = artifact / "stop.json"
    state = read_json(state_path) or {}
    now = time.time()
    stage = state.get("stage")
    if stage and now - float(state.get("at") or 0) < settings.stop_grace_seconds:
        return
    sig = stop_sequence(stage)
    if sig is None:
        return
    signal_group(row.get("runner_pid"), row.get("runner_pgid"), sig)
    atomic_write_text(state_path, json.dumps({"stage": stage_name(sig), "at": now, "reason": reason}))


def watch_running(settings: Settings) -> None:
    with connect(settings.db_path) as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM subtasks WHERE status = 'running'").fetchall()]
        agents = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM agents").fetchall()}
    for row in rows:
        artifact = Path(row["payload_path"])
        meta = read_json(artifact / "runner-meta.json") or {}
        reap_if_child(row.get("runner_pid"))
        alive = process_matches(row.get("runner_pid"), meta.get("lstart"), meta.get("spec_path"))
        cancel = (artifact / "cancel.requested").exists()
        timed_out = _timed_out(row, agents.get(row["agent_id"]))
        if alive and (cancel or timed_out):
            _escalate(settings, row, artifact, "cancelled" if cancel else "timeout")
        if alive:
            previous = _parse_time(row.get("heartbeat_at"))
            if previous is None or (datetime.now(timezone.utc) - previous).total_seconds() >= 5:
                with connect(settings.db_path) as conn:
                    conn.execute("UPDATE subtasks SET heartbeat_at = ? WHERE id = ?", (utc_now(), row["id"]))
            continue
        finalize(settings, row["id"], cancelled=cancel, timed_out=timed_out and not cancel)


def finalize(settings: Settings, subtask_id: str, *, cancelled: bool = False, timed_out: bool = False) -> None:
    from app.tasks_service import refresh_task

    with connect(settings.db_path) as conn:
        row = one(conn, "SELECT * FROM subtasks WHERE id = ?", (subtask_id,))
        agent = one(conn, "SELECT * FROM agents WHERE id = ?", (row["agent_id"],)) if row else None
        task = one(conn, "SELECT * FROM tasks WHERE id = ?", (row["task_id"],)) if row else None
    if row is None or row["status"] != "running" or agent is None or task is None:
        return
    artifact = Path(row["payload_path"])
    if (artifact / "cancel.requested").exists():
        cancelled = True
    exit_data = read_json(artifact / "exit.json") or {}
    exit_known = (artifact / "exit.json").exists() and not (artifact / "exit.json").is_symlink()
    exit_code = exit_data.get("exit_code") if isinstance(exit_data.get("exit_code"), int) else None
    if exit_data.get("timed_out"):
        timed_out = True
    _phase(settings, row, "parsing")
    stdout = read_text(artifact / "stdout.log")
    stderr = read_text(artifact / "stderr.log")
    last_message = read_text(artifact / "last-message.json")
    write_native_events(stdout, artifact / "native-events.jsonl")
    try:
        parsed, session_id, strict = get_driver(agent["driver"]).parse(artifact)
    except Exception:
        parsed, session_id, strict = fallback_result(stdout or stderr), None, False
    atomic_write_text(artifact / "normalized.json", json.dumps(parsed, ensure_ascii=False, indent=2))
    native_nonempty = bool(stdout.strip() or stderr.strip() or last_message.strip())
    status, error_code = decide_status(
        exit_code=exit_code if isinstance(exit_code, int) else 1,
        strict=bool(strict) and exit_known,
        timed_out=timed_out,
        cancelled=cancelled,
        exit_known=exit_known,
        native_nonempty=native_nonempty,
    )
    drift = _drift_warning(settings, task, row)
    warning = drift
    patch_path = None
    if row["execution_mode"] == "worktree" and row.get("workspace_path") and Path(row["workspace_path"]).is_dir():
        try:
            stats = collect_patch(
                Path(row["workspace_path"]),
                row["base_commit"],
                artifact / "patch.diff",
                artifact / "untracked.json",
            )
            atomic_write_text(artifact / "patch-stats.json", json.dumps(stats, ensure_ascii=False, indent=2))
            patch_path = str(artifact / "patch.diff")
        except Exception as exc:
            warning = (warning + " " if warning else "") + f"补丁收集失败：{exc}"
    error = warning
    if status in {"failed", "timeout", "unavailable"}:
        tail = redact(stderr, 400).strip()
        if tail:
            error = f"{error}\n{tail}".strip() if error else tail
    now = utc_now()
    with connect(settings.db_path) as conn:
        updated = conn.execute(
            """
            UPDATE subtasks
            SET status = ?, exit_code = ?, native_result_path = ?, normalized_result_path = ?,
                patch_path = ?, agent_session_id = ?, finished_at = ?, error_code = ?, error = ?,
                phase = 'done', input_drift = ?, heartbeat_at = ?
            WHERE id = ? AND status = 'running'
            """,
            (
                status,
                exit_code,
                str(artifact / "stdout.log"),
                str(artifact / "normalized.json"),
                patch_path,
                session_id,
                now,
                error_code,
                redact(error, 800) if error else None,
                1 if drift else 0,
                now,
                subtask_id,
            ),
        )
        if updated.rowcount:
            _event(
                conn,
                row["task_id"],
                subtask_id,
                "subtask_update",
                {"subtask_id": subtask_id, "status": status, "phase": "done", "error_code": error_code},
            )
    if updated.rowcount:
        refresh_task(settings, row["task_id"])


def _drift_warning(settings: Settings, task: dict, row: dict) -> str:
    base_path = task_dir(settings, task["id"]) / "base.json"
    base = read_json(base_path) or {}
    if row["execution_mode"] == "readonly" and base.get("snapshot_path"):
        current = digest_tree(Path(base["snapshot_path"]))
        if task.get("input_digest") and current != task["input_digest"]:
            return "输入已变化，比较可信度降低"
        return ""
    context = Path(task["context_path"]) if task.get("context_path") else None
    if context and is_git_repo(context):
        try:
            current = repo_baseline(context)
        except ConsoleError:
            return ""
        if current["head"] != base.get("base_commit") or current["branch"] != base.get("branch"):
            return "该 Agent 运行期间原仓库 HEAD 或分支发生变化"
    return ""


def recover(settings: Settings) -> None:
    with connect(settings.db_path) as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM subtasks WHERE status = 'running'").fetchall()]
    for row in rows:
        artifact = Path(row["payload_path"])
        meta = read_json(artifact / "runner-meta.json") or {}
        reap_if_child(row.get("runner_pid"))
        if process_matches(row.get("runner_pid"), meta.get("lstart"), meta.get("spec_path")):
            with connect(settings.db_path) as conn:
                _event(conn, row["task_id"], row["id"], "subtask_update", {"subtask_id": row["id"], "status": "running", "phase": row.get("phase") or "agent_running"})
            continue
        finalize(settings, row["id"])
