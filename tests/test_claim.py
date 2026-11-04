from app.db import connect
from app.timeutil import utc_now
from app.worker import claim_and_start


def _insert(settings, agent_id, task_id, subtask_id, created):
    now = utc_now()
    config = '{"timeout_seconds":30,"supported_modes":["readonly"],"project_rules":"off","mcp":"off","extra_args":[]}'
    with connect(settings.db_path) as conn:
        if conn.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone() is None:
            conn.execute(
                """
                INSERT INTO agents (
                  id, name, driver, config_json, executable_path, health_status, capabilities,
                  max_concurrency, enabled, created_at, updated_at
                ) VALUES (?, ?, 'custom_cli', ?, '/bin/echo', 'ready', '[]', 1, 1, ?, ?)
                """,
                (agent_id, agent_id, config, now, now),
            )
        if conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
            conn.execute(
                """
                INSERT INTO tasks (
                  id, title, prompt, context_path, execution_mode, strategy, status, created_at, updated_at
                ) VALUES (?, 't', 'p', '/tmp', 'readonly', 'selected', 'pending', ?, ?)
                """,
                (task_id, now, now),
            )
        conn.execute(
            """
            INSERT INTO subtasks (
              id, task_id, agent_id, execution_mode, payload_path, status, created_at, phase
            ) VALUES (?, ?, ?, 'readonly', '/tmp', 'queued', ?, 'queued')
            """,
            (subtask_id, task_id, agent_id, created),
        )


def test_claim_is_atomic_and_respects_agent_capacity(settings, monkeypatch):
    started = []
    monkeypatch.setattr("app.worker._start", lambda _settings, row: started.append(row["agent_id"]))
    _insert(settings, "a", "task", "s1", "2026-01-01T00:00:00.000000Z")
    _insert(settings, "a", "task", "s2", "2026-01-01T00:00:01.000000Z")
    _insert(settings, "b", "task", "s3", "2026-01-01T00:00:02.000000Z")
    assert claim_and_start(settings) is True
    assert claim_and_start(settings) is True
    assert claim_and_start(settings) is False
    assert started == ["a", "b"]
    with connect(settings.db_path) as conn:
        queued = conn.execute("SELECT id FROM subtasks WHERE status = 'queued'").fetchall()
    assert [row["id"] for row in queued] == ["s2"]
