"""Streamlit-level behavior for the local telemetry dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from streamlit.testing.v1 import AppTest

from airchive.dashboard.cache import SyncState
from airchive.dashboard.config import DashboardConfig
from airchive.dashboard.models import ObservationProjection
from airchive.dashboard.service import RefreshResult
from airchive.redaction import clear_secrets, register_secret

SENTINEL = "SENTINEL-BROWSER-SECRET-5f6c17a1"


def dashboard_script(service, config, now):
    from airchive.dashboard.app import render_dashboard

    render_dashboard(service, config, now=now)


def instant(minute: int) -> datetime:
    return datetime(2026, 8, 24, 1, minute, tzinfo=UTC)


def observation(
    minute: int,
    *,
    interval: float | None = 1.0,
    status: str = "NORMAL",
    flags: list[str] | None = None,
    energy_ok: bool = True,
    state_ok: bool = True,
) -> ObservationProjection:
    at = instant(minute)
    value = ObservationProjection.from_document(
        {
            "sampleId": at.strftime("%Y%m%dT%H%M%SZ"),
            "scheduledAt": at,
            "observedAt": at,
            "persistedAt": at,
            "localDate": "2026-08-24",
            "timezone": "Asia/Manila",
            "completeness": int(energy_ok) * 2 + int(state_ok),
            "energy": {
                "rawDailyTotal": str(minute),
                "rawDailyTotalNumber": float(minute),
                "unit": "Wh",
                "intervalValue": str(interval) if interval is not None else None,
                "intervalValueNumber": interval,
                "intervalSeconds": 300,
            },
            "quality": {"intervalStatus": status, "flags": flags or []},
            "source": {
                "energy": {
                    "ok": energy_ok,
                    "failureClass": None if energy_ok else "DEVICE_OFFLINE",
                },
                "state": {
                    "ok": state_ok,
                    "failureClass": None if state_ok else "DEVICE_OFFLINE",
                },
            },
            "state": {
                "operation": {"airConOperationMode": "POWER_ON"},
                "airConJobMode": {"currentJobMode": "COOL"},
                "temperature": {"targetTemperature": 25, "unit": "C"},
            },
        },
        storage_path=f"devices/device-1/telemetry/sample-{minute}",
    )
    assert value is not None
    return value


class UiService:
    def __init__(
        self,
        observations: list[ObservationProjection],
        *,
        state: SyncState | None = None,
        refresh: RefreshResult | None = None,
        raw=None,
    ):
        self.observations = observations
        self._state = state or SyncState(
            watermark=instant(2),
            last_success_at=instant(2),
            last_attempt_at=instant(2),
            health={
                "lastAttemptAt": instant(2).isoformat(),
                "lastSuccessAt": instant(2).isoformat(),
                "consecutiveFailures": 0,
            },
            reconciliation={"pending": {}},
        )
        self.refresh_result = refresh or RefreshResult(performed=False, succeeded=True)
        self.raw = raw if raw is not None else {"raw": {"state": "loaded"}}
        self.raw_calls = 0
        self.clear_calls = 0
        self.load_calls = []

    def load_range(self, since, until, *, now, force_refresh=False):
        self.load_calls.append((since, until, now, force_refresh))
        return list(self.observations), self.refresh_result

    def state(self):
        return self._state

    def latest(self):
        return self.observations[-1] if self.observations else None

    def raw_observation(self, sample_id, *, now=None):
        self.raw_calls += 1
        return self.raw

    def clear_cache(self):
        self.clear_calls += 1
        self.observations = []


def config(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        project_id="project-1",
        device_id="device-1",
        timezone=ZoneInfo("Asia/Manila"),
        timezone_name="Asia/Manila",
        cache_path=tmp_path / "dashboard.sqlite3",
        refresh_seconds=300,
    )


def run_app(service: UiService, dashboard_config: DashboardConfig, now: datetime):
    return AppTest.from_function(
        dashboard_script,
        args=(service, dashboard_config, now),
        default_timeout=10,
    ).run()


def all_visible_text(app) -> str:
    values = []
    for element_type in (
        "caption",
        "error",
        "info",
        "json",
        "markdown",
        "metric",
        "subheader",
        "success",
        "title",
        "warning",
    ):
        for element in app.get(element_type):
            label = getattr(element, "label", None)
            if label:
                values.append(str(label))
            values.append(str(getattr(element, "value", element)))
    return "\n".join(values)


def test_healthy_dashboard_renders_overview_chart_table_and_timezone(tmp_path):
    service = UiService([observation(0), observation(1)])
    app = run_app(service, config(tmp_path), instant(2))

    assert not app.exception
    text = all_visible_text(app)
    assert "Airchive" in text
    assert "Asia/Manila" in text
    assert "Latest interval" in text
    assert "POWER_ON" in text
    assert app.get("vega_lite_chart")
    assert len(app.dataframe) >= 1
    assert service.raw_calls == 0


def test_dashboard_explains_statuses_and_common_actions(tmp_path):
    service = UiService([observation(0), observation(1)])
    app = run_app(service, config(tmp_path), instant(2))

    assert not app.exception
    text = all_visible_text(app)
    assert "Start here" in text
    assert "Legend & quick tips" in text
    assert "NORMAL" in text
    assert "UNAVAILABLE / GAP" in text
    assert "Coverage" in text
    assert "Refresh now" in text
    assert "Anomalies" in text
    assert "Raw payload" in text
    assert "Incremental and read-only" in text


def test_stale_failing_partial_and_empty_states_are_explicit(tmp_path):
    failing_state = SyncState(
        last_success_at=instant(0),
        last_attempt_at=instant(0),
        last_error_class="RuntimeError",
        health={
            "lastAttemptAt": instant(0).isoformat(),
            "lastSuccessAt": instant(0).isoformat(),
            "consecutiveFailures": 2,
            "lastErrorClass": "AUTH_FATAL",
            "lastErrorMessage": "invalid token",
        },
        reconciliation={"pending": {"rollover": {}}},
    )
    partial = UiService(
        [
            observation(
                0,
                interval=None,
                status="ENERGY_UNAVAILABLE",
                flags=["DEVICE_OFFLINE"],
                energy_ok=False,
                state_ok=False,
            )
        ],
        state=failing_state,
        refresh=RefreshResult(performed=True, succeeded=False, error_class="RuntimeError"),
    )
    app = run_app(partial, config(tmp_path), instant(20))
    text = all_visible_text(app)

    assert "Showing the last valid cached data" in text
    assert "Collection is stale" in text
    assert "2 consecutive failure" in text
    assert "This range is incomplete" in text
    assert "ENERGY_UNAVAILABLE" in text

    empty = UiService(
        [],
        refresh=RefreshResult(performed=True, succeeded=False, error_class="Unavailable"),
    )
    empty_app = run_app(empty, config(tmp_path), instant(2))
    empty_text = all_visible_text(empty_app)
    assert "No cached telemetry is available yet" in empty_text
    assert "No observations are available" in empty_text
    assert "Unavailable" in empty_text


def test_null_interval_is_not_rendered_as_measured_zero(tmp_path):
    service = UiService([observation(0), observation(1, interval=None)])
    app = run_app(service, config(tmp_path), instant(2))

    assert not app.exception
    text = all_visible_text(app)
    assert "1/288 usable intervals" in text
    assert "excluded, not counted as zero" in text
    assert app.get("vega_lite_chart")


def test_anomaly_filter_and_raw_loading_are_explicit(tmp_path):
    service = UiService(
        [
            observation(0),
            observation(1, interval=None, status="ENERGY_UNAVAILABLE"),
        ]
    )
    app = run_app(service, config(tmp_path), instant(2))
    assert service.raw_calls == 0

    app.radio[0].set_value("Anomalies").run()
    assert not app.exception
    assert "ENERGY_UNAVAILABLE" in all_visible_text(app)
    assert service.raw_calls == 0

    raw_button = next(button for button in app.button if button.label == "Load raw payload")
    raw_button.click().run()
    assert service.raw_calls == 1
    assert "loaded" in all_visible_text(app)


def test_manual_refresh_and_confirmation_gated_cache_reset(tmp_path):
    service = UiService([observation(0)])
    app = run_app(service, config(tmp_path), instant(2))

    refresh = next(button for button in app.button if button.label == "Refresh now")
    refresh.click().run()
    assert service.load_calls[-1][3] is True

    reset = next(button for button in app.button if button.label == "Clear local cache")
    assert reset.disabled
    app.checkbox[0].check().run()
    reset = next(button for button in app.button if button.label == "Clear local cache")
    assert not reset.disabled
    reset.click().run()
    assert service.clear_calls == 1


def test_browser_visible_output_scrubs_registered_secrets(tmp_path, monkeypatch):
    register_secret(SENTINEL)
    monkeypatch.setenv("LG_THINQ_PAT", SENTINEL)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", f"C:/{SENTINEL}/key.json")
    try:
        service = UiService(
            [observation(0)], raw={"raw": {"state": f"contains {SENTINEL}"}}
        )
        app = run_app(service, config(tmp_path), instant(2))
        raw_button = next(button for button in app.button if button.label == "Load raw payload")
        raw_button.click().run()
        text = all_visible_text(app)
        assert SENTINEL not in text
        assert "Authorization" not in text
        assert "<redacted>" in text
    finally:
        clear_secrets()


def test_status_badge_and_grouped_sections_stay_visible(tmp_path):
    service = UiService([observation(0), observation(1)])
    app = run_app(service, config(tmp_path), instant(2))
    text = all_visible_text(app)

    assert "Healthy" in text
    assert "At a glance" in text
    assert "Energy over time" in text
    assert "Explore observations" in text
    assert "Collector & device details" in text
    assert "Local cache" in text


def test_status_badge_reports_stale_and_failing_collectors(tmp_path):
    stale = UiService([observation(0)])
    assert "Stale data" in all_visible_text(run_app(stale, config(tmp_path), instant(30)))

    failing = UiService(
        [observation(0)],
        refresh=RefreshResult(performed=True, succeeded=False, error_class="RuntimeError"),
    )
    assert "Needs attention" in all_visible_text(
        run_app(failing, config(tmp_path), instant(2))
    )

    empty = UiService([])
    assert "Waiting for data" in all_visible_text(run_app(empty, config(tmp_path), instant(2)))
