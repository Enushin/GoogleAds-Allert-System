import logging

from zoneinfo import ZoneInfo

from google_ads_alert import LoggingConfig, configure_logging, get_logger


class _BufferHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        self.records.append(record)


def test_configure_logging_sets_timezone_for_formatter():
    logger = configure_logging(LoggingConfig(timezone=ZoneInfo("Asia/Tokyo")))

    handler = logger.handlers[0]
    formatter = handler.formatter
    record = logging.LogRecord(
        name=logger.name,
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="テスト",
        args=(),
        exc_info=None,
    )

    formatted_time = formatter.formatTime(record)
    assert formatted_time.endswith("JST")


def test_get_logger_returns_child_logger():
    base = configure_logging()
    assert base.name == "google_ads_alert"
    child = get_logger("worker")

    assert child.name.endswith("worker")

    buffer = _BufferHandler()
    child.addHandler(buffer)
    child.setLevel(logging.INFO)
    child.propagate = False

    child.info("message")
    assert buffer.records
