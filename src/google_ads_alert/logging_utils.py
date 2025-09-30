"""Utilities for configuring consistent project logging."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import IO
from zoneinfo import ZoneInfo

from .forecast import _coerce_timezone


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
DEFAULT_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S %Z"


class _TimezoneAwareFormatter(logging.Formatter):
    """Formatter that renders timestamps in a specific timezone."""

    def __init__(self, timezone: ZoneInfo, fmt: str | None = None, datefmt: str | None = None) -> None:
        default_fmt = fmt or DEFAULT_LOG_FORMAT
        super().__init__(default_fmt, datefmt)
        self._timezone = timezone

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802 - required by logging.Formatter
        dt = datetime.fromtimestamp(record.created, self._timezone)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime(DEFAULT_LOG_DATEFMT)


@dataclass(frozen=True)
class LoggingConfig:
    """Configuration payload for :func:`configure_logging`."""

    level: int | str = logging.INFO
    timezone: ZoneInfo | None = None
    fmt: str | None = None
    datefmt: str | None = None
    stream: IO[str] | None = None


def _clear_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def configure_logging(config: LoggingConfig | None = None) -> logging.Logger:
    """Configure the project logger with timezone-aware formatting."""

    cfg = config or LoggingConfig()
    tz = _coerce_timezone(cfg.timezone)

    logger = logging.getLogger("google_ads_alert")
    logger.setLevel(cfg.level)
    logger.propagate = False

    _clear_handlers(logger)

    handler = logging.StreamHandler(cfg.stream)
    handler.setLevel(cfg.level)
    handler.setFormatter(
        _TimezoneAwareFormatter(
            timezone=tz,
            fmt=cfg.fmt,
            datefmt=cfg.datefmt,
        )
    )
    logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger of the project root logger."""

    base = logging.getLogger("google_ads_alert")
    return base.getChild(name) if name else base


__all__ = ("LoggingConfig", "configure_logging", "get_logger")

