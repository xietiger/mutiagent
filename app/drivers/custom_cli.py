from __future__ import annotations

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_generic, read_text


class CustomCLIDriver(Driver):
    name = "custom_cli"

    def build_argv(self, ctx: RunContext) -> list[str]:
        return assert_argv_safe([ctx.executable, *ctx.extra_args])

    def parse(self, artifact_dir):
        return parse_generic(read_text(artifact_dir / "stdout.log"))
