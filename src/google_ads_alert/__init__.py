"""Core package for Google Ads budget alert system."""

from .forecast import (
    DailyForecastInput,
    DailyForecastResult,
    CombinedForecastInput,
    CombinedForecastResult,
    MonthlyPaceInput,
    MonthlyPaceResult,
    calculate_daily_projection,
    calculate_monthly_pace,
    build_combined_forecast,
)
from .schedule import DailyScheduleConfig, generate_daily_schedule
from .notification import SlackNotificationOptions, build_slack_notification_payload

__all__ = [
    "DailyForecastInput",
    "DailyForecastResult",
    "CombinedForecastInput",
    "CombinedForecastResult",
    "MonthlyPaceInput",
    "MonthlyPaceResult",
    "calculate_daily_projection",
    "calculate_monthly_pace",
    "build_combined_forecast",
    "DailyScheduleConfig",
    "generate_daily_schedule",
    "SlackNotificationOptions",
    "build_slack_notification_payload",
]
