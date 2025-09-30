"""Utility helpers for building alert execution schedules."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .forecast import _coerce_timezone


@dataclass(frozen=True)
class DailyScheduleConfig:
    """Configuration for generating daily alert execution times.

    Attributes
    ----------
    timezone:
        Target timezone for the generated run times. ``None`` falls back to
        the project default (Asia/Tokyo).
    start_hour:
        First hour (0-23) when the schedule may trigger. The exact first run
        will be aligned to this hour and ``start_minute``.
    start_minute:
        Minute component (0-59) used for the first run of the day.
    end_hour:
        Last hour (0-23) allowed for execution. When multiple runs are
        generated the final one will be aligned to ``end_hour`` and
        ``end_minute``.
    end_minute:
        Minute component (0-59) of the final run of the day.
    run_count:
        Desired number of executions per day. Must be at least one. Defaults to
        three so alerts land at 8:00, 14:00, and 20:00 in the Asia/Tokyo
        timezone.
    """

    timezone: ZoneInfo | None = None
    start_hour: int = 8
    start_minute: int = 0
    end_hour: int = 20
    end_minute: int = 0
    run_count: int = 3


def _validate_hour(hour: int) -> None:
    if not 0 <= hour <= 23:
        raise ValueError("Hour must be within the range 0-23")


def _validate_minute(minute: int) -> None:
    if not 0 <= minute <= 59:
        raise ValueError("Minute must be within the range 0-59")


def _build_anchor_datetime(
    target_date: date, hour: int, minute: int, tz: ZoneInfo
) -> datetime:
    _validate_hour(hour)
    _validate_minute(minute)
    return datetime(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=hour,
        minute=minute,
        tzinfo=tz,
    )


def generate_daily_schedule(
    target_date: date, config: DailyScheduleConfig | None = None
) -> list[datetime]:
    """Return alert run times for ``target_date``.

    The generated schedule always includes the start and end anchors. When
    ``run_count`` is one the result consists of the start hour only. For
    higher counts the remaining entries are evenly spaced between the
    anchors (hour and minute precision).
    """

    cfg = config or DailyScheduleConfig()
    tz = _coerce_timezone(cfg.timezone)
    start_dt = _build_anchor_datetime(
        target_date, cfg.start_hour, cfg.start_minute, tz
    )
    if cfg.run_count <= 0:
        raise ValueError("run_count must be greater than 0")

    if cfg.run_count == 1:
        return [start_dt]

    end_dt = _build_anchor_datetime(
        target_date, cfg.end_hour, cfg.end_minute, tz
    )
    if end_dt < start_dt:
        raise ValueError("end_hour must be greater than or equal to start_hour")

    interval_seconds = (end_dt - start_dt).total_seconds()
    if cfg.run_count == 2:
        return [start_dt, end_dt]

    step = interval_seconds / (cfg.run_count - 1)
    schedule: list[datetime] = []
    for i in range(cfg.run_count):
        delta = timedelta(seconds=step * i)
        schedule.append(start_dt + delta)

    # ensure final anchor is exactly aligned even with floating point rounding
    schedule[-1] = end_dt
    return schedule


def _zoneinfo_from_datetime(dt: datetime) -> ZoneInfo | None:
    tzinfo = dt.tzinfo
    if tzinfo is None:
        return None
    if isinstance(tzinfo, ZoneInfo):
        return tzinfo
    tz_name = tzinfo.tzname(dt)
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return None
    return None


def find_next_run_datetime(
    now: datetime,
    schedule: Sequence[datetime],
    timezone: ZoneInfo | None = None,
) -> datetime | None:
    """Return the next scheduled execution time at or after ``now``.

    Parameters
    ----------
    now:
        Reference datetime used to locate the next execution. Naive datetimes
        are interpreted in the detected timezone.
    schedule:
        Collection of scheduled execution times. Entries may be naive or
        timezone aware. The sequence is not required to be sorted.
    timezone:
        Optional override timezone applied when neither ``schedule`` entries
        nor ``now`` provide one. Defaults to the project standard timezone.
    """

    if not schedule:
        return None

    tz_candidate = timezone
    if tz_candidate is None:
        for candidate in schedule:
            candidate_tz = _zoneinfo_from_datetime(candidate)
            if candidate_tz is not None:
                tz_candidate = candidate_tz
                break
    if tz_candidate is None:
        tz_candidate = _zoneinfo_from_datetime(now)
    tz = _coerce_timezone(tz_candidate)

    if now.tzinfo is None:
        localized_now = now.replace(tzinfo=tz)
    else:
        localized_now = now.astimezone(tz)

    def _normalize(entries: Iterable[datetime]) -> list[datetime]:
        normalized: list[datetime] = []
        for entry in entries:
            if entry.tzinfo is None:
                normalized.append(entry.replace(tzinfo=tz))
            else:
                normalized.append(entry.astimezone(tz))
        return normalized

    normalized_schedule = sorted(_normalize(schedule))

    for run in normalized_schedule:
        if run >= localized_now:
            return run

    return None

@dataclass(frozen=True)
class DailyScheduleWindow:
    """Upcoming executions for a given date."""

    date: date
    run_times: tuple[datetime, ...]


def _resolve_schedule_context(
    now: datetime, config: DailyScheduleConfig | None
) -> tuple[ZoneInfo, DailyScheduleConfig, datetime]:
    cfg = config or DailyScheduleConfig()
    tz_candidate: ZoneInfo | None = cfg.timezone
    if tz_candidate is None:
        tz_candidate = _zoneinfo_from_datetime(now)
    tz = _coerce_timezone(tz_candidate)

    effective_cfg = cfg if cfg.timezone is not None else replace(cfg, timezone=tz)

    if now.tzinfo is None:
        localized_now = now.replace(tzinfo=tz)
    else:
        localized_now = now.astimezone(tz)

    return tz, effective_cfg, localized_now


def generate_upcoming_run_windows(
    now: datetime,
    days: int,
    config: DailyScheduleConfig | None = None,
) -> list[DailyScheduleWindow]:
    """Return the remaining executions for each of the next ``days`` days.

    The first window omits past run times relative to ``now`` while subsequent
    windows include the full schedule for their date.
    """

    if days <= 0:
        raise ValueError("days must be greater than 0")

    _tz, effective_cfg, localized_now = _resolve_schedule_context(now, config)

    windows: list[DailyScheduleWindow] = []
    current_date = localized_now.date()
    for offset in range(days):
        target_date = current_date + timedelta(days=offset)
        daily_schedule = generate_daily_schedule(target_date, effective_cfg)
        if offset == 0:
            runs = tuple(run for run in daily_schedule if run >= localized_now)
        else:
            runs = tuple(daily_schedule)
        windows.append(DailyScheduleWindow(date=target_date, run_times=runs))

    return windows


def generate_upcoming_run_times(
    now: datetime,
    days: int,
    config: DailyScheduleConfig | None = None,
) -> list[datetime]:
    """Return scheduled executions from ``now`` across ``days`` days."""

    windows = generate_upcoming_run_windows(now, days, config)
    upcoming: list[datetime] = []
    for window in windows:
        upcoming.extend(window.run_times)
    return upcoming


__all__ = [
    "DailyScheduleConfig",
    "DailyScheduleWindow",
    "generate_daily_schedule",
    "find_next_run_datetime",
    "generate_upcoming_run_windows",
    "generate_upcoming_run_times",
]
