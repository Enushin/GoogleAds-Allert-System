from __future__ import annotations

from datetime import datetime

from zoneinfo import ZoneInfo

from google_ads_alert.google_ads_client import (
    DailyCostSummary,
    GoogleAdsClientConfig,
    GoogleAdsCostService,
    GoogleAdsCredentials,
    QueryRange,
    build_cost_query,
    build_daily_query_range,
)


class DummyTransport:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.requests: list[tuple[str, str]] = []

    def search(self, customer_id: str, query: str):  # pragma: no cover - simple passthrough
        self.requests.append((customer_id, query))
        return iter(self._rows)


def test_build_daily_query_range_localizes_naive_datetime() -> None:
    tz = ZoneInfo("Asia/Tokyo")
    as_of = datetime(2024, 5, 15, 10, 30)  # naive

    query_range = build_daily_query_range(as_of, tz)

    assert query_range.start == datetime(2024, 5, 15, tzinfo=tz)
    assert query_range.end == datetime(2024, 5, 16, tzinfo=tz)


def test_build_cost_query_spans_single_day() -> None:
    tz = ZoneInfo("Asia/Tokyo")
    query_range = QueryRange(
        start=datetime(2024, 4, 1, tzinfo=tz),
        end=datetime(2024, 4, 2, tzinfo=tz),
    )

    query = build_cost_query(query_range)

    assert "SELECT segments.date, metrics.cost_micros" in query
    assert "FROM customer" in query
    assert "2024-04-01" in query
    assert "2024-04-01" == query.rsplit("'", 2)[1]


def test_cost_service_aggregates_rows_and_converts_timezone() -> None:
    tz = ZoneInfo("Asia/Tokyo")
    credentials = GoogleAdsCredentials(
        developer_token="dev",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )
    config = GoogleAdsClientConfig(customer_id="123-456-7890", credentials=credentials, timezone=tz)
    rows = [
        {"metrics": {"cost_micros": "1000000"}},
        {"metrics": {"cost_micros": 2000000}},
        {"metrics": {}},  # ignored
    ]
    transport = DummyTransport(rows)
    service = GoogleAdsCostService(config, transport)

    summary = service.fetch_daily_cost(datetime(2024, 6, 10, 5, 0))

    assert isinstance(summary, DailyCostSummary)
    assert summary.as_of.tzinfo == tz
    assert summary.report_start == datetime(2024, 6, 10, tzinfo=tz)
    assert summary.report_end == datetime(2024, 6, 11, tzinfo=tz)
    assert summary.total_cost_micros == 3_000_000
    assert summary.total_cost == 3.0

    assert transport.requests  # ensure API called
    customer_id, query = transport.requests[0]
    assert customer_id == "123-456-7890"
    assert "segments.date" in query

