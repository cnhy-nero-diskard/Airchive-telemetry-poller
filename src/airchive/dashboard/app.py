"""Streamlit application for local, read-only telemetry inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import streamlit as st

from airchive.config import ConfigError
from airchive.dashboard.cache import DashboardCache
from airchive.dashboard.charts import energy_chart
from airchive.dashboard.config import (
    DashboardConfig,
    load_dashboard_config,
    load_dashboard_dotenv,
)
from airchive.dashboard.models import ObservationProjection
from airchive.dashboard.presentation import (
    Overview,
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


def _render_glance(
    overview: Overview,
    latest: ObservationProjection | None,
    observations: list[ObservationProjection],
) -> None:
    st.subheader("At a glance")
    st.caption("Start here: current health, latest usage, and data quality.")

    unit = latest.unit if latest else None
    status = latest.interval_status if latest and latest.interval_status else "Unavailable"
    with st.container(horizontal=True):
        st.metric(
            "Latest sample age",
            _format_age(overview.latest_age_seconds),
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/schedule:",
            help="How long ago the newest stored observation was collected.",
        )
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
        st.metric(
            "Today's device counter",
            _format_number(latest.raw_daily_total_number if latest else None, unit),
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/speed:",
            help="The raw cumulative daily counter reported by the device.",
        )
        st.metric(
            "Data quality",
            status,
            border=True,
            height=KPI_CARD_HEIGHT,
            icon=":material/verified:",
            help="NORMAL is usable. Other statuses are explained in the legend below.",
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

    rows = chart_rows(observations, config.timezone)
    if not rows:
        st.info("No observations are available in this range.", icon=":material/info:")
        return

    with st.container(border=True):
        st.altair_chart(
            energy_chart(
                rows,
                timezone_name=config.timezone_name,
                unit=unit,
                palette=_active_palette(),
            ),
            width="stretch",
        )
    non_normal = [
        row for row in rows if row["intervalStatus"] != "NORMAL" or row["anomalous"]
    ]
    if non_normal:
        label = "Samples behind the chart's gaps and non-normal markers"
        with st.expander(f"{label} ({len(non_normal)})"):
            st.dataframe(non_normal, hide_index=True, width="stretch")


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

    energy_tab, table_tab, diagnostics_tab = st.tabs(
        ["Energy over time", "Observations", "Diagnostics & help"]
    )
    with energy_tab:
        _render_energy_tab(observations, config, latest, since=since, until=current)
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
