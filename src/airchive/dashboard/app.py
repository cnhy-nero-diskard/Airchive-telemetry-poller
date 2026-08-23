"""Streamlit application for local, read-only telemetry inspection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from airchive.config import ConfigError
from airchive.dashboard.cache import DashboardCache
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
from airchive.dashboard.service import DashboardService
from airchive.redaction import scrub_object
from airchive.storage.client import build_client

RANGE_OPTIONS = {"24 hours": 1, "7 days": 7, "30 days": 30}


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


def _render_legend_and_hints() -> None:
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
    with st.expander("Collector & device details"):
        st.caption(
            "Technical context for troubleshooting. Most day-to-day checks can stop at "
            "the summary above."
        )
        details = st.columns(3)
        with details[0]:
            st.markdown("**Collector timing**")
            st.write(f"Last attempt: {_format_instant(overview.last_attempt_at, config)}")
            st.write(f"Last success: {_format_instant(overview.last_success_at, config)}")
            st.write(f"Pending reconciliation: {overview.pending_reconciliations}")
        with details[1]:
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
        with details[2]:
            st.markdown("**Latest device state**")
            if latest and latest.principal_state:
                for key, value in latest.principal_state.items():
                    st.write(f"{key}: {value}")
            else:
                st.write("Unavailable")


def _render_cache_controls(service: DashboardService, cache_path: Path) -> None:
    with st.expander("Advanced: local cache"):
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

    st.title("Airchive")
    st.caption(
        f"A read-only view of device {config.device_id} · Times shown in "
        f"{config.timezone_name}"
    )

    if recovered_cache is not None:
        st.warning(
            f"A corrupt local cache was moved to {recovered_cache}; a clean cache is active."
        )

    with st.container(border=True):
        range_column, refresh_column = st.columns([4, 1])
        with range_column:
            range_label = st.selectbox(
                "History window",
                tuple(RANGE_OPTIONS),
                index=0,
                help=(
                    "Controls the chart and observation table. Start with 24 hours to "
                    "keep the view focused."
                ),
            )
            st.caption(
                "Changing the window reuses locally cached history whenever possible."
            )
        with refresh_column:
            st.write("")
            manual_refresh = st.button("Refresh now", type="primary", width="stretch")
            st.caption("Incremental and read-only")

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

    st.subheader("At a glance")
    st.caption("Start here: current health, latest usage, and data quality.")

    if not refresh.succeeded:
        message = f"Firestore refresh failed ({refresh.error_class or 'unknown error'})."
        if observations:
            st.warning(f"{message} Showing the last valid cached data.")
        else:
            st.error(f"{message} No cached telemetry is available yet.")
    elif overview.refresh_error_class:
        st.warning(
            f"The previous refresh failed ({overview.refresh_error_class}); "
            "the latest retry succeeded."
        )

    if overview.stale:
        st.warning(
            f"Collection is stale: the latest stored observation is "
            f"{_format_age(overview.latest_age_seconds)}."
        )
    if overview.consecutive_failures:
        failure = overview.last_error_class or "unknown failure"
        detail = (
            f" — {overview.last_error_message}" if overview.last_error_message else ""
        )
        st.error(
            f"Collector has {overview.consecutive_failures} consecutive failure(s): "
            f"{failure}{detail}"
        )
    elif not overview.stale and latest is not None and refresh.succeeded:
        st.success(
            f"Collector looks healthy. Latest sample arrived "
            f"{_format_age(overview.latest_age_seconds)}."
        )
    elif latest is None and refresh.succeeded:
        st.info("No stored observations yet. The dashboard will update after collection starts.")

    st.caption(
        f"Last successful Firestore sync: {_format_instant(overview.last_sync_at, config)}"
    )

    latest_energy = latest.interval_value_number if latest else None
    latest_unit = latest.unit if latest else None
    raw_total = latest.raw_daily_total_number if latest else None
    status = latest.interval_status if latest and latest.interval_status else "Unavailable"
    metrics = st.columns(4)
    metrics[0].metric(
        "Latest sample age",
        _format_age(overview.latest_age_seconds),
        help="How long ago the newest stored observation was collected.",
    )
    metrics[1].metric(
        "Latest interval use",
        _format_number(latest_energy, latest_unit),
        help="Energy used between the two most recent usable samples.",
    )
    metrics[2].metric(
        "Today's device counter",
        _format_number(raw_total, latest_unit),
        help="The raw cumulative daily counter reported by the device.",
    )
    metrics[3].metric(
        "Data quality",
        status,
        help="NORMAL is usable. Other statuses are explained in the legend below.",
    )

    _render_system_details(overview, latest, config)

    st.divider()
    st.subheader("Energy over time")
    st.caption(
        "Each plotted point is stored interval usage. Missing values stay as visible "
        "gaps instead of being shown as zero."
    )
    summary = summarize_range(
        observations,
        since=since,
        until=current,
        cadence_seconds=config.refresh_seconds,
    )
    summary_columns = st.columns(3)
    summary_columns[0].metric(
        "Measured interval total",
        _format_number(summary.total, latest_unit),
        help="Sum of non-null stored interval values; missing intervals are excluded.",
    )
    summary_columns[1].metric(
        "Usable coverage",
        summary.coverage_label,
        help="Usable stored intervals divided by intervals expected in this window.",
    )
    summary_columns[2].metric(
        "Samples needing attention",
        summary.anomaly_count,
        help="Observations with a non-normal status or a quality flag.",
    )
    if not summary.complete:
        st.warning(
            "This range is incomplete. The total includes only stored non-null intervals; "
            "gaps and unresolved values are excluded, not counted as zero."
        )

    _render_legend_and_hints()

    rows = chart_rows(observations, config.timezone)
    if rows:
        chart_frame = pd.DataFrame(rows)
        st.line_chart(
            chart_frame,
            x="observedAt",
            y="intervalValue",
            x_label=f"Observed at ({config.timezone_name})",
            y_label=latest_unit or "Stored interval value",
        )
        non_normal = [
            row
            for row in rows
            if row["intervalStatus"] != "NORMAL" or row["anomalous"]
        ]
        if non_normal:
            st.caption("Samples behind the chart's gaps and non-normal markers")
            st.dataframe(non_normal, hide_index=True, width="stretch")
    else:
        st.info("No observations are available in this range.")

    st.divider()
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
            "Observed at": _format_instant(item.observed_at, config),
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
    st.dataframe(table, hide_index=True, width="stretch")

    if visible:
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
            selected_columns = st.columns(3)
            selected_columns[0].metric(
                "Observed",
                _format_instant(selected.observed_at, config),
            )
            selected_columns[1].metric(
                "Interval use",
                _format_number(selected.interval_value_number, selected.unit),
            )
            selected_columns[2].metric(
                "Status",
                selected.interval_status or "Unavailable",
            )
            st.caption(f"Sample ID: {selected.sample_id}")
            with st.expander("Normalized technical fields"):
                st.json(scrub_object(selected.to_json_value()), expanded=False)
        raw_key = f"raw_observation_{selected_id}"
        if st.button("Load raw payload", key=f"load_{selected_id}"):
            st.session_state[raw_key] = service.raw_observation(selected_id, now=current)
        st.caption(
            "Raw data is optional and may be verbose. It is fetched only on request and "
            "is not saved in the dashboard cache."
        )
        if raw_key in st.session_state:
            st.caption(
                "Raw stored payload (loaded on demand; not persisted in dashboard cache)"
            )
            st.json(scrub_object(st.session_state[raw_key]))
    else:
        st.caption("No rows match the current filter.")

    _render_cache_controls(service, config.cache_path)


def main() -> None:
    st.set_page_config(page_title="Airchive", page_icon="❄️", layout="wide")
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
