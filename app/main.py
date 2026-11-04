from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.agents import router as agents_router
from app.api.tasks import router as tasks_router
from app.config import Settings, load_settings
from app.db import init_db
from app.errors import ConsoleError
from app.probe import probe_all, seed_builtins
from app.scheduler import Scheduler
from app.worker import recover

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None, *, seed: bool = True, start_scheduler: bool = True) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(app.state.settings)
        if app.state.seed:
            seed_builtins(app.state.settings)
            probe_all(app.state.settings)
        recover(app.state.settings)
        scheduler = Scheduler(app.state.settings)
        app.state.scheduler = scheduler
        if app.state.start_scheduler:
            scheduler.start()
        yield
        scheduler.stop()

    app = FastAPI(title="本地多 Agent 控制台", lifespan=lifespan)
    app.state.settings = settings
    app.state.seed = seed
    app.state.start_scheduler = start_scheduler
    app.include_router(agents_router)
    app.include_router(tasks_router)

    @app.exception_handler(ConsoleError)
    async def handle_console_error(_request: Request, exc: ConsoleError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message, "error_code": exc.code})

    @app.get("/health")
    def health():
        return {"ok": True, "bind": "127.0.0.1"}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def main() -> None:
    settings = load_settings()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
