"""Chart construction for the dashboard, kept free of Streamlit state."""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd

from airchive.dashboard.theme import ChartPalette

ATTENTION_MARKER = "Needs attention"
GAP_MARKER = "No stored value"
CHART_HEIGHT = 320


def _marker(row: dict[str, Any]) -> str | None:
    if row["intervalValue"] is None:
        return GAP_MARKER
    if row["anomalous"] or row["intervalStatus"] != "NORMAL":
        return ATTENTION_MARKER
    return None


def chart_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the plotting frame, dropping timezone offsets after conversion.

    Observation times arrive already converted to the configured day timezone.
    Removing the offset makes Vega-Lite render that same wall clock instead of
    re-rendering the instant in the browser's timezone.
    """
    return pd.DataFrame(
        [
            {
                "observedAt": row["observedAt"].replace(tzinfo=None),
                "intervalValue": row["intervalValue"],
                "intervalStatus": row["intervalStatus"],
                "marker": _marker(row),
            }
            for row in rows
        ]
    )


def energy_chart(
    rows: list[dict[str, Any]],
    *,
    timezone_name: str,
    unit: str | None,
    palette: ChartPalette,
) -> alt.LayerChart:
    """Layer stored interval usage with gap and attention markers."""
    frame = chart_frame(rows)
    base = alt.Chart(frame)
    x = alt.X(
        "observedAt:T",
        title=f"Observed at ({timezone_name})",
        axis=alt.Axis(grid=False, labelAngle=0, tickCount=6),
    )
    y = alt.Y(
        "intervalValue:Q",
        title=unit or "Stored interval value",
        axis=alt.Axis(grid=True, gridDash=[2, 3]),
    )
    color = alt.Color(
        "marker:N",
        scale=alt.Scale(
            domain=[ATTENTION_MARKER, GAP_MARKER],
            range=[palette.attention, palette.gap],
        ),
        legend=alt.Legend(title=None, orient="top", direction="horizontal", offset=6),
    )
    tooltip = [
        alt.Tooltip("observedAt:T", title="Observed", format="%Y-%m-%d %H:%M"),
        alt.Tooltip(
            "intervalValue:Q",
            title=f"Interval use ({unit})" if unit else "Interval use",
        ),
        alt.Tooltip("intervalStatus:N", title="Status"),
    ]

    # Missing intervals are drawn as dashed uprights rather than plotted values,
    # so a gap can never be mistaken for measured zero consumption.
    gaps = (
        base.transform_filter(alt.datum.marker == GAP_MARKER)
        .mark_rule(strokeWidth=1.5, strokeDash=[3, 3], opacity=0.7)
        .encode(x=x, color=color, tooltip=tooltip)
    )
    line = base.mark_line(strokeWidth=2, color=palette.series).encode(x=x, y=y)
    attention = (
        base.transform_filter(alt.datum.marker == ATTENTION_MARKER)
        .mark_point(shape="triangle", filled=True, size=90)
        .encode(x=x, y=y, color=color, tooltip=tooltip)
    )

    hover = alt.selection_point(
        fields=["observedAt"],
        nearest=True,
        on="pointerover",
        clear="pointerout",
        empty=False,
    )
    crosshair = (
        base.mark_rule(color=palette.guide, strokeWidth=1)
        .encode(x=x, opacity=alt.condition(hover, alt.value(0.7), alt.value(0)))
        .add_params(hover)
    )
    focus = base.mark_circle(size=90, color=palette.series).encode(
        x=x,
        y=y,
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=tooltip,
    )

    return (
        alt.layer(gaps, line, attention, crosshair, focus)
        .properties(height=CHART_HEIGHT)
        .configure_view(strokeWidth=0)
    )
