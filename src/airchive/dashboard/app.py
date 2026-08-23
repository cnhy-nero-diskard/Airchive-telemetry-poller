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
from airchive.dashboard.presentation import (
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


def _render_cache_controls(service: DashboardService, cache_path: Path) -> None:
    with st.expander("Cache controls"):
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

    header, refresh_column = st.columns([5, 1])
    with header:
        st.title("Airchive")
        st.caption(
            f"Local read-only telemetry · {config.timezone_name} · device {config.device_id}"
        )
    with refresh_column:
        manual_refresh = st.button("Refresh now", type="primary", width="stretch")

    if recovered_cache is not None:
        st.warning(
            f"A corrupt local cache was moved to {recovered_cache}; a clean cache is active."
        )

    range_label = st.selectbox("Time range", tuple(RANGE_OPTIONS), index=0)
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
        detail = f" — {overview.last_error_message}" if overview.last_error_message else ""
        st.error(
            f"Collector has {overview.consecutive_failures} consecutive failure(s): "
            f"{failure}{detail}"
        )

    st.caption(
        f"Last successful Firestore sync: {_format_instant(overview.last_sync_at, config)}"
    )

    latest_energy = latest.interval_value_number if latest else None
    latest_unit = latest.unit if latest else None
    raw_total = latest.raw_daily_total_number if latest else None
    status = latest.interval_status if latest and latest.interval_status else "Unavailable"
    metrics = st.columns(4)
    metrics[0].metric("Latest observation", _format_age(overview.latest_age_seconds))
    metrics[1].metric("Latest interval", _format_number(latest_energy, latest_unit))
    metrics[2].metric("Daily counter", _format_number(raw_total, latest_unit))
    metrics[3].metric("Interval status", status)

    details = st.columns(3)
    with details[0]:
        st.subheader("Collector")
        st.write(f"Last attempt: {_format_instant(overview.last_attempt_at, config)}")
        st.write(f"Last success: {_format_instant(overview.last_success_at, config)}")
        st.write(f"Pending reconciliation: {overview.pending_reconciliations}")
    with details[1]:
        st.subheader("Sources")
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
        st.subheader("Latest device state")
        if latest and latest.principal_state:
            for key, value in latest.principal_state.items():
                st.write(f"{key}: {value}")
        else:
            st.write("Unavailable")

    st.divider()
    st.subheader("Interval consumption")
    summary = summarize_range(
        observations,
        since=since,
        until=current,
        cadence_seconds=config.refresh_seconds,
    )
    summary_columns = st.columns(3)
    summary_columns[0].metric(
        "Stored interval total",
        _format_number(summary.total, latest_unit),
        help="Sum of non-null stored interval values; missing intervals are never treated as zero.",
    )
    summary_columns[1].metric("Coverage", summary.coverage_label)
    summary_columns[2].metric("Anomalies", summary.anomaly_count)
    if not summary.complete:
        st.warning(
            "This range is incomplete. The total includes only stored non-null intervals; "
            "gaps and unresolved values are excluded, not counted as zero."
        )

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
            st.caption("Gap and non-normal markers")
            st.dataframe(non_normal, hide_index=True, width="stretch")
    else:
        st.info("No observations are available in this range.")

    st.divider()
    st.subheader("Stored observations")
    row_filter = st.radio("Rows", ("All", "Anomalies"), horizontal=True)
    visible = list(reversed(observations))
    if row_filter == "Anomalies":
        visible = [item for item in visible if is_anomalous(item)]
    table = [
        {
            "sampleId": item.sample_id,
            "observedAt": _format_instant(item.observed_at, config),
            "raw": item.raw_daily_total_number,
            "interval": item.interval_value_number,
            "status": item.interval_status,
            "flags": ", ".join(item.flags),
            "energy": _source_label(item.energy_ok, item.energy_failure_class),
            "state": _source_label(item.state_ok, item.state_failure_class),
        }
        for item in visible
    ]
    st.dataframe(table, hide_index=True, width="stretch")

    if visible:
        selected_id = st.selectbox(
            "Observation details",
            [item.sample_id for item in visible],
            key="selected_sample_id",
        )
        selected = next(item for item in visible if item.sample_id == selected_id)
        st.json(scrub_object(selected.to_json_value()), expanded=False)
        raw_key = f"raw_observation_{selected_id}"
        if st.button("Load raw payload", key=f"load_{selected_id}"):
            st.session_state[raw_key] = service.raw_observation(selected_id, now=current)
        if raw_key in st.session_state:
            st.caption("Raw stored payload (loaded on demand; not persisted in dashboard cache)")
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
