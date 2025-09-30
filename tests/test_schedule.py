from datetime import date

import pytest
from zoneinfo import ZoneInfo

from google_ads_alert.schedule import DailyScheduleConfig, generate_daily_schedule


TOKYO = ZoneInfo("Asia/Tokyo")


def test_generate_schedule_default_config_produces_three_runs():
    schedule = generate_daily_schedule(date(2024, 1, 5))

    assert len(schedule) == 3
    assert schedule[0].hour == 8
    assert schedule[-1].hour == 20
    # evenly spaced between 8 and 20 => 12 hours total / 2 intervals = 6 hours
    deltas = [
        (schedule[i + 1] - schedule[i]).total_seconds() / 3600 for i in range(2)
    ]
    for delta in deltas:
        assert pytest.approx(delta, rel=1e-6) == 6


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


def test_generate_schedule_supports_minute_precision():
    schedule = generate_daily_schedule(
        date(2024, 1, 5),
        DailyScheduleConfig(
            start_hour=9,
            start_minute=30,
            end_hour=18,
            end_minute=15,
            run_count=4,
        ),
    )

    assert schedule[0].hour == 9
    assert schedule[0].minute == 30
    assert schedule[-1].hour == 18
    assert schedule[-1].minute == 15
    assert schedule[1] < schedule[2]  # intermediate ordering preserved
    total_seconds = (schedule[-1] - schedule[0]).total_seconds()
    expected_step = total_seconds / 3
    for i in range(len(schedule) - 1):
        delta = (schedule[i + 1] - schedule[i]).total_seconds()
        assert pytest.approx(delta, rel=1e-9) == expected_step


def test_generate_schedule_invalid_hours_raise_error():
    with pytest.raises(ValueError):
        generate_daily_schedule(date(2024, 1, 5), DailyScheduleConfig(start_hour=-1))

    with pytest.raises(ValueError):
        generate_daily_schedule(date(2024, 1, 5), DailyScheduleConfig(end_hour=24))

    with pytest.raises(ValueError):
        generate_daily_schedule(
            date(2024, 1, 5), DailyScheduleConfig(start_hour=20, end_hour=10, run_count=3)
        )


def test_generate_schedule_invalid_minutes_raise_error():
    with pytest.raises(ValueError):
        generate_daily_schedule(
            date(2024, 1, 5), DailyScheduleConfig(start_minute=-1)
        )

    with pytest.raises(ValueError):
        generate_daily_schedule(
            date(2024, 1, 5), DailyScheduleConfig(end_minute=60)
        )


def test_generate_schedule_non_positive_run_count_is_rejected():
    for invalid in (0, -2):
        with pytest.raises(ValueError):
            generate_daily_schedule(
                date(2024, 1, 5), DailyScheduleConfig(run_count=invalid)
            )
