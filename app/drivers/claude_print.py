from __future__ import annotations

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_claude, read_text


class ClaudePrintDriver(Driver):
    name = "claude_print"
    ide_capable = False

    def build_argv(self, ctx: RunContext) -> list[str]:
        readonly = ctx.execution_mode == "readonly"
        tools = "Read,Glob,Grep" if readonly else "Read,Glob,Grep,Edit,Write"
        argv = [ctx.executable]
        if ctx.project_rules == "off":
            argv.append("--restricted")
        argv += [
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            str(ctx.schema_path),
            "--tools",
            tools,
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
            "--no-session-persistence",
        ]
        if ctx.mcp == "off":
            argv.append("--strict-mcp-config")
        if self.ide_capable and ctx.ide_mode:
            argv.append("--ide")
        return assert_argv_safe(argv)

    def parse(self, artifact_dir):
        return parse_claude(read_text(artifact_dir / "stdout.log"))
