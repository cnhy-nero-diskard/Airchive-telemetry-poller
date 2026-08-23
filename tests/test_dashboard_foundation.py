"""Dashboard dependency, configuration, and safe local launch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from airchive import cli
from airchive.config import ConfigError
from airchive.dashboard.config import (
    CACHE_PATH_ENV,
    load_dashboard_config,
    load_dashboard_dotenv,
)
from airchive.dashboard.launch import command, run


def inspection_env(tmp_path: Path) -> dict[str, str]:
    return {
        "FIREBASE_PROJECT_ID": "airchive-test",
        "LG_DEVICE_ID": "device-1",
        "LG_DAY_TIMEZONE": "Asia/Manila",
        CACHE_PATH_ENV: str(tmp_path / "dashboard.sqlite3"),
    }


def test_dashboard_package_and_streamlit_import():
    import streamlit  # noqa: F401

    import airchive.dashboard.app  # noqa: F401


def test_dashboard_config_needs_no_thinq_credentials(tmp_path):
    config = load_dashboard_config(inspection_env(tmp_path))

    assert config.project_id == "airchive-test"
    assert config.device_id == "device-1"
    assert config.timezone_name == "Asia/Manila"
    assert config.cache_path == tmp_path / "dashboard.sqlite3"
    assert config.refresh_seconds == 300


def test_dashboard_config_reports_missing_values_without_echoing_secrets(tmp_path):
    sentinel = "SENTINEL-PAT-should-never-render"

    with pytest.raises(ConfigError) as excinfo:
        load_dashboard_config({"LG_THINQ_PAT": sentinel, CACHE_PATH_ENV: str(tmp_path / "x")})

    rendered = str(excinfo.value)
    assert "FIREBASE_PROJECT_ID" in rendered
    assert "LG_DEVICE_ID" in rendered
    assert sentinel not in rendered


def test_dashboard_dotenv_does_not_import_thinq_secrets(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "LG_THINQ_PAT=secret-that-dashboard-must-not-load\n"
        "FIREBASE_PROJECT_ID=project-from-file\n"
        "LG_DEVICE_ID=device-from-file\n",
        encoding="utf-8",
    )
    environ = {}

    load_dashboard_dotenv(dotenv, environ)

    assert environ == {
        "FIREBASE_PROJECT_ID": "project-from-file",
        "LG_DEVICE_ID": "device-from-file",
    }


def test_launch_command_is_loopback_only():
    argv = command()

    assert argv[:4] == [argv[0], "-m", "streamlit", "run"]
    assert "--server.address=127.0.0.1" in argv
    assert "--server.showEmailPrompt=false" in argv
    assert not any("0.0.0.0" in argument for argument in argv)


def test_launch_uses_injected_runner_without_a_shell():
    calls = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    assert run(runner=fake_runner) == 0
    assert calls[0][1] == {"check": False}
    assert "--server.address=127.0.0.1" in calls[0][0]


def test_cli_dashboard_dispatch_does_not_launch_real_server(monkeypatch):
    invoked = []
    monkeypatch.setattr("airchive.dashboard.launch.run", lambda: invoked.append(True) or 0)

    assert cli.main(["dashboard"]) == 0
    assert invoked == [True]


def test_launch_handles_local_interrupt_without_a_traceback():
    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    assert run(runner=interrupted) == 130
