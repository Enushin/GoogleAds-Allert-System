"""Core package for Google Ads budget alert system."""

from .forecast import (
    DailyForecastInput,
    DailyForecastResult,
    MonthlyPaceInput,
    MonthlyPaceResult,
    calculate_daily_projection,
    calculate_monthly_pace,
)
from .schedule import DailyScheduleConfig, generate_daily_schedule

__all__ = [
    "DailyForecastInput",
    "DailyForecastResult",
    "MonthlyPaceInput",
    "MonthlyPaceResult",
    "calculate_daily_projection",
    "calculate_monthly_pace",
    "DailyScheduleConfig",
    "generate_daily_schedule",
]
