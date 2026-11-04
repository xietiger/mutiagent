import json
from pathlib import Path

from app.db import connect
from app.timeutil import utc_now
from app.worker import recover


def _seed(settings, subtask_id, status, payload: Path, pid=None):
    now = utc_now()
    payload.mkdir(parents=True, exist_ok=True)
    config = '{"timeout_seconds":30,"supported_modes":["readonly"],"project_rules":"off","mcp":"off","extra_args":[]}'
    with connect(settings.db_path) as conn:
        if conn.execute("SELECT id FROM agents WHERE id = 'echo'").fetchone() is None:
            conn.execute(
                """
                INSERT INTO agents (
                  id, name, driver, config_json, executable_path, health_status, capabilities,
                  max_concurrency, enabled, created_at, updated_at
                ) VALUES ('echo', 'Echo', 'custom_cli', ?, '/bin/echo', 'ready', '[]', 1, 1, ?, ?)
                """,
                (config, now, now),
            )
        if conn.execute("SELECT id FROM tasks WHERE id = 'task'").fetchone() is None:
            conn.execute(
                """
                INSERT INTO tasks (
                  id, title, prompt, context_path, execution_mode, strategy, input_digest, status, created_at, updated_at
                ) VALUES ('task', 't', 'p', ?, 'readonly', 'selected', 'abc', 'running', ?, ?)
                """,
                (str(settings.allowed_roots[0]), now, now),
            )
        conn.execute(
            """
            INSERT INTO subtasks (
              id, task_id, agent_id, execution_mode, workspace_path, payload_path, runner_pid,
              status, created_at, phase, input_digest
            ) VALUES (?, 'task', 'echo', 'readonly', ?, ?, ?, ?, ?, 'agent_running', 'abc')
            """,
            (subtask_id, str(settings.allowed_roots[0]), str(payload), pid, status, now),
        )


def _status(settings, subtask_id):
    with connect(settings.db_path) as conn:
        return conn.execute("SELECT status, error_code FROM subtasks WHERE id = ?", (subtask_id,)).fetchone()


def test_recover_keeps_live_runner_and_does_not_requeue(settings, monkeypatch):
    payload = settings.artifacts_dir / "task" / "subtasks" / "live"
    _seed(settings, "live", "running", payload, pid=123)
    _seed(settings, "waiting", "queued", settings.artifacts_dir / "task" / "subtasks" / "waiting")
    monkeypatch.setattr("app.worker.process_matches", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("app.worker.reap_if_child", lambda _pid: None)
    recover(settings)
    assert _status(settings, "live")["status"] == "running"
    assert _status(settings, "waiting")["status"] == "queued"


def test_recover_reads_exit_json_without_rerun(settings, monkeypatch):
    monkeypatch.setattr("app.worker.process_matches", lambda *_args, **_kwargs: False)
    payload = settings.artifacts_dir / "task" / "subtasks" / "done"
    _seed(settings, "done", "running", payload, pid=999999)
    contract = {
        "schema_version": 1,
        "summary": "ok",
        "category": "review",
        "findings": [],
        "notes": "",
        "follow_ups": [],
    }
    (payload / "stdout.log").write_text(json.dumps(contract), encoding="utf-8")
    (payload / "exit.json").write_text(json.dumps({"exit_code": 0, "returncode": 0, "timed_out": False}), encoding="utf-8")
    recover(settings)
    row = _status(settings, "done")
    assert row["status"] == "succeeded"
    assert row["status"] != "queued"


def test_recover_native_result_without_exit_is_degraded(settings, monkeypatch):
    monkeypatch.setattr("app.worker.process_matches", lambda *_args, **_kwargs: False)
    payload = settings.artifacts_dir / "task" / "subtasks" / "partial"
    _seed(settings, "partial", "running", payload, pid=999998)
    (payload / "stdout.log").write_text(
        json.dumps({"schema_version": 1, "summary": "partial", "category": "other", "findings": [], "notes": "", "follow_ups": []}),
        encoding="utf-8",
    )
    recover(settings)
    row = _status(settings, "partial")
    assert row["status"] == "degraded"
    assert row["error_code"] == "missing_exit"


def test_recover_orphan_without_result_fails(settings, monkeypatch):
    monkeypatch.setattr("app.worker.process_matches", lambda *_args, **_kwargs: False)
    payload = settings.artifacts_dir / "task" / "subtasks" / "orphan"
    _seed(settings, "orphan", "running", payload, pid=999997)
    recover(settings)
    row = _status(settings, "orphan")
    assert row["status"] == "failed"
    assert row["error_code"] == "orphaned_runner"
