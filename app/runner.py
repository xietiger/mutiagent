from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.drivers.base import FORBIDDEN_FRAGMENTS
from app.environment import BASE_ALLOW, DRIVER_EXTRA
from app.paths import atomic_write_text
from app.timeutil import utc_now


def _write_exit(path: Path, *, returncode: int | None, timed_out: bool, argv0: str, signal_no: int | None) -> None:
    exit_code = None
    if isinstance(returncode, int):
        exit_code = returncode if returncode >= 0 else 128 + abs(returncode)
    atomic_write_text(
        path,
        json.dumps(
            {
                "exit_code": exit_code,
                "returncode": returncode,
                "signal": signal_no,
                "finished_at": utc_now(),
                "pid": os.getpid(),
                "timed_out": timed_out,
                "argv0": argv0,
            },
            ensure_ascii=False,
        ),
    )


def _env_for(spec: dict) -> dict[str, str]:
    allowed = set(BASE_ALLOW)
    allowed.update(DRIVER_EXTRA.get(spec.get("driver") or "", ()))
    if spec.get("internal"):
        allowed.add("PYTHONPATH")
    source = spec.get("env") or {}
    env = {key: value for key, value in source.items() if key in allowed and isinstance(value, str)}
    env.setdefault("LANG", "C.UTF-8")
    return env


def _reject(argv: list[str], allow_force: bool) -> str | None:
    if not argv or not isinstance(argv[0], str) or not os.path.isabs(argv[0]):
        return "argv0 必须是绝对路径"
    for arg in argv:
        if not isinstance(arg, str):
            return "参数必须是字符串"
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in arg:
                return fragment
        if arg == "--force" and not allow_force:
            return "--force"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    exit_path = Path(spec["exit_path"])
    argv = list(spec["argv"])
    reason = _reject(argv, bool(spec.get("allow_force")))
    if reason:
        _write_exit(exit_path, returncode=127, timed_out=False, argv0=argv[0] if argv else "", signal_no=None)
        print(reason, file=sys.stderr)
        return
    heartbeat = Path(spec["heartbeat_path"])
    state = {"signal": None}

    def _handle(signum, _frame):
        state["signal"] = signum

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    child = subprocess.Popen(
        argv,
        cwd=spec["cwd"],
        env=_env_for(spec),
        stdin=open(spec["stdin_path"], "rb"),
        stdout=open(spec["stdout_path"], "wb"),
        stderr=open(spec["stderr_path"], "wb"),
        start_new_session=False,
    )
    timeout = float(spec.get("timeout_seconds") or 900)
    grace = float(spec.get("grace_seconds") or 5)
    deadline = time.monotonic() + timeout
    timed_out = False
    escalated = False
    code = None
    while code is None:
        try:
            code = child.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            try:
                heartbeat.write_text(utc_now(), encoding="utf-8")
            except OSError:
                pass
            now = time.monotonic()
            if not timed_out and now >= deadline:
                timed_out = True
                try:
                    os.kill(child.pid, signal.SIGINT)
                except OSError:
                    pass
            if timed_out and now >= deadline + grace and not escalated:
                escalated = True
                try:
                    os.kill(child.pid, signal.SIGTERM)
                except OSError:
                    pass
            if timed_out and now >= deadline + grace * 2:
                _write_exit(exit_path, returncode=child.poll() if child.poll() is not None else -9, timed_out=True, argv0=argv[0], signal_no=signal.SIGKILL)
                try:
                    os.killpg(os.getpgrp(), signal.SIGKILL)
                except OSError:
                    pass
                return
    _write_exit(
        exit_path,
        returncode=code,
        timed_out=timed_out,
        argv0=argv[0],
        signal_no=state["signal"],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(type(exc).__name__ + "\n")
        sys.exit(1)
