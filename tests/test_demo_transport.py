from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

from google_ads_alert.config import ConfigError
from google_ads_alert.google_ads_client import (
    GoogleAdsClientConfig,
    GoogleAdsCostService,
    GoogleAdsCredentials,
)
from google_ads_alert.transports.demo import build_transport


def _build_config() -> GoogleAdsClientConfig:
    return GoogleAdsClientConfig(
        customer_id="123-456-7890",
        credentials=GoogleAdsCredentials(
            developer_token="token",
            client_id="client",
            client_secret="secret",
            refresh_token="refresh",
        ),
        timezone=ZoneInfo("Asia/Tokyo"),
    )


def test_demo_transport_uses_configured_costs() -> None:
    config = _build_config()
    env = {"DEMO_DAILY_COST": "1234.5", "DEMO_MONTH_TO_DATE_COST": "67890.0"}

    transport = build_transport(config, env)
    service = GoogleAdsCostService(config, transport)
    reference = datetime(2024, 6, 15, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    daily = service.fetch_daily_cost(reference)
    monthly = service.fetch_month_to_date_cost(reference)

    assert daily.total_cost == pytest.approx(1234.5)
    assert monthly.total_cost == pytest.approx(67890.0)


def test_demo_transport_defaults_apply_without_env() -> None:
    config = _build_config()
    transport = build_transport(config, {})
    service = GoogleAdsCostService(config, transport)
    reference = datetime(2024, 6, 15, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    daily = service.fetch_daily_cost(reference)
    monthly = service.fetch_month_to_date_cost(reference)

    assert daily.total_cost == pytest.approx(50_000.0)
    assert monthly.total_cost == pytest.approx(1_200_000.0)


@pytest.mark.parametrize(
    "env_key",
    ["DEMO_DAILY_COST", "DEMO_MONTH_TO_DATE_COST"],
)
def test_demo_transport_rejects_invalid_cost_values(env_key: str) -> None:
    config = _build_config()

    with pytest.raises(ConfigError, match=env_key):
        build_transport(config, {env_key: "not-a-number"})


def test_demo_transport_requires_between_clause() -> None:
    config = _build_config()
    transport = build_transport(config, {})

    with pytest.raises(ConfigError):
        list(transport.search(config.customer_id, "SELECT metrics.cost_micros FROM campaign"))
