from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.output.parse import parse_generic

FORBIDDEN_FRAGMENTS = (
    "danger-full-access",
    "--dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust",
    "--yolo",
)


class UnsafeArgv(RuntimeError):
    pass


@dataclass
class RunContext:
    executable: str
    workspace: str
    schema_path: Path
    artifact_dir: Path
    execution_mode: str
    project_rules: str
    mcp: str
    ide_mode: bool
    extra_args: tuple[str, ...] = ()
    http_url: str = ""


def assert_argv_safe(argv: list[str], *, allow_force: bool = False) -> list[str]:
    if not argv or not Path(argv[0]).is_absolute():
        raise UnsafeArgv("argv0 必须是绝对路径")
    for arg in argv:
        if not isinstance(arg, str) or "\x00" in arg:
            raise UnsafeArgv("参数无效")
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in arg:
                raise UnsafeArgv(fragment)
        if arg == "--force" and not allow_force:
            raise UnsafeArgv("--force")
    return argv


class Driver:
    name = "base"

    def build_argv(self, ctx: RunContext) -> list[str]:
        raise NotImplementedError

    def parse(self, artifact_dir: Path):
        from app.output.parse import read_text

        return parse_generic(read_text(artifact_dir / "stdout.log"))
