from datetime import date, datetime, timedelta, timezone

import pytest
from zoneinfo import ZoneInfo

from google_ads_alert.schedule import (
    DailyScheduleConfig,
    DailyScheduleWindow,
    find_next_run_datetime,
    generate_daily_schedule,
    generate_upcoming_run_times,
    generate_upcoming_run_windows,
)


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


def test_generate_schedule_non_positive_run_count_raises_error():
    with pytest.raises(ValueError):
        generate_daily_schedule(date(2024, 1, 5), DailyScheduleConfig(run_count=0))

    with pytest.raises(ValueError):
        generate_daily_schedule(date(2024, 1, 5), DailyScheduleConfig(run_count=-3))


def test_find_next_run_datetime_returns_upcoming_entry():
    schedule = generate_daily_schedule(date(2024, 1, 5))
    reference = schedule[0] - timedelta(minutes=15)

    next_run = find_next_run_datetime(reference, schedule)

    assert next_run == schedule[0]


def test_find_next_run_datetime_uses_reference_timezone_for_naive_schedule():
    schedule = [
        entry.replace(tzinfo=None) for entry in generate_daily_schedule(date(2024, 1, 5))
    ]
    now = datetime(2024, 1, 5, 7, 0, tzinfo=ZoneInfo("UTC"))

    next_run = find_next_run_datetime(now, schedule)

    assert next_run is not None
    assert isinstance(next_run.tzinfo, ZoneInfo)
    assert next_run.tzinfo.key == "UTC"
    assert next_run.hour == 8


def test_find_next_run_datetime_handles_timezone_conversion():
    schedule = generate_daily_schedule(date(2024, 1, 5))
    now_utc = datetime(2024, 1, 5, 9, 0, tzinfo=ZoneInfo("UTC"))

    next_run = find_next_run_datetime(now_utc, schedule)

    assert next_run == schedule[-1]
    assert next_run.tzinfo == TOKYO


def test_find_next_run_datetime_returns_none_when_all_past():
    schedule = generate_daily_schedule(date(2024, 1, 5))
    after_last = schedule[-1] + timedelta(minutes=1)

    assert find_next_run_datetime(after_last, schedule) is None


def test_generate_upcoming_run_times_filters_past_entries_and_future_days():
    now = datetime(2024, 1, 5, 10, 0, tzinfo=TOKYO)

    upcoming = generate_upcoming_run_times(now, days=2)

    expected_hours = [14, 20, 8, 14, 20]
    assert [run.hour for run in upcoming] == expected_hours
    assert upcoming[0].date() == date(2024, 1, 5)
    assert upcoming[-1].date() == date(2024, 1, 6)


def test_generate_upcoming_run_times_localizes_naive_reference():
    london = ZoneInfo("Europe/London")
    config = DailyScheduleConfig(timezone=london, start_hour=9, end_hour=18, run_count=3)
    now = datetime(2024, 6, 1, 8, 30)

    upcoming = generate_upcoming_run_times(now, days=1, config=config)

    assert all(run.tzinfo == london for run in upcoming)
    assert [(run.hour, run.minute) for run in upcoming] == [
        (9, 0),
        (13, 30),
        (18, 0),
    ]
    assert upcoming[0] >= now.replace(tzinfo=london)


def test_generate_upcoming_run_times_uses_reference_timezone_when_config_unspecified():
    london = ZoneInfo("Europe/London")
    now = datetime(2024, 6, 1, 8, 30, tzinfo=london)

    upcoming = generate_upcoming_run_times(now, days=1)

    assert all(run.tzinfo == london for run in upcoming)
    assert [run.hour for run in upcoming] == [14, 20]
    assert all(run.date() == now.date() for run in upcoming)


def test_generate_upcoming_run_times_interprets_fixed_offset_timezone_reference():
    now = datetime(2024, 6, 1, 8, 30, tzinfo=timezone.utc)

    upcoming = generate_upcoming_run_times(now, days=1)

    assert all(isinstance(run.tzinfo, ZoneInfo) for run in upcoming)
    assert {run.tzinfo.key for run in upcoming} == {"UTC"}
    assert [run.hour for run in upcoming] == [14, 20]
    assert all(run.date() == now.date() for run in upcoming)


def test_generate_upcoming_run_times_rejects_non_positive_days():
    now = datetime(2024, 1, 5, 8, 0, tzinfo=TOKYO)

    with pytest.raises(ValueError):
        generate_upcoming_run_times(now, days=0)


def test_generate_upcoming_run_windows_includes_empty_current_day():
    now = datetime(2024, 1, 5, 22, 0, tzinfo=TOKYO)

    windows = generate_upcoming_run_windows(now, days=2)

    assert [window.date for window in windows] == [date(2024, 1, 5), date(2024, 1, 6)]
    assert windows[0].run_times == ()
    assert isinstance(windows[0], DailyScheduleWindow)
    assert [run.hour for run in windows[1].run_times] == [8, 14, 20]


def test_generate_upcoming_run_windows_localizes_naive_reference():
    london = ZoneInfo("Europe/London")
    config = DailyScheduleConfig(timezone=london, start_hour=9, end_hour=18, run_count=3)
    now = datetime(2024, 6, 1, 8, 30)

    windows = generate_upcoming_run_windows(now, days=1, config=config)

    assert len(windows) == 1
    assert windows[0].date == date(2024, 6, 1)
    assert windows[0].run_times[0] >= now.replace(tzinfo=london)
    assert all(run.tzinfo == london for run in windows[0].run_times)
