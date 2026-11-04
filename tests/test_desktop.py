import socket

from app.config import load_settings
from app.desktop import app_url, endpoint_ready, port_in_use


def test_app_url_uses_loopback():
    settings = load_settings()
    assert app_url(settings) == f"http://127.0.0.1:{settings.port}/"


def test_port_in_use_follows_the_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert port_in_use("127.0.0.1", port)
    assert not port_in_use("127.0.0.1", port)


def test_endpoint_ready_is_false_when_nothing_listens():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert endpoint_ready(f"http://127.0.0.1:{port}/health", timeout=0.2) is False
