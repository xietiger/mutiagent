from __future__ import annotations

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_grok, read_text


class GrokBuildDriver(Driver):
    name = "grok_build"

    def build_argv(self, ctx: RunContext) -> list[str]:
        readonly = ctx.execution_mode == "readonly"
        tools = "read_file,grep,list_dir" if readonly else "read_file,grep,list_dir,search_replace"
        argv = [
            ctx.executable,
            "--prompt-file",
            str(ctx.artifact_dir / "prompt.txt"),
            "--cwd",
            ctx.workspace,
            "--output-format",
            "json",
            "--json-schema",
            str(ctx.schema_path),
            "--permission-mode",
            "dontAsk",
            "--sandbox",
            "read-only" if readonly else "workspace",
            "--tools",
            tools,
            "--disable-web-search",
        ]
        return assert_argv_safe(argv)

    def parse(self, artifact_dir):
        return parse_grok(read_text(artifact_dir / "stdout.log"))
