"""Request-triggered collector entry point for Cloud Run."""

from __future__ import annotations

import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer

from airchive.commands import poll as poll_cmd
from airchive.logging_setup import get_logger

HOST = "0.0.0.0"
DEFAULT_PORT = 8080
TRIGGER_PATH = "/poll"

logger = get_logger("serve")


def port_from_environment() -> int:
    """Return the configured listening port, using Cloud Run's default."""
    raw_port = os.environ.get("PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port


class PollRequestHandler(BaseHTTPRequestHandler):
    """Accept exactly one route and run one poll cycle for each POST."""

    server_version = "AirchiveHTTP/1.0"

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != TRIGGER_PATH:
            self._reject_path()
            return
        self._run_cycle()

    def _reject_path(self) -> None:
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _reject_method(self) -> None:
        if self.path == TRIGGER_PATH:
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method Not Allowed")
        else:
            self._reject_path()

    def __getattr__(self, name: str):
        """Make even unknown HTTP verbs resolve to the safe rejection path."""
        if name.startswith("do_"):
            return self._reject_method
        raise AttributeError(name)

    def _run_cycle(self) -> None:
        try:
            exit_code = poll_cmd.run(once=True)
        except Exception:  # noqa: BLE001 - the request must not kill the server
            logger.exception("poll cycle raised an unexpected exception")
            self._respond(HTTPStatus.INTERNAL_SERVER_ERROR, b"poll cycle failed\n")
            return

        if exit_code == 0:
            self._respond(HTTPStatus.OK, b"poll cycle completed\n")
        else:
            logger.error("poll cycle failed", extra={"exit_code": exit_code})
            self._respond(HTTPStatus.INTERNAL_SERVER_ERROR, b"poll cycle failed\n")

    def _respond(self, status: HTTPStatus, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = HOST, port: int | None = None) -> HTTPServer:
    """Build the single-threaded server used by the CLI and tests."""
    selected_port = port if port is not None else port_from_environment()
    return HTTPServer((host, selected_port), PollRequestHandler)


def run() -> int:
    """Serve request-triggered poll cycles until the process is interrupted."""
    server = create_server()
    logger.info("collector service listening", extra={"host": HOST, "port": server.server_port})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("collector service interrupted")
    finally:
        server.server_close()
    return 0
