"""Command line utilities for the Google Ads alert workflow."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .config import ApplicationConfig, ConfigError, load_config, load_env_file
from .google_ads_client import GoogleAdsCostService, GoogleAdsSearchTransport
from .schedule import generate_daily_schedule, generate_upcoming_run_windows
from .workflow import (
    ForecastSnapshot,
    NotificationSender,
    SlackPayload,
    build_forecast_snapshot,
    dispatch_slack_alert,
)


@dataclass(frozen=True)
class DoctorCheck:
    """Result of a single validation executed by :func:`run_doctor`."""

    name: str
    passed: bool
    details: str


@dataclass(frozen=True)
class DoctorReport:
    """Aggregated outcome of the configuration doctor command."""

    checks: tuple[DoctorCheck, ...]
    errors: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """Return ``True`` when all checks succeeded and no fatal errors occurred."""

        return not self.errors and all(check.passed for check in self.checks)


@dataclass(frozen=True)
class SchedulePreviewWindow:
    """Upcoming executions for a specific date."""

    date: date
    run_times: tuple[datetime, ...]


@dataclass(frozen=True)
class SchedulePreview:
    """Snapshot of future scheduled runs."""

    generated_at: datetime
    windows: tuple[SchedulePreviewWindow, ...]


def _load_application_config(
    env_path: str | Path | None,
    *,
    base_env: Mapping[str, str] | None,
) -> tuple[ApplicationConfig, list[DoctorCheck], Mapping[str, str]]:
    checks: list[DoctorCheck] = []
    base_values = dict(base_env or os.environ)
    if env_path is None:
        source_label = "environment variables"
        try:
            config = load_config(base_values)
        except ConfigError as exc:
            raise ConfigError(f"Failed to load configuration: {exc}") from exc
        env_values: Mapping[str, str] = base_values
    else:
        path = Path(env_path)
        source_label = str(path)
        file_values = load_env_file(path)
        merged = {**base_values, **file_values}
        try:
            config = load_config(merged)
        except ConfigError as exc:
            raise ConfigError(f"Failed to load configuration from {path}: {exc}") from exc
        env_values = merged

    checks.append(
        DoctorCheck(
            name="configuration.load",
            passed=True,
            details=f"Configuration loaded from {source_label}",
        )
    )
    return config, checks, env_values


def _check_slack_webhook(config: ApplicationConfig) -> DoctorCheck:
    url = config.slack.webhook_url.strip()
    if not url:
        return DoctorCheck(
            name="slack.webhook",
            passed=False,
            details="Slack webhook URL is empty.",
        )
    if not url.startswith("https://"):
        return DoctorCheck(
            name="slack.webhook",
            passed=False,
            details="Slack webhook URL must start with 'https://'.",
        )

    endpoint_note = ""
    if "hooks.slack.com" not in url:
        endpoint_note = " (non-standard endpoint detected)"

    return DoctorCheck(
        name="slack.webhook",
        passed=True,
        details=f"Webhook appears valid{endpoint_note}.",
    )


def _check_budgets(config: ApplicationConfig) -> Iterable[DoctorCheck]:
    checks: list[DoctorCheck] = []

    for label, value in (("daily", config.daily_budget), ("monthly", config.monthly_budget)):
        if value is None:
            checks.append(
                DoctorCheck(
                    name=f"budget.{label}",
                    passed=True,
                    details=f"No {label} budget configured.",
                )
            )
            continue

        if value < 0:
            checks.append(
                DoctorCheck(
                    name=f"budget.{label}",
                    passed=False,
                    details=f"{label.title()} budget must not be negative (current: {value}).",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    name=f"budget.{label}",
                    passed=True,
                    details=f"{label.title()} budget configured: {value:,.2f}.",
                )
            )
    return checks


def _check_schedule(config: ApplicationConfig) -> DoctorCheck:
    try:
        run_times = generate_daily_schedule(date.today(), config.schedule)
    except ValueError as exc:
        return DoctorCheck(
            name="schedule.generate",
            passed=False,
            details=str(exc),
        )

    if not run_times:
        return DoctorCheck(
            name="schedule.generate",
            passed=False,
            details="Schedule generation returned no run times.",
        )

    tz_name = run_times[0].tzinfo.tzname(run_times[0]) if run_times[0].tzinfo else "naive"
    description = (
        f"Generated {len(run_times)} run(s); first at {run_times[0].isoformat()}"
        f" ({tz_name})."
    )
    return DoctorCheck(
        name="schedule.generate",
        passed=True,
        details=description,
    )


def run_doctor(
    env_path: str | Path | None = None,
    *,
    base_env: Mapping[str, str] | None = None,
) -> DoctorReport:
    """Execute configuration validations and return their outcome."""

    try:
        config, checks, _ = _load_application_config(env_path, base_env=base_env)
    except ConfigError as exc:
        return DoctorReport(checks=(), errors=(str(exc),))

    checks.append(_check_slack_webhook(config))
    checks.extend(_check_budgets(config))
    checks.append(_check_schedule(config))

    return DoctorReport(checks=tuple(checks))


def render_report(report: DoctorReport) -> str:
    """Render a human-friendly summary for :class:`DoctorReport`."""

    status = "PASS" if report.passed else "FAIL"
    lines = [f"Doctor summary: {status}"]

    for check in report.checks:
        symbol = "✔" if check.passed else "✖"
        lines.append(f"{symbol} {check.name}: {check.details}")

    for error in report.errors:
        lines.append(f"✖ error: {error}")

    return "\n".join(lines)


def _resolve_preview_timezone(
    config: ApplicationConfig, windows: Sequence[SchedulePreviewWindow]
) -> ZoneInfo | None:
    for window in windows:
        for run in window.run_times:
            tzinfo = run.tzinfo
            if tzinfo is None:
                continue
            if isinstance(tzinfo, ZoneInfo):
                return tzinfo
            tz_name = tzinfo.tzname(run)
            if tz_name:
                try:
                    return ZoneInfo(tz_name)
                except Exception:  # pragma: no cover - ZoneInfo errors vary
                    continue
    if isinstance(config.schedule.timezone, ZoneInfo):
        return config.schedule.timezone
    try:
        return ZoneInfo("Asia/Tokyo")
    except Exception:  # pragma: no cover - ZoneInfo errors vary
        return None


def generate_schedule_preview(
    config: ApplicationConfig,
    *,
    days: int,
    reference_time: datetime | None = None,
) -> SchedulePreview:
    """Build a :class:`SchedulePreview` for the next ``days`` days."""

    if days <= 0:
        raise ValueError("days must be greater than 0")

    now = reference_time or datetime.now()
    windows = tuple(
        SchedulePreviewWindow(window.date, tuple(window.run_times))
        for window in generate_upcoming_run_windows(now, days, config.schedule)
    )

    tz = _resolve_preview_timezone(config, windows)
    if tz is not None:
        if now.tzinfo is None:
            generated_at = now.replace(tzinfo=tz)
        else:
            generated_at = now.astimezone(tz)
    else:
        generated_at = now

    return SchedulePreview(generated_at=generated_at, windows=windows)


def run_schedule_preview(
    env_path: str | Path | None,
    *,
    days: int,
    base_env: Mapping[str, str] | None = None,
    reference_time: datetime | None = None,
) -> SchedulePreview:
    """Load configuration and return a schedule preview."""

    config, _, _ = _load_application_config(env_path, base_env=base_env)
    return generate_schedule_preview(
        config, days=days, reference_time=reference_time
    )


def render_schedule_preview(preview: SchedulePreview) -> str:
    """Return a readable summary of :class:`SchedulePreview`."""

    lines = [
        "Schedule preview:",
        f"Generated at: {preview.generated_at.isoformat()}",
    ]

    if not preview.windows:
        lines.append("No schedule entries available.")
        return "\n".join(lines)

    for window in preview.windows:
        lines.append(f"{window.date.isoformat()}")
        if window.run_times:
            for run in window.run_times:
                lines.append(f"  - {run.isoformat()}")
        else:
            lines.append("  (no remaining runs)")

    return "\n".join(lines)


TransportFactory = Callable[[ApplicationConfig, Mapping[str, str]], GoogleAdsSearchTransport]
SenderFactory = Callable[[ApplicationConfig, Mapping[str, str]], NotificationSender]


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single alert execution cycle."""

    snapshot: ForecastSnapshot
    payload: SlackPayload
    delivered: bool
    dry_run: bool


class RunError(RuntimeError):
    """Raised when an alert execution fails."""


def _import_factory(spec: str, *, default_attr: str) -> Callable:
    module_name, _, attr = spec.partition(":")
    if not module_name:
        raise ConfigError(f"Invalid factory specification: '{spec}'")
    module = importlib.import_module(module_name)
    attribute = attr or default_attr
    try:
        factory = getattr(module, attribute)
    except AttributeError as exc:
        raise ConfigError(
            f"Factory '{attribute}' was not found in module '{module_name}'"
        ) from exc
    if not callable(factory):
        raise ConfigError(f"Factory '{attribute}' in module '{module_name}' is not callable")
    return factory


def _resolve_transport_factory(
    config: ApplicationConfig,
    env_values: Mapping[str, str],
    transport_factory: TransportFactory | None,
    transport_path: str | None,
) -> GoogleAdsSearchTransport:
    if transport_factory is not None:
        return transport_factory(config, env_values)

    spec = transport_path or env_values.get("GOOGLE_ADS_TRANSPORT")
    if not spec:
        raise ConfigError(
            "No Google Ads transport configured. Set 'GOOGLE_ADS_TRANSPORT' or "
            "pass a transport factory."
        )

    factory = _import_factory(spec, default_attr="build_transport")
    return factory(config, env_values)


def _build_slack_sender(webhook_url: str) -> NotificationSender:
    def _sender(payload: SlackPayload) -> None:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if 200 <= getattr(response, "status", 200) < 300:
                    return
                raise RunError(
                    f"Slack webhook responded with status {getattr(response, 'status', 'unknown')}"
                )
        except urllib.error.HTTPError as exc:  # pragma: no cover - network errors vary
            raise RunError(f"Slack webhook error: {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:  # pragma: no cover - network errors vary
            raise RunError(f"Failed to reach Slack webhook: {exc.reason}") from exc

    return _sender


def _resolve_sender_factory(
    config: ApplicationConfig,
    env_values: Mapping[str, str],
    sender_factory: SenderFactory | None,
    sender_path: str | None,
) -> NotificationSender:
    if sender_factory is not None:
        return sender_factory(config, env_values)

    spec = sender_path or env_values.get("SLACK_SENDER_FACTORY")
    if spec:
        factory = _import_factory(spec, default_attr="build_sender")
        return factory(config, env_values)

    return _build_slack_sender(config.slack.webhook_url)


def run_once(
    env_path: str | Path | None,
    *,
    base_env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    transport_factory: TransportFactory | None = None,
    sender_factory: SenderFactory | None = None,
    reference_time: datetime | None = None,
    transport_path: str | None = None,
    sender_path: str | None = None,
) -> RunResult:
    """Execute a single forecast + notification cycle."""

    config, _, env_values = _load_application_config(env_path, base_env=base_env)

    transport = _resolve_transport_factory(
        config, env_values, transport_factory, transport_path
    )

    cost_service = GoogleAdsCostService(config.google_ads, transport)

    snapshot = build_forecast_snapshot(
        cost_service,
        as_of=reference_time,
        daily_budget=config.daily_budget,
        monthly_budget=config.monthly_budget,
        timezone_override=config.schedule.timezone,
    )

    delivered = False
    if dry_run:
        sender = lambda payload: None  # type: ignore[assignment]
    else:
        sender = _resolve_sender_factory(
            config, env_values, sender_factory, sender_path
        )
        delivered = True

    try:
        payload = dispatch_slack_alert(
            snapshot, sender, options=config.slack.options
        )
    except RunError:
        raise
    except Exception as exc:  # pragma: no cover - unexpected sender errors
        raise RunError(str(exc)) from exc

    return RunResult(
        snapshot=snapshot,
        payload=payload,
        delivered=delivered,
        dry_run=dry_run,
    )


def render_run_result(result: RunResult) -> str:
    """Render a textual summary for :class:`RunResult`."""

    snapshot = result.snapshot
    daily_cost = snapshot.daily_cost.total_cost
    month_cost = snapshot.month_to_date_cost.total_cost

    delivery_status = (
        "skipped (dry-run)" if result.dry_run else "sent to Slack"
    )

    lines = [
        "Run result:",
        f"As of: {snapshot.as_of.isoformat()}",
        f"Daily spend: {daily_cost:,.2f}",
        f"Month-to-date spend: {month_cost:,.2f}",
        f"Delivery: {delivery_status}",
        "Payload:",
        json.dumps(result.payload, ensure_ascii=False, indent=2),
    ]
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the command line interface."""

    parser = argparse.ArgumentParser(prog="google_ads_alert", description="Google Ads alert utilities")
    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate configuration and scheduling setup.",
    )
    doctor_parser.add_argument(
        "-e",
        "--env-file",
        dest="env_file",
        help="Path to a .env file used for validation.",
    )

    schedule_parser = subparsers.add_parser(
        "schedule",
        help="Preview upcoming schedule run times.",
    )
    schedule_parser.add_argument(
        "-e",
        "--env-file",
        dest="env_file",
        help="Path to a .env file used for preview generation.",
    )
    schedule_parser.add_argument(
        "-d",
        "--days",
        dest="days",
        type=int,
        default=1,
        help="Number of days to preview (default: 1).",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Execute a single alert cycle and dispatch a Slack notification.",
    )
    run_parser.add_argument(
        "-e",
        "--env-file",
        dest="env_file",
        help="Path to a .env file used for execution.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render the Slack payload without sending it.",
    )
    run_parser.add_argument(
        "--transport",
        dest="transport",
        help="Python path to a transport factory (module:callable).",
    )
    run_parser.add_argument(
        "--sender",
        dest="sender",
        help="Python path to a sender factory (module:callable).",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point used by ``python -m google_ads_alert``."""

    parser = build_argument_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        report = run_doctor(args.env_file)
        print(render_report(report))
        return 0 if report.passed else 1

    if args.command == "schedule":
        try:
            preview = run_schedule_preview(args.env_file, days=args.days)
        except ConfigError as exc:
            print(f"Failed to load configuration: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"Invalid schedule options: {exc}", file=sys.stderr)
            return 1

        print(render_schedule_preview(preview))
        return 0

    if args.command == "run":
        try:
            result = run_once(
                args.env_file,
                dry_run=args.dry_run,
                transport_path=args.transport,
                sender_path=args.sender,
            )
        except ConfigError as exc:
            print(f"Failed to load configuration: {exc}", file=sys.stderr)
            return 1
        except RunError as exc:
            print(f"Run failed: {exc}", file=sys.stderr)
            return 1

        print(render_run_result(result))
        return 0

    parser.print_help()
    return 1


__all__ = [
    "DoctorCheck",
    "DoctorReport",
    "SchedulePreview",
    "SchedulePreviewWindow",
    "generate_schedule_preview",
    "build_argument_parser",
    "main",
    "render_report",
    "render_schedule_preview",
    "run_doctor",
    "run_schedule_preview",
    "RunResult",
    "RunError",
    "render_run_result",
    "run_once",
]
