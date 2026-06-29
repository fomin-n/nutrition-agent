import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app.llm.client import Settings

LOGGER = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug("health_http %s", format % args)


@dataclass(frozen=True)
class HealthServer:
    server: ThreadingHTTPServer
    thread: Thread

    @property
    def host(self) -> str:
        host, _port = self.server.server_address[:2]
        return str(host)

    @property
    def port(self) -> int:
        _host, port = self.server.server_address[:2]
        return int(port)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_health_server(settings: Settings) -> HealthServer | None:
    if not settings.health_http_enabled:
        return None
    try:
        server = ThreadingHTTPServer(
            (settings.health_http_host, settings.health_http_port),
            _HealthHandler,
        )
    except OSError as exc:
        raise RuntimeError(
            "Failed to start health HTTP server on "
            f"{settings.health_http_host}:{settings.health_http_port}: {exc}"
        ) from exc

    thread = Thread(target=server.serve_forever, name="nutrition-health-http", daemon=True)
    thread.start()
    handle = HealthServer(server=server, thread=thread)
    LOGGER.info("Health HTTP server listening on %s:%s", handle.host, handle.port)
    return handle
