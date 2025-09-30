"""Utilities for computing service level indicators from run history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone, tzinfo
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence


class MetricsLoadError(ValueError):
    """Raised when a run history file cannot be parsed."""


class AlertRunStatus(str, Enum):
    """Status of a scheduled alert execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AlertRunRecord:
    """Represents a single scheduled execution of the alert workflow."""

    scheduled_for: datetime
    status: AlertRunStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    forecast_success: bool | None = None
    data_fresh: bool | None = None


@dataclass(frozen=True)
class SliMeasurement:
    """Computed ratio for a specific service level indicator."""

    name: str
    label: str
    numerator: int
    denominator: int
    value: float


@dataclass(frozen=True)
class SliReport:
    """Aggregate SLI metrics for a set of alert run records."""

    generated_at: datetime
    total_records: int
    notification_delivery: SliMeasurement
    forecast_success: SliMeasurement
    data_freshness: SliMeasurement

    @property
    def measurements(self) -> tuple[SliMeasurement, SliMeasurement, SliMeasurement]:
        return (
            self.notification_delivery,
            self.forecast_success,
            self.data_freshness,
        )


@dataclass(frozen=True)
class SliReportGroup:
    """Container holding grouped SLI results for rendering or serialisation."""

    key: str
    label: str
    report: SliReport


def _parse_datetime(value: object, *, field: str, required: bool) -> datetime | None:
    if value is None:
        if required:
            raise MetricsLoadError(f"Missing required field '{field}'")
        return None
    if not isinstance(value, str):
        raise MetricsLoadError(f"Field '{field}' must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MetricsLoadError(f"Invalid datetime for field '{field}': {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_status(value: object) -> AlertRunStatus:
    if not isinstance(value, str):
        raise MetricsLoadError("Field 'status' must be a string")
    normalized = value.strip().lower()
    try:
        return AlertRunStatus(normalized)
    except ValueError as exc:
        allowed = ", ".join(sorted(item.value for item in AlertRunStatus))
        raise MetricsLoadError(
            f"Unsupported status '{value}'. Expected one of: {allowed}."
        ) from exc


def _parse_optional_bool(value: object, *, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise MetricsLoadError(f"Field '{field}' must be a boolean if provided")


def _record_from_dict(payload: dict[str, object]) -> AlertRunRecord:
    scheduled_for = _parse_datetime(payload.get("scheduled_for"), field="scheduled_for", required=True)
    status = _parse_status(payload.get("status"))
    started_at = _parse_datetime(payload.get("started_at"), field="started_at", required=False)
    completed_at = _parse_datetime(payload.get("completed_at"), field="completed_at", required=False)
    forecast_success = _parse_optional_bool(payload.get("forecast_success"), field="forecast_success")
    data_fresh = _parse_optional_bool(payload.get("data_fresh"), field="data_fresh")

    return AlertRunRecord(
        scheduled_for=scheduled_for,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        forecast_success=forecast_success,
        data_fresh=data_fresh,
    )


def load_alert_run_records_from_jsonl(path: str | Path) -> list[AlertRunRecord]:
    """Load :class:`AlertRunRecord` entries from a JSON Lines file."""

    file_path = Path(path)
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:  # pragma: no cover - depends on filesystem
        raise MetricsLoadError(f"Run history file not found: {file_path}") from exc

    records: list[AlertRunRecord] = []
    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MetricsLoadError(
                f"Invalid JSON payload on line {index}: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise MetricsLoadError(
                f"Each line must be a JSON object (line {index})"
            )
        records.append(_record_from_dict(payload))

    return records


def filter_records_by_schedule(
    records: Iterable[AlertRunRecord],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[AlertRunRecord]:
    """Filter ``records`` by ``scheduled_for`` bounds.

    The ``start``/``end`` parameters accept naive or timezone-aware datetimes.
    Naive values are assumed to be in UTC for consistency with
    :func:`load_alert_run_records_from_jsonl`.
    """

    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    normalized_start = _normalize(start) if start else None
    normalized_end = _normalize(end) if end else None

    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise ValueError("start must be earlier than end")

    filtered: list[AlertRunRecord] = []
    for record in records:
        if normalized_start and record.scheduled_for < normalized_start:
            continue
        if normalized_end and record.scheduled_for > normalized_end:
            continue
        filtered.append(record)

    return filtered


def _boolean_measure(
    name: str,
    label: str,
    values: Sequence[bool],
) -> SliMeasurement:
    numerator = sum(1 for value in values if value)
    denominator = len(values)
    value = numerator / denominator if denominator else 0.0
    return SliMeasurement(name=name, label=label, numerator=numerator, denominator=denominator, value=value)


def compute_sli_report(
    records: Sequence[AlertRunRecord],
    *,
    generated_at: datetime | None = None,
) -> SliReport:
    """Compute core SLI metrics from ``records``."""

    timestamp = generated_at or datetime.now(timezone.utc)
    delivery_candidates = [
        record
        for record in records
        if record.status in {AlertRunStatus.SUCCESS, AlertRunStatus.FAILURE}
    ]
    delivery_values = [record.status is AlertRunStatus.SUCCESS for record in delivery_candidates]

    forecast_values = [
        record.forecast_success
        for record in records
        if record.forecast_success is not None
    ]

    data_fresh_values = [
        record.data_fresh
        for record in records
        if record.data_fresh is not None
    ]

    delivery_measure = _boolean_measure(
        "notification_delivery",
        "Notification delivery success rate",
        delivery_values,
    )
    forecast_measure = _boolean_measure(
        "forecast_success",
        "Forecast processing success rate",
        [bool(value) for value in forecast_values],
    )
    data_fresh_measure = _boolean_measure(
        "data_freshness",
        "Data freshness rate",
        [bool(value) for value in data_fresh_values],
    )

    return SliReport(
        generated_at=timestamp,
        total_records=len(records),
        notification_delivery=delivery_measure,
        forecast_success=forecast_measure,
        data_freshness=data_fresh_measure,
    )


def compute_grouped_sli_reports(
    records: Sequence[AlertRunRecord],
    *,
    group_by: str = "overall",
    grouping_timezone: tzinfo | None = None,
    generated_at: datetime | None = None,
) -> list[SliReportGroup]:
    """Return grouped SLI reports for ``records``.

    ``group_by`` accepts ``"overall"``, ``"day"``, ``"week"`` or ``"month"``. When a
    timezone-aware grouping is requested the ``grouping_timezone`` is applied
    (defaults to UTC) to derive the local period key.
    """

    normalized_group = group_by.lower()
    timestamp = generated_at or datetime.now(timezone.utc)

    if normalized_group == "overall":
        report = compute_sli_report(records, generated_at=timestamp)
        return [SliReportGroup(key="overall", label="Overall", report=report)]

    if normalized_group not in {"day", "week", "month"}:
        raise ValueError(f"Unsupported group_by value: {group_by}")

    tz = grouping_timezone or timezone.utc

    if normalized_group == "day":
        buckets: dict[date, list[AlertRunRecord]] = {}
        for record in records:
            scheduled = record.scheduled_for
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            local_dt = scheduled.astimezone(tz)
            buckets.setdefault(local_dt.date(), []).append(record)

        grouped: list[SliReportGroup] = []
        for bucket_key in sorted(buckets):
            day_records = buckets[bucket_key]
            label = bucket_key.isoformat()
            report = compute_sli_report(day_records, generated_at=timestamp)
            grouped.append(SliReportGroup(key=label, label=label, report=report))
        return grouped

    if normalized_group == "week":
        buckets: dict[tuple[int, int], list[AlertRunRecord]] = {}
        for record in records:
            scheduled = record.scheduled_for
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            local_dt = scheduled.astimezone(tz)
            iso_year, iso_week, _ = local_dt.isocalendar()
            buckets.setdefault((iso_year, iso_week), []).append(record)

        grouped = []
        for iso_year, iso_week in sorted(buckets):
            week_records = buckets[(iso_year, iso_week)]
            label = f"{iso_year}-W{iso_week:02d}"
            report = compute_sli_report(week_records, generated_at=timestamp)
            grouped.append(SliReportGroup(key=label, label=label, report=report))

        return grouped

    buckets: dict[tuple[int, int], list[AlertRunRecord]] = {}
    for record in records:
        scheduled = record.scheduled_for
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        local_dt = scheduled.astimezone(tz)
        buckets.setdefault((local_dt.year, local_dt.month), []).append(record)

    grouped = []
    for year, month in sorted(buckets):
        month_records = buckets[(year, month)]
        label = f"{year}-{month:02d}"
        report = compute_sli_report(month_records, generated_at=timestamp)
        grouped.append(SliReportGroup(key=label, label=label, report=report))

    return grouped


def render_sli_report(report: SliReport) -> str:
    """Render ``report`` into a human readable summary."""

    lines = [
        "SLI report:",
        f"Generated at: {report.generated_at.isoformat()}",
        f"Records analyzed: {report.total_records}",
    ]

    for measurement in report.measurements:
        percent = measurement.value * 100
        lines.append(
            f"- {measurement.label}: {measurement.numerator}/{measurement.denominator} "
            f"({percent:.2f}%)"
        )

    return "\n".join(lines)


def render_grouped_sli_reports(
    grouped: Sequence[SliReportGroup],
    *,
    group_by: str,
    timezone_label: str | None = None,
) -> str:
    """Render grouped reports for interactive review."""

    normalized_group = group_by.lower()

    if normalized_group == "overall":
        if not grouped:
            empty_report = compute_sli_report(())
            return render_sli_report(empty_report)
        return render_sli_report(grouped[0].report)

    if normalized_group not in {"day", "week", "month"}:
        raise ValueError(f"Unsupported group_by value: {group_by}")

    header = f"SLI report grouped by {normalized_group}"
    if timezone_label:
        header = f"{header} (timezone: {timezone_label})"

    if not grouped:
        return "\n".join([header, "No records matched the selected filters."])

    if normalized_group == "day":
        label_title = "Date"
    elif normalized_group == "week":
        label_title = "Week"
    else:
        label_title = "Month"

    lines = [header]
    for group in grouped:
        lines.append("")
        lines.append(f"{label_title}: {group.label}")
        lines.append(f"Generated at: {group.report.generated_at.isoformat()}")
        lines.append(f"Records analyzed: {group.report.total_records}")
        for measurement in group.report.measurements:
            percent = measurement.value * 100
            lines.append(
                f"- {measurement.label}: {measurement.numerator}/{measurement.denominator} "
                f"({percent:.2f}%)"
            )

    return "\n".join(lines)


def sli_report_to_dict(report: SliReport) -> dict[str, object]:
    """Convert :class:`SliReport` into a JSON-serialisable dictionary."""

    return {
        "generated_at": report.generated_at.isoformat(),
        "total_records": report.total_records,
        "measurements": [
            {
                "name": measurement.name,
                "label": measurement.label,
                "numerator": measurement.numerator,
                "denominator": measurement.denominator,
                "value": measurement.value,
            }
            for measurement in report.measurements
        ],
    }


def grouped_sli_reports_to_dict(
    grouped: Sequence[SliReportGroup],
    *,
    group_by: str,
    timezone_label: str | None = None,
) -> dict[str, object]:
    """Serialise grouped reports into a structured dictionary."""

    payload: dict[str, object] = {
        "group_by": group_by,
        "groups": [
            {
                "key": group.key,
                "label": group.label,
                "report": sli_report_to_dict(group.report),
            }
            for group in grouped
        ],
    }

    if timezone_label:
        payload["timezone"] = timezone_label

    return payload


__all__ = [
    "AlertRunRecord",
    "AlertRunStatus",
    "MetricsLoadError",
    "SliMeasurement",
    "SliReport",
    "SliReportGroup",
    "compute_sli_report",
    "compute_grouped_sli_reports",
    "filter_records_by_schedule",
    "load_alert_run_records_from_jsonl",
    "render_grouped_sli_reports",
    "render_sli_report",
    "sli_report_to_dict",
    "grouped_sli_reports_to_dict",
]

