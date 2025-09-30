from __future__ import annotations

from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

from google_ads_alert.google_ads_client import DailyCostSummary, MonthToDateCostSummary
from google_ads_alert.notification import SlackNotificationOptions
from google_ads_alert.workflow import (
    build_forecast_snapshot,
    dispatch_slack_alert,
)


class DummyCostService:
    def __init__(
        self,
        daily_summary: DailyCostSummary,
        month_summary: MonthToDateCostSummary,
    ) -> None:
        self._daily = daily_summary
        self._monthly = month_summary
        self.daily_calls: list[datetime] = []
        self.monthly_calls: list[datetime] = []

    def fetch_daily_cost(self, as_of: datetime) -> DailyCostSummary:
        self.daily_calls.append(as_of)
        return self._daily

    def fetch_month_to_date_cost(self, as_of: datetime) -> MonthToDateCostSummary:
        self.monthly_calls.append(as_of)
        return self._monthly


@pytest.fixture
def snapshot_inputs() -> tuple[DummyCostService, datetime]:
    tz = ZoneInfo("Asia/Tokyo")
    daily_summary = DailyCostSummary(
        as_of=datetime(2024, 6, 10, 12, 0, tzinfo=tz),
        report_start=datetime(2024, 6, 10, tzinfo=tz),
        report_end=datetime(2024, 6, 11, tzinfo=tz),
        total_cost_micros=5_000_000,
    )
    monthly_summary = MonthToDateCostSummary(
        as_of=datetime(2024, 6, 10, 12, 0, tzinfo=tz),
        report_start=datetime(2024, 6, 1, tzinfo=tz),
        report_end=datetime(2024, 6, 11, tzinfo=tz),
        total_cost_micros=55_000_000,
    )
    service = DummyCostService(daily_summary, monthly_summary)
    reference = datetime(2024, 6, 10, 3, 0, tzinfo=ZoneInfo("UTC"))
    return service, reference


def test_build_forecast_snapshot_aggregates_costs(snapshot_inputs) -> None:
    service, reference = snapshot_inputs
    tz = ZoneInfo("Asia/Tokyo")

    snapshot = build_forecast_snapshot(
        service,
        as_of=reference,
        daily_budget=10.0,
        monthly_budget=300.0,
        timezone_override=tz,
    )

    assert service.daily_calls[0] == reference
    assert service.monthly_calls[0] == reference
    assert snapshot.as_of == service._daily.as_of
    assert snapshot.daily_cost.total_cost == pytest.approx(5.0)
    assert snapshot.month_to_date_cost.total_cost == pytest.approx(55.0)
    assert snapshot.forecast.daily.projected_spend == pytest.approx(10.0)
    assert snapshot.forecast.daily_budget == pytest.approx(10.0)
    assert snapshot.forecast.monthly_budget == pytest.approx(300.0)
    assert snapshot.forecast.monthly.month_to_date_spend == pytest.approx(55.0)


def test_dispatch_slack_alert_sends_payload(snapshot_inputs) -> None:
    service, reference = snapshot_inputs

    snapshot = build_forecast_snapshot(service, as_of=reference)

    sent_payloads: list[dict[str, object]] = []

    payload = dispatch_slack_alert(
        snapshot,
        sent_payloads.append,
        options=SlackNotificationOptions(account_name="Test"),
    )

    assert sent_payloads and sent_payloads[0] is payload
    assert payload["blocks"][0]["type"] == "header"
    assert "最終更新" in payload["blocks"][1]["elements"][0]["text"]
