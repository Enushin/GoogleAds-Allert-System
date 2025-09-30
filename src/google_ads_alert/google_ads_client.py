"""Lightweight helpers for interacting with the Google Ads API.

The real Google Ads Python client is feature rich but also heavy for unit
tests.  The utilities in this module focus on the pieces that the alerting
workflow needs immediately: shaping daily reporting windows, preparing GAQL
queries, and aggregating the resulting spend metrics.  A thin transport
protocol keeps the implementation testable without enforcing a concrete
dependency on ``google-ads``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Protocol

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
    ) -> None:
        self._config = config
        self._transport = transport

    def fetch_daily_cost(self, as_of: datetime) -> DailyCostSummary:
        """Retrieve and aggregate the spend for the day of ``as_of``."""

        tz = _coerce_timezone(self._config.timezone)
        localized_as_of = _localize(as_of, tz)
        query_range = build_daily_query_range(localized_as_of, tz)
        query = build_cost_query(query_range)

        total_micros = 0
        for row in self._transport.search(self._config.customer_id, query):
            total_micros += _extract_cost_micros(row)

        return DailyCostSummary(
            as_of=localized_as_of,
            report_start=query_range.start,
            report_end=query_range.end,
            total_cost_micros=total_micros,
        )


__all__ = [
    "DailyCostSummary",
    "GoogleAdsClientConfig",
    "GoogleAdsCostService",
    "GoogleAdsCredentials",
    "GoogleAdsSearchTransport",
    "QueryRange",
    "build_cost_query",
    "build_daily_query_range",
]

