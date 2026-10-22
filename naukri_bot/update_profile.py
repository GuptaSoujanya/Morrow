"""Keep the Naukri profile "recently updated" without spending apply quota.

Recruiter searches on Naukri sort and filter on how recently a profile was
modified, so a profile nobody touched for a week sinks below ones that were.
This module toggles a trailing "." on the resume headline, which Naukri counts
as an update, three times a day. It is a port of the standalone
naukri-auto-updater onto this package's browser session and verified login, so
there is one saved session, one .env and one set of selectors to maintain.

    python3 -m naukri_bot.update_profile --dry-run   # open the editor, change nothing
    python3 -m naukri_bot.update_profile             # toggle the dot once, now
    python3 -m naukri_bot.update_profile --if-due    # only when a daily slot is due
    python3 -m naukri_bot.update_profile --review    # toggle, then the Playwright agent checks the whole profile

--review hands the signed-in browser to the same Playwright browser agent the
job boards use (sites_bot.platforms.update_profile): it compares the profile with
the facts from the resume and profile.yaml, fixes what is missing or out of date,
and saves. The morning pipeline passes it.

--if-due is what the launchd agent installed by scripts/install_profile_updater.sh
runs every 15 minutes: it acts only when the latest passed slot (09:00, 13:30,
18:30) has neither succeeded nor used up its attempts, so a laptop that slept
through two slots catches up once when it wakes, not twice.

The package rule applies here too: nothing is reported as updated unless it was
verified. The editor is read back before Save is clicked, and the profile page is
reloaded and read again after it.

Exit codes match the apply run: 0 ok (or nothing due), 1 configuration problem,
2 login needs a human, 3 update failed.
"""

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from common import report as report_module
from common import resume as resume_module
from common.browser import human_pause, safe_get
from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_LOGIN, EXIT_OK, configure_logging, keep_log, send_alert
from common.models import LoginResult, Settings

logger = logging.getLogger(__name__)

PROFILE_URL = "https://www.naukri.com/mnjuser/profile"


def _profile_board() -> Any:
    from sites_bot.board import Board

    # Only the profile fields matter: Naukri's apply run has its own code (naukri_bot.cli).
    return Board(name="naukri", label="Naukri", home="https://www.naukri.com/", feeds=(), search="",
                 job_link="", job_id="", apply="", applied="", profile_url=PROFILE_URL)


PROFILE_BOARD = _profile_board()
_REVIEW_EXTRA = ("The resume headline was just saved by another step; leave it as it is. Check the key "
                 "skills, profile summary, employment, career profile (preferred locations, expected "
                 "salary, notice period) and IT skills sections.")

_HEADLINE_CARD = ".resumeHeadline"
_EDIT_ICON = ".resumeHeadline span.edit.icon"
_EDITOR = "#resumeHeadlineTxt"
# The Save button is the submit control of the form the editor sits in.
_SAVE_BUTTON = "//*[@id='resumeHeadlineTxt']/ancestor::form[1]//button[@type='submit']"

#: Daily run slots in local time (the machine runs on IST).
SLOTS = (dtime(9, 0), dtime(13, 30), dtime(18, 30))
#: Invocations a slot may fail before it is given up on for the day.
MAX_ATTEMPTS_PER_SLOT = 2
#: Browser attempts within one invocation.
MAX_ATTEMPTS = 3
#: How long a visible browser window stays open for a person to finish a
#: captcha or OTP challenge. Naukri asks for one on the first login from a new
#: browser profile; once it is answered the saved session carries later runs.
MANUAL_LOGIN_TIMEOUT_S = 300


class ProfileUpdateError(RuntimeError):
    """The headline could not be updated, or the update could not be verified."""


class _NeedsHuman(Exception):
    """Login hit a captcha or OTP -- no amount of retrying will fix it."""


@dataclass
class HeadlineUpdate:
    before: str
    after: str
    #: False on a dry run: the editor was opened and read, nothing was saved.
    saved: bool
    resume: Optional[resume_module.ResumeUpload] = None
    resume_error: str = ""
    review_error: str = ""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def toggle_trailing_dot(text: str) -> str:
    """Add a trailing "." if missing, remove it if present."""
    stripped = text.rstrip()
    if stripped.endswith("."):
        return stripped[:-1].rstrip()
    return stripped + "."


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _save_is_shown(shown: str, before: str, after: str) -> bool:
    """Whether the profile page shows the saved headline.

    When the dot was removed, the new headline is a prefix of the old one, so
    its mere presence proves nothing: the old text must have gone as well.
    """
    after_n, before_n = _normalise(after), _normalise(before)
    if after_n not in shown:
        return False
    if before_n != after_n and before_n.startswith(after_n):
        return before_n not in shown
    return True


# ---------------------------------------------------------------------------
# Slot memory: which of today's runs already happened
# ---------------------------------------------------------------------------


def _slot_key(now: datetime, slot: dtime) -> str:
    return "%s %s" % (now.strftime("%Y-%m-%d"), slot.strftime("%H:%M"))


def due_slot(now: datetime, state: Dict[str, Any]) -> Optional[str]:
    """The latest slot today whose time has passed and that has neither
    succeeded nor used up its attempts.

    Only the latest passed slot counts: a laptop asleep through 09:00 and 13:30
    that wakes at 14:00 runs once, for 13:30, rather than twice.
    """
    passed = [slot for slot in SLOTS if now.time() >= slot]
    if not passed:
        return None
    key = _slot_key(now, passed[-1])
    entry = state.get(key, {})
    if entry.get("done") or entry.get("attempts", 0) >= MAX_ATTEMPTS_PER_SLOT:
        return None
    return key


def load_state(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: Dict[str, Any]) -> None:
    # Keep roughly the last two weeks of slots.
    recent = dict(sorted(state.items())[-45:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recent, indent=2), encoding="utf-8")


def mark(path: Path, key: str, done: bool) -> None:
    """Record an attempt at a slot (done=False) or its success (done=True)."""
    state = load_state(path)
    entry = state.setdefault(key, {"attempts": 0})
    if not done:
        entry["attempts"] = entry.get("attempts", 0) + 1
    entry["done"] = bool(entry.get("done")) or done
    entry["last"] = datetime.now().isoformat(timespec="seconds")
    save_state(path, state)


def resume_due(state: Dict[str, Any], pdf: Path, today: Optional[str] = None) -> bool:
    """True unless this exact PDF already went up today."""
    record = state.get("resume") or {}
    today = today or datetime.now().strftime("%Y-%m-%d")
    return record.get("digest") != resume_module.file_digest(pdf) or record.get("date") != today


def mark_resume(path: Path, pdf: Path) -> None:
    state = load_state(path)
    state["resume"] = {
        "digest": resume_module.file_digest(pdf),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "file": str(pdf),
        "last": datetime.now().isoformat(timespec="seconds"),
    }
    save_state(path, state)


# ---------------------------------------------------------------------------
# Browser work
# ---------------------------------------------------------------------------


def _wait(
    driver: Any, condition: Callable[[Any], Any], timeout: float, what: str
) -> Any:
    try:
        return WebDriverWait(driver, timeout).until(condition)
    except TimeoutException:
        raise ProfileUpdateError(
            "%s did not appear within %.0f seconds" % (what, timeout)
        )


def _visible_element(driver: Any, by: str, selector: str) -> Optional[Any]:
    try:
        for element in driver.find_elements(by, selector):
            if element.is_displayed():
                return element
    except (StaleElementReferenceException, WebDriverException) as exc:
        logger.debug("Could not inspect %s (%s): %s", selector, type(exc).__name__, exc)
    return None


def _scroll_to(driver: Any, element: Any) -> None:
    # Naukri's sticky top bar covers anything scrolled only to the viewport edge.
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", element)
    human_pause(0.5, 1.5)


def _click(driver: Any, element: Any) -> None:
    try:
        element.click()
    except (ElementClickInterceptedException, WebDriverException) as exc:
        logger.warning(
            "Click was intercepted (%s); clicking through the DOM instead",
            type(exc).__name__,
        )
        driver.execute_script("arguments[0].click()", element)


def _editor_value(editor: Any) -> str:
    return editor.get_attribute("value") or ""


# React-controlled fields ignore a plain `.value = x`; the prototype setter plus
# an input event is what they listen for.
_SET_VALUE_SCRIPT = (
    "var el = arguments[0], value = arguments[1];"
    "var proto = el.tagName === 'TEXTAREA'"
    "  ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;"
    "Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);"
    "el.dispatchEvent(new Event('input', {bubbles: true}));"
    "el.dispatchEvent(new Event('change', {bubbles: true}));"
)


def _write_editor(driver: Any, editor: Any, text: str) -> None:
    """Replace the editor's text with real key events, falling back to the
    native value setter if the keys did not produce exactly the intended text."""
    editor.click()
    platform_name = str(driver.capabilities.get("platformName", "")).casefold()
    modifier = Keys.COMMAND if "mac" in platform_name else Keys.CONTROL
    editor.send_keys(modifier, "a")
    editor.send_keys(Keys.DELETE)
    # One send_keys call rather than key-by-key: a headline is up to 250
    # characters, and character-at-a-time typing is what left the chatbot
    # drawer stale mid-write.
    editor.send_keys(text)
    if _editor_value(editor) == text:
        return
    logger.warning(
        "Key events did not produce the intended headline; setting it directly"
    )
    driver.execute_script(_SET_VALUE_SCRIPT, editor, text)


def _shown_headline(driver: Any) -> str:
    card = _visible_element(driver, By.CSS_SELECTOR, _HEADLINE_CARD)
    return _normalise(card.text) if card is not None else ""


def update_resume_headline(driver: Any, dry_run: bool = False) -> HeadlineUpdate:
    """Toggle the trailing dot on the resume headline and verify the save.

    With dry_run the editor is opened and read and the Save button is located,
    then the page is reloaded without saving: enough to prove every selector
    still matches Naukri's markup without changing the profile.
    """
    if not safe_get(driver, PROFILE_URL):
        raise ProfileUpdateError("could not open the profile page")
    _wait(
        driver,
        lambda d: _visible_element(d, By.CSS_SELECTOR, _HEADLINE_CARD),
        20,
        "the resume headline card",
    )
    edit = _wait(
        driver,
        lambda d: _visible_element(d, By.CSS_SELECTOR, _EDIT_ICON),
        10,
        "the headline edit control",
    )
    _scroll_to(driver, edit)
    _click(driver, edit)

    editor = _wait(
        driver,
        lambda d: _visible_element(d, By.CSS_SELECTOR, _EDITOR),
        15,
        "the headline editor",
    )
    current = _editor_value(editor)
    if not current.strip():
        raise ProfileUpdateError("the resume headline is empty; set one by hand first")
    new_value = toggle_trailing_dot(current)
    save = _wait(
        driver,
        lambda d: _visible_element(d, By.XPATH, _SAVE_BUTTON),
        5,
        "the Save button",
    )

    if dry_run:
        logger.info(
            "Dry run: the headline would be saved %s a trailing dot (%d characters). "
            "Nothing was changed.",
            "with" if new_value.endswith(".") else "without",
            len(new_value),
        )
        safe_get(driver, PROFILE_URL)  # discard the open editor
        return HeadlineUpdate(before=current, after=new_value, saved=False)

    _write_editor(driver, editor, new_value)
    typed = _editor_value(editor)
    if typed != new_value:
        # A headline is public and shown to every recruiter, so a truncated or
        # doubled one must never be saved. Reloading discards the editor.
        safe_get(driver, PROFILE_URL)
        raise ProfileUpdateError(
            "the editor held %d characters instead of the intended %d; "
            "nothing was saved" % (len(typed), len(new_value))
        )

    _scroll_to(driver, save)
    _click(driver, save)
    _wait(
        driver,
        lambda d: _visible_element(d, By.CSS_SELECTOR, _EDITOR) is None,
        15,
        "the editor to close after Save",
    )
    human_pause(2.0, 4.0)

    if not safe_get(driver, PROFILE_URL):
        raise ProfileUpdateError("could not reload the profile page to verify the save")
    _wait(
        driver,
        lambda d: _visible_element(d, By.CSS_SELECTOR, _HEADLINE_CARD),
        20,
        "the resume headline card after reload",
    )
    if not _save_is_shown(_shown_headline(driver), current, new_value):
        raise ProfileUpdateError(
            "the saved headline is not shown on the profile page after reload"
        )

    logger.info(
        "Headline updated; it now %s with a trailing dot.",
        "ends" if new_value.endswith(".") else "does not end",
    )
    return HeadlineUpdate(before=current, after=new_value, saved=True)


def _screenshot(driver: Any, settings: Settings) -> None:
    directory = Path(settings.screenshot_dir or "data/screenshots")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (
            "profile-update-%s.png" % datetime.now().strftime("%Y%m%d-%H%M%S")
        )
        if driver.save_screenshot(str(path)):
            logger.error("Saved a screenshot of the failure to %s", path)
    except (OSError, WebDriverException) as exc:
        logger.warning(
            "Could not save a failure screenshot (%s): %s", type(exc).__name__, exc
        )


def with_session(settings: Settings, work: Callable[[Any], Any]) -> Any:
    """Verified login, then `work(driver)`; a screenshot if it fails, browser closed."""
    from . import auth
    from common import browser

    driver = browser.create_driver(settings)
    try:
        login_result = auth.ensure_logged_in(driver, settings)
        if not login_result.ok and login_result.needs_manual and not settings.headless:
            # The window is on screen, so a person can answer the challenge in
            # it. Quitting straight away, as the first run did, closed the very
            # window the person was being told to sign in through.
            logger.warning(
                "Naukri is asking for a captcha or OTP (%s). Finish signing in "
                "in the Chrome window; waiting up to %d minutes.",
                login_result.reason,
                MANUAL_LOGIN_TIMEOUT_S // 60,
            )
            if auth.wait_for_manual_login(driver, MANUAL_LOGIN_TIMEOUT_S):
                login_result = LoginResult(ok=True, reason="manual", needs_manual=False)
            else:
                _screenshot(driver, settings)
                raise _NeedsHuman(
                    "%s; nobody finished the sign-in within %d minutes"
                    % (login_result.reason, MANUAL_LOGIN_TIMEOUT_S // 60)
                )
        if not login_result.ok:
            if login_result.needs_manual:
                raise _NeedsHuman(login_result.reason)
            raise ProfileUpdateError("login failed: %s" % login_result.reason)
        logger.info("Login verified.")
        try:
            return work(driver)
        except Exception:
            _screenshot(driver, settings)
            raise
    finally:
        try:
            driver.quit()
        except Exception as exc:  # driver teardown must never mask a real error
            logger.debug("Ignoring driver teardown error: %s", exc)


def review_profile(driver: Any, settings: Settings, profile: Any, dry_run: bool = False) -> bool:
    """The Playwright agent checks the whole profile against the facts and saves it."""
    from sites_bot import platforms

    return platforms.update_profile(driver, PROFILE_BOARD, settings, profile, dry_run=dry_run,
                                    extra=_REVIEW_EXTRA)


def run_once(
    settings: Settings, dry_run: bool = False, resume_pdf: Optional[Path] = None,
    profile: Any = None,
) -> HeadlineUpdate:
    """One browser session: headline toggle, the resume upload when one is due, then
    the agent's profile review when a profile is given."""

    def _work(driver: Any) -> HeadlineUpdate:
        result = update_resume_headline(driver, dry_run=dry_run)
        if resume_pdf is not None:
            try:
                result.resume = resume_module.upload_resume(driver, resume_pdf, dry_run=dry_run)
            except resume_module.ResumeError as exc:
                result.resume_error = str(exc)
                logger.error("Resume upload failed: %s", exc)
                _screenshot(driver, settings)
        if profile is not None and not review_profile(driver, settings, profile, dry_run):
            result.review_error = "the browser agent did not save the profile"
        return result

    return with_session(settings, _work)


def _resume_to_upload(settings: Settings, state_path: Path, dry_run: bool) -> Optional[Path]:
    """The compiled base resume, when UPLOAD_RESUME_DAILY asks for it and it is due."""
    if not settings.upload_resume_daily:
        return None
    try:
        pdf = resume_module.build_base_pdf(settings)
    except resume_module.ResumeError as exc:
        logger.error("Resume not compiled, so not uploaded: %s", exc)
        return None
    if not dry_run and not resume_due(load_state(state_path), pdf):
        logger.info("Resume %s is already on the profile today.", pdf.name)
        return None
    return pdf


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _remember_profile() -> None:
    """Track the update in .memory/profiles.json with the profile link."""
    from common import memory

    try:
        memory.record_profile("naukri", memory.PROFILE_UPDATED, PROFILE_URL, "headline re-saved")
    except OSError as exc:
        logger.warning("Could not note the profile in .memory (%s)", exc)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="naukri_bot.update_profile",
        description=(
            "Keep your Naukri profile 'recently updated' by toggling a trailing "
            "dot on the resume headline. Spends none of the apply quota."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Log in, open the headline editor and read it, then reload without "
            "saving. Ignores DRY_RUN in .env, which only concerns applications."
        ),
    )
    parser.add_argument(
        "--if-due",
        action="store_true",
        help=(
            "Only run when one of the daily slots (09:00, 13:30, 18:30) is due "
            "and not yet done. This is what the launchd agent passes."
        ),
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help=(
            "After the headline, let the Playwright browser agent compare the whole "
            "profile with your facts, fix what is out of date and save it."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser headless. Login is more likely to be challenged.",
    )
    parser.add_argument(
        "--env",
        default=None,
        metavar="PATH",
        help="Path to the .env file (default: .env beside the package).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    from common import config

    overrides = {}  # type: Dict[str, Any]
    if args.headless:
        overrides["headless"] = True
    try:
        settings = config.load_settings(args.env, overrides)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG

    problems = settings.validate()
    if problems:
        for problem in problems:
            logger.error("Config: %s", problem)
        logger.error("Fix the above in your .env file (see .env.example).")
        return EXIT_CONFIG

    state_path = Path(settings.profile_update_state_path)
    slot = None
    if args.if_due:
        slot = due_slot(datetime.now(), load_state(state_path))
        if slot is None:
            logger.debug("No profile-update slot is due.")
            return EXIT_OK
        logger.info("Profile-update slot %s is due.", slot)
        if not args.dry_run:
            mark(state_path, slot, done=False)
    keep_log(settings, "profile-update")

    if settings.max_start_delay_s > 0 and not args.dry_run:
        delay = random.randint(0, settings.max_start_delay_s)
        logger.info("Waiting %d seconds before starting.", delay)
        time.sleep(delay)

    resume_pdf = _resume_to_upload(settings, state_path, args.dry_run)
    profile = None
    if args.review:
        from common import profile as profile_module

        try:
            profile = profile_module.load_profile(settings)
        except Exception as exc:
            logger.error("Could not load the profile facts for --review: %s", exc)
            return EXIT_CONFIG

    last_error = None  # type: Optional[BaseException]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = run_once(settings, dry_run=args.dry_run, resume_pdf=resume_pdf, profile=profile)
        except _NeedsHuman as exc:
            logger.error("Login needs a human: %s", exc)
            logger.error(
                "Run again without --headless and finish the captcha or OTP in the "
                "Chrome window within %d minutes; the session is then saved and "
                "later runs will not ask again.",
                MANUAL_LOGIN_TIMEOUT_S // 60,
            )
            send_alert(settings, "Naukri profile update: login needs a human (%s)" % exc)
            return EXIT_LOGIN
        except KeyboardInterrupt:
            logger.warning("Interrupted.")
            return EXIT_FAILED
        except Exception as exc:
            last_error = exc
            logger.error("Attempt %d of %d failed: %s", attempt, MAX_ATTEMPTS, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(30 * attempt)
            continue

        if result.saved and slot is not None:
            mark(state_path, slot, done=True)
        if result.saved:
            _remember_profile()
        logger.info(
            "%s (%d -> %d characters).",
            "Profile updated" if result.saved else "Dry run finished; nothing was changed",
            len(result.before),
            len(result.after),
        )
        if result.resume is not None and result.resume.uploaded and resume_pdf is not None:
            mark_resume(state_path, resume_pdf)
            logger.info("Resume on the profile: %s (%s).", result.resume.file_name, result.resume.shown)
        if not args.dry_run:
            report_module.update_quietly(settings)
        if result.resume_error:
            send_alert(settings, "Naukri resume upload failed: %s" % result.resume_error)
            return EXIT_FAILED
        if result.review_error:
            send_alert(settings, "Naukri profile review failed: %s" % result.review_error)
            return EXIT_FAILED
        return EXIT_OK

    if not args.dry_run:
        report_module.update_quietly(settings)
    send_alert(
        settings,
        "Naukri profile update failed after %d attempts: %s" % (MAX_ATTEMPTS, last_error),
    )
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
