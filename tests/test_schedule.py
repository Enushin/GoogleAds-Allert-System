from datetime import date

import pytest
from zoneinfo import ZoneInfo

from google_ads_alert.schedule import DailyScheduleConfig, generate_daily_schedule


TOKYO = ZoneInfo("Asia/Tokyo")


def test_generate_schedule_default_config_produces_six_runs():
    schedule = generate_daily_schedule(date(2024, 1, 5))

    assert len(schedule) == 6
    assert schedule[0].hour == 9
    assert schedule[-1].hour == 23
    # evenly spaced between 9 and 23 => 14 hours total / 5 intervals = 2.8 hours
    deltas = [
        (schedule[i + 1] - schedule[i]).total_seconds() / 3600 for i in range(5)
    ]
    for delta in deltas:
        assert pytest.approx(delta, rel=1e-6) == 2.8


def test_generate_schedule_respects_custom_timezone():
    london = ZoneInfo("Europe/London")
    schedule = generate_daily_schedule(
        date(2024, 6, 1), DailyScheduleConfig(timezone=london, start_hour=8, end_hour=20)
    )

    assert schedule[0].tzinfo == london
    assert schedule[0].hour == 8
    assert schedule[-1].hour == 20


def test_generate_schedule_with_single_run_returns_start_only():
    schedule = generate_daily_schedule(
        date(2024, 1, 5), DailyScheduleConfig(run_count=1, start_hour=10)
    )

    assert schedule == [schedule[0]]
    assert schedule[0].hour == 10


def test_generate_schedule_invalid_hours_raise_error():
    with pytest.raises(ValueError):
        generate_daily_schedule(date(2024, 1, 5), DailyScheduleConfig(start_hour=-1))

    with pytest.raises(ValueError):
        generate_daily_schedule(date(2024, 1, 5), DailyScheduleConfig(end_hour=24))

    with pytest.raises(ValueError):
        generate_daily_schedule(
            date(2024, 1, 5), DailyScheduleConfig(start_hour=20, end_hour=10, run_count=3)
        )
