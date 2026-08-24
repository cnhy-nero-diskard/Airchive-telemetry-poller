"""Chart construction and theme resolution for the dashboard."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from airchive.dashboard.charts import (
    ATTENTION_MARKER,
    GAP_MARKER,
    chart_frame,
    energy_chart,
)
from airchive.dashboard.theme import DARK, LIGHT, chart_palette, theme_options

MANILA = ZoneInfo("Asia/Manila")


def row(minute: int, *, value: float | None, status: str = "NORMAL", anomalous=False):
    return {
        "observedAt": datetime(2026, 8, 24, 1, minute, tzinfo=UTC).astimezone(MANILA),
        "intervalValue": value,
        "intervalStatus": status,
        "anomalous": anomalous,
    }


def test_chart_frame_marks_gaps_and_attention_without_inventing_values():
    frame = chart_frame(
        [
            row(0, value=1.0),
            row(1, value=None, status="ENERGY_UNAVAILABLE"),
            row(2, value=2.0, status="RESET_SUSPECTED", anomalous=True),
        ]
    )

    assert frame["marker"].isna()[0]
    assert list(frame["marker"][1:]) == [GAP_MARKER, ATTENTION_MARKER]
    assert math.isnan(frame["intervalValue"][1])
    assert frame["intervalValue"][0] == 1.0


def test_chart_frame_renders_configured_timezone_wall_clock():
    frame = chart_frame([row(0, value=1.0)])
    observed = frame["observedAt"][0]

    # 01:00 UTC is 09:00 in Asia/Manila; the offset is dropped so Vega-Lite
    # cannot re-render the instant in the browser's timezone.
    assert observed.hour == 9
    assert observed.tzinfo is None


def test_energy_chart_layers_gaps_line_attention_and_hover():
    palette = chart_palette(LIGHT)
    spec = energy_chart(
        [row(0, value=1.0), row(1, value=None, status="ENERGY_UNAVAILABLE")],
        timezone_name="Asia/Manila",
        unit="Wh",
        palette=palette,
    ).to_dict()

    layers = spec["layer"]
    assert len(layers) == 5
    gap_layer, line_layer = layers[0], layers[1]
    assert gap_layer["mark"]["type"] == "rule"
    assert "y" not in gap_layer["encoding"]
    assert gap_layer["encoding"]["color"]["scale"]["range"] == [
        palette.attention,
        palette.gap,
    ]
    assert line_layer["mark"]["color"] == palette.series
    assert line_layer["encoding"]["y"]["field"] == "intervalValue"
    assert line_layer["encoding"]["y"]["title"] == "Wh"
    assert "Asia/Manila" in layers[1]["encoding"]["x"]["title"]
    assert any(param["select"]["on"] == "pointerover" for param in spec["params"])


def test_chart_palette_is_stepped_per_surface():
    light, dark = chart_palette(LIGHT), chart_palette(DARK)

    assert light != dark
    assert chart_palette(None) == light
    assert chart_palette("unknown") == light


def test_theme_options_configure_both_surfaces():
    flags = theme_options()

    assert all(flag.startswith("--theme.") for flag in flags)
    assert "--theme.light.primaryColor=#2a78d6" in flags
    assert "--theme.dark.primaryColor=#3987e5" in flags
    assert "--theme.light.backgroundColor=#fcfcfb" in flags
    assert "--theme.dark.backgroundColor=#141413" in flags
