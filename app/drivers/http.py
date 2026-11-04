from __future__ import annotations

import sys

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_generic, read_text


class HTTPDriver(Driver):
    name = "http"

    def build_argv(self, ctx: RunContext) -> list[str]:
        argv = [sys.executable, "-m", "app.http_exec", ctx.http_url]
        return assert_argv_safe(argv)

    def parse(self, artifact_dir):
        return parse_generic(read_text(artifact_dir / "stdout.log"))
