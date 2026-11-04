from __future__ import annotations

import json
from pathlib import Path

from app.output.validate import fallback_result, try_strict


def read_text(path: Path, limit: int = 2_000_000) -> str:
    if not path.exists() or path.is_symlink():
        return ""
    data = path.read_bytes()[:limit]
    return data.decode("utf-8", errors="replace")


def loads_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_json_objects(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    found: list[dict] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        index = start + max(end, 1)
    return found


def write_native_events(stdout_text: str, dest: Path) -> None:
    lines = []
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        if loads_object(stripped) is not None:
            lines.append(stripped)
    if lines:
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _session(obj: dict) -> str | None:
    for key in ("session_id", "thread_id", "sessionId"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


def _message_text(obj: dict) -> str | None:
    item = obj.get("item") if isinstance(obj.get("item"), dict) else None
    for candidate in (
        obj.get("text"),
        obj.get("content") if obj.get("role") in {"assistant", "agent", None} else None,
        None if item is None else item.get("text"),
        None if item is None else item.get("content"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    message = obj.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return None


def _from_text(text: str) -> tuple[dict, bool] | None:
    direct = loads_object(text.strip())
    if isinstance(direct, dict):
        strict = try_strict(direct)
        if strict:
            return strict, True
    for obj in reversed(extract_json_objects(text)):
        strict = try_strict(obj)
        if strict:
            return strict, True
    return None


def parse_codex(last_message: str, stdout: str) -> tuple[dict, str | None, bool]:
    session = None
    if last_message.strip():
        found = _from_text(last_message)
        if found:
            return found[0], None, True
    last_text = ""
    for obj in extract_json_objects(stdout):
        session = session or _session(obj)
        text = _message_text(obj)
        if not text:
            continue
        last_text = text
        found = _from_text(text)
        if found:
            return found[0], session, True
    if last_message.strip():
        return fallback_result(last_message), session, False
    if last_text:
        return fallback_result(last_text), session, False
    return fallback_result(stdout), session, False


def parse_claude(stdout: str) -> tuple[dict, str | None, bool]:
    session = None
    prose = ""
    for obj in reversed(extract_json_objects(stdout)):
        session = session or _session(obj)
        structured = obj.get("structured_output")
        if isinstance(structured, dict):
            strict = try_strict(structured)
            if strict:
                return strict, session, True
        result = obj.get("result")
        if isinstance(result, dict):
            strict = try_strict(result)
            if strict:
                return strict, session, True
        if isinstance(result, str) and result.strip():
            prose = result
            found = _from_text(result)
            if found:
                return found[0], session, True
        strict = try_strict(obj)
        if strict:
            return strict, session, True
    return fallback_result(prose or stdout), session, False


def parse_grok(stdout: str) -> tuple[dict, str | None, bool]:
    session = None
    prose = ""
    for obj in reversed(extract_json_objects(stdout)):
        session = session or _session(obj)
        for key in ("text", "result", "content"):
            value = obj.get(key)
            if isinstance(value, dict):
                strict = try_strict(value)
                if strict:
                    return strict, session, True
            if isinstance(value, str) and value.strip():
                prose = value
                found = _from_text(value)
                if found:
                    return found[0], session, True
        strict = try_strict(obj)
        if strict:
            return strict, session, True
    return fallback_result(prose or stdout), session, False


def parse_kimi(stdout: str) -> tuple[dict, str | None, bool]:
    session = None
    prose = ""
    structured = None
    for obj in extract_json_objects(stdout):
        session = session or _session(obj)
        if obj.get("role") != "assistant":
            structured = structured or try_strict(obj)
            continue
        content = obj.get("content")
        if isinstance(content, dict):
            structured = structured or try_strict(content)
        if isinstance(content, str) and content.strip():
            prose = content
            found = _from_text(content)
            if found:
                structured = structured or found[0]
    if structured:
        return structured, session, True
    return fallback_result(prose or stdout), session, False


def parse_generic(stdout: str) -> tuple[dict, str | None, bool]:
    found = _from_text(stdout)
    if found:
        return found[0], None, True
    return fallback_result(stdout), None, False
