from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from google_ads_alert.metrics import (
    AlertRunStatus,
    MetricsLoadError,
    compute_grouped_sli_reports,
    compute_sli_report,
    filter_records_by_schedule,
    grouped_sli_reports_to_dict,
    load_alert_run_records_from_jsonl,
    render_grouped_sli_reports,
    render_sli_report,
    sli_report_to_dict,
)


def _write_history(path: Path, rows: list[dict[str, object]]) -> None:
    payload = "\n".join(json.dumps(row) for row in rows)
    path.write_text(payload, encoding="utf-8")


def test_load_alert_run_records_from_jsonl(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
            {
                "scheduled_for": "2024-05-01T14:00:00+09:00",
                "status": "failure",
                "forecast_success": False,
                "data_fresh": False,
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)

    assert len(records) == 2
    assert records[0].status is AlertRunStatus.SUCCESS
    assert records[1].status is AlertRunStatus.FAILURE
    assert records[0].forecast_success is True
    assert records[1].data_fresh is False


def test_compute_sli_report_returns_expected_ratios(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
            {
                "scheduled_for": "2024-05-01T14:00:00+09:00",
                "status": "failure",
                "forecast_success": False,
                "data_fresh": False,
            },
            {
                "scheduled_for": "2024-05-01T20:00:00+09:00",
                "status": "skipped",
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    report = compute_sli_report(records)

    assert report.notification_delivery.numerator == 1
    assert report.notification_delivery.denominator == 2
    assert report.forecast_success.value == pytest.approx(0.5)
    assert report.data_freshness.value == pytest.approx(0.5)

    summary = render_sli_report(report)
    assert "Notification delivery" in summary
    assert "Data freshness" in summary


def test_load_alert_run_records_reports_invalid_payload(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(history, ["not-json"])

    with pytest.raises(MetricsLoadError):
        load_alert_run_records_from_jsonl(history)


def test_filter_records_by_schedule_limits_range(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            },
            {
                "scheduled_for": "2024-05-01T14:00:00+09:00",
                "status": "failure",
            },
            {
                "scheduled_for": "2024-05-02T08:00:00+09:00",
                "status": "success",
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    start = datetime.fromisoformat("2024-05-01T12:00:00+09:00")
    end = datetime.fromisoformat("2024-05-02T00:00:00+09:00")

    filtered = filter_records_by_schedule(records, start=start, end=end)

    assert len(filtered) == 1
    assert filtered[0].scheduled_for == datetime.fromisoformat(
        "2024-05-01T14:00:00+09:00"
    )


def test_filter_records_by_schedule_rejects_invalid_range(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+00:00",
                "status": "success",
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    start = datetime(2024, 5, 2, tzinfo=timezone.utc)
    end = datetime(2024, 5, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        filter_records_by_schedule(records, start=start, end=end)


def test_sli_report_to_dict_serialises_measurements(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
            {
                "scheduled_for": "2024-05-01T14:00:00+09:00",
                "status": "failure",
                "forecast_success": False,
                "data_fresh": False,
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    report = compute_sli_report(records)
    payload = sli_report_to_dict(report)

    assert payload["total_records"] == 2
    measurement_names = {item["name"] for item in payload["measurements"]}
    assert measurement_names == {
        "notification_delivery",
        "forecast_success",
        "data_freshness",
    }


def test_compute_grouped_sli_reports_groups_by_day(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
            {
                "scheduled_for": "2024-05-01T20:00:00+09:00",
                "status": "failure",
                "forecast_success": False,
                "data_fresh": False,
            },
            {
                "scheduled_for": "2024-05-02T09:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="day",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
        generated_at=datetime(2024, 5, 3, tzinfo=timezone.utc),
    )

    assert [group.label for group in grouped] == ["2024-05-01", "2024-05-02"]
    assert grouped[0].report.total_records == 2
    assert grouped[1].report.notification_delivery.numerator == 1


def test_compute_grouped_sli_reports_groups_by_week(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
            {
                "scheduled_for": "2024-05-04T08:00:00+09:00",
                "status": "failure",
                "forecast_success": False,
                "data_fresh": False,
            },
            {
                "scheduled_for": "2024-05-08T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
                "data_fresh": True,
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="week",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
        generated_at=datetime(2024, 5, 9, tzinfo=timezone.utc),
    )

    assert [group.label for group in grouped] == ["2024-W18", "2024-W19"]
    assert grouped[0].report.total_records == 2
    assert grouped[1].report.notification_delivery.numerator == 1


def test_compute_grouped_sli_reports_groups_by_month(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-04-01T08:00:00+09:00",
                "status": "success",
            },
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "failure",
            },
            {
                "scheduled_for": "2024-05-15T08:00:00+09:00",
                "status": "success",
            },
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="month",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
        generated_at=datetime(2024, 5, 20, tzinfo=timezone.utc),
    )

    assert [group.label for group in grouped] == ["2024-04", "2024-05"]
    assert grouped[0].report.total_records == 1
    assert grouped[1].report.notification_delivery.denominator == 2


def test_render_grouped_sli_reports_returns_text_for_day_grouping(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="day",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
    )

    text = render_grouped_sli_reports(
        grouped,
        group_by="day",
        timezone_label="Asia/Tokyo",
    )

    assert "grouped by day" in text
    assert "Date: 2024-05-01" in text


def test_render_grouped_sli_reports_returns_text_for_week_grouping(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="week",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
    )

    text = render_grouped_sli_reports(
        grouped,
        group_by="week",
        timezone_label="Asia/Tokyo",
    )

    assert "grouped by week" in text
    assert "Week: 2024-W18" in text


def test_render_grouped_sli_reports_returns_text_for_month_grouping(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="month",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
    )

    text = render_grouped_sli_reports(
        grouped,
        group_by="month",
        timezone_label="Asia/Tokyo",
    )

    assert "grouped by month" in text
    assert "Month: 2024-05" in text


def test_grouped_sli_reports_to_dict_serialises_groups(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
                "forecast_success": True,
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="day",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
    )

    payload = grouped_sli_reports_to_dict(
        grouped,
        group_by="day",
        timezone_label="Asia/Tokyo",
    )

    assert payload["group_by"] == "day"
    assert payload["timezone"] == "Asia/Tokyo"
    assert payload["groups"][0]["report"]["total_records"] == 1


def test_grouped_sli_reports_to_dict_serialises_week_groups(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="week",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
    )

    payload = grouped_sli_reports_to_dict(
        grouped,
        group_by="week",
        timezone_label="Asia/Tokyo",
    )

    assert payload["group_by"] == "week"
    assert payload["timezone"] == "Asia/Tokyo"
    assert payload["groups"][0]["label"] == "2024-W18"


def test_grouped_sli_reports_to_dict_serialises_month_groups(tmp_path: Path) -> None:
    history = tmp_path / "history.jsonl"
    _write_history(
        history,
        [
            {
                "scheduled_for": "2024-05-01T08:00:00+09:00",
                "status": "success",
            }
        ],
    )

    records = load_alert_run_records_from_jsonl(history)
    grouped = compute_grouped_sli_reports(
        records,
        group_by="month",
        grouping_timezone=ZoneInfo("Asia/Tokyo"),
    )

    payload = grouped_sli_reports_to_dict(
        grouped,
        group_by="month",
        timezone_label="Asia/Tokyo",
    )

    assert payload["group_by"] == "month"
    assert payload["timezone"] == "Asia/Tokyo"
    assert payload["groups"][0]["label"] == "2024-05"
