"""Notification payload builders for forecast results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from zoneinfo import ZoneInfo

from .forecast import CombinedForecastResult, _coerce_timezone


@dataclass(frozen=True)
class SlackNotificationOptions:
    """Options controlling Slack payload rendering."""

    account_name: str | None = None
    currency_symbol: str = "¥"
    timezone: ZoneInfo | None = None
    include_monthly_section: bool = True
    include_spend_rate: bool = False
    include_average_daily_spend: bool = False


def _format_currency(value: float, currency_symbol: str) -> str:
    formatted = f"{value:,.2f}"
    if formatted.endswith(".00"):
        formatted = formatted[:-3]
    return f"{currency_symbol}{formatted}"


def _format_gap(value: float, currency_symbol: str) -> str:
    if value == 0:
        return _format_currency(0, currency_symbol)

    sign = "+" if value > 0 else "-"
    return f"{sign}{_format_currency(abs(value), currency_symbol)}"


def _format_percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_timestamp(dt: datetime, tz: ZoneInfo) -> str:
    localized = dt.astimezone(tz)
    return localized.strftime("%Y-%m-%d %H:%M %Z")


def _format_optional_percentage(value: Optional[float], fallback: str = "—") -> str:
    if value is None:
        return fallback
    return _format_percentage(value)


def _daily_section(
    forecast: CombinedForecastResult, opts: SlackNotificationOptions
) -> Dict[str, List[Dict[str, str]] | str]:
    daily = forecast.daily
    fields: List[Dict[str, str]] = []

    currency_symbol = opts.currency_symbol

    current_text = (
        f"*本日時点の消化*\n{_format_currency(daily.current_spend, currency_symbol)}"
    )
    fields.append({"type": "mrkdwn", "text": current_text})

    if daily.projected_spend is None:
        projection_text = "*当日24時予測*\n計算可能なデータが不足しています"
    else:
        pieces = [
            _format_currency(daily.projected_spend, currency_symbol),
        ]
        if forecast.daily_budget is not None and forecast.daily_budget > 0:
            pieces.append(
                f"予算 {_format_currency(forecast.daily_budget, currency_symbol)}"
            )
            if forecast.daily_budget_gap is not None:
                pieces.append(
                    f"差分 {_format_gap(forecast.daily_budget_gap, currency_symbol)}"
                )
        if daily.budget_utilization is not None:
            pieces.append(
                f"進捗 {_format_percentage(daily.budget_utilization)}"
            )

        projection_text = f"*当日24時予測*\n" + " / ".join(pieces)

    fields.append({"type": "mrkdwn", "text": projection_text})

    if opts.include_spend_rate:
        if daily.spend_rate_per_hour is None:
            spend_rate_text = "*1時間あたりの消化*\n計算可能なデータが不足しています"
        else:
            spend_rate_text = (
                "*1時間あたりの消化*\n"
                f"{_format_currency(daily.spend_rate_per_hour, currency_symbol)}/時"
            )
        fields.append({"type": "mrkdwn", "text": spend_rate_text})

    return {"type": "section", "fields": fields}


def _monthly_section(
    forecast: CombinedForecastResult, opts: SlackNotificationOptions
) -> Dict[str, List[Dict[str, str]] | str]:
    monthly = forecast.monthly
    fields: List[Dict[str, str]] = []

    currency_symbol = opts.currency_symbol

    days_text = (
        f"*月間累計消化*\n{_format_currency(monthly.month_to_date_spend, currency_symbol)}"
        f" (経過日 {monthly.days_elapsed}/{monthly.days_in_month})"
    )
    fields.append({"type": "mrkdwn", "text": days_text})

    projected_pieces = [
        _format_currency(monthly.projected_month_end_spend, currency_symbol),
    ]
    if forecast.monthly_budget is not None and forecast.monthly_budget > 0:
        projected_pieces.append(
            f"予算 {_format_currency(forecast.monthly_budget, currency_symbol)}"
        )
        if forecast.monthly_budget_gap is not None:
            projected_pieces.append(
                f"差分 {_format_gap(forecast.monthly_budget_gap, currency_symbol)}"
            )
    projected_pieces.append(
        f"進捗 {_format_optional_percentage(monthly.budget_utilization)}"
    )

    projected_text = "*月末着地予測*\n" + " / ".join(projected_pieces)
    fields.append({"type": "mrkdwn", "text": projected_text})

    if opts.include_average_daily_spend:
        average_text = (
            "*平均日次消化*\n"
            f"{_format_currency(monthly.average_daily_spend, currency_symbol)}/日"
        )
        fields.append({"type": "mrkdwn", "text": average_text})

    return {"type": "section", "fields": fields}


def build_slack_notification_payload(
    forecast: CombinedForecastResult,
    options: SlackNotificationOptions | None = None,
) -> Dict[str, object]:
    """Render a Slack-compatible payload describing ``forecast``."""

    opts = options or SlackNotificationOptions()
    tz = _coerce_timezone(opts.timezone)
    as_of = forecast.daily.as_of
    timestamp = _format_timestamp(as_of, tz)

    header_title = (
        f"{opts.account_name}の予算アラート"
        if opts.account_name
        else "広告費予測アラート"
    )

    blocks: List[Dict[str, object]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_title, "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"最終更新: {timestamp}",
                }
            ],
        },
        _daily_section(forecast, opts),
    ]

    if opts.include_monthly_section:
        blocks.append(_monthly_section(forecast, opts))

    fallback_daily = (
        "日次予測計算不可"
        if forecast.daily.projected_spend is None
        else _format_currency(forecast.daily.projected_spend, opts.currency_symbol)
    )
    fallback_monthly: str
    fallback_average: str | None = None
    fallback_spend_rate: str | None = None
    if opts.include_spend_rate:
        if forecast.daily.spend_rate_per_hour is None:
            fallback_spend_rate = "1時間あたりの消化: 計算可能なデータが不足しています"
        else:
            fallback_spend_rate = (
                "1時間あたりの消化: "
                f"{_format_currency(forecast.daily.spend_rate_per_hour, opts.currency_symbol)}/時"
            )

    if opts.include_monthly_section:
        fallback_monthly = _format_currency(
            forecast.monthly.projected_month_end_spend, opts.currency_symbol
        )
        if opts.include_average_daily_spend:
            fallback_average = "平均日次消化: " + _format_currency(
                forecast.monthly.average_daily_spend, opts.currency_symbol
            ) + "/日"
    else:
        fallback_monthly = "—"

    fallback_parts = [
        header_title,
        f"日次予測: {fallback_daily}",
    ]
    if fallback_spend_rate is not None:
        fallback_parts.append(fallback_spend_rate)

    if opts.include_monthly_section:
        fallback_parts.append(f"月末予測: {fallback_monthly}")
        if fallback_average is not None:
            fallback_parts.append(fallback_average)

    return {
        "text": " / ".join(fallback_parts),
        "blocks": blocks,
    }


__all__ = [
    "SlackNotificationOptions",
    "build_slack_notification_payload",
]

