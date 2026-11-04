from __future__ import annotations

import os
import sys
from pathlib import Path


def _sandbox_profile(executable: str) -> str:
    state_dir = Path(executable).resolve().parent.parent
    writable = [state_dir, Path("/private/tmp"), Path("/tmp")]
    temp = os.environ.get("TMPDIR")
    if temp:
        writable.append(Path(temp))
    paths = " ".join(f'(subpath "{path}")' for path in writable if path.exists())
    return f'(version 1)(allow default)(deny file-write*)(allow file-write* {paths})'


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: kimi_bridge EXECUTABLE readonly|worktree")
    executable, mode = sys.argv[1], sys.argv[2]
    if mode not in {"readonly", "worktree"}:
        raise SystemExit("invalid Kimi execution mode")
    prompt = sys.stdin.read()
    if not prompt.strip():
        raise SystemExit("empty Kimi prompt")
    command = [
        executable,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
    ]
    if mode == "worktree":
        command.append("--auto")
        os.execv(executable, command)
    sandbox = "/usr/bin/sandbox-exec"
    if not Path(sandbox).is_file():
        raise SystemExit("readonly Kimi execution requires /usr/bin/sandbox-exec")
    os.execv(sandbox, [sandbox, "-p", _sandbox_profile(executable), *command])


if __name__ == "__main__":
    main()
