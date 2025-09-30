"""Lightweight helpers for interacting with the Google Ads API.

The real Google Ads Python client is feature rich but also heavy for unit
tests.  The utilities in this module focus on the pieces that the alerting
workflow needs immediately: shaping daily reporting windows, preparing GAQL
queries, and aggregating the resulting spend metrics.  A thin transport
protocol keeps the implementation testable without enforcing a concrete
dependency on ``google-ads``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable, Protocol

from zoneinfo import ZoneInfo

from .forecast import _coerce_timezone


def _localize(as_of: datetime, tz: ZoneInfo) -> datetime:
    """Return ``as_of`` localized to ``tz`` without altering the moment."""

    if as_of.tzinfo is None:
        return as_of.replace(tzinfo=tz)
    return as_of.astimezone(tz)


@dataclass(frozen=True)
class GoogleAdsCredentials:
    """Bundle of OAuth related fields required by the Google Ads API."""

    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None


@dataclass(frozen=True)
class GoogleAdsClientConfig:
    """Configuration values shared across Google Ads API calls."""

    customer_id: str
    credentials: GoogleAdsCredentials
    timezone: ZoneInfo | None = None
    endpoint: str = "https://googleads.googleapis.com"


@dataclass(frozen=True)
class RetryConfig:
    """Behavioral controls for retrying failed Google Ads API calls."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if not self.retryable_exceptions:
            raise ValueError("retryable_exceptions must not be empty")

    def is_retryable(self, error: BaseException) -> bool:
        """Return ``True`` when ``error`` should trigger another attempt."""

        return isinstance(error, self.retryable_exceptions)


@dataclass(frozen=True)
class QueryRange:
    """Datetime window used for GAQL time based filtering."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class DailyCostSummary:
    """Aggregated spend metrics for a daily Google Ads report."""

    as_of: datetime
    report_start: datetime
    report_end: datetime
    total_cost_micros: int

    @property
    def total_cost(self) -> float:
        """Return the cost converted from micros to standard currency units."""

        return self.total_cost_micros / 1_000_000


@dataclass(frozen=True)
class MonthToDateCostSummary:
    """Aggregated spend metrics for the month-to-date reporting window."""

    as_of: datetime
    report_start: datetime
    report_end: datetime
    total_cost_micros: int

    @property
    def total_cost(self) -> float:
        """Return the cost converted from micros to standard currency units."""

        return self.total_cost_micros / 1_000_000


class GoogleAdsSearchTransport(Protocol):
    """Protocol describing the minimal Google Ads search capability."""

    def search(self, customer_id: str, query: str) -> Iterable[dict]:
        """Execute ``query`` for ``customer_id`` and yield decoded rows."""


def build_daily_query_range(
    as_of: datetime, timezone: ZoneInfo | None = None
) -> QueryRange:
    """Return a reporting window spanning the local calendar day of ``as_of``."""

    tz = _coerce_timezone(timezone)
    localized = _localize(as_of, tz)
    day_start = localized.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return QueryRange(start=day_start, end=day_end)


def build_month_to_date_query_range(
    as_of: datetime, timezone: ZoneInfo | None = None
) -> QueryRange:
    """Return a reporting window covering the month-to-date span of ``as_of``."""

    tz = _coerce_timezone(timezone)
    localized = _localize(as_of, tz)
    month_start = localized.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_day = localized.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    return QueryRange(start=month_start, end=next_day)


def build_cost_query(query_range: QueryRange) -> str:
    """Generate a GAQL query that retrieves cost metrics for ``query_range``."""

    start_date = query_range.start.date()
    # ``end`` is exclusive, therefore subtract one day to get the inclusive end
    end_date = (query_range.end - timedelta(days=1)).date()
    return (
        "SELECT segments.date, metrics.cost_micros "
        "FROM customer "
        f"WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'"
    )


def _extract_cost_micros(row: dict) -> int:
    """Best effort extraction of ``metrics.cost_micros`` from ``row``."""

    value = row
    for key in ("metrics", "cost_micros"):
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return 0

    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


class GoogleAdsCostService:
    """Utility wrapper that aggregates daily spend using a transport backend."""

    def __init__(
        self,
        config: GoogleAdsClientConfig,
        transport: GoogleAdsSearchTransport,
        retry_config: RetryConfig | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._retry_config = retry_config or RetryConfig()
        self._sleep = sleep or time.sleep

    def _execute_cost_query(self, query_range: QueryRange) -> int:
        query = build_cost_query(query_range)

        attempt = 0
        delay = self._retry_config.initial_backoff_seconds
        last_error: Exception | None = None

        while attempt < self._retry_config.max_attempts:
            attempt += 1
            try:
                total_micros = 0
                for row in self._transport.search(self._config.customer_id, query):
                    total_micros += _extract_cost_micros(row)
                return total_micros
            except Exception as exc:
                last_error = exc
                if not self._retry_config.is_retryable(exc) or attempt >= self._retry_config.max_attempts:
                    raise

                if delay > 0:
                    self._sleep(delay)
                delay *= self._retry_config.backoff_multiplier

        if last_error is not None:
            raise last_error
        raise RuntimeError("Cost query failed without executing")

    def fetch_daily_cost(self, as_of: datetime) -> DailyCostSummary:
        """Retrieve and aggregate the spend for the day of ``as_of``."""

        tz = _coerce_timezone(self._config.timezone)
        localized_as_of = _localize(as_of, tz)
        query_range = build_daily_query_range(localized_as_of, tz)
        total_micros = self._execute_cost_query(query_range)

        return DailyCostSummary(
            as_of=localized_as_of,
            report_start=query_range.start,
            report_end=query_range.end,
            total_cost_micros=total_micros,
        )

    def fetch_month_to_date_cost(self, as_of: datetime) -> MonthToDateCostSummary:
        """Retrieve the aggregated spend from the start of the month to ``as_of``."""

        tz = _coerce_timezone(self._config.timezone)
        localized_as_of = _localize(as_of, tz)
        query_range = build_month_to_date_query_range(localized_as_of, tz)
        total_micros = self._execute_cost_query(query_range)

        return MonthToDateCostSummary(
            as_of=localized_as_of,
            report_start=query_range.start,
            report_end=query_range.end,
            total_cost_micros=total_micros,
        )


__all__ = [
    "DailyCostSummary",
    "MonthToDateCostSummary",
    "GoogleAdsClientConfig",
    "GoogleAdsCostService",
    "GoogleAdsCredentials",
    "RetryConfig",
    "GoogleAdsSearchTransport",
    "QueryRange",
    "build_cost_query",
    "build_daily_query_range",
    "build_month_to_date_query_range",
]

