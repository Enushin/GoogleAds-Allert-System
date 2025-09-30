from datetime import datetime

import pytest

from google_ads_alert.forecast import (
    DailyForecastInput,
    MonthlyPaceInput,
    calculate_daily_projection,
    calculate_monthly_pace,
)
from zoneinfo import ZoneInfo


TOKYO = ZoneInfo("Asia/Tokyo")


def test_daily_projection_midday():
    as_of = datetime(2024, 1, 15, 12, 0, tzinfo=TOKYO)
    params = DailyForecastInput(
        as_of=as_of,
        current_spend=5000.0,
        daily_budget=10000.0,
    )

    result = calculate_daily_projection(params)

    assert result.projected_spend == pytest.approx(10000.0)
    assert result.spend_rate_per_hour == pytest.approx(10000.0 / 24)
    assert result.budget_utilization == pytest.approx(0.5)
    assert result.elapsed.total_seconds() == pytest.approx(12 * 3600)


def test_daily_projection_no_elapsed_time_returns_none():
    as_of = datetime(2024, 1, 15, 0, 0, tzinfo=TOKYO)
    params = DailyForecastInput(as_of=as_of, current_spend=0.0)

    result = calculate_daily_projection(params)

    assert result.projected_spend is None
    assert result.spend_rate_per_hour is None


def test_daily_projection_accepts_naive_datetime():
    as_of = datetime(2024, 1, 15, 12, 0)  # naive datetime interpreted in Tokyo time
    params = DailyForecastInput(as_of=as_of, current_spend=1200.0)

    result = calculate_daily_projection(params)

    assert result.as_of.tzinfo == TOKYO
    # Half day elapsed -> double the spend
    assert result.projected_spend == pytest.approx(2400.0)


def test_monthly_pace_projects_full_month():
    as_of = datetime(2024, 1, 10, 9, 0, tzinfo=TOKYO)
    params = MonthlyPaceInput(
        as_of=as_of,
        month_to_date_spend=90000.0,
        monthly_budget=300000.0,
    )

    result = calculate_monthly_pace(params)

    # 10 days elapsed in a 31-day month => average 9,000 per day projected to 279,000
    assert result.average_daily_spend == pytest.approx(9000.0)
    assert result.projected_month_end_spend == pytest.approx(279000.0)
    assert result.days_elapsed == 10
    assert result.days_in_month == 31
    assert result.budget_utilization == pytest.approx(279000.0 / 300000.0)


def test_monthly_pace_handles_december_transition():
    as_of = datetime(2023, 12, 31, 23, 0, tzinfo=TOKYO)
    params = MonthlyPaceInput(as_of=as_of, month_to_date_spend=310000.0)

    result = calculate_monthly_pace(params)

    assert result.days_in_month == 31
    assert result.days_elapsed == 31
    assert result.projected_month_end_spend == pytest.approx(310000.0)


def test_monthly_pace_accepts_naive_datetime():
    as_of = datetime(2024, 2, 10, 9, 0)  # naive datetime assumed to be in Tokyo
    params = MonthlyPaceInput(as_of=as_of, month_to_date_spend=100000.0)

    result = calculate_monthly_pace(params)

    assert result.as_of.tzinfo == TOKYO
    assert result.days_elapsed == 10

