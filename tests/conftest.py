import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.db import init_db


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("CONSOLE_SUMMARY_URL", raising=False)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    cfg = Settings(
        host="127.0.0.1",
        port=8765,
        root=tmp_path,
        db_path=data / "console.db",
        artifacts_dir=tmp_path / "artifacts",
        allowed_roots=(allowed.resolve(),),
        global_max_concurrency=4,
        stop_grace_seconds=0.2,
        scheduler_interval=0.05,
        summary_url=None,
        project_root=ROOT,
    )
    init_db(cfg)
    return cfg


@pytest.fixture
def project(settings):
    path = settings.allowed_roots[0] / "repo"
    path.mkdir()
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    return path


def write_script(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path
