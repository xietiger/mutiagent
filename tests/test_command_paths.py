from pathlib import Path

import pytest

from app.drivers.base import RunContext, UnsafeArgv
from app.drivers.claude_print import ClaudePrintDriver
from app.drivers.codebuddy import CodeBuddyDriver
from app.drivers.codex_exec import CodexExecDriver
from app.drivers.grok_build import GrokBuildDriver
from app.drivers.kimi_code import KimiCodeDriver
from app.presets import discover_codebuddy, discover_grok_build, discover_kimi_code


def _ctx(tmp_path: Path, executable: Path, mode: str = "readonly") -> RunContext:
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    artifact = tmp_path / "artifact"
    artifact.mkdir(exist_ok=True)
    return RunContext(
        executable=str(executable),
        workspace=str(tmp_path / "workspace"),
        schema_path=artifact / "schema.json",
        artifact_dir=artifact,
        execution_mode=mode,
        project_rules="off",
        mcp="off",
        ide_mode=False,
    )


def test_drivers_use_absolute_argv_and_safe_modes(tmp_path):
    codex = CodexExecDriver().build_argv(_ctx(tmp_path, tmp_path / "codex"))
    assert Path(codex[0]).is_absolute()
    assert codex[codex.index("--sandbox") + 1] == "read-only"
    assert "danger-full-access" not in codex
    write = CodexExecDriver().build_argv(_ctx(tmp_path, tmp_path / "codex2", "worktree"))
    assert write[write.index("--sandbox") + 1] == "workspace-write"

    claude = ClaudePrintDriver().build_argv(_ctx(tmp_path, tmp_path / "claude"))
    assert "--restricted" in claude
    assert "Read,Glob,Grep" in claude
    assert "Edit" not in " ".join(claude)
    claude_write = ClaudePrintDriver().build_argv(_ctx(tmp_path, tmp_path / "claude-write", "worktree"))
    assert "Edit,Write" in " ".join(claude_write)

    grok = GrokBuildDriver().build_argv(_ctx(tmp_path, tmp_path / "grok"))
    assert grok[grok.index("--sandbox") + 1] == "read-only"
    assert grok[grok.index("--tools") + 1] == "read_file,grep,list_dir"
    grok_write = GrokBuildDriver().build_argv(_ctx(tmp_path, tmp_path / "grok-write", "worktree"))
    assert grok_write[grok_write.index("--sandbox") + 1] == "workspace"
    assert "search_replace" in grok_write[grok_write.index("--tools") + 1]

    buddy = CodeBuddyDriver().build_argv(_ctx(tmp_path, tmp_path / "codebuddy"))
    assert buddy[buddy.index("--tools") + 1] == "Read,Glob,Grep"
    buddy_write = CodeBuddyDriver().build_argv(_ctx(tmp_path, tmp_path / "codebuddy-write", "worktree"))
    assert "Edit,Write" in buddy_write[buddy_write.index("--tools") + 1]

    kimi = KimiCodeDriver().build_argv(_ctx(tmp_path, tmp_path / "kimi"))
    assert kimi[1:3] == ["-m", "app.drivers.kimi_bridge"]
    assert kimi[-1] == "readonly"
    kimi_write = KimiCodeDriver().build_argv(_ctx(tmp_path, tmp_path / "kimi-write", "worktree"))
    assert kimi_write[-1] == "worktree"


def test_new_builtin_discovery_uses_confirmed_paths(tmp_path):
    grok = tmp_path / ".grok" / "bin" / "grok"
    buddy = tmp_path / ".npm-global" / "bin" / "codebuddy"
    kimi = tmp_path / ".kimi-code" / "bin" / "kimi"
    grok.parent.mkdir(parents=True)
    buddy.parent.mkdir(parents=True)
    kimi.parent.mkdir(parents=True)
    grok.write_text("#!/bin/sh\n", encoding="utf-8")
    buddy.write_text("#!/bin/sh\n", encoding="utf-8")
    kimi.write_text("#!/bin/sh\n", encoding="utf-8")
    grok.chmod(0o755)
    buddy.chmod(0o755)
    kimi.chmod(0o755)
    assert discover_grok_build(tmp_path) == grok
    assert discover_codebuddy(tmp_path) == buddy
    assert discover_kimi_code(tmp_path) == kimi


def test_force_is_rejected_for_codex(tmp_path):
    ctx = _ctx(tmp_path, tmp_path / "codex")
    argv = CodexExecDriver().build_argv(ctx)
    argv.append("--force")
    with pytest.raises(UnsafeArgv):
        from app.drivers.base import assert_argv_safe

        assert_argv_safe(argv)


def test_source_has_no_shell_or_path_lookup():
    for path in (Path(__file__).resolve().parents[1] / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "shell=True" not in text
        assert "shutil.which" not in text
        assert "os.system" not in text
