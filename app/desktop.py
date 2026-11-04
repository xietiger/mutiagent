"""Open Relay in its own window on this computer."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import uvicorn

from app.config import Settings, load_settings
from app.main import create_app

START_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Relay</title>
  <style>
    html, body { margin: 0; height: 100%; background: #f7f7f5; color: #1c1d1f;
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { height: 100%; display: grid; place-items: center; }
    p { margin: 0; letter-spacing: 0.01em; }
  </style>
</head>
<body>
  <main><p>正在打开 Relay…</p></main>
</body>
</html>
"""

ERROR_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Relay</title>
  <style>
    html, body { margin: 0; height: 100%; background: #f7f7f5; color: #1c1d1f;
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { height: 100%; display: grid; place-items: center; }
    section { width: min(420px, calc(100% - 48px)); }
    h1 { margin: 0 0 8px; font-size: 22px; font-weight: 600; }
    p { margin: 0; color: #4d5156; }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>Relay 没有启动</h1>
      <p>{message}</p>
    </section>
  </main>
</body>
</html>
"""


@dataclass
class Launch:
    settings: Settings
    url: str
    owned: bool = False
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None


def app_url(settings: Settings) -> str:
    return f"http://{settings.host}:{settings.port}/"


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def endpoint_ready(url: str, timeout: float = 0.4) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_until_ready(url: str, timeout: float = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if endpoint_ready(url):
            return True
        time.sleep(0.2)
    return False


def configure_logging(settings: Settings) -> None:
    log_dir = settings.root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_dir / "desktop.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def alert(message: str) -> None:
    logging.error(message)
    if os.environ.get("RELAY_DESKTOP_SMOKE") == "1":
        return
    safe = message.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'display dialog "{safe}" buttons {{"好"}} default button 1 with title "Relay"'],
        timeout=120,
        check=False,
    )


def start_server(settings: Settings) -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="relay-server", daemon=True)
    thread.start()
    return server, thread


def stop_server(launch: Launch) -> None:
    if not launch.owned or launch.server is None or launch.thread is None:
        return
    launch.server.should_exit = True
    launch.thread.join(timeout=3)


def show_error(window, message: str) -> None:
    logging.error(message)
    escaped = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    window.load_html(ERROR_HTML.replace("{message}", escaped))


def boot(launch: Launch) -> None:
    import webview

    health = launch.url + "health"
    window = webview.windows[0]
    try:
        if endpoint_ready(health):
            logging.info("using server already listening at %s", launch.url)
        elif port_in_use(launch.settings.host, launch.settings.port):
            show_error(window, f"{launch.settings.port} 端口已被其他程序占用。")
            return
        else:
            launch.server, launch.thread = start_server(launch.settings)
            launch.owned = True
            if not wait_until_ready(health):
                show_error(window, "本地服务没有在预期时间内就绪。可以查看 data/desktop.log。")
                return
        window.load_url(launch.url)
        logging.info("window opened %s", launch.url)
    except Exception:
        logging.exception("desktop window failed")
        show_error(window, "窗口启动失败。可以查看 data/desktop.log。")
    finally:
        if os.environ.get("RELAY_DESKTOP_SMOKE") == "1":
            time.sleep(0.8)
            window.destroy()


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    try:
        import webview
    except ImportError:
        alert("还没有安装窗口组件。请在项目目录运行 .venv/bin/pip install -r requirements.txt")
        raise SystemExit(1) from None

    launch = Launch(settings=settings, url=app_url(settings))
    webview.create_window(
        "Relay",
        html=START_HTML,
        width=1280,
        height=840,
        min_size=(960, 640),
        background_color="#f7f7f5",
        text_select=True,
    )
    webview.start(boot, launch)
    stop_server(launch)


if __name__ == "__main__":
    main()
