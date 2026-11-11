"""What every bot's command line shares: exit codes, logging, the saved run log, alerts."""

import json
import logging
import urllib.request
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Optional, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Settings
from . import paths

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_LOGIN = 2
EXIT_FAILED = 3
EXIT_BROWSER_LOCKED = 4
#: The model's session or usage limit was hit; the pipeline pauses the lane instead of failing each job.
EXIT_QUOTA = 5

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _run_days(spec: str) -> Set[int]:
    spec = (spec or "").strip().lower()
    if not spec or spec in ("any", "every day", "everyday", "all"):
        return set(range(7))
    days: Set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, last = (_WEEKDAYS.index(edge.strip()[:3]) for edge in part.split("-", 1))
            span = range(first, last + 1) if first <= last else [*range(first, 7), *range(0, last + 1)]
            days.update(span)
        else:
            days.add(_WEEKDAYS.index(part[:3]))
    return days


def outside_run_window(settings: Settings, now: Optional[datetime] = None) -> str:
    """Why this is not a time to apply (RUN_WINDOW / RUN_DAYS / RUN_TIMEZONE), or "" when it is.

    Employers read applications sent in their working hours; a form submitted at
    02:00 reads as a bot. Boards also throttle by the clock. An empty RUN_WINDOW
    allows any time; a value that cannot be read is logged and ignored, so a typo
    never silently stops every run.
    """
    window = (settings.run_window or "").strip()
    if not window:
        return ""
    try:
        start_text, end_text = (edge.strip() for edge in window.split("-", 1))
        start, end = dtime.fromisoformat(start_text), dtime.fromisoformat(end_text)
        days = _run_days(settings.run_days)
        zone = ZoneInfo(settings.run_timezone or "Asia/Kolkata")
    except (ValueError, ZoneInfoNotFoundError) as exc:
        logger.warning("RUN_WINDOW=%r RUN_DAYS=%r RUN_TIMEZONE=%r could not be read (%s); running anyway",
                       settings.run_window, settings.run_days, settings.run_timezone, exc)
        return ""
    moment = (now or datetime.now(timezone.utc)).astimezone(zone)
    label = "%s %s-%s %s" % (settings.run_days or "every day", start_text, end_text, zone.key)
    if moment.weekday() not in days:
        return "it is %s and the run window is %s" % (moment.strftime("%A"), label)
    # A window that ends before it starts runs overnight: 22:00-06:00 is open at 23:00 and 05:00.
    now_time = moment.time()
    if not (start <= now_time < end if start <= end else now_time >= start or now_time < end):
        return "it is %s and the run window is %s" % (moment.strftime("%H:%M"), label)
    return ""


# The third column used to be the Python module path ("naukri_bot.ranking",
# "sites_bot.external"), which misled: the ranking module serves every bot, and the
# company-site code runs during Naukri, boards and startup runs alike. The column now
# names the part of the tool at work in plain words; see log_label().
_LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(who)-14s %(message)s"

_PACKAGE_LABELS = {
    "naukri_bot": "naukri",
    "startup_bot": "startups",
    "linkedin_bot": "linkedin",
    "sites_bot": "boards",
    "pipeline": "pipeline",
    "common": "run",
}
_MODULE_LABELS = {
    "common.company_outreach": "company emails",
    "common.run": "run",
    "naukri_bot.auth": "naukri sign-in",
    "naukri_bot.sources": "naukri search",
    "naukri_bot.update_profile": "naukri profile",
    "sites_bot.external": "company site",
    "sites_bot.gmail_web": "gmail",
    "sites_bot.platforms": "boards",
    "urllib3": "http",
}
_tool = ""


def log_label(name: str) -> str:
    """Plain-words label for a logger name: 'sites_bot.browser_agent' -> 'browser agent'."""
    if name in ("__main__", "root"):
        return _tool or "main"
    for prefix, label in _MODULE_LABELS.items():
        if name == prefix or name.startswith(prefix + "."):
            return label
    package, _, rest = name.partition(".")
    if package not in _PACKAGE_LABELS:
        return package
    module = rest.split(".")[0]
    if not module or module in ("cli", "__main__"):
        return _PACKAGE_LABELS[package]
    words = module.replace("_", " ")
    return "naukri " + words if package == "naukri_bot" else words


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.who = log_label(record.name)
        return super().format(record)


def configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=[handler])
    # Selenium and urllib3 are noisy at DEBUG and tell us nothing useful.
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("WDM").setLevel(logging.WARNING)


class _KeptLog(logging.FileHandler):
    pass


def keep_log(settings: Settings, tool: str, now: Optional[datetime] = None) -> Optional[Path]:
    """Also write this run's log to user/reports/<date>/logs/, next to the day's report."""
    global _tool
    _tool = tool
    now = now or datetime.now()
    path = (
        Path(settings.report_dir or paths.user("reports"))
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
    handler.setFormatter(_Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
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
        detail = str(exc).replace(settings.telegram_bot_token, "<token>")
        logger.warning("Telegram alert failed (%s): %s", type(exc).__name__, detail)
