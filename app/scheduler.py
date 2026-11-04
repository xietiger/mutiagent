from __future__ import annotations

import logging
import threading

from app.config import Settings
from app.worker import claim_and_start, watch_running

log = logging.getLogger("agent_console.scheduler")


class Scheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="console-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            self._stop.wait(self.settings.scheduler_interval)

    def tick(self) -> None:
        with self._lock:
            watch_running(self.settings)
            while claim_and_start(self.settings):
                continue
