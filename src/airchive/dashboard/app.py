"""Streamlit application for local, read-only telemetry inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from airchive.config import ConfigError
from airchive.dashboard.cache import DashboardCache
from airchive.dashboard.charts import energy_bar_chart, energy_chart
from airchive.dashboard.config import (
    DashboardConfig,
    load_dashboard_config,
    load_dashboard_dotenv,
)
from airchive.dashboard.models import ObservationProjection
from airchive.dashboard.presentation import (
    Overview,
    bucket_options,
    bucket_rows,
    bucket_series,
    build_overview,
    chart_rows,
    is_anomalous,
    summarize_range,
)
from airchive.dashboard.repository import DashboardRepository
from airchive.dashboard.service import DashboardService, RefreshResult
from airchive.dashboard.theme import ChartPalette, chart_palette
from airchive.redaction import scrub_object
from airchive.storage.client import build_client

RANGE_OPTIONS = {"24 hours": 1, "7 days": 7, "30 days": 30}
SPARKLINE_POINTS = 24
KPI_CARD_HEIGHT = 165

PAGE_STYLES = """
<style>
  div[data-testid="stMainBlockContainer"] {
    padding-top: 5rem;
    padding-bottom: 4rem;
    max-width: 1500px;
  }
  div[data-testid="stMainBlockContainer"] h1 {
    padding: 0.25rem 0 0;
    letter-spacing: -0.02em;
  }
  .st-key-header_status {
    align-items: flex-end;
  }
  div[data-testid="stMetric"] {
    padding: 0.9rem 1rem;
  }
  div[data-testid="stMetricValue"] {
    font-variant-numeric: tabular-nums;
  }
  div[data-testid="stTabs"] button[role="tab"] p {
    font-weight: 600;
  }
</style>
"""


@dataclass(frozen=True)
class Runtime:
    service: DashboardService
    recovered_cache: Path | None = None


@st.cache_resource(show_spinner=False)
def build_runtime(
    project_id: str,
    device_id: str,
    cache_path: str,
    refresh_seconds: int,
) -> Runtime:
    client = build_client(project_id)
    cache, recovered = DashboardCache.open_recovering(cache_path)
    repository = DashboardRepository(client, device_id)
    service = DashboardService(
        repository,
        cache,
        project_id=project_id,
        device_id=device_id,
        refresh_seconds=refresh_seconds,
    )
    return Runtime(service=service, recovered_cache=recovered)


def _format_instant(value: datetime | None, config: DashboardConfig) -> str:
    if value is None:
        return "Unavailable"
    return value.astimezone(config.timezone).strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_number(value: float | None, unit: str | None) -> str:
    if value is None:
        return "Unavailable"
    rendered = f"{value:,.3f}".rstrip("0").rstrip(".")
    return f"{rendered} {unit}" if unit else rendered


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "Unavailable"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    return f"{seconds / 3600:.1f}h ago"


def _source_label(ok: bool | None, failure_class: str | None) -> str:
    if ok is True:
        return "ok"
    if failure_class:
        return f"failed ({failure_class})"
    return "unavailable"


def _health_badge(overview: Overview, refresh: RefreshResult) -> tuple[str, str, str]:
    """Return the label, color, and icon that summarize collector state."""
    if not refresh.succeeded or overview.consecutive_failures:
        return "Needs attention", "red", ":material/error:"
    if overview.latest is None:
        return "Waiting for data", "gray", ":material/hourglass_empty:"
    if overview.stale:
        return "Stale data", "orange", ":material/schedule:"
    return "Healthy", "green", ":material/check_circle:"


def _active_palette() -> ChartPalette:
    """Resolve chart colors for the browser's current Streamlit surface."""
    try:
        theme = st.context.theme
    except Exception:  # pragma: no cover - context is absent outside a session
        return chart_palette(None)
    return chart_palette(getattr(theme, "type", None))


def _sparkline(observations: list[ObservationProjection]) -> list[float] | None:
    values = [
        item.interval_value_number
        for item in observations
        if item.interval_value_number is not None
    ]
    return values[-SPARKLINE_POINTS:] if len(values) > 1 else None


def _render_header(
    config: DashboardConfig,
    overview: Overview,
    refresh: RefreshResult,
) -> None:
    identity, status = st.columns([3, 2], vertical_alignment="center")
    with identity:
        st.title("Airchive")
        st.caption(
            f"A read-only view of device {config.device_id} · Times shown in "
            f"{config.timezone_name}"
        )
    with status, st.container(key="header_status", horizontal_alignment="right"):
        label, color, icon = _health_badge(overview, refresh)
        st.badge(label, color=color, icon=icon)
        st.caption(
            "Last successful Firestore sync: "
            f"{_format_instant(overview.last_sync_at, config)}"
        )


def _render_controls() -> tuple[str, bool]:
    with st.container(border=True):
        window, action, hint = st.columns([2, 1, 3], vertical_alignment="bottom")
        with window:
            range_label = st.selectbox(
                "History window",
                tuple(RANGE_OPTIONS),
                index=0,
                help=(
                    "Controls the chart and observation table. Start with 24 hours to "
                    "keep the view focused."
                ),
            )
        with action:
            manual_refresh = st.button("Refresh now", type="primary", width="stretch")
        with hint:
            st.caption(
                "Refresh now checks Firestore for changes only. Incremental and "
                "read-only."
            )
            st.caption(
                "Changing the window reuses locally cached history whenever possible."
            )
    return range_label, manual_refresh


def _render_banners(
    overview: Overview,
    refresh: RefreshResult,
    latest: ObservationProjection | None,
    observations: list[ObservationProjection],
) -> None:
    if not refresh.succeeded:
        message = f"Firestore refresh failed ({refresh.error_class or 'unknown error'})."
        offline = ":material/cloud_off:"
        if observations:
            st.warning(f"{message} Showing the last valid cached data.", icon=offline)
        else:
            st.error(f"{message} No cached telemetry is available yet.", icon=offline)
    elif overview.refresh_error_class:
        st.warning(
            f"The previous refresh failed ({overview.refresh_error_class}); "
            "the latest retry succeeded.",
            icon=":material/history:",
        )

    if overview.stale:
        st.warning(
            f"Collection is stale: the latest stored observation is "
            f"{_format_age(overview.latest_age_seconds)}.",
            icon=":material/schedule:",
        )
    if overview.consecutive_failures:
        failure = overview.last_error_class or "unknown failure"
        detail = (
            f" — {overview.last_error_message}" if overview.last_error_message else ""
        )
        st.error(
            f"Collector has {overview.consecutive_failures} consecutive failure(s): "
            f"{failure}{detail}",
            icon=":material/error:",
        )
    elif not overview.stale and latest is not None and refresh.succeeded:
        st.success(
            f"Collector looks healthy. Latest sample arrived "
            f"{_format_age(overview.latest_age_seconds)}.",
            icon=":material/check_circle:",
        )
    elif latest is None and refresh.succeeded:
        st.info(
            "No stored observations yet. The dashboard will update after collection "
            "starts.",
            icon=":material/info:",
        )


def _principal(latest: ObservationProjection | None, key: str) -> object | None:
    """Read one principal state field, keeping the device's own vocabulary."""
    if latest is None:
        return None
    value = latest.principal_state.get(key)
    return None if value in (None, "") else value


def _format_temperature(value: object | None, unit: object | None) -> str:
    if value is None:
        return "Unavailable"
    number = f"{value:g}" if isinstance(value, int | float) else str(value)
    if unit in ("C", "F"):
        return f"{number} °{unit}"
    return f"{number} {unit}" if unit else number


def _render_glance(
    overview: Overview,
    latest: ObservationProjection | None,
    observations: list[ObservationProjection],
) -> None:
    st.subheader("At a glance")
    st.caption(
        "Start here: current health, latest usage, data quality, and how the device "
        "was set."
    )

    unit = latest.unit if latest else None
    status = latest.interval_status if latest and latest.interval_status else "Unavailable"
    temperature_unit = _principal(latest, "unit")
    target = _principal(latest, "targetTemperature")

    # Two rows of three keep every card the same size; a single wrapping row
    # would stretch the leftover card across the full width.
    age_card, energy_card, counter_card = st.columns(3)
    with age_card:
        st.metric(
            "Latest sample age",
            _format_age(overview.latest_age_seconds),
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/schedule:",
            help="How long ago the newest stored observation was collected.",
        )
    with energy_card:
        st.metric(
            "Latest interval use",
            _format_number(latest.interval_value_number if latest else None, unit),
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/bolt:",
            chart_data=_sparkline(observations),
            chart_type="area",
            help="Energy used between the two most recent usable samples.",
        )
    with counter_card:
        st.metric(
            "Today's device counter",
            _format_number(latest.raw_daily_total_number if latest else None, unit),
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/speed:",
            help="The raw cumulative daily counter reported by the device.",
        )

    quality_card, temperature_card, wind_card = st.columns(3)
    with quality_card:
        st.metric(
            "Data quality",
            status,
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/verified:",
            help="NORMAL is usable. Other statuses are explained in the legend below.",
        )
    with temperature_card:
        st.metric(
            "Room temperature",
            _format_temperature(_principal(latest, "currentTemperature"), temperature_unit),
            delta=(
                f"Target {_format_temperature(target, temperature_unit)}"
                if target is not None
                else None
            ),
            delta_color="off",
            delta_arrow="off",
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/thermostat:",
            help=(
                "Stored device temperatures at the latest sample, in the unit the "
                "device reported."
            ),
        )
    with wind_card:
        st.metric(
            "Wind strength",
            str(_principal(latest, "windStrength") or "Unavailable"),
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/air:",
            help="Fan setting stored with the latest sample, in the device's own wording.",
        )


def _render_energy_tab(
    observations: list[ObservationProjection],
    config: DashboardConfig,
    latest: ObservationProjection | None,
    *,
    since: datetime,
    until: datetime,
) -> None:
    st.subheader("Energy over time")
    st.caption(
        "Each plotted point is stored interval usage. Missing values stay as visible "
        "gaps instead of being shown as zero."
    )
    unit = latest.unit if latest else None
    summary = summarize_range(
        observations,
        since=since,
        until=until,
        cadence_seconds=config.refresh_seconds,
    )
    with st.container(horizontal=True):
        st.metric(
            "Measured interval total",
            _format_number(summary.total, unit),
            border=True,
            icon=":material/functions:",
            help="Sum of non-null stored interval values; missing intervals are excluded.",
        )
        st.metric(
            "Usable coverage",
            summary.coverage_label,
            border=True,
            icon=":material/data_check:",
            help="Usable stored intervals divided by intervals expected in this window.",
        )
        st.metric(
            "Samples needing attention",
            summary.anomaly_count,
            border=True,
            icon=":material/warning:",
            help="Observations with a non-normal status or a quality flag.",
        )
    if not summary.complete:
        st.warning(
            "This range is incomplete. The total includes only stored non-null intervals; "
            "gaps and unresolved values are excluded, not counted as zero.",
            icon=":material/warning:",
        )

    options = bucket_options(config.refresh_seconds)
    raw_label = next(iter(options))
    granularity = st.segmented_control(
        "Interval",
        tuple(options),
        default=raw_label,
        key="chart_granularity",
        help=(
            "Aggregation width. Coarser intervals sum the stored samples inside each "
            "slot; slots with no stored value stay empty."
        ),
    )
    granularity = granularity or raw_label

    if not observations:
        st.info("No observations are available in this range.", icon=":material/info:")
        return

    palette = _active_palette()
    if granularity == raw_label:
        rows = chart_rows(observations, config.timezone)
        chart = energy_chart(
            rows,
            timezone_name=config.timezone_name,
            unit=unit,
            palette=palette,
        )
        detail = [
            row for row in rows if row["intervalStatus"] != "NORMAL" or row["anomalous"]
        ]
        detail_label = "Samples behind the chart's gaps and non-normal markers"
    else:
        buckets = bucket_series(
            observations,
            timezone=config.timezone,
            bucket_seconds=options[granularity],
            since=since,
            until=until,
            cadence_seconds=config.refresh_seconds,
        )
        rows = bucket_rows(buckets)
        chart = energy_bar_chart(
            rows,
            timezone_name=config.timezone_name,
            unit=unit,
            palette=palette,
        )
        detail = [row for row in rows if row["state"] != "Complete"]
        detail_label = f"{granularity} slots with missing or partial coverage"

    with st.container(border=True):
        st.altair_chart(chart, width="stretch")
    if detail:
        with st.expander(f"{detail_label} ({len(detail)})"):
            st.dataframe(detail, hide_index=True, width="stretch")


def _energy_display(value: float | None, unit: str | None) -> tuple[float | None, str | None]:
    """Scale watt-hours to kilowatt-hours for the device-style readouts."""
    if value is None:
        return None, unit
    if unit == "Wh":
        return value / 1000, "kWh"
    return value, unit


def _format_energy(value: float | None, unit: str | None) -> str:
    """Format a scaled energy value with enough precision for small totals."""
    if value is None:
        return "Unavailable"
    digits = 2 if abs(value) >= 1 else 3
    rendered = f"{value:,.{digits}f}"
    return f"{rendered} {unit}" if unit else rendered


def _power_kw(latest: ObservationProjection | None) -> float | None:
    """Average power across the latest stored interval, in kilowatts."""
    if latest is None or latest.interval_value_number is None:
        return None
    seconds = latest.interval_seconds
    if not seconds:
        return None
    per_second = latest.interval_value_number / seconds
    if latest.unit == "Wh":
        return per_second * 3.6
    if latest.unit == "kWh":
        return per_second * 3600
    return None


def _period_window(
    period: str,
    day: date,
    timezone: ZoneInfo,
) -> tuple[datetime, datetime, int, str]:
    """Return the local window, bucket width, and axis format for a period."""
    start_of_day = datetime.combine(day, time.min, tzinfo=timezone)
    if period == "Week":
        start = start_of_day - timedelta(days=6)
        return start, start_of_day + timedelta(days=1), 86400, "%a %d"
    if period == "Month":
        start = start_of_day.replace(day=1)
        end_month = (start + timedelta(days=31)).replace(day=1)
        return start, end_month, 86400, "%d"
    return start_of_day, start_of_day + timedelta(days=1), 3600, "%H:%M"


def _shift_period(period: str, day: date, direction: int) -> date:
    if period == "Week":
        return day + timedelta(days=7 * direction)
    if period == "Month":
        anchor = day.replace(day=1)
        moved = anchor - timedelta(days=1) if direction < 0 else anchor + timedelta(days=31)
        return moved.replace(day=1)
    return day + timedelta(days=direction)


def _render_device_view_tab(
    service: DashboardService,
    config: DashboardConfig,
    *,
    now: datetime,
) -> None:
    st.subheader("Device view")
    st.caption(
        "A device-app style summary built only from stored telemetry. Totals come "
        "from stored intervals, so slots without a stored value stay empty."
    )
    today = now.astimezone(config.timezone).date()
    period = (
        st.segmented_control(
            "Period",
            ("Day", "Week", "Month"),
            default="Day",
            key="device_period",
            label_visibility="collapsed",
        )
        or "Day"
    )
    if "device_day" not in st.session_state:
        st.session_state["device_day"] = today

    back, label_column, forward = st.columns([1, 6, 1], vertical_alignment="center")
    with back:
        if st.button("Earlier period", width="stretch", icon=":material/chevron_left:"):
            st.session_state["device_day"] = _shift_period(
                period, st.session_state["device_day"], -1
            )
    with forward:
        at_latest = st.session_state["device_day"] >= today
        if st.button(
            "Later period",
            width="stretch",
            icon=":material/chevron_right:",
            disabled=at_latest,
        ):
            st.session_state["device_day"] = min(
                today, _shift_period(period, st.session_state["device_day"], 1)
            )
    day = min(st.session_state["device_day"], today)
    since_local, until_local, bucket_seconds, axis_format = _period_window(
        period, day, config.timezone
    )
    with label_column:
        st.markdown(
            f"<div style='text-align:center;font-size:1.15rem;font-weight:600'>"
            f"{_period_label(period, since_local, until_local)}</div>",
            unsafe_allow_html=True,
        )

    until_local = min(until_local, now.astimezone(config.timezone))
    observations, _ = service.load_range(
        since_local.astimezone(UTC), until_local.astimezone(UTC), now=now
    )
    latest = observations[-1] if observations else None
    unit = latest.unit if latest else None

    power = _power_kw(latest)
    measured = sum(
        item.interval_value_number
        for item in observations
        if item.interval_value_number is not None
    )
    total, total_unit = _energy_display(measured, unit)
    counter, counter_unit = _energy_display(
        latest.raw_daily_total_number if latest else None, unit
    )

    with st.container(border=True):
        power_row, total_row = st.columns(2, vertical_alignment="center")
        with power_row:
            observed = (
                latest.observed_at.astimezone(config.timezone).strftime("%I:%M %p").lstrip("0")
                if latest and latest.observed_at
                else "Unavailable"
            )
            st.metric(
                f"Power over the latest stored interval · {observed}",
                _format_energy(power, "kW"),
                help=(
                    "Average power across the newest stored interval in this period: "
                    "interval energy divided by interval duration."
                ),
            )
        with total_row:
            st.metric(
                f"Measured usage this {period.lower()}",
                _format_energy(total, total_unit),
                help="Sum of stored non-null interval values inside this period.",
            )
        if period == "Day" and counter is not None:
            st.caption(
                "Device daily counter at the latest sample: "
                + _format_energy(counter, counter_unit)
            )

    if not observations:
        st.info(
            "No stored observations in this period.",
            icon=":material/info:",
        )
        return

    buckets = bucket_series(
        observations,
        timezone=config.timezone,
        bucket_seconds=bucket_seconds,
        since=since_local,
        until=until_local,
        cadence_seconds=config.refresh_seconds,
    )
    rows = bucket_rows(buckets)
    scaled = [
        {**row, "total": _energy_display(row["total"], unit)[0]} for row in rows
    ]
    with st.container(border=True):
        st.altair_chart(
            energy_bar_chart(
                scaled,
                timezone_name=config.timezone_name,
                unit=total_unit,
                palette=_active_palette(),
                axis_format=axis_format,
                time_format="%b %d %H:%M" if bucket_seconds < 86400 else "%b %d",
            ),
            width="stretch",
        )
    peak = max(
        (bucket for bucket in buckets if bucket.total is not None),
        key=lambda bucket: bucket.total,
        default=None,
    )
    if peak is not None:
        peak_value, peak_unit = _energy_display(peak.total, unit)
        window = (
            f"{peak.start.strftime('%I:%M %p').lstrip('0')}–"
            f"{peak.end.strftime('%I:%M %p').lstrip('0')}"
            if bucket_seconds < 86400
            else peak.start.strftime("%a %b %d")
        )
        st.caption(f"Highest slot: {window} · {_format_energy(peak_value, peak_unit)}")
    st.caption(
        "Bars cover only elapsed time in this period. A slot with no stored value is "
        "drawn as a dashed marker instead of a zero-height bar."
    )


def _period_label(period: str, since: datetime, until: datetime) -> str:
    if period == "Day":
        return since.strftime("%a, %b %d, %Y")
    if period == "Week":
        return f"{since.strftime('%b %d')} – {(until - timedelta(days=1)).strftime('%b %d, %Y')}"
    return since.strftime("%B %Y")


def _render_observations_tab(
    observations: list[ObservationProjection],
    service: DashboardService,
    config: DashboardConfig,
    *,
    now: datetime,
) -> None:
    st.subheader("Explore observations")
    st.caption(
        "Filter for unusual samples, then choose one below for a friendly summary or "
        "technical details."
    )
    row_filter = st.radio(
        "Show rows",
        ("All", "Anomalies"),
        horizontal=True,
        help="Anomalies include non-normal interval statuses and quality flags.",
    )
    visible = list(reversed(observations))
    if row_filter == "Anomalies":
        visible = [item for item in visible if is_anomalous(item)]
    table = [
        {
            "Observed at": (
                item.observed_at.astimezone(config.timezone)
                if item.observed_at is not None
                else None
            ),
            "Interval use": item.interval_value_number,
            "Status": item.interval_status,
            "Quality flags": ", ".join(item.flags) or "—",
            "Energy source": _source_label(item.energy_ok, item.energy_failure_class),
            "State source": _source_label(item.state_ok, item.state_failure_class),
            "Daily counter": item.raw_daily_total_number,
            "Sample ID": item.sample_id,
        }
        for item in visible
    ]
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "Observed at": st.column_config.DatetimeColumn(
                format="YYYY-MM-DD HH:mm:ss", width="medium"
            ),
            "Interval use": st.column_config.NumberColumn(format="%.3f"),
            "Daily counter": st.column_config.NumberColumn(format="%.3f"),
            "Status": st.column_config.TextColumn(width="medium"),
            "Sample ID": st.column_config.TextColumn(width="medium"),
        },
    )

    if not visible:
        st.caption("No rows match the current filter.")
        return

    by_id = {item.sample_id: item for item in visible}
    selected_id = st.selectbox(
        "Inspect one observation",
        list(by_id),
        key="selected_sample_id",
        format_func=lambda sample_id: (
            f"{_format_instant(by_id[sample_id].observed_at, config)} · "
            f"{by_id[sample_id].interval_status or 'Unavailable'}"
        ),
        help="Choose an observation to see its status before opening technical data.",
    )
    selected = by_id[selected_id]
    with st.container(border=True):
        with st.container(horizontal=True):
            st.metric(
                "Observed",
                _format_instant(selected.observed_at, config),
                icon=":material/event:",
            )
            st.metric(
                "Interval use",
                _format_number(selected.interval_value_number, selected.unit),
                icon=":material/bolt:",
            )
            st.metric(
                "Status",
                selected.interval_status or "Unavailable",
                icon=":material/verified:",
            )
        st.caption(f"Sample ID: {selected.sample_id}")
        with st.expander("Normalized technical fields"):
            st.json(scrub_object(selected.to_json_value()), expanded=False)

    raw_key = f"raw_observation_{selected_id}"
    with st.container(border=True):
        st.markdown("**Raw payload**")
        st.caption(
            "Raw data is optional and may be verbose. It is fetched only on request "
            "and is not saved in the dashboard cache."
        )
        if st.button("Load raw payload", key=f"load_{selected_id}"):
            st.session_state[raw_key] = service.raw_observation(selected_id, now=now)
        if raw_key in st.session_state:
            st.caption(
                "Raw stored payload (loaded on demand; not persisted in dashboard cache)"
            )
            st.json(scrub_object(st.session_state[raw_key]))


def _render_legend() -> None:
    with st.container(border=True):
        st.markdown("#### Legend & quick tips")
        st.caption("A quick reference for the labels and controls used on this page.")
        legend, hints = st.columns(2)
        with legend:
            st.markdown(
                """
**Status legend**

- **NORMAL** — a measured interval with no known quality issue.
- **ANOMALY** — a stored status or quality flag needs attention.
- **UNAVAILABLE / GAP** — no usable interval value was stored; it is not zero.
- **STALE / FAILED** — collection or refresh is late or has reported an error.
"""
            )
        with hints:
            st.markdown(
                """
**Quick tips**

- **History window:** start with 24 hours; expand only when you need more context.
- **Coverage:** usable stored intervals divided by intervals expected for the window.
- **Refresh now:** checks Firestore incrementally; it does not reload all history.
- **Anomalies:** filter the table to find gaps and unusual samples quickly.
- **Raw payload:** loaded from Firestore only after you explicitly request it.
"""
            )


def _render_system_details(
    overview: Overview,
    latest: ObservationProjection | None,
    config: DashboardConfig,
) -> None:
    st.subheader("Collector & device details")
    st.caption(
        "Technical context for troubleshooting. Most day-to-day checks can stop at "
        "the summary above."
    )
    timing, sources, device = st.columns(3, border=True)
    with timing:
        st.markdown("**Collector timing**")
        st.write(f"Last attempt: {_format_instant(overview.last_attempt_at, config)}")
        st.write(f"Last success: {_format_instant(overview.last_success_at, config)}")
        st.write(f"Pending reconciliation: {overview.pending_reconciliations}")
    with sources:
        st.markdown("**Source checks**")
        st.write(
            "Energy: "
            + _source_label(
                latest.energy_ok if latest else None,
                latest.energy_failure_class if latest else None,
            )
        )
        st.write(
            "State: "
            + _source_label(
                latest.state_ok if latest else None,
                latest.state_failure_class if latest else None,
            )
        )
        duration = latest.interval_seconds if latest else None
        st.write(
            f"Interval duration: {duration:.0f}s"
            if duration is not None
            else "Interval duration: Unavailable"
        )
    with device:
        st.markdown("**Latest device state**")
        if latest and latest.principal_state:
            for key, value in latest.principal_state.items():
                st.write(f"{key}: {value}")
        else:
            st.write("Unavailable")


def _render_cache_controls(service: DashboardService, cache_path: Path) -> None:
    with st.container(border=True):
        st.markdown("**Local cache**")
        st.caption(
            "The cache reduces Firestore reads. Clearing it is safe, but the next view "
            "must download its selected history again."
        )
        st.caption(f"Local cache: {cache_path}")
        confirmed = st.checkbox(
            "I understand this clears only the local dashboard cache",
            key="confirm_cache_reset",
        )
        if st.button("Clear local cache", disabled=not confirmed, type="secondary"):
            service.clear_cache()
            st.session_state.pop("confirm_cache_reset", None)
            for key in list(st.session_state):
                if str(key).startswith("raw_observation_"):
                    st.session_state.pop(key, None)
            st.rerun()


def render_dashboard(
    service: DashboardService,
    config: DashboardConfig,
    *,
    now: datetime | None = None,
    recovered_cache: Path | None = None,
) -> None:
    current = now or datetime.now(UTC)
    st.html(PAGE_STYLES)

    # The header reports state that is only known after loading, so reserve its
    # place above the controls and fill it in once the range has been read.
    header = st.container()
    range_label, manual_refresh = _render_controls()

    days = RANGE_OPTIONS[range_label]
    since = current - timedelta(days=days)
    observations, refresh = service.load_range(
        since,
        current,
        now=current,
        force_refresh=manual_refresh,
    )
    state = service.state()
    latest = service.latest()
    overview = build_overview(
        latest,
        state,
        now=current,
        cadence_seconds=config.refresh_seconds,
    )

    with header:
        _render_header(config, overview, refresh)
        if recovered_cache is not None:
            st.warning(
                f"A corrupt local cache was moved to {recovered_cache}; a clean cache "
                "is active.",
                icon=":material/build:",
            )

    _render_banners(overview, refresh, latest, observations)
    _render_glance(overview, latest, observations)

    energy_tab, device_tab, table_tab, diagnostics_tab = st.tabs(
        ["Energy over time", "Device view", "Observations", "Diagnostics & help"]
    )
    with energy_tab:
        _render_energy_tab(observations, config, latest, since=since, until=current)
    with device_tab:
        _render_device_view_tab(service, config, now=current)
    with table_tab:
        _render_observations_tab(observations, service, config, now=current)
    with diagnostics_tab:
        _render_legend()
        _render_system_details(overview, latest, config)
        _render_cache_controls(service, config.cache_path)


def main() -> None:
    st.set_page_config(
        page_title="Airchive",
        page_icon="❄️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    load_dashboard_dotenv()
    try:
        config = load_dashboard_config()
    except ConfigError as exc:
        st.title("Airchive")
        st.error(str(exc))
        st.info("Set FIREBASE_PROJECT_ID and LG_DEVICE_ID, then restart the dashboard.")
        return

    runtime = build_runtime(
        config.project_id,
        config.device_id,
        str(config.cache_path),
        config.refresh_seconds,
    )

    @st.fragment(run_every=timedelta(seconds=config.refresh_seconds))
    def dashboard_fragment() -> None:
        render_dashboard(
            runtime.service,
            config,
            recovered_cache=runtime.recovered_cache,
        )

    dashboard_fragment()


if __name__ == "__main__":
    main()
