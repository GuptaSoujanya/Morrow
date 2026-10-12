"""What every bot's command line shares: exit codes, logging, the saved run log, alerts."""

import json
import logging
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Settings

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_LOGIN = 2
EXIT_FAILED = 3


_LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(name)s  %(message)s"


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=_LOG_FORMAT,
        datefmt="%H:%M:%S",
    )
    # Selenium and urllib3 are noisy at DEBUG and tell us nothing useful.
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("WDM").setLevel(logging.WARNING)


class _KeptLog(logging.FileHandler):
    pass


def keep_log(settings: Settings, tool: str, now: Optional[datetime] = None) -> Optional[Path]:
    """Also write this run's log to reports/<date>/logs/, next to the day's report."""
    now = now or datetime.now()
    path = (
        Path(settings.report_dir or "reports")
        / now.strftime("%Y-%m-%d")
        / "logs"
        / ("%s-%s.log" % (tool, now.strftime("%H%M%S")))
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h, _KeptLog)]:
        root.removeHandler(old)
        old.close()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = _KeptLog(str(path), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save this run's log to %s: %s", path, exc)
        return None
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(handler)
    logger.info("This run's log: %s", path)
    return path


def send_alert(settings: Settings, message: str) -> None:
    """Telegram message on failure; a no-op unless both values are configured."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return
    url = "https://api.telegram.org/bot%s/sendMessage" % settings.telegram_bot_token
    body = json.dumps({"chat_id": settings.telegram_chat_id, "text": message})
    request = urllib.request.Request(
        url, data=body.encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=15)
    except (OSError, ValueError) as exc:  # alerting must never mask the real failure
        logger.warning("Telegram alert failed (%s): %s", type(exc).__name__, exc)
