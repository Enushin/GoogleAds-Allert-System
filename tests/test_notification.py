from datetime import datetime

from zoneinfo import ZoneInfo

from google_ads_alert import (
    CombinedForecastInput,
    build_combined_forecast,
)
from google_ads_alert.notification import (
    SlackNotificationOptions,
    build_slack_notification_payload,
)


TOKYO = ZoneInfo("Asia/Tokyo")


def test_build_slack_payload_includes_budget_and_progress_details():
    params = CombinedForecastInput(
        as_of=datetime(2024, 4, 15, 12, 0, tzinfo=TOKYO),
        current_spend=100000.0,
        month_to_date_spend=1500000.0,
        daily_budget=200000.0,
        monthly_budget=6000000.0,
    )
    forecast = build_combined_forecast(params)

    payload = build_slack_notification_payload(
        forecast,
        SlackNotificationOptions(account_name="テストアカウント"),
    )

    assert payload["text"].startswith("テストアカウントの予算アラート")

    header_block = payload["blocks"][0]
    assert header_block["text"]["text"] == "テストアカウントの予算アラート"

    context_block = payload["blocks"][1]
    assert "2024-04-15" in context_block["elements"][0]["text"]

    daily_fields = [field["text"] for field in payload["blocks"][2]["fields"]]
    assert any("当日24時予測" in text for text in daily_fields)
    assert any("予算 ¥200,000" in text for text in daily_fields)
    assert any("差分 ¥0" in text for text in daily_fields)

    monthly_fields = [field["text"] for field in payload["blocks"][3]["fields"]]
    assert any("月末着地予測" in text for text in monthly_fields)
    assert any("予算 ¥6,000,000" in text for text in monthly_fields)


def test_build_slack_payload_without_monthly_section():
    params = CombinedForecastInput(
        as_of=datetime(2024, 4, 15, 12, 0, tzinfo=TOKYO),
        current_spend=85000.0,
        month_to_date_spend=1500000.0,
        daily_budget=200000.0,
    )
    forecast = build_combined_forecast(params)

    payload = build_slack_notification_payload(
        forecast,
        SlackNotificationOptions(currency_symbol="$", include_monthly_section=False),
    )

    assert len(payload["blocks"]) == 3
    assert payload["text"].endswith(
        "日次予測: $170,000"
    )


def test_build_slack_payload_formats_budget_gaps_with_signs():
    params = CombinedForecastInput(
        as_of=datetime(2024, 4, 15, 12, 0, tzinfo=TOKYO),
        current_spend=150000.0,
        month_to_date_spend=100000.0,
        daily_budget=200000.0,
        monthly_budget=400000.0,
    )
    forecast = build_combined_forecast(params)

    payload = build_slack_notification_payload(forecast)

    daily_fields = [field["text"] for field in payload["blocks"][2]["fields"]]
    assert any("差分 +¥100,000" in text for text in daily_fields)

    monthly_fields = [field["text"] for field in payload["blocks"][3]["fields"]]
    assert any("差分 -¥200,000" in text for text in monthly_fields)

