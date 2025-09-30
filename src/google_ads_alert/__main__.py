"""Module entry point to expose ``python -m google_ads_alert``."""

from .cli import main


def _run() -> int:
    return main()


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(_run())
