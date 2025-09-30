"""Workflow helpers for orchestrating Google Ads budget alerts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from zoneinfo import ZoneInfo

from .forecast import (
    CombinedForecastInput,
    CombinedForecastResult,
    build_combined_forecast,
    _coerce_timezone,
)
from .google_ads_client import (
    DailyCostSummary,
    GoogleAdsCostService,
    MonthToDateCostSummary,
)
from .notification import SlackNotificationOptions, build_slack_notification_payload

SlackPayload = dict[str, object]


class NotificationSender(Protocol):
    """Callable contract for dispatching rendered notification payloads."""

    def __call__(self, payload: SlackPayload) -> None:  # pragma: no cover - interface
        ...


@dataclass(frozen=True)
class ForecastSnapshot:
    """Collected spend summaries and rendered forecast for an alert cycle."""

    as_of: datetime
    daily_cost: DailyCostSummary
    month_to_date_cost: MonthToDateCostSummary
    forecast: CombinedForecastResult


def build_forecast_snapshot(
    cost_service: GoogleAdsCostService,
    *,
    as_of: datetime | None = None,
    daily_budget: float | None = None,
    monthly_budget: float | None = None,
    timezone_override: ZoneInfo | None = None,
) -> ForecastSnapshot:
    """Create a consolidated forecast snapshot using ``cost_service`` data."""

    reference = as_of or datetime.now(timezone.utc)

    daily_summary = cost_service.fetch_daily_cost(reference)
    month_summary = cost_service.fetch_month_to_date_cost(reference)

    tz_candidate = timezone_override
    if tz_candidate is None:
        summary_tz = daily_summary.as_of.tzinfo
        if isinstance(summary_tz, ZoneInfo):
            tz_candidate = summary_tz

    tz = _coerce_timezone(tz_candidate)

    forecast = build_combined_forecast(
        CombinedForecastInput(
            as_of=daily_summary.as_of,
            current_spend=daily_summary.total_cost,
            month_to_date_spend=month_summary.total_cost,
            daily_budget=daily_budget,
            monthly_budget=monthly_budget,
            timezone=tz,
        )
    )

    return ForecastSnapshot(
        as_of=daily_summary.as_of,
        daily_cost=daily_summary,
        month_to_date_cost=month_summary,
        forecast=forecast,
    )


def dispatch_slack_alert(
    snapshot: ForecastSnapshot,
    sender: NotificationSender,
    *,
    options: SlackNotificationOptions | None = None,
) -> SlackPayload:
    """Render a Slack payload for ``snapshot`` and hand it to ``sender``."""

    payload = build_slack_notification_payload(snapshot.forecast, options)
    sender(payload)
    return payload


__all__ = [
    "ForecastSnapshot",
    "NotificationSender",
    "SlackPayload",
    "build_forecast_snapshot",
    "dispatch_slack_alert",
]
