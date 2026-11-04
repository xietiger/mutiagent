from __future__ import annotations

from app.drivers.base import Driver, RunContext, assert_argv_safe
from app.output.parse import parse_codex, read_text


class CodexExecDriver(Driver):
    name = "codex_exec"

    def build_argv(self, ctx: RunContext) -> list[str]:
        sandbox = "read-only" if ctx.execution_mode == "readonly" else "workspace-write"
        argv = [
            ctx.executable,
            "exec",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
            "-C",
            ctx.workspace,
            "--output-schema",
            str(ctx.schema_path),
            "-o",
            str(ctx.artifact_dir / "last-message.json"),
            "-",
        ]
        return assert_argv_safe(argv)

    def parse(self, artifact_dir):
        return parse_codex(
            read_text(artifact_dir / "last-message.json"),
            read_text(artifact_dir / "stdout.log"),
        )
