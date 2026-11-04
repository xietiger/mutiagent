from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    root: Path
    db_path: Path
    artifacts_dir: Path
    allowed_roots: tuple[Path, ...]
    global_max_concurrency: int
    stop_grace_seconds: float
    scheduler_interval: float
    summary_url: str | None
    project_root: Path


def _roots_from_env(raw: str) -> tuple[Path, ...]:
    if not raw.strip():
        return (Path.home().resolve(),)
    roots: list[Path] = []
    for part in raw.split(os.pathsep):
        if not part.strip():
            continue
        path = Path(part).expanduser()
        if path.exists():
            roots.append(path.resolve())
    return tuple(roots) if roots else (Path.home().resolve(),)


def load_settings() -> Settings:
    """Load settings. The listen address is always loopback."""
    root = project_root()
    port = int(os.environ.get("CONSOLE_PORT", "8765"))
    db_path = Path(os.environ.get("CONSOLE_DB", str(root / "data" / "console.db"))).expanduser()
    artifacts = Path(os.environ.get("CONSOLE_ARTIFACTS", str(root / "artifacts"))).expanduser()
    concurrency = int(os.environ.get("CONSOLE_GLOBAL_MAX_CONCURRENCY", "4"))
    concurrency = max(1, min(concurrency, 8))
    summary = os.environ.get("CONSOLE_SUMMARY_URL", "").strip() or None
    return Settings(
        host="127.0.0.1",
        port=port,
        root=root,
        db_path=db_path,
        artifacts_dir=artifacts,
        allowed_roots=_roots_from_env(os.environ.get("CONSOLE_ALLOWED_ROOTS", "")),
        global_max_concurrency=concurrency,
        stop_grace_seconds=float(os.environ.get("CONSOLE_STOP_GRACE_SECONDS", "5")),
        scheduler_interval=float(os.environ.get("CONSOLE_SCHEDULER_INTERVAL", "0.5")),
        summary_url=summary,
        project_root=root,
    )
