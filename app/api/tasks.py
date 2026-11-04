from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.db import connect, one, rows
from app.errors import ConsoleError
from app.paths import resolve_artifact
from app.redact import redact
from app.tasks_service import cancel_task, create_task, list_tasks, retry_subtask, task_detail

router = APIRouter()


def _settings(request: Request):
    return request.app.state.settings


@router.post("/tasks", status_code=201)
def post_task(request: Request, body: dict):
    detail, status = create_task(_settings(request), body)
    if status == 200:
        from fastapi.responses import JSONResponse

        return JSONResponse(detail, status_code=200)
    return detail


@router.get("/tasks")
def get_tasks(request: Request):
    return list_tasks(_settings(request))


@router.get("/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    return task_detail(_settings(request), task_id)


@router.post("/tasks/{task_id}/cancel")
def post_cancel(task_id: str, request: Request):
    return cancel_task(_settings(request), task_id)


@router.post("/subtasks/{subtask_id}/retry")
def post_retry(subtask_id: str, request: Request):
    return retry_subtask(_settings(request), subtask_id)


@router.get("/tasks/{task_id}/events")
async def events(task_id: str, request: Request):
    settings = _settings(request)
    with connect(settings.db_path) as conn:
        if one(conn, "SELECT id FROM tasks WHERE id = ?", (task_id,)) is None:
            raise ConsoleError("任务不存在", 404, "task_missing")
    header = request.headers.get("last-event-id") or "0"
    try:
        last_id = int(header)
    except ValueError:
        last_id = 0

    async def generate():
        nonlocal last_id
        yield ": connected\n\n"
        ticks = 0
        while True:
            if await request.is_disconnected():
                break
            with connect(settings.db_path) as conn:
                found = rows(
                    conn,
                    "SELECT id, type, payload FROM events WHERE task_id = ? AND id > ? ORDER BY id",
                    (task_id, last_id),
                )
            for event in found:
                last_id = event["id"]
                yield f"id: {event['id']}\nevent: {event['type']}\ndata: {event['payload']}\n\n"
            ticks += 1
            if ticks >= 15:
                yield ": ping\n\n"
                ticks = 0
            await asyncio.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/artifacts/{task_id}/{subtask_id}/{filename}")
def download(task_id: str, subtask_id: str, filename: str, request: Request):
    path = resolve_artifact(_settings(request), task_id, subtask_id, filename)
    size = path.stat().st_size
    with path.open("rb") as handle:
        data = handle.read(2_000_000)
    text = redact(data.decode("utf-8", errors="replace"))
    if size > 2_000_000:
        text += "\n…[truncated]"
    return PlainTextResponse(text)


@router.get("/tasks/{task_id}/subtasks/{subtask_id}/tail")
def tail(task_id: str, subtask_id: str, request: Request, stream: str = "stdout", lines: int = 200):
    filename = "stdout.log" if stream == "stdout" else "stderr.log" if stream == "stderr" else ""
    if not filename:
        raise ConsoleError("stream 只能是 stdout 或 stderr", 422, "bad_stream")
    try:
        path = resolve_artifact(_settings(request), task_id, subtask_id, filename)
    except ConsoleError as exc:
        if exc.code == "artifact_missing":
            return PlainTextResponse("")
        raise
    data = path.read_bytes()[-200_000:]
    text = "\n".join(data.decode("utf-8", errors="replace").splitlines()[-max(1, min(lines, 400)) :])
    return PlainTextResponse(redact(text))
