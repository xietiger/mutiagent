from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


def reap_if_child(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        return


def process_info(pid: int) -> dict | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        started = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        command = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if started.returncode != 0 or not command.stdout.strip():
        return None
    return {"lstart": started.stdout.strip(), "command": command.stdout.strip()}


def process_matches(pid: int | None, lstart: str | None, spec_path: str | None) -> bool:
    if pid is None:
        return False
    info = process_info(pid)
    if info is None:
        return False
    command = info["command"]
    if "app.runner" not in command and "app/runner.py" not in command:
        return False
    if spec_path and spec_path not in command:
        return False
    if lstart and info["lstart"] != lstart:
        return False
    return bool(lstart or spec_path)


def signal_group(pid: int | None, pgid: int | None, sig: int) -> None:
    target = pgid or pid
    if not target:
        return
    try:
        os.killpg(target, sig)
    except (ProcessLookupError, PermissionError, OSError):
        if pid:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                return


def stop_sequence(stage: str | None) -> int | None:
    if stage is None:
        return signal.SIGINT
    if stage == "sigint":
        return signal.SIGTERM
    if stage == "sigterm":
        return signal.SIGKILL
    return None


def stage_name(sig: int) -> str:
    return {
        signal.SIGINT: "sigint",
        signal.SIGTERM: "sigterm",
        signal.SIGKILL: "sigkill",
    }.get(sig, "signal")


def read_json(path: Path) -> dict | None:
    if not path.exists() or path.is_symlink():
        return None
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
