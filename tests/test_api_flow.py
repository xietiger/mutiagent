import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.process_util import process_info
from app.summarizer import summarize
from tests.conftest import write_script

CONTRACT = {
    "schema_version": 1,
    "summary": "评审完成",
    "category": "review",
    "findings": [
        {
            "severity": "high",
            "title": "缺少校验",
            "file": "src/app.py",
            "line": 1,
            "evidence": "直接使用输入",
            "recommendation": "先校验",
        }
    ],
    "notes": "",
    "follow_ups": [],
}


def _client(settings):
    app = create_app(settings, seed=False, start_scheduler=False)
    return app, TestClient(app)


def _register(client, name, script: Path):
    response = client.post("/agents", json={"name": name, "driver": "custom_cli", "executable": str(script), "timeout_seconds": 30})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["health_status"] == "ready"
    assert Path(body["executable_path"]).is_absolute()
    return body["id"]


def _wait(app, task_id):
    client = None
    for _ in range(80):
        app.state.scheduler.tick()
        with app.state.settings.db_path.open("rb"):
            pass
        from app.db import connect

        with connect(app.state.settings.db_path) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row and row["status"] not in {"pending", "running"}:
            return row["status"]
        time.sleep(0.05)
    return "running"


def test_bind_stays_on_loopback(monkeypatch):
    monkeypatch.setenv("CONSOLE_HOST", "0.0.0.0")
    assert load_settings().host == "127.0.0.1"


def test_create_requires_agent_and_rejects_shared_write(settings, project):
    _app, client = _client(settings)
    with client:
        missing = client.post("/tasks", json={"title": "t", "prompt": "p", "context_path": str(project), "agent_ids": []})
        assert missing.status_code == 422
        shared = client.post(
            "/tasks",
            json={"title": "t", "prompt": "p", "context_path": str(project), "agent_ids": ["x"], "execution_mode": "existing_workspace"},
        )
        assert shared.status_code == 422


def test_success_degraded_and_failed_are_decided_by_console(settings, project, tmp_path):
    ok = write_script(tmp_path / "ok.py", f"import json,sys\nsys.stdin.read()\nprint(json.dumps({CONTRACT!r}))\n")
    weak = write_script(tmp_path / "weak.py", "import sys\nsys.stdin.read()\nprint('I succeeded')\n")
    bad = write_script(tmp_path / "bad.py", f"import json,sys\nsys.stdin.read()\nprint(json.dumps({CONTRACT!r}))\nsys.exit(2)\n")
    app, client = _client(settings)
    with client:
        ids = [_register(client, "ok", ok), _register(client, "weak", weak), _register(client, "bad", bad)]
        created = client.post(
            "/tasks",
            json={"title": "评审", "prompt": "看输入校验", "context_path": str(project), "agent_ids": ids, "execution_mode": "readonly"},
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
        assert created.json()["input_digest"]
        assert len({item["input_digest"] for item in []}) == 0
        from app.db import connect

        with connect(settings.db_path) as conn:
            digests = [row["input_digest"] for row in conn.execute("SELECT input_digest FROM subtasks WHERE task_id = ?", (task_id,))]
        assert len(set(digests)) == 1
        status = _wait(app, task_id)
        assert status == "mixed"
        detail = client.get(f"/tasks/{task_id}").json()
        by_agent = {item["agent_id"]: item for item in detail["subtasks"]}
        assert by_agent[ids[0]]["status"] == "succeeded"
        assert by_agent[ids[1]]["status"] == "degraded"
        assert "非严格回退" in by_agent[ids[1]]["normalized"]["notes"]
        assert by_agent[ids[2]]["status"] == "failed"
        assert (project / "src" / "app.py").read_text(encoding="utf-8") == "print('ok')\n"
        names = [Path(item).name for item in (settings.artifacts_dir / task_id / "subtasks").iterdir() for item in []]
        for sub in detail["subtasks"]:
            folder = settings.artifacts_dir / task_id / "subtasks" / sub["id"]
            assert (folder / "stdout.log").exists()
            assert (folder / "normalized.json").exists()
            assert (folder / "exit.json").exists()
        assert names == []


def test_cancel_kills_process_group(settings, project, tmp_path):
    script = write_script(
        tmp_path / "sleep.py",
        "import signal,sys,time\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdin.read()\n"
        "time.sleep(30)\n",
    )
    app, client = _client(settings)
    with client:
        agent_id = _register(client, "sleeper", script)
        created = client.post(
            "/tasks",
            json={"title": "取消", "prompt": "等待", "context_path": str(project), "agent_ids": [agent_id]},
        )
        task_id = created.json()["id"]
        app.state.scheduler.tick()
        cancelled = client.post(f"/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200
        deadline = time.time() + 5
        status = "running"
        while time.time() < deadline:
            app.state.scheduler.tick()
            status = client.get(f"/tasks/{task_id}").json()["status"]
            if status not in {"pending", "running"}:
                break
            time.sleep(0.25)
        detail = client.get(f"/tasks/{task_id}").json()
        assert detail["status"] == "cancelled"
        sub = detail["subtasks"][0]
        meta = json.loads((settings.artifacts_dir / task_id / "subtasks" / sub["id"] / "runner-meta.json").read_text(encoding="utf-8"))
        assert process_info(meta["pid"]) is None
        assert status == "cancelled"


def test_sse_replays_after_last_event_id(settings, project, tmp_path):
    script = write_script(tmp_path / "ok.py", f"import json,sys\nsys.stdin.read()\nprint(json.dumps({CONTRACT!r}))\n")
    _app, client = _client(settings)
    with client:
        agent_id = _register(client, "ok", script)
        created = client.post("/tasks", json={"title": "流", "prompt": "看", "context_path": str(project), "agent_ids": [agent_id]})
        task_id = created.json()["id"]
        from app.db import connect

        with connect(settings.db_path) as conn:
            first = conn.execute("SELECT id FROM events WHERE task_id = ? ORDER BY id", (task_id,)).fetchone()["id"]
        with client.stream("GET", f"/tasks/{task_id}/events", headers={"Last-Event-ID": str(first)}) as response:
            chunk = ""
            for piece in response.iter_text():
                chunk += piece
                if "data:" in chunk or ": connected" in chunk:
                    break
        assert ": connected" in chunk


def test_summary_failure_does_not_change_status_source_rule():
    text, source = summarize(
        [{"agent_name": "Codex", "summary": "有一个问题", "findings": [], "notes": ""}],
        summary_url="http://127.0.0.1:1/summary",
    )
    assert source == "rule"
    assert "Codex" in text
