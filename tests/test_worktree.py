import subprocess
from pathlib import Path

import pytest

from app.errors import ConsoleError
from app.snapshots import collect_patch, create_worktree, prepare_baseline, repo_baseline


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["/usr/bin/git", "-C", str(repo), *args], check=True, capture_output=True)


def test_worktrees_are_isolated(settings, project):
    _git(project, "init")
    _git(project, "-c", "user.email=test@example.com", "-c", "user.name=Test", "add", ".")
    _git(project, "-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-m", "base")
    baseline = prepare_baseline(settings, project, "task", "worktree")
    original = repo_baseline(project)
    one = settings.artifacts_dir / "task" / "subtasks" / "a" / "worktree"
    two = settings.artifacts_dir / "task" / "subtasks" / "b" / "worktree"
    create_worktree(project, one, baseline["base_commit"])
    create_worktree(project, two, baseline["base_commit"])
    (one / "a.txt").write_text("from-a\n", encoding="utf-8")
    (two / "b.txt").write_text("from-b\n", encoding="utf-8")
    patch_a = settings.artifacts_dir / "a.diff"
    patch_b = settings.artifacts_dir / "b.diff"
    collect_patch(one, baseline["base_commit"], patch_a, settings.artifacts_dir / "a.json")
    collect_patch(two, baseline["base_commit"], patch_b, settings.artifacts_dir / "b.json")
    assert b"a.txt" in patch_a.read_bytes()
    assert b"b.txt" not in patch_a.read_bytes()
    assert b"b.txt" in patch_b.read_bytes()
    assert repo_baseline(project)["head"] == original["head"]
    assert not (project / "a.txt").exists()


def test_worktree_requires_git(settings, project):
    with pytest.raises(ConsoleError):
        prepare_baseline(settings, project, "task", "worktree")
