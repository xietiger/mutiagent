import json
from pathlib import Path

from app.db import connect, one
from app.presets import builtin_presets
from app.probe import apply_probe, probe_executable, seed_builtins
from app.timeutil import utc_now


def _script(path: Path, body: str) -> str:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def test_probe_classifies_identity(tmp_path):
    good = _script(
        tmp_path / "codex",
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "--version) echo 'codex-cli 1.2.3' ;;\n"
        "exec) echo '--json --sandbox --output-schema --output-last-message' ;;\n"
        "login) echo 'logged in' ;;\n"
        "esac\n",
    )
    config = {
        "identity_regex": "codex-cli",
        "help_args": ["exec", "--help"],
        "help_tokens": ["--json", "--sandbox", "--output-schema"],
        "auth_args": ["login", "status"],
        "auth_kind": "codex",
        "expected_identity": "codex-cli",
    }
    assert probe_executable("codex_exec", good, config)["health_status"] == "ready"
    grok = _script(tmp_path / "agent", "#!/bin/sh\necho 'grok 1.0.0'\n")
    missing = probe_executable("custom_cli", str(tmp_path / "missing" / "agent"), {"identity_regex": ".*"})
    assert missing["health_status"] == "not_installed"


def test_seed_never_stores_grok_path(settings):
    seed_builtins(settings)
    with connect(settings.db_path) as conn:
        cursor = one(conn, "SELECT * FROM agents WHERE id = 'cursor'")
        grok = one(conn, "SELECT * FROM agents WHERE id = 'grok-build'")
        buddy = one(conn, "SELECT * FROM agents WHERE id = 'codebuddy'")
        kimi = one(conn, "SELECT * FROM agents WHERE id = 'kimi-code'")
    assert cursor is None
    assert grok is not None and grok["driver"] == "grok_build"
    assert buddy is not None and buddy["driver"] == "codebuddy"
    assert kimi is not None and kimi["driver"] == "kimi_code"
def test_vscode_agents_are_not_builtin():
    ids = {preset["id"] for preset in builtin_presets()}
    assert "claude-vscode" not in ids
    assert "claude-vscode-ide" not in ids


def test_redact_keeps_auth_text_out_of_detail():
    from app.redact import redact

    raw = "API key configured - sk-examplekeyvalue123456"
    cleaned = redact(raw)
    assert "examplekeyvalue" not in cleaned
    assert "sk-[redacted]" in cleaned
    now = utc_now()
    assert now.endswith("Z")
    assert json.dumps({"ok": True})
