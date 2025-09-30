from __future__ import annotations

"""Environment driven configuration loading helpers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import os

from zoneinfo import ZoneInfo

from .forecast import _coerce_timezone
from .google_ads_client import GoogleAdsClientConfig, GoogleAdsCredentials
from .notification import SlackNotificationOptions
from .schedule import DailyScheduleConfig


class ConfigError(ValueError):
    """Raised when configuration values are missing or invalid."""


@dataclass(frozen=True)
class SlackConfig:
    """Slack specific configuration including the webhook and payload options."""

    webhook_url: str
    options: SlackNotificationOptions


@dataclass(frozen=True)
class ApplicationConfig:
    """Aggregate configuration required to run the alert workflow."""

    google_ads: GoogleAdsClientConfig
    slack: SlackConfig
    schedule: DailyScheduleConfig
    daily_budget: float | None = None
    monthly_budget: float | None = None


def _read_env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    if env is None:
        return os.environ
    return env


def _get_required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _get_optional(env: Mapping[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_timezone(value: str | None) -> ZoneInfo | None:
    if not value:
        return None
    try:
        return ZoneInfo(value)
    except Exception as exc:  # pragma: no cover - ZoneInfo raises various errors
        raise ConfigError(f"Invalid timezone identifier: {value}") from exc


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"Expected integer for value '{value}'") from exc


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"Expected float for value '{value}'") from exc


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise ConfigError(f"Expected boolean value for '{value}'")


def load_google_ads_config(env: Mapping[str, str] | None = None) -> GoogleAdsClientConfig:
    """Build :class:`GoogleAdsClientConfig` from environment variables."""

    values = _read_env(env)
    credentials = GoogleAdsCredentials(
        developer_token=_get_required(values, "GOOGLE_ADS_DEVELOPER_TOKEN"),
        client_id=_get_required(values, "GOOGLE_ADS_CLIENT_ID"),
        client_secret=_get_required(values, "GOOGLE_ADS_CLIENT_SECRET"),
        refresh_token=_get_required(values, "GOOGLE_ADS_REFRESH_TOKEN"),
        login_customer_id=_get_optional(values, "GOOGLE_ADS_LOGIN_CUSTOMER_ID"),
    )

    timezone = _parse_timezone(_get_optional(values, "GOOGLE_ADS_TIMEZONE"))
    endpoint = _get_optional(values, "GOOGLE_ADS_ENDPOINT")

    return GoogleAdsClientConfig(
        customer_id=_get_required(values, "GOOGLE_ADS_CUSTOMER_ID"),
        credentials=credentials,
        timezone=timezone,
        endpoint=endpoint or GoogleAdsClientConfig.__dataclass_fields__["endpoint"].default,
    )


def load_slack_config(env: Mapping[str, str] | None = None) -> SlackConfig:
    """Build :class:`SlackConfig` using environment variables."""

    values = _read_env(env)
    webhook_url = _get_required(values, "SLACK_WEBHOOK_URL")
    timezone = _parse_timezone(_get_optional(values, "SLACK_TIMEZONE"))
    options = SlackNotificationOptions(
        account_name=_get_optional(values, "SLACK_ACCOUNT_NAME"),
        currency_symbol=(
            _get_optional(values, "SLACK_CURRENCY_SYMBOL")
            or SlackNotificationOptions.__dataclass_fields__["currency_symbol"].default
        ),
        timezone=_coerce_timezone(timezone),
        include_monthly_section=_parse_bool(
            values.get("SLACK_INCLUDE_MONTHLY_SECTION"),
            default=SlackNotificationOptions.__dataclass_fields__["include_monthly_section"].default,
        ),
        include_spend_rate=_parse_bool(
            values.get("SLACK_INCLUDE_SPEND_RATE"),
            default=SlackNotificationOptions.__dataclass_fields__["include_spend_rate"].default,
        ),
    )

    return SlackConfig(webhook_url=webhook_url, options=options)


def load_schedule_config(env: Mapping[str, str] | None = None) -> DailyScheduleConfig:
    """Build :class:`DailyScheduleConfig` from environment variables."""

    values = _read_env(env)
    defaults = DailyScheduleConfig()
    timezone = _parse_timezone(_get_optional(values, "ALERT_TIMEZONE"))
    return DailyScheduleConfig(
        timezone=_coerce_timezone(timezone),
        start_hour=_parse_int(values.get("ALERT_START_HOUR"), default=defaults.start_hour),
        start_minute=_parse_int(values.get("ALERT_START_MINUTE"), default=defaults.start_minute),
        end_hour=_parse_int(values.get("ALERT_END_HOUR"), default=defaults.end_hour),
        end_minute=_parse_int(values.get("ALERT_END_MINUTE"), default=defaults.end_minute),
        run_count=_parse_int(values.get("ALERT_RUN_COUNT"), default=defaults.run_count),
    )


def load_config(env: Mapping[str, str] | None = None) -> ApplicationConfig:
    """Load the aggregated application configuration from ``env``."""

    values = _read_env(env)
    google_ads = load_google_ads_config(values)
    slack = load_slack_config(values)
    schedule = load_schedule_config(values)
    daily_budget = _parse_float(_get_optional(values, "DAILY_BUDGET"))
    monthly_budget = _parse_float(_get_optional(values, "MONTHLY_BUDGET"))

    return ApplicationConfig(
        google_ads=google_ads,
        slack=slack,
        schedule=schedule,
        daily_budget=daily_budget,
        monthly_budget=monthly_budget,
    )


def load_env_file(path: os.PathLike[str] | str, *, encoding: str = "utf-8") -> dict[str, str]:
    """Parse a ``.env`` style file and return its key/value pairs."""

    env_path = Path(path)
    try:
        lines = env_path.read_text(encoding=encoding).splitlines()
    except FileNotFoundError as exc:  # pragma: no cover - Path raises FileNotFoundError
        raise ConfigError(f"Environment file not found: {env_path}") from exc

    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        key, sep, value = line.partition("=")
        if not sep:
            raise ConfigError(f"Invalid environment line: {raw_line!r}")

        key = key.strip()
        if not key:
            raise ConfigError(f"Missing key in environment line: {raw_line!r}")

        value = value.strip()
        if not value:
            values[key] = ""
            continue

        if value[0] in {'"', "'"}:
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise ConfigError(f"Unterminated quoted value in line: {raw_line!r}")
            value = value[1:-1]
        else:
            comment_index = value.find(" #")
            if comment_index != -1:
                value = value[:comment_index].rstrip()

        values[key] = value

    return values


def load_config_from_env_file(
    path: os.PathLike[str] | str,
    *,
    base_env: Mapping[str, str] | None = None,
    override_existing: bool = True,
) -> ApplicationConfig:
    """Load :class:`ApplicationConfig` from a ``.env`` file."""

    file_values = load_env_file(path)
    base_values = dict(_read_env(base_env))

    if override_existing:
        merged: dict[str, str] = {**base_values, **file_values}
    else:
        merged = {**file_values, **{k: v for k, v in base_values.items() if k not in file_values}}

    return load_config(merged)


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
]

