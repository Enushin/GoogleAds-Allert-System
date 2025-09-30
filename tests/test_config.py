from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from google_ads_alert.config import (
    ApplicationConfig,
    ConfigError,
    SlackConfig,
    load_config,
    load_google_ads_config,
    load_schedule_config,
    load_slack_config,
)
from google_ads_alert.google_ads_client import GoogleAdsClientConfig
from google_ads_alert.schedule import DailyScheduleConfig


def _base_env() -> dict[str, str]:
    return {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "dev-token",
        "GOOGLE_ADS_CLIENT_ID": "client-id",
        "GOOGLE_ADS_CLIENT_SECRET": "client-secret",
        "GOOGLE_ADS_REFRESH_TOKEN": "refresh-token",
        "GOOGLE_ADS_CUSTOMER_ID": "123-456-7890",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.test/T000/B000/XXX",
    }


def test_load_google_ads_config_success() -> None:
    env = _base_env() | {
        "GOOGLE_ADS_TIMEZONE": "UTC",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "987-654-3210",
        "GOOGLE_ADS_ENDPOINT": "https://example.googleapis.com",
    }

    config = load_google_ads_config(env)

    assert isinstance(config, GoogleAdsClientConfig)
    assert config.customer_id == "123-456-7890"
    assert config.credentials.developer_token == "dev-token"
    assert config.credentials.login_customer_id == "987-654-3210"
    assert config.timezone == ZoneInfo("UTC")
    assert config.endpoint == "https://example.googleapis.com"


def test_load_google_ads_config_missing_required() -> None:
    env = _base_env()
    del env["GOOGLE_ADS_CUSTOMER_ID"]

    with pytest.raises(ConfigError):
        load_google_ads_config(env)


def test_load_slack_config_defaults_and_overrides() -> None:
    env = _base_env() | {
        "SLACK_ACCOUNT_NAME": "Marketing Team",
        "SLACK_CURRENCY_SYMBOL": "$",
        "SLACK_TIMEZONE": "UTC",
        "SLACK_INCLUDE_MONTHLY_SECTION": "false",
        "SLACK_INCLUDE_SPEND_RATE": "yes",
    }

    config = load_slack_config(env)

    assert isinstance(config, SlackConfig)
    assert config.webhook_url.endswith("XXX")
    assert config.options.account_name == "Marketing Team"
    assert config.options.currency_symbol == "$"
    assert config.options.timezone == ZoneInfo("UTC")
    assert config.options.include_monthly_section is False
    assert config.options.include_spend_rate is True


def test_load_schedule_config_with_overrides() -> None:
    env = _base_env() | {
        "ALERT_TIMEZONE": "UTC",
        "ALERT_START_HOUR": "9",
        "ALERT_START_MINUTE": "30",
        "ALERT_END_HOUR": "21",
        "ALERT_END_MINUTE": "45",
        "ALERT_RUN_COUNT": "4",
    }

    config = load_schedule_config(env)

    assert isinstance(config, DailyScheduleConfig)
    assert config.timezone == ZoneInfo("UTC")
    assert config.start_hour == 9
    assert config.start_minute == 30
    assert config.end_hour == 21
    assert config.end_minute == 45
    assert config.run_count == 4


def test_load_config_aggregates_sections() -> None:
    env = _base_env() | {
        "GOOGLE_ADS_TIMEZONE": "UTC",
        "ALERT_TIMEZONE": "UTC",
        "ALERT_RUN_COUNT": "1",
        "SLACK_INCLUDE_SPEND_RATE": "true",
        "DAILY_BUDGET": "50000.5",
        "MONTHLY_BUDGET": "1000000",
    }

    config = load_config(env)

    assert isinstance(config, ApplicationConfig)
    assert config.google_ads.timezone == ZoneInfo("UTC")
    assert config.slack.options.include_spend_rate is True
    assert config.schedule.run_count == 1
    assert config.daily_budget == pytest.approx(50000.5)
    assert config.monthly_budget == pytest.approx(1_000_000)


def test_load_slack_config_invalid_boolean_raises() -> None:
    env = _base_env() | {"SLACK_INCLUDE_SPEND_RATE": "maybe"}

    with pytest.raises(ConfigError):
        load_slack_config(env)

