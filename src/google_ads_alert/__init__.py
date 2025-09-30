"""Core package for Google Ads budget alert system."""

from .config import (
    ApplicationConfig,
    ConfigError,
    SlackConfig,
    load_config,
    load_config_from_env_file,
    load_env_file,
    load_google_ads_config,
    load_schedule_config,
    load_slack_config,
)
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
from .google_ads_client import (
    DailyCostSummary,
    GoogleAdsClientConfig,
    GoogleAdsCostService,
    GoogleAdsCredentials,
    GoogleAdsSearchTransport,
    QueryRange,
    build_cost_query,
    build_daily_query_range,
)
from .schedule import (
    DailyScheduleConfig,
    find_next_run_datetime,
    generate_daily_schedule,
)
from .notification import SlackNotificationOptions, build_slack_notification_payload

__all__ = [
    "ApplicationConfig",
    "ConfigError",
    "SlackConfig",
    "load_config",
    "load_config_from_env_file",
    "load_env_file",
    "load_google_ads_config",
    "load_schedule_config",
    "load_slack_config",
    "DailyForecastInput",
    "DailyForecastResult",
    "CombinedForecastInput",
    "CombinedForecastResult",
    "MonthlyPaceInput",
    "MonthlyPaceResult",
    "calculate_daily_projection",
    "calculate_monthly_pace",
    "build_combined_forecast",
    "DailyCostSummary",
    "GoogleAdsClientConfig",
    "GoogleAdsCostService",
    "GoogleAdsCredentials",
    "GoogleAdsSearchTransport",
    "QueryRange",
    "build_cost_query",
    "build_daily_query_range",
    "DailyScheduleConfig",
    "find_next_run_datetime",
    "generate_daily_schedule",
    "SlackNotificationOptions",
    "build_slack_notification_payload",
]
