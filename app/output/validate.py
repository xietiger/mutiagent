from __future__ import annotations

from pathlib import Path

from app.errors import ContractError

CATEGORIES = {"code", "research", "review", "data", "other"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
CONFIDENCE = {"high", "medium", "low"}
AGENT_STATUS_KEYS = {"status", "exit_code", "console_status", "health_status"}


def _text(value: object, limit: int, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ContractError(f"{field} 必须是字符串")
    return value.strip()[:limit]


def _file(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ContractError("file 必须是相对路径或 null")
    text = value.strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~") or text.startswith("../") or "/../" in f"/{text}/":
        raise ContractError("file 必须是相对路径")
    parts = Path(text).parts
    if ".." in parts or text.startswith(".."):
        raise ContractError("file 不能包含 ..")
    if text.startswith("./"):
        text = text[2:]
    return text[:500]


def _line(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ContractError("line 必须是正整数或 null")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or value < 1:
        raise ContractError("line 必须是正整数或 null")
    return value


def validate_and_normalize(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ContractError("结果必须是 JSON 对象")
    data = {key: value for key, value in payload.items() if key not in AGENT_STATUS_KEYS}
    if data.get("schema_version") != 1:
        raise ContractError("schema_version 必须为 1")
    summary = _text(data.get("summary"), 4000, "summary")
    if not summary:
        raise ContractError("summary 不能为空")
    category = str(data.get("category", "")).strip().lower()
    if category not in CATEGORIES:
        raise ContractError("category 不在允许范围内")
    findings_in = data.get("findings", [])
    if not isinstance(findings_in, list):
        raise ContractError("findings 必须是数组")
    findings = []
    for item in findings_in[:100]:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 300, "title")
        if not title:
            continue
        severity = str(item.get("severity", "")).strip().lower()
        if severity not in SEVERITIES:
            raise ContractError("severity 不在允许范围内")
        finding = {
            "severity": severity,
            "title": title,
            "file": _file(item.get("file")),
            "line": _line(item.get("line")),
            "evidence": _text(item.get("evidence", ""), 2000, "evidence"),
            "recommendation": _text(item.get("recommendation", ""), 2000, "recommendation"),
        }
        confidence = item.get("confidence")
        if isinstance(confidence, str) and confidence.lower() in CONFIDENCE:
            finding["confidence"] = confidence.lower()
        findings.append(finding)
    follow = data.get("follow_ups", [])
    if not isinstance(follow, list):
        raise ContractError("follow_ups 必须是数组")
    follow_ups = [_text(item, 500, "follow_ups") for item in follow[:20] if isinstance(item, str) and item.strip()]
    return {
        "schema_version": 1,
        "summary": summary,
        "category": category,
        "findings": findings,
        "notes": _text(data.get("notes", ""), 4000, "notes"),
        "follow_ups": follow_ups,
    }


def try_strict(payload: object) -> dict | None:
    try:
        return validate_and_normalize(payload)
    except ContractError:
        return None


def fallback_result(text: str) -> dict:
    summary = (text or "").strip()[:4000] or "（无结构化结果）"
    return validate_and_normalize(
        {
            "schema_version": 1,
            "summary": summary,
            "category": "other",
            "findings": [],
            "notes": "结果来自非严格回退",
            "follow_ups": [],
        }
    )
