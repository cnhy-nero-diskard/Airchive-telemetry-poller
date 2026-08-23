"""Configuration for the local dashboard only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from airchive.config import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    ConfigError,
    load_dotenv,
    load_inspection_config,
)

CACHE_PATH_ENV = "AIRCHIVE_DASHBOARD_CACHE_PATH"
DASHBOARD_DOTENV_NAMES = frozenset(
    {
        "FIREBASE_PROJECT_ID",
        "LG_DEVICE_ID",
        "LG_DAY_TIMEZONE",
        "POLL_INTERVAL_SECONDS",
        CACHE_PATH_ENV,
        "GOOGLE_APPLICATION_CREDENTIALS",
    }
)


@dataclass(frozen=True)
class DashboardConfig:
    project_id: str
    device_id: str
    timezone: ZoneInfo
    timezone_name: str
    cache_path: Path
    refresh_seconds: int


def default_cache_path() -> Path:
    """Return a user-local path that is independent of the checkout."""
    return Path.home() / ".airchive" / "dashboard-cache.sqlite3"


def load_dashboard_dotenv(
    path: str | Path = ".env", environ: dict[str, str] | None = None
) -> None:
    """Load only settings the dashboard can use; never import ThinQ secrets."""
    load_dotenv(path, environ, allowed_names=DASHBOARD_DOTENV_NAMES)


def load_dashboard_config(
    environ: dict[str, str] | None = None,
) -> DashboardConfig:
    """Load only stored-data settings; ThinQ credentials are intentionally absent."""
    env = os.environ if environ is None else environ
    project_id, device_id, timezone, timezone_name = load_inspection_config(env)
    problems: list[str] = []

    raw_refresh = (env.get("POLL_INTERVAL_SECONDS") or "").strip()
    refresh_seconds = DEFAULT_POLL_INTERVAL_SECONDS
    if raw_refresh:
        try:
            refresh_seconds = int(raw_refresh)
        except ValueError:
            problems.append("POLL_INTERVAL_SECONDS must be a positive integer number of seconds.")
        else:
            if refresh_seconds <= 0:
                problems.append(
                    "POLL_INTERVAL_SECONDS must be a positive integer number of seconds."
                )

    raw_cache_path = (env.get(CACHE_PATH_ENV) or "").strip()
    cache_path = Path(raw_cache_path).expanduser() if raw_cache_path else default_cache_path()
    if cache_path.exists() and cache_path.is_dir():
        problems.append(f"{CACHE_PATH_ENV} must name a file, not a directory.")

    if problems:
        raise ConfigError(problems)

    return DashboardConfig(
        project_id=project_id,
        device_id=device_id,
        timezone=timezone,
        timezone_name=timezone_name,
        cache_path=cache_path,
        refresh_seconds=refresh_seconds,
    )
