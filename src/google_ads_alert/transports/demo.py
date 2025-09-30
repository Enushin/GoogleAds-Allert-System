"""Deterministic transport useful for local development and demos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable, Mapping

from ..config import ConfigError
from ..google_ads_client import GoogleAdsClientConfig, GoogleAdsSearchTransport


_DATE_RANGE_RE = re.compile(
    r"WHERE\s+segments\.date\s+BETWEEN\s+'(\d{4}-\d{2}-\d{2})'\s+AND\s+'(\d{4}-\d{2}-\d{2})'"
)

_DEFAULT_DAILY_COST = 50_000.0
_DEFAULT_MONTH_TO_DATE_COST = 1_200_000.0


def _parse_cost(value: str | None, *, key: str, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"Invalid numeric value for {key}: {value}") from exc


def _to_micros(amount: float) -> int:
    return int(round(amount * 1_000_000))


@dataclass(frozen=True)
class DemoTransport:
    """Simple transport that returns fixed spend totals."""

    daily_cost_micros: int
    month_to_date_cost_micros: int

    def search(self, customer_id: str, query: str) -> Iterable[dict]:
        match = _DATE_RANGE_RE.search(query)
        if not match:
            raise ConfigError(
                "Demo transport received an unsupported query. "
                "Expected a GAQL date BETWEEN clause."
            )

        start = date.fromisoformat(match.group(1))
        end = date.fromisoformat(match.group(2))

        if start == end:
            total = self.daily_cost_micros
        else:
            total = self.month_to_date_cost_micros

        return [{"metrics": {"cost_micros": str(total)}}]


def build_transport(
    config: GoogleAdsClientConfig, env: Mapping[str, str]
) -> GoogleAdsSearchTransport:
    """Factory compatible with ``GOOGLE_ADS_TRANSPORT`` for demo usage."""

    daily_cost = _parse_cost(env.get("DEMO_DAILY_COST"), key="DEMO_DAILY_COST", default=_DEFAULT_DAILY_COST)
    month_cost = _parse_cost(
        env.get("DEMO_MONTH_TO_DATE_COST"),
        key="DEMO_MONTH_TO_DATE_COST",
        default=_DEFAULT_MONTH_TO_DATE_COST,
    )

    return DemoTransport(
        daily_cost_micros=_to_micros(daily_cost),
        month_to_date_cost_micros=_to_micros(month_cost),
    )


__all__ = ["DemoTransport", "build_transport"]
