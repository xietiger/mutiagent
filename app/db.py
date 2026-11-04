from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import Settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  driver TEXT NOT NULL CHECK (driver IN (
    'codex_exec', 'claude_print', 'claude_vscode_print',
    'grok_build', 'codebuddy', 'kimi_code', 'custom_cli', 'http'
  )),
  config_json TEXT NOT NULL,
  executable_path TEXT NOT NULL,
  executable_identity TEXT,
  version TEXT,
  health_status TEXT NOT NULL DEFAULT 'unchecked',
  health_detail TEXT,
  health_checked_at TEXT,
  capabilities TEXT NOT NULL DEFAULT '[]',
  max_concurrency INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  context_path TEXT,
  execution_mode TEXT NOT NULL DEFAULT 'readonly'
    CHECK (execution_mode IN ('readonly', 'worktree', 'existing_workspace')),
  strategy TEXT NOT NULL DEFAULT 'selected'
    CHECK (strategy IN ('selected', 'fanout')),
  base_commit TEXT,
  input_digest TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  summary TEXT,
  summary_source TEXT,
  idempotency_key TEXT UNIQUE,
  request_hash TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subtasks (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  agent_id TEXT NOT NULL REFERENCES agents(id),
  attempt INTEGER NOT NULL DEFAULT 1,
  retry_of TEXT REFERENCES subtasks(id),
  execution_mode TEXT NOT NULL,
  workspace_path TEXT,
  base_commit TEXT,
  payload_path TEXT NOT NULL,
  runner_pid INTEGER,
  runner_pgid INTEGER,
  runner_started_at TEXT,
  runner_exit_path TEXT,
  heartbeat_at TEXT,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
    'queued', 'running', 'succeeded', 'degraded',
    'failed', 'timeout', 'cancelled', 'unavailable'
  )),
  exit_code INTEGER,
  native_result_path TEXT,
  normalized_result_path TEXT,
  patch_path TEXT,
  agent_session_id TEXT,
  started_at TEXT,
  finished_at TEXT,
  error_code TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  phase TEXT NOT NULL DEFAULT 'queued',
  input_digest TEXT,
  input_drift INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  subtask_id TEXT,
  type TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subtasks_status ON subtasks(status, agent_id);
CREATE INDEX IF NOT EXISTS idx_subtasks_task ON subtasks(task_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id);
"""


def _migrate_agent_drivers(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'agents'").fetchone()
    if row is None or "cursor_agent" not in (row["sql"] or ""):
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA legacy_alter_table=ON")
    try:
        conn.executescript(
            """
            BEGIN IMMEDIATE;
            DELETE FROM agents
            WHERE id IN ('cursor', 'claude-vscode', 'claude-vscode-ide')
              AND NOT EXISTS (
                SELECT 1 FROM subtasks WHERE subtasks.agent_id = agents.id
              );
            ALTER TABLE agents RENAME TO agents_driver_migration;
            CREATE TABLE agents (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              driver TEXT NOT NULL CHECK (driver IN (
                'codex_exec', 'claude_print', 'claude_vscode_print',
                'grok_build', 'codebuddy', 'kimi_code', 'custom_cli', 'http'
              )),
              config_json TEXT NOT NULL,
              executable_path TEXT NOT NULL,
              executable_identity TEXT,
              version TEXT,
              health_status TEXT NOT NULL DEFAULT 'unchecked',
              health_detail TEXT,
              health_checked_at TEXT,
              capabilities TEXT NOT NULL DEFAULT '[]',
              max_concurrency INTEGER NOT NULL DEFAULT 1,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO agents (
              id, name, driver, config_json, executable_path, executable_identity,
              version, health_status, health_detail, health_checked_at, capabilities,
              max_concurrency, enabled, created_at, updated_at
            )
            SELECT
              id, name, driver, config_json, executable_path, executable_identity,
              version, health_status, health_detail, health_checked_at, capabilities,
              max_concurrency, enabled, created_at, updated_at
            FROM agents_driver_migration;
            DROP TABLE agents_driver_migration;
            COMMIT;
            """
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table=OFF")
        conn.execute("PRAGMA foreign_keys=ON")


def init_db(settings: Settings) -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    with connect(settings.db_path) as conn:
        _migrate_agent_drivers(conn)
        conn.executescript(SCHEMA)


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def one(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None
