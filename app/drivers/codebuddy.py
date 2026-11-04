from __future__ import annotations

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_claude, read_text


class CodeBuddyDriver(Driver):
    name = "codebuddy"

    def build_argv(self, ctx: RunContext) -> list[str]:
        readonly = ctx.execution_mode == "readonly"
        tools = "Read,Glob,Grep" if readonly else "Read,Glob,Grep,Edit,Write"
        argv = [
            ctx.executable,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            str(ctx.schema_path),
            "--tools",
            tools,
            "--permission-mode",
            "dontAsk",
        ]
        if ctx.mcp == "off":
            argv.append("--strict-mcp-config")
        return assert_argv_safe(argv)

    def parse(self, artifact_dir):
        return parse_claude(read_text(artifact_dir / "stdout.log"))
