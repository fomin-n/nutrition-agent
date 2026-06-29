from http.client import HTTPConnection

from app.bot.health_server import start_health_server
from app.llm.client import Settings


def test_health_server_does_not_start_when_disabled() -> None:
    assert start_health_server(Settings(health_http_enabled=False)) is None


def test_health_server_serves_healthz_and_404() -> None:
    handle = start_health_server(
        Settings(
            health_http_enabled=True,
            health_http_host="127.0.0.1",
            health_http_port=0,
        )
    )
    assert handle is not None
    try:
        conn = HTTPConnection(handle.host, handle.port, timeout=2)
        conn.request("GET", "/healthz")
        response = conn.getresponse()
        body = response.read()
        conn.close()

        assert response.status == 200
        assert body == b"ok\n"

        conn = HTTPConnection(handle.host, handle.port, timeout=2)
        conn.request("GET", "/not-found")
        missing = conn.getresponse()
        missing.read()
        conn.close()

        assert missing.status == 404
    finally:
        handle.stop()
