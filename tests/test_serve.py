"""Tests for the request-triggered collector entry point."""

from __future__ import annotations

import http.client
import json
import logging
import threading
from io import StringIO

import pytest

from airchive import cli, serve
from airchive.commands import poll as poll_cmd
from airchive.logging_setup import configure_logging
from airchive.redaction import clear_secrets, register_secret


@pytest.fixture
def server():
    value = serve.create_server("127.0.0.1", 0)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    try:
        yield value
    finally:
        value.shutdown()
        thread.join(timeout=2)
        value.server_close()


def request(server, method: str, path: str):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_post_runs_one_cycle_and_maps_exit_codes(server, monkeypatch):
    calls = []
    results = iter((0, 1))

    def fake_run(*, once):
        calls.append(once)
        return next(results)

    monkeypatch.setattr(poll_cmd, "run", fake_run)

    assert request(server, "POST", serve.TRIGGER_PATH)[0] == 200
    assert request(server, "POST", serve.TRIGGER_PATH)[0] == 500
    assert calls == [True, True]


def test_invalid_methods_and_paths_do_not_run_a_cycle(server, monkeypatch):
    calls = []
    monkeypatch.setattr(poll_cmd, "run", lambda **kwargs: calls.append(kwargs) or 0)

    assert request(server, "GET", serve.TRIGGER_PATH)[0] == 405
    assert request(server, "PATCH", serve.TRIGGER_PATH)[0] == 405
    assert request(server, "POST", "/not-the-trigger")[0] == 404
    assert calls == []


def test_unexpected_cycle_exception_returns_500_and_server_survives(server, monkeypatch):
    results = iter((RuntimeError("secret-token-value"), 0))

    def fake_run(*, once):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(poll_cmd, "run", fake_run)
    stream = StringIO()
    configure_logging("INFO", stream=stream)
    register_secret("secret-token-value")

    try:
        assert request(server, "POST", serve.TRIGGER_PATH)[0] == 500
        assert request(server, "POST", serve.TRIGGER_PATH)[0] == 200

        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        exception_record = next(
            record for record in records if "unexpected exception" in record["message"]
        )
        assert exception_record["severity"] == "ERROR"
        assert "secret-token-value" not in stream.getvalue()
    finally:
        clear_secrets()


def test_serve_uses_cloud_run_port(monkeypatch):
    created = {}

    class FakeServer:
        server_port = 9099

        def __init__(self, address, handler):
            created["address"] = address
            created["handler"] = handler

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setenv("PORT", "9099")
    monkeypatch.setattr(serve, "HTTPServer", FakeServer)

    assert serve.run() == 0
    assert created["address"] == ("0.0.0.0", 9099)
    assert created["handler"] is serve.PollRequestHandler


def test_default_port_and_invalid_port(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert serve.port_from_environment() == 8080

    monkeypatch.setenv("PORT", "not-a-port")
    with pytest.raises(ValueError, match="PORT must be an integer"):
        serve.port_from_environment()


def test_cli_dispatches_serve_and_preserves_poll_once(monkeypatch):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    seen = []
    monkeypatch.setattr(serve, "run", lambda: seen.append("serve") or 0)
    monkeypatch.setattr(poll_cmd, "run", lambda *, once: seen.append(("poll", once)) or 0)

    assert cli.main(["serve"]) == 0
    assert cli.main(["poll", "--once"]) == 0
    assert seen == ["serve", ("poll", True)]


def test_service_logger_is_structured():
    assert serve.logger.name == "airchive.serve"
    assert logging.getLogger("airchive.serve").name == serve.logger.name
