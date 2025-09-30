"""Utility helpers for building alert execution schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List

from zoneinfo import ZoneInfo

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
        Desired number of executions per day. Defaults to three so alerts land
        at 8:00, 14:00, and 20:00 in the Asia/Tokyo timezone.
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
) -> List[datetime]:
    """Return alert run times for ``target_date``.

    The generated schedule always includes the start and end anchors. When
    ``run_count`` is one the result consists of the start hour only. For
    higher counts the remaining entries are evenly spaced between the
    anchors (hour and minute precision). ``run_count`` must be a positive
    integer, otherwise a :class:`ValueError` is raised.
    """

    cfg = config or DailyScheduleConfig()
    if cfg.run_count <= 0:
        raise ValueError("run_count must be a positive integer")

    tz = _coerce_timezone(cfg.timezone)
    start_dt = _build_anchor_datetime(
        target_date, cfg.start_hour, cfg.start_minute, tz
    )
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
    schedule: List[datetime] = []
    for i in range(cfg.run_count):
        delta = timedelta(seconds=step * i)
        schedule.append(start_dt + delta)

    # ensure final anchor is exactly aligned even with floating point rounding
    schedule[-1] = end_dt
    return schedule


__all__ = ["DailyScheduleConfig", "generate_daily_schedule"]
