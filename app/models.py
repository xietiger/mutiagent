from __future__ import annotations

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    driver: str
    executable: str
    args: list[str] = Field(default_factory=list)
    http_url: str | None = None
    timeout_seconds: int = 900
    max_concurrency: int = 1
    supported_modes: list[str] = Field(default_factory=lambda: ["readonly", "worktree"])
    project_rules: str = "off"
    mcp: str = "off"


class AgentPatch(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    timeout_seconds: int | None = None
    max_concurrency: int | None = None
    project_rules: str | None = None
    mcp: str | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    agent_ids: list[str] = Field(default_factory=list)
    context_path: str
    execution_mode: str = "readonly"
    strategy: str = "selected"
    idempotency_key: str | None = None
