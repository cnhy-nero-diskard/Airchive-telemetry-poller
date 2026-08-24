"""Visual theme for the local dashboard process.

Streamlit theme settings are passed on the command line so the appearance does
not depend on the operator's working directory or on a checked-in
``.streamlit/config.toml``. Chart colors are resolved per surface because Vega
marks cannot follow the browser's color scheme on their own.
"""

from __future__ import annotations

from dataclasses import dataclass

LIGHT = "light"
DARK = "dark"


@dataclass(frozen=True)
class ChartPalette:
    """Mark colors stepped for one chart surface."""

    series: str
    attention: str
    gap: str
    guide: str


# Each hue is stepped for the surface it is drawn on. Adjacent marks clear the
# colorblind and normal-vision separation floors on both surfaces; the neutral
# gap color is deliberately unsaturated because a missing interval is absent
# data rather than a measured category.
_PALETTES = {
    LIGHT: ChartPalette(
        series="#2a78d6",
        attention="#eb6834",
        gap="#78776f",
        guide="#8a8a85",
    ),
    DARK: ChartPalette(
        series="#3987e5",
        attention="#d95926",
        gap="#8f8e86",
        guide="#9b9b94",
    ),
}

_LIGHT_THEME = {
    "primaryColor": "#2a78d6",
    "backgroundColor": "#fcfcfb",
    "secondaryBackgroundColor": "#f2f1ed",
    "textColor": "#1a1a19",
    "borderColor": "#e2e0da",
    "dataframeHeaderBackgroundColor": "#f2f1ed",
}
_DARK_THEME = {
    "primaryColor": "#3987e5",
    "backgroundColor": "#141413",
    "secondaryBackgroundColor": "#1f1f1e",
    "textColor": "#f5f4ef",
    "borderColor": "#3a3a37",
    "dataframeHeaderBackgroundColor": "#1f1f1e",
}
_SHARED_THEME = {
    "baseRadius": "0.6rem",
    "buttonRadius": "0.5rem",
    "showWidgetBorder": "true",
    "metricValueFontSize": "1.7rem",
}


def chart_palette(mode: str | None) -> ChartPalette:
    """Return the chart palette for the given Streamlit theme type."""
    return _PALETTES[DARK] if mode == DARK else _PALETTES[LIGHT]


def theme_options() -> list[str]:
    """Return Streamlit theme flags for both light and dark surfaces."""
    flags = [f"--theme.{name}={value}" for name, value in _SHARED_THEME.items()]
    flags += [f"--theme.light.{name}={value}" for name, value in _LIGHT_THEME.items()]
    flags += [f"--theme.dark.{name}={value}" for name, value in _DARK_THEME.items()]
    return flags
