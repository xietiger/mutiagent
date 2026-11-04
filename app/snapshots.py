from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import Settings
from app.errors import ConsoleError
from app.paths import atomic_write_text, same_tree

SKIP_DIRS = {
    ".git",
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
}
SKIP_FILE_NAMES = {"credentials.json", "id_rsa", "id_ed25519", "id_ecdsa"}


def git_binary() -> str:
    for candidate in ("/usr/bin/git", "/opt/homebrew/bin/git"):
        if os.access(candidate, os.X_OK):
            return candidate
    raise ConsoleError("找不到绝对路径上的 git", 422, "git_missing")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [git_binary(), *args],
        cwd=repo,
        check=check,
        capture_output=True,
    )


def git_text(repo: Path, *args: str) -> str:
    completed = _git(repo, *args, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace")[:300]
        raise ConsoleError(f"git 命令失败：{detail}", 422, "git_failed")
    return completed.stdout.decode("utf-8", errors="replace")


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def repo_baseline(path: Path) -> dict:
    if not is_git_repo(path):
        raise ConsoleError("worktree 模式要求目标是 Git 仓库", 422, "not_a_git_repo")
    head = git_text(path, "rev-parse", "HEAD").strip()
    if not head:
        raise ConsoleError("仓库还没有可识别的基线提交", 422, "baseline_missing")
    branch = git_text(path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    porcelain = git_text(path, "status", "--porcelain")
    return {"head": head, "branch": branch, "dirty": bool(porcelain.strip()), "porcelain": porcelain}


def digest_tree(root: Path) -> str:
    hasher = hashlib.sha256()
    if not root.exists():
        return hasher.hexdigest()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            hasher.update(path.relative_to(root).as_posix().encode())
            hasher.update(b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            hasher.update(b"\0")
    return hasher.hexdigest()


def _skip_file(name: str) -> bool:
    return name in SKIP_FILE_NAMES or name == ".env" or name.startswith(".env.") or name.endswith((".pem", ".key"))


def copy_tree(src: Path, dst: Path, extra_skip: list[Path]) -> list[str]:
    notes: list[str] = []
    src_real = src.resolve()
    blocked = []
    for item in extra_skip:
        try:
            blocked.append(item.resolve())
        except FileNotFoundError:
            blocked.append(item)
    dst.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in list(dirnames):
            child = current / name
            if name in SKIP_DIRS:
                notes.append(f"skipped {child.relative_to(src).as_posix()}")
                continue
            try:
                child_real = child.resolve()
            except OSError:
                notes.append(f"skipped {name}")
                continue
            if any(child_real == item or same_tree(child_real, item) for item in blocked):
                notes.append(f"skipped {child.relative_to(src).as_posix()}")
                continue
            if child.is_symlink():
                notes.append(f"skipped symlink {child.relative_to(src).as_posix()}")
                continue
            kept.append(name)
        dirnames[:] = kept
        (dst / current.relative_to(src)).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            source = current / name
            relative = source.relative_to(src)
            if _skip_file(name):
                notes.append(f"skipped {relative.as_posix()}")
                continue
            target = dst / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                try:
                    linked = source.resolve(strict=True)
                except OSError:
                    notes.append(f"skipped broken symlink {relative.as_posix()}")
                    continue
                if not same_tree(linked, src_real):
                    notes.append(f"skipped escaping symlink {relative.as_posix()}")
                    continue
                shutil.copy2(linked, target, follow_symlinks=False)
                continue
            if source.is_file():
                shutil.copy2(source, target)
    return notes


def prepare_baseline(settings: Settings, context: Path, task_id: str, execution_mode: str) -> dict:
    destination = settings.artifacts_dir / task_id
    destination.mkdir(parents=True, exist_ok=True)
    if execution_mode == "worktree":
        baseline = repo_baseline(context)
        digest = hashlib.sha256(f"{baseline['head']}\n{baseline['porcelain']}".encode()).hexdigest()
        info = {
            "context_path": str(context),
            "snapshot_path": None,
            "base_commit": baseline["head"],
            "branch": baseline["branch"],
            "dirty": baseline["dirty"],
            "input_digest": digest,
            "notes": ["基线不包含未提交改动"] if baseline["dirty"] else [],
        }
    elif execution_mode == "readonly":
        snapshot = destination / "snapshot"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        notes = copy_tree(context, snapshot, [settings.artifacts_dir, settings.db_path.parent, snapshot])
        git_info = {"head": None, "branch": None, "dirty": False}
        if is_git_repo(context):
            try:
                git_info = repo_baseline(context)
            except ConsoleError:
                git_info = {"head": None, "branch": None, "dirty": False}
        info = {
            "context_path": str(context),
            "snapshot_path": str(snapshot),
            "base_commit": git_info.get("head"),
            "branch": git_info.get("branch"),
            "dirty": bool(git_info.get("dirty")),
            "input_digest": digest_tree(snapshot),
            "notes": notes[:80],
        }
    else:
        raise ConsoleError("首版不实现 existing_workspace", 422, "mode_not_supported")
    atomic_write_text(destination / "base.json", _dump(info))
    return info


def worktree_destination(settings: Settings, repo: Path, task_id: str, subtask_id: str) -> Path:
    preferred = settings.artifacts_dir / task_id / "subtasks" / subtask_id / "worktree"
    try:
        preferred.resolve().relative_to(repo.resolve())
        inside = True
    except ValueError:
        inside = False
    if inside:
        return Path(tempfile.gettempdir()) / "agent-console" / task_id / subtask_id / "worktree"
    return preferred


def create_worktree(repo: Path, dest: Path, commit: str) -> None:
    if dest.exists():
        raise ConsoleError("worktree 目录已存在，拒绝覆盖", 409, "worktree_exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    completed = _git(repo, "worktree", "add", "--detach", str(dest), commit, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise ConsoleError(f"创建 worktree 失败：{detail}", 422, "worktree_failed")


def collect_patch(worktree: Path, base_commit: str, diff_path: Path, untracked_path: Path) -> dict:
    tracked = _git(worktree, "diff", "--binary", base_commit, check=False)
    blob = tracked.stdout or b""
    if blob and not blob.endswith(b"\n"):
        blob += b"\n"
    listed = _git(worktree, "ls-files", "--others", "--exclude-standard", check=False)
    untracked = []
    for rel in listed.stdout.decode("utf-8", errors="replace").splitlines():
        if not rel.strip():
            continue
        untracked.append(rel)
        arg = rel if not rel.startswith("-") else f"./{rel}"
        extra = _git(worktree, "diff", "--no-index", "--binary", "/dev/null", arg, check=False)
        if extra.stdout:
            blob += extra.stdout
            if not extra.stdout.endswith(b"\n"):
                blob += b"\n"
    diff_path.write_bytes(blob)
    atomic_write_text(untracked_path, _dump({"files": untracked}))
    file_count = sum(1 for line in blob.splitlines() if line.startswith(b"diff --git "))
    return {
        "bytes": len(blob),
        "files": file_count,
        "untracked": len(untracked),
        "note": "不会自动合并或应用",
    }


def _dump(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)
