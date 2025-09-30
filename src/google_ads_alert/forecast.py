"""Forecast calculations for Google Ads budget monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from zoneinfo import ZoneInfo


DEFAULT_TZ = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class DailyForecastInput:
    """Parameters required to build a day-end spend projection."""

    as_of: datetime
    current_spend: float
    daily_budget: Optional[float] = None
    timezone: ZoneInfo | None = None


@dataclass(frozen=True)
class DailyForecastResult:
    """Result of a daily projection calculation."""

    as_of: datetime
    current_spend: float
    elapsed: timedelta
    day_duration: timedelta
    projected_spend: Optional[float]
    spend_rate_per_hour: Optional[float]
    budget_utilization: Optional[float]


@dataclass(frozen=True)
class MonthlyPaceInput:
    """Parameters for the month-to-date pacing calculation."""

    as_of: datetime
    month_to_date_spend: float
    monthly_budget: Optional[float] = None
    timezone: ZoneInfo | None = None


@dataclass(frozen=True)
class MonthlyPaceResult:
    """Outcome of the month-to-date pacing calculation."""

    as_of: datetime
    month_to_date_spend: float
    average_daily_spend: float
    projected_month_end_spend: float
    days_elapsed: int
    days_in_month: int
    budget_utilization: Optional[float]


def _coerce_timezone(tz: ZoneInfo | None) -> ZoneInfo:
    return tz or DEFAULT_TZ


def _localize_datetime(as_of: datetime, tz: ZoneInfo) -> datetime:
    """Return ``as_of`` as a timezone-aware datetime in ``tz``."""

    if as_of.tzinfo is None:
        return as_of.replace(tzinfo=tz)
    return as_of.astimezone(tz)


def _day_bounds(as_of: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, datetime]:
    localized = _localize_datetime(as_of, tz)
    day_start = localized.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end, localized


def calculate_daily_projection(params: DailyForecastInput) -> DailyForecastResult:
    """Estimate the day-end spend based on the current progress.

    The projection uses a proportional scaling between the elapsed time
    in the current day and the observed spend so far. When the elapsed
    time is zero (e.g., just after midnight), the projection cannot be
    computed and ``projected_spend`` will be ``None``.
    """

    tz = _coerce_timezone(params.timezone)
    day_start, day_end, localized_as_of = _day_bounds(params.as_of, tz)
    elapsed = localized_as_of - day_start
    day_duration = day_end - day_start

    projected_spend: Optional[float]
    spend_rate_per_hour: Optional[float]
    if elapsed.total_seconds() <= 0:
        projected_spend = None
        spend_rate_per_hour = None
    else:
        seconds_elapsed = elapsed.total_seconds()
        rate_per_second = params.current_spend / seconds_elapsed
        projected_spend = rate_per_second * day_duration.total_seconds()
        spend_rate_per_hour = rate_per_second * 3600

    budget_utilization: Optional[float]
    if params.daily_budget is None or params.daily_budget == 0:
        budget_utilization = None
    else:
        budget_utilization = params.current_spend / params.daily_budget

    return DailyForecastResult(
        as_of=localized_as_of,
        current_spend=params.current_spend,
        elapsed=elapsed,
        day_duration=day_duration,
        projected_spend=projected_spend,
        spend_rate_per_hour=spend_rate_per_hour,
        budget_utilization=budget_utilization,
    )


def calculate_monthly_pace(params: MonthlyPaceInput) -> MonthlyPaceResult:
    """Compute the projected spend for the month based on current pace."""

    tz = _coerce_timezone(params.timezone)
    localized = _localize_datetime(params.as_of, tz)
    first_of_month = localized.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if localized.month == 12:
        next_month = localized.replace(year=localized.year + 1, month=1, day=1)
    else:
        next_month = localized.replace(month=localized.month + 1, day=1)
    days_elapsed = (localized.date() - first_of_month.date()).days + 1
    days_in_month = (next_month.date() - first_of_month.date()).days

    average_daily_spend = params.month_to_date_spend / max(days_elapsed, 1)
    projected_month_end_spend = average_daily_spend * days_in_month

    budget_utilization: Optional[float]
    if params.monthly_budget is None or params.monthly_budget == 0:
        budget_utilization = None
    else:
        budget_utilization = projected_month_end_spend / params.monthly_budget

    return MonthlyPaceResult(
        as_of=localized,
        month_to_date_spend=params.month_to_date_spend,
        average_daily_spend=average_daily_spend,
        projected_month_end_spend=projected_month_end_spend,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        budget_utilization=budget_utilization,
    )

