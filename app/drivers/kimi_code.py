from __future__ import annotations

import sys

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_kimi, read_text


class KimiCodeDriver(Driver):
    name = "kimi_code"

    def build_argv(self, ctx: RunContext) -> list[str]:
        argv = [
            sys.executable,
            "-m",
            "app.drivers.kimi_bridge",
            ctx.executable,
            "readonly" if ctx.execution_mode == "readonly" else "worktree",
        ]
        return assert_argv_safe(argv)

    def parse(self, artifact_dir):
        return parse_kimi(read_text(artifact_dir / "stdout.log"))
