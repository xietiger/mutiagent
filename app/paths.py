from __future__ import annotations

import os
from pathlib import Path

from app.config import Settings
from app.errors import ConsoleError

SENSITIVE_PARTS = {".ssh", ".aws", ".gnupg", ".kube", "Keychains"}
ARTIFACT_FILES = {
    "stdout.log",
    "stderr.log",
    "native-events.jsonl",
    "last-message.json",
    "normalized.json",
    "exit.json",
    "patch.diff",
    "prompt.txt",
    "command.json",
    "untracked.json",
    "patch-stats.json",
    "runner-meta.json",
}


def resolve_context(settings: Settings, raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise ConsoleError("需要填写上下文目录", 422, "context_required")
    path = Path(raw).expanduser()
    try:
        real = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ConsoleError("上下文目录不存在", 422, "context_missing") from exc
    if not real.is_dir():
        raise ConsoleError("上下文必须是目录", 422, "context_not_directory")
    if real in {Path("/").resolve(), Path.home().resolve()}:
        raise ConsoleError("请选择具体项目目录，不能把根目录或整个用户主目录当作上下文", 422, "context_too_broad")
    if any(part in SENSITIVE_PARTS for part in real.parts):
        raise ConsoleError("上下文路径包含敏感目录，已拒绝", 422, "context_sensitive")
    allowed = False
    for root in settings.allowed_roots:
        try:
            real.relative_to(root.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise ConsoleError("上下文目录不在允许的根目录内", 422, "context_outside_root")
    artifacts = settings.artifacts_dir.resolve()
    if real == artifacts or artifacts in real.parents:
        raise ConsoleError("不能把产物目录当作上下文", 422, "context_is_artifacts")
    data_dir = settings.db_path.parent.resolve()
    if real == data_dir or data_dir in real.parents:
        raise ConsoleError("不能把控制台数据目录当作上下文", 422, "context_is_data")
    return real


def subtask_dir(settings: Settings, task_id: str, subtask_id: str) -> Path:
    _reject_id(task_id)
    _reject_id(subtask_id)
    return settings.artifacts_dir / task_id / "subtasks" / subtask_id


def task_dir(settings: Settings, task_id: str) -> Path:
    _reject_id(task_id)
    return settings.artifacts_dir / task_id


def resolve_artifact(settings: Settings, task_id: str, subtask_id: str, filename: str) -> Path:
    if filename not in ARTIFACT_FILES or "/" in filename or "\\" in filename:
        raise ConsoleError("不允许下载该文件", 404, "artifact_rejected")
    root = subtask_dir(settings, task_id, subtask_id)
    if root.is_symlink():
        raise ConsoleError("拒绝符号链接产物", 400, "symlink_rejected")
    root_real = root.resolve()
    candidate = root_real / filename
    if candidate.is_symlink():
        raise ConsoleError("拒绝符号链接产物", 400, "symlink_rejected")
    if not candidate.exists() or not candidate.is_file():
        raise ConsoleError("文件不存在", 404, "artifact_missing")
    if candidate.resolve().parent != root_real:
        raise ConsoleError("路径越界", 400, "path_traversal")
    artifacts = settings.artifacts_dir.resolve()
    try:
        candidate.resolve().relative_to(artifacts)
    except ValueError as exc:
        raise ConsoleError("产物位于允许目录之外", 400, "artifact_outside") from exc
    return candidate


def _reject_id(value: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ConsoleError("非法标识", 400, "bad_id")


def same_tree(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
