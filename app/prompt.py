from __future__ import annotations


def build_prompt(*, user_prompt: str, execution_mode: str, workspace: str) -> str:
    mode = "readonly" if execution_mode == "readonly" else "worktree"
    return (
        "你是本次并行评审中的一个参与者，只根据提供的任务和上下文独立完成。\n"
        "不要假设其他 Agent 的结论。\n"
        "不要向用户提出需要交互确认的问题。\n"
        "只返回控制台要求的结构化最终结果。\n"
        "最终结果必须是一个 JSON 对象，包含字段 schema_version、summary、category、findings、notes、follow_ups。\n"
        "schema_version 固定为 1。\n"
        "category 只能是 code、research、review、data、other。\n"
        "findings 中的 severity 只能是 critical、high、medium、low、info。\n"
        "file 使用仓库相对路径或 null，line 使用正整数或 null。\n"
        "不要在结果里写控制台状态、退出码，也不要自报 succeeded、failed 或其他执行状态。\n"
        f"执行模式：{mode}\n"
        f"工作目录：{workspace}\n"
        "任务：\n"
        f"{user_prompt.rstrip()}\n"
    )
