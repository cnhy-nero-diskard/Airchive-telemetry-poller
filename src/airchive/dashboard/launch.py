"""Launch Streamlit through the supported local-only command."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from airchive.dashboard.theme import theme_options


def command() -> list[str]:
    app_path = Path(__file__).with_name("app.py").resolve()
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        "--server.headless=false",
        "--server.showEmailPrompt=false",
        "--browser.gatherUsageStats=false",
        *theme_options(),
    ]


def run(
    *,
    runner: Callable[..., Any] = subprocess.run,
    argv: Sequence[str] | None = None,
) -> int:
    """Run Streamlit and return its exit code without invoking a shell."""
    try:
        completed = runner([*command(), *(argv or ())], check=False)
    except KeyboardInterrupt:
        return 130
    return int(completed.returncode)
