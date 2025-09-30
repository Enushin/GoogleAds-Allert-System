"""Core package for Google Ads budget alert system."""

from .forecast import (
    DailyForecastInput,
    DailyForecastResult,
    MonthlyPaceInput,
    MonthlyPaceResult,
    calculate_daily_projection,
    calculate_monthly_pace,
)

__all__ = [
    "DailyForecastInput",
    "DailyForecastResult",
    "MonthlyPaceInput",
    "MonthlyPaceResult",
    "calculate_daily_projection",
    "calculate_monthly_pace",
]
