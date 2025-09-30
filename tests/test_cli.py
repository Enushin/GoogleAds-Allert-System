from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from zoneinfo import ZoneInfo

from google_ads_alert.cli import (
    DoctorCheck,
    DoctorReport,
    RunError,
    RunResult,
    SchedulePreview,
    SchedulePreviewWindow,
    SchedulerSetupError,
    build_argument_parser,
    generate_schedule_preview,
    main,
    render_report,
    render_run_result,
    render_schedule_preview,
    run_doctor,
    run_once,
    run_schedule_preview,
    run_scheduler,
)
from google_ads_alert.config import ConfigError, load_config
from google_ads_alert.forecast import (
    CombinedForecastResult,
    DailyForecastResult,
    MonthlyPaceResult,
)
from google_ads_alert.google_ads_client import DailyCostSummary, MonthToDateCostSummary
from google_ads_alert.metrics import MetricsLoadError
from google_ads_alert.workflow import ForecastSnapshot


MIN_ENV = {
    "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
    "GOOGLE_ADS_CLIENT_ID": "client-id",
    "GOOGLE_ADS_CLIENT_SECRET": "secret",
    "GOOGLE_ADS_REFRESH_TOKEN": "refresh-token",
    "GOOGLE_ADS_CUSTOMER_ID": "123-456-7890",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX",
}


def test_run_doctor_successful() -> None:
    report = run_doctor(base_env=MIN_ENV)

    assert report.passed
    assert all(check.passed for check in report.checks)


def test_run_doctor_reports_config_error() -> None:
    report = run_doctor(base_env={})

    assert not report.passed
    assert report.errors


def test_run_doctor_flags_invalid_schedule() -> None:
    env = {**MIN_ENV, "ALERT_RUN_COUNT": "0"}
    report = run_doctor(base_env=env)

    assert not report.passed
    assert any(check.name == "schedule.generate" and not check.passed for check in report.checks)


def test_render_report_includes_failures() -> None:
    report = DoctorReport(
        checks=(
            DoctorCheck(name="ok", passed=True, details="fine"),
            DoctorCheck(name="bad", passed=False, details="problem"),
        ),
        errors=("fatal",),
    )

    text = render_report(report)
    assert "FAIL" in text
    assert "problem" in text
    assert "fatal" in text


def test_main_returns_exit_code(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_run_doctor(env_path=None, *, base_env=None):
        captured["env_path"] = env_path
        return DoctorReport(checks=(DoctorCheck(name="ok", passed=True, details="done"),))

    monkeypatch.setattr("google_ads_alert.cli.run_doctor", fake_run_doctor)

    exit_code = main(["doctor", "--env-file", "sample.env"])

    assert exit_code == 0
    assert captured["env_path"] == "sample.env"

    output = capsys.readouterr().out
    assert "Doctor summary" in output


def test_main_propagates_failure(monkeypatch, capsys) -> None:
    def fake_run_doctor(env_path=None, *, base_env=None):
        return DoctorReport(
            checks=(DoctorCheck(name="bad", passed=False, details="oops"),)
        )

    monkeypatch.setattr("google_ads_alert.cli.run_doctor", fake_run_doctor)

    exit_code = main(["doctor"])

    assert exit_code == 1
    assert "FAIL" in capsys.readouterr().out


def test_build_argument_parser_sets_prog() -> None:
    parser = build_argument_parser()
    assert parser.prog == "google_ads_alert"


def test_generate_schedule_preview_returns_windows() -> None:
    env = {**MIN_ENV, "ALERT_TIMEZONE": "UTC"}
    config = load_config(env)
    reference = datetime(2024, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC"))

    preview = generate_schedule_preview(config, days=2, reference_time=reference)

    assert preview.generated_at.tzinfo == ZoneInfo("UTC")
    assert len(preview.windows) == 2
    assert all(run.tzinfo == ZoneInfo("UTC") for run in preview.windows[0].run_times)


def test_run_schedule_preview_uses_base_env() -> None:
    env = {**MIN_ENV, "ALERT_TIMEZONE": "UTC"}
    reference = datetime(2024, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC"))

    preview = run_schedule_preview(None, base_env=env, days=1, reference_time=reference)

    assert preview.windows


def test_render_schedule_preview_formats_output() -> None:
    preview = SchedulePreview(
        generated_at=datetime(2024, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC")),
        windows=(
            SchedulePreviewWindow(date=date(2024, 1, 1), run_times=()),
        ),
    )

    text = render_schedule_preview(preview)
    assert "Schedule preview" in text
    assert "no remaining runs" in text


def test_main_schedule_command(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_run_schedule(env_path=None, *, days, base_env=None, reference_time=None):
        captured["env_path"] = env_path
        captured["days"] = days
        return SchedulePreview(
            generated_at=datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC")),
            windows=(
                SchedulePreviewWindow(
                    date=date(2024, 1, 1),
                    run_times=(datetime(2024, 1, 1, 8, 0, tzinfo=ZoneInfo("UTC")),),
                ),
            ),
        )

    monkeypatch.setattr("google_ads_alert.cli.run_schedule_preview", fake_run_schedule)

    exit_code = main(["schedule", "--days", "2", "--env-file", "sample.env"])

    assert exit_code == 0
    assert captured["env_path"] == "sample.env"
    assert captured["days"] == 2

    output = capsys.readouterr().out
    assert "Schedule preview" in output


def test_main_schedule_reports_errors(monkeypatch, capsys) -> None:
    def fake_run_schedule(env_path=None, *, days, base_env=None, reference_time=None):
        raise ConfigError("boom")

    monkeypatch.setattr("google_ads_alert.cli.run_schedule_preview", fake_run_schedule)

    exit_code = main(["schedule"])

    assert exit_code == 1
    assert "boom" in capsys.readouterr().err


def test_run_once_dry_run(monkeypatch) -> None:
    env = {
        **MIN_ENV,
        "DAILY_BUDGET": "100000",
        "MONTHLY_BUDGET": "3000000",
        "ALERT_TIMEZONE": "UTC",
    }

    as_of = datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))

    class DummyService:
        def __init__(self, config, transport):
            self._config = config
            self._transport = transport

        def fetch_daily_cost(self, reference):
            return DailyCostSummary(
                as_of=reference,
                report_start=reference.replace(hour=0, minute=0, second=0, microsecond=0),
                report_end=reference.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1),
                total_cost_micros=12_345_000,
            )

        def fetch_month_to_date_cost(self, reference):
            start = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = reference.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            return MonthToDateCostSummary(
                as_of=reference,
                report_start=start,
                report_end=end,
                total_cost_micros=67_890_000,
            )

    monkeypatch.setattr("google_ads_alert.cli.GoogleAdsCostService", DummyService)

    result = run_once(
        None,
        base_env=env,
        dry_run=True,
        transport_factory=lambda config, env_values: object(),
        reference_time=as_of,
    )

    assert result.dry_run
    assert not result.delivered
    assert result.snapshot.as_of == as_of
    assert result.payload["blocks"]


def test_run_once_with_demo_transport() -> None:
    env = {
        **MIN_ENV,
        "GOOGLE_ADS_TRANSPORT": "google_ads_alert.transports.demo:build_transport",
        "GOOGLE_ADS_TIMEZONE": "Asia/Tokyo",
        "ALERT_TIMEZONE": "Asia/Tokyo",
        "DEMO_DAILY_COST": "1234.5",
        "DEMO_MONTH_TO_DATE_COST": "67890.0",
        "DAILY_BUDGET": "200000",
        "MONTHLY_BUDGET": "5000000",
    }

    reference = datetime(2024, 6, 15, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    result = run_once(
        None,
        base_env=env,
        dry_run=True,
        reference_time=reference,
    )

    assert result.dry_run
    assert not result.delivered
    assert result.snapshot.as_of == reference
    assert result.snapshot.daily_cost.total_cost == pytest.approx(1234.5)
    assert result.snapshot.month_to_date_cost.total_cost == pytest.approx(67890.0)
    assert result.payload["blocks"]


def test_render_run_result_outputs_payload(monkeypatch) -> None:
    env = {
        **MIN_ENV,
        "DAILY_BUDGET": "100000",
        "MONTHLY_BUDGET": "3000000",
    }
    as_of = datetime(2024, 5, 1, 9, 30, tzinfo=ZoneInfo("UTC"))

    class DummyService:
        def __init__(self, config, transport):
            self._config = config
            self._transport = transport

        def fetch_daily_cost(self, reference):
            return DailyCostSummary(
                as_of=reference,
                report_start=reference.replace(hour=0, minute=0, second=0, microsecond=0),
                report_end=reference.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1),
                total_cost_micros=5_000_000_000,
            )

        def fetch_month_to_date_cost(self, reference):
            start = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = reference.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            return MonthToDateCostSummary(
                as_of=reference,
                report_start=start,
                report_end=end,
                total_cost_micros=25_000_000_000,
            )

    monkeypatch.setattr("google_ads_alert.cli.GoogleAdsCostService", DummyService)

    result = run_once(
        None,
        base_env=env,
        dry_run=True,
        transport_factory=lambda config, env_values: object(),
        reference_time=as_of,
    )

    text = render_run_result(result)
    assert "Run result" in text
    assert "Payload" in text
    assert "5,000.00" in text


def test_main_run_command(monkeypatch, capsys) -> None:
    as_of = datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))
    snapshot = ForecastSnapshot(
        as_of=as_of,
        daily_cost=DailyCostSummary(
            as_of=as_of,
            report_start=as_of - timedelta(days=1),
            report_end=as_of + timedelta(days=1),
            total_cost_micros=0,
        ),
        month_to_date_cost=MonthToDateCostSummary(
            as_of=as_of,
            report_start=as_of.replace(day=1),
            report_end=as_of + timedelta(days=1),
            total_cost_micros=0,
        ),
        forecast=CombinedForecastResult(
            daily=DailyForecastResult(
                as_of=as_of,
                current_spend=0.0,
                elapsed=timedelta(hours=1),
                day_duration=timedelta(hours=24),
                projected_spend=0.0,
                spend_rate_per_hour=0.0,
                budget_utilization=0.0,
            ),
            monthly=MonthlyPaceResult(
                as_of=as_of,
                month_to_date_spend=0.0,
                average_daily_spend=0.0,
                projected_month_end_spend=0.0,
                days_elapsed=1,
                days_in_month=31,
                budget_utilization=0.0,
            ),
            daily_budget_gap=0.0,
            monthly_budget_gap=0.0,
            daily_budget=0.0,
            monthly_budget=0.0,
        ),
    )

    sentinel = RunResult(
        snapshot=snapshot,
        payload={"ok": True},
        delivered=False,
        dry_run=True,
    )

    def fake_run_once(env_path, **kwargs):
        assert env_path == "sample.env"
        assert kwargs["dry_run"] is True
        return sentinel

    def fake_render(result):
        assert result is sentinel
        return "rendered"

    monkeypatch.setattr("google_ads_alert.cli.run_once", fake_run_once)
    monkeypatch.setattr("google_ads_alert.cli.render_run_result", fake_render)

    exit_code = main(["run", "--env-file", "sample.env", "--dry-run"])

    assert exit_code == 0
    assert "rendered" in capsys.readouterr().out


def test_main_run_reports_errors(monkeypatch, capsys) -> None:
    def fake_run_once(env_path, **kwargs):
        raise RunError("failed")

    monkeypatch.setattr("google_ads_alert.cli.run_once", fake_run_once)

    exit_code = main(["run"])

    assert exit_code == 1
    assert "failed" in capsys.readouterr().err


def test_run_scheduler_registers_cron_jobs(monkeypatch) -> None:
    env = {
        **MIN_ENV,
        "ALERT_TIMEZONE": "UTC",
        "ALERT_START_HOUR": "8",
        "ALERT_END_HOUR": "12",
        "ALERT_RUN_COUNT": "2",
    }

    captured: list[dict[str, object]] = []

    def fake_run_once(env_path, **kwargs):
        captured.append({"env_path": env_path, **kwargs})
        return None

    monkeypatch.setattr("google_ads_alert.cli.run_once", fake_run_once)

    class StubScheduler:
        def __init__(self) -> None:
            self.jobs: list[dict[str, object]] = []
            self.removed = False

        def add_job(self, func, trigger, **kwargs):
            entry = {"func": func, "trigger": trigger, **kwargs}
            self.jobs.append(entry)

        def start(self) -> None:  # pragma: no cover - not used in this test
            raise AssertionError("start should not be invoked")

        def remove_all_jobs(self) -> None:
            self.removed = True

        def shutdown(self, wait: bool = True) -> None:  # pragma: no cover - optional
            pass

    stub = StubScheduler()

    scheduler = run_scheduler(
        None,
        base_env=env,
        dry_run=True,
        scheduler_factory=lambda tz: stub,
    )

    assert scheduler is stub
    assert stub.removed
    assert len(stub.jobs) == 2
    assert all(job["trigger"] == "cron" for job in stub.jobs)
    assert {job["hour"] for job in stub.jobs} == {8, 12}
    assert all(job["minute"] == 0 for job in stub.jobs)
    assert all(job["second"] == 0 for job in stub.jobs)
    assert all(job["timezone"] == ZoneInfo("UTC") for job in stub.jobs)

    # Execute the first scheduled job and ensure run_once receives the expected arguments.
    stub.jobs[0]["func"]()

    assert captured
    call = captured[0]
    assert call["env_path"] is None
    assert call["dry_run"] is True
    assert "GOOGLE_ADS_CLIENT_ID" in call["base_env"]


def test_run_scheduler_requires_apscheduler_when_missing() -> None:
    env = dict(MIN_ENV)

    with pytest.raises(SchedulerSetupError):
        run_scheduler(None, base_env=env)


def test_main_serve_uses_scheduler(monkeypatch, capsys) -> None:
    class StubScheduler:
        def __init__(self) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

        def shutdown(self, wait: bool = True) -> None:  # pragma: no cover - optional
            self.started = False

    stub = StubScheduler()

    def fake_run_scheduler(env_path, **kwargs):
        assert kwargs["dry_run"] is True
        return stub

    monkeypatch.setattr("google_ads_alert.cli.run_scheduler", fake_run_scheduler)

    exit_code = main(["serve", "--dry-run"])

    assert exit_code == 0
    assert stub.started
    output = capsys.readouterr().out
    assert "Scheduler started" in output


def test_main_metrics_command(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T08:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T14:00:00+09:00",
                        "status": "failure",
                        "forecast_success": False,
                        "data_fresh": False,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(["metrics", str(history)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "SLI report" in captured.out
    assert "Notification delivery" in captured.out


def test_main_metrics_command_supports_filters_and_json(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T08:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T14:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--start",
            "2024-05-01T12:00:00+09:00",
            "--end",
            "2024-05-01T23:59:00+09:00",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["total_records"] == 1
    assert payload["measurements"][0]["numerator"] == 1


def test_main_metrics_command_supports_day_grouping(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T08:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
                json.dumps(
                    {
                        "scheduled_for": "2024-05-02T08:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--group-by",
            "day",
            "--timezone",
            "Asia/Tokyo",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "grouped by day" in captured.out
    assert "Date: 2024-05-02" in captured.out


def test_main_metrics_command_supports_week_grouping(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T08:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
                json.dumps(
                    {
                        "scheduled_for": "2024-05-08T08:00:00+09:00",
                        "status": "success",
                        "forecast_success": True,
                        "data_fresh": True,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--group-by",
            "week",
            "--timezone",
            "Asia/Tokyo",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "grouped by week" in captured.out
    assert "Week: 2024-W18" in captured.out


def test_main_metrics_command_supports_month_grouping(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "scheduled_for": "2024-04-30T23:00:00+00:00",
                        "status": "success",
                    }
                ),
                json.dumps(
                    {
                        "scheduled_for": "2024-05-01T08:00:00+09:00",
                        "status": "failure",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--group-by",
            "month",
            "--timezone",
            "Asia/Tokyo",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "grouped by month" in captured.out
    assert "Month: 2024-05" in captured.out


def test_main_metrics_command_outputs_json_for_day_grouping(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--group-by",
            "day",
            "--timezone",
            "Asia/Tokyo",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["group_by"] == "day"
    assert payload["groups"][0]["report"]["total_records"] == 1


def test_main_metrics_command_outputs_json_for_week_grouping(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--group-by",
            "week",
            "--timezone",
            "Asia/Tokyo",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["group_by"] == "week"
    assert payload["groups"][0]["report"]["total_records"] == 1


def test_main_metrics_command_outputs_json_for_month_grouping(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--group-by",
            "month",
            "--timezone",
            "Asia/Tokyo",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["group_by"] == "month"
    assert payload["groups"][0]["report"]["total_records"] == 1


def test_main_metrics_command_reports_invalid_datetime(capsys) -> None:
    exit_code = main([
        "metrics",
        "history.jsonl",
        "--start",
        "invalid",
    ])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Invalid metrics option" in captured.err


def test_main_metrics_command_reports_invalid_range(tmp_path, capsys) -> None:
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "metrics",
            str(history),
            "--start",
            "2024-05-02T00:00:00+09:00",
            "--end",
            "2024-05-01T00:00:00+09:00",
        ]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Failed to compute metrics" in captured.err


def test_main_metrics_reports_errors(monkeypatch, capsys) -> None:
    def fake_loader(path):
        raise MetricsLoadError("bad data")

    monkeypatch.setattr(
        "google_ads_alert.cli.load_alert_run_records_from_jsonl", fake_loader
    )

    exit_code = main(["metrics", "history.jsonl"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Failed to load metrics" in captured.err
