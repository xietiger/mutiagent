from pathlib import Path

import pytest

from app.errors import ConsoleError
from app.paths import resolve_artifact, resolve_context


def test_context_rejects_escape_and_home(settings, tmp_path):
    with pytest.raises(ConsoleError):
        resolve_context(settings, str(tmp_path / "missing"))
    outside = tmp_path / "outside"
    outside.mkdir()
    link = settings.allowed_roots[0] / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ConsoleError):
        resolve_context(settings, str(link))
    home_settings = settings
    with pytest.raises(ConsoleError):
        resolve_context(home_settings, "/")


def test_snapshot_skips_escaping_symlink(settings, project):
    secret = settings.root / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    (project / "leak").symlink_to(secret)
    (project / ".env").write_text("TOKEN=abc", encoding="utf-8")
    from app.snapshots import prepare_baseline

    info = prepare_baseline(settings, project, "task", "readonly")
    snapshot = Path(info["snapshot_path"])
    assert (snapshot / "src" / "app.py").is_file()
    assert not (snapshot / "leak").exists()
    assert not (snapshot / ".env").exists()
    assert "top-secret" not in "\n".join(path.read_text(encoding="utf-8") for path in snapshot.rglob("*") if path.is_file())


def test_artifact_download_rejects_traversal_and_symlink(settings):
    root = settings.artifacts_dir / "task" / "subtasks" / "sub"
    root.mkdir(parents=True)
    (root / "stdout.log").write_text("hello", encoding="utf-8")
    outside = settings.root / "secret.log"
    outside.write_text("secret", encoding="utf-8")
    (root / "stderr.log").symlink_to(outside)
    assert resolve_artifact(settings, "task", "sub", "stdout.log").read_text(encoding="utf-8") == "hello"
    with pytest.raises(ConsoleError):
        resolve_artifact(settings, "task", "sub", "../stdout.log")
    with pytest.raises(ConsoleError):
        resolve_artifact(settings, "task", "sub", "stderr.log")
