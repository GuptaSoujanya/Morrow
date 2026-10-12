"""Entry point: python3 -m linkedin_bot --dry-run | --propose | --post | --if-due"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_LOGIN, EXIT_OK, configure_logging, keep_log
from common.run import send_alert

from . import config as config_module
from . import publisher
from .card import render_card
from .config import LinkedInSettings, parse_post_time
from .news import pick_article
from .writer import Draft, render_text, write_post

logger = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_DAY = 2


class PosterError(RuntimeError):
    pass


class _NeedsHuman(Exception):
    pass


@dataclass
class Prepared:
    draft: Draft
    card: Path
    text: str


# --- state --------------------------------------------------------------------


def load_state(path: Path) -> Dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("days", {})
    state.setdefault("posted", [])
    state.setdefault("skipped", [])
    return state


def save_state(path: Path, state: Dict[str, Any]) -> None:
    days = state.get("days", {})
    state["days"] = dict(sorted(days.items())[-60:])
    state["posted"] = state.get("posted", [])[-365:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_due(now: datetime, post_time: str, state: Dict[str, Any]) -> bool:
    parsed = parse_post_time(post_time)
    if parsed is None:
        return False
    hour, minute = parsed
    if (now.hour, now.minute) < (hour, minute):
        return False
    entry = state.get("days", {}).get(now.strftime("%Y-%m-%d"), {})
    return not entry.get("done") and entry.get("attempts", 0) < MAX_ATTEMPTS_PER_DAY


def mark_day(path: Path, day: str, done: bool) -> None:
    state = load_state(path)
    entry = state["days"].setdefault(day, {"attempts": 0})
    if not done:
        entry["attempts"] = entry.get("attempts", 0) + 1
    entry["done"] = bool(entry.get("done")) or done
    entry["last"] = datetime.now().isoformat(timespec="seconds")
    save_state(path, state)


def already_posted(state: Dict[str, Any], url: str) -> bool:
    from .news import normalise_url

    key = normalise_url(url)
    return any(normalise_url(e.get("url", "")) == key for e in state.get("posted", []))


# --- drafts -------------------------------------------------------------------


def draft_path(settings: LinkedInSettings, day: str) -> Path:
    return Path(settings.draft_dir) / ("%s.md" % day)


def write_draft(path: Path, draft: Draft, card: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = [
        "---",
        "source_title: %s" % draft.source_title.replace("\n", " "),
        "source_url: %s" % draft.source_url,
        "card: %s" % card,
        "generated_at: %s" % datetime.now().isoformat(timespec="seconds"),
        "---",
        "",
    ]
    path.write_text("\n".join(front) + render_text(draft) + "\n", encoding="utf-8")
    return path


def read_draft(path: Path) -> Tuple[Dict[str, str], str]:
    """Front matter as a dict, then the post text exactly as it will be posted."""
    raw = path.read_text(encoding="utf-8")
    meta = {}  # type: Dict[str, str]
    text = raw
    if raw.startswith("---\n"):
        end = raw.find("\n---\n", 4)
        if end != -1:
            for line in raw[4:end].splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()
            text = raw[end + 5:]
    return meta, text.strip()


# --- the work -----------------------------------------------------------------


def prepare(settings: LinkedInSettings, day: str) -> Prepared:
    """Pick an article, write the post, draw the card. No browser."""
    from common.llm import build_client

    state = load_state(Path(settings.state_path))
    article = pick_article(settings, state)
    if article is None:
        raise PosterError("no fresh article on your topics today; nothing to post")
    logger.info("Reacting to: %s (%s)", article.title, article.url)

    client = build_client(settings.naukri)
    if not client.available():
        raise PosterError("no LLM backend available; set LLM_BACKEND (see .env.example)")
    draft = write_post(client, article)
    if draft is None:
        raise PosterError("could not get a post that passes the voice checks for %s" % article.url)

    card = render_card(
        draft.card_line, article.source, Path(settings.draft_dir) / ("%s.png" % day)
    )
    return Prepared(draft=draft, card=card, text=render_text(draft))


def post_with_browser(
    settings: LinkedInSettings, text: str, card: Path
) -> publisher.PublishResult:
    from common.browser import create_driver

    driver = create_driver(settings.naukri)
    try:
        login = publisher.ensure_logged_in(driver, settings)
        if not login.ok and login.needs_manual and not settings.headless:
            logger.warning(
                "LinkedIn wants a security check (%s). Finish it in the Chrome window; "
                "waiting up to %d minutes.",
                login.reason,
                int(publisher.MANUAL_LOGIN_TIMEOUT_S // 60),
            )
            if publisher.wait_for_manual_login(driver):
                login = publisher.ensure_logged_in(driver, settings)
            else:
                publisher.screenshot(driver, settings.naukri.screenshot_dir)
                raise _NeedsHuman("%s; nobody finished the sign-in" % login.reason)
        if not login.ok:
            if login.needs_manual or login.reason == "bad_credentials":
                raise _NeedsHuman(login.reason)
            raise PosterError("login failed: %s" % login.reason)
        logger.info("Login verified.")
        return publisher.publish(driver, text, str(card), settings.naukri.screenshot_dir)
    finally:
        try:
            driver.quit()
        except Exception as exc:  # teardown must never mask the real outcome
            logger.debug("Ignoring driver teardown error: %s", exc)


def record_posted(
    path: Path, url: str, title: str, day: str, draft: Optional[Path]
) -> None:
    state = load_state(path)
    state["posted"].append(
        {"url": url, "title": title, "date": day, "draft": str(draft) if draft else ""}
    )
    entry = state["days"].setdefault(day, {"attempts": 0})
    entry["done"] = True
    entry["last"] = datetime.now().isoformat(timespec="seconds")
    save_state(path, state)


# --- entry point --------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="linkedin_bot",
        description=(
            "One LinkedIn post a day: a fresh article on your topics, a short "
            "reaction in your own words, an image card, a verified publish."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Find an article, write the post and the card, print the draft. No browser.",
    )
    mode.add_argument(
        "--propose",
        action="store_true",
        help="Like --dry-run, but also save linkedin/drafts/<date>.md and send it on Telegram.",
    )
    mode.add_argument(
        "--post",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "Publish the given draft file, else today's saved draft, else a new one. "
            "Refuses a draft whose article was already posted."
        ),
    )
    mode.add_argument(
        "--if-due",
        action="store_true",
        help=(
            "Once a day after LINKEDIN_POST_TIME: propose a draft, or post it when "
            "LINKEDIN_AUTO_POST=true. This is what the launchd agent passes."
        ),
    )
    parser.add_argument("--headless", action="store_true", help="Run the browser headless.")
    parser.add_argument("--env", default=None, metavar="PATH", help="Path to the .env file.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    return parser.parse_args(argv)


def _load(args: argparse.Namespace) -> Optional[LinkedInSettings]:
    overrides = {}  # type: Dict[str, Any]
    if args.headless:
        overrides["headless"] = True
    try:
        return config_module.load_settings(args.env, overrides)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return None


def _show(prepared: Prepared) -> None:
    print("\n--- draft ---------------------------------------------------------")
    print(prepared.text)
    print("--- card: %s" % prepared.card)
    print("--- source: %s\n" % prepared.draft.source_title)


def _propose(settings: LinkedInSettings, day: str, save: bool) -> Tuple[int, Optional[Prepared]]:
    try:
        prepared = prepare(settings, day)
    except PosterError as exc:
        logger.error("%s", exc)
        return EXIT_FAILED, None
    _show(prepared)
    if save:
        path = write_draft(draft_path(settings, day), prepared.draft, prepared.card)
        logger.info("Draft saved to %s", path)
        send_alert(
            settings.naukri,
            "LinkedIn draft for %s (card: %s)\n\n%s" % (day, prepared.card, prepared.text),
        )
    return EXIT_OK, prepared


def _post(settings: LinkedInSettings, day: str, path_arg: Optional[str]) -> int:
    state_path = Path(settings.state_path)
    state = load_state(state_path)
    source_path = None  # type: Optional[Path]
    if path_arg:
        source_path = Path(path_arg)
    elif draft_path(settings, day).is_file():
        source_path = draft_path(settings, day)

    if source_path is not None:
        meta, text = read_draft(source_path)
        url = meta.get("source_url", "")
        title = meta.get("source_title", "")
        card = Path(meta.get("card", "")) if meta.get("card") else None
        if not text or card is None or not card.is_file():
            logger.error("Draft %s is missing its text or its card image", source_path)
            return EXIT_FAILED
        logger.info("Posting the saved draft %s", source_path)
    else:
        try:
            prepared = prepare(settings, day)
        except PosterError as exc:
            logger.error("%s", exc)
            return EXIT_FAILED
        _show(prepared)
        source_path = write_draft(draft_path(settings, day), prepared.draft, prepared.card)
        text, url, title, card = (
            prepared.text,
            prepared.draft.source_url,
            prepared.draft.source_title,
            prepared.card,
        )

    if url and already_posted(state, url):
        logger.error("That article was already posted (%s); refusing to post it again", url)
        return EXIT_FAILED

    try:
        result = post_with_browser(settings, text, card)
    except _NeedsHuman as exc:
        logger.error("LinkedIn login needs a human: %s", exc)
        send_alert(settings.naukri, "LinkedIn post: login needs a human (%s)" % exc)
        return EXIT_LOGIN
    except PosterError as exc:
        logger.error("%s", exc)
        send_alert(settings.naukri, "LinkedIn post failed: %s" % exc)
        return EXIT_FAILED

    if result.ok:
        record_posted(state_path, url, title, day, source_path)
        logger.info("Posted and verified (%s).", result.detail)
        return EXIT_OK
    if result.stage == "unconfirmed":
        # It may well be live. Marking the day done is what stops a retry
        # from putting a duplicate on a public profile.
        mark_day(state_path, day, done=True)
        send_alert(
            settings.naukri,
            "LinkedIn post unconfirmed: %s. Check your profile before posting again." % result.detail,
        )
        logger.error("Unconfirmed: %s. Check the profile by hand.", result.detail)
        return EXIT_FAILED
    send_alert(settings.naukri, "LinkedIn post failed at %s: %s" % (result.stage, result.detail))
    return EXIT_FAILED


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    settings = _load(args)
    if settings is None:
        return EXIT_CONFIG

    needs_browser = args.post is not None or (args.if_due and settings.auto_post)
    problems = settings.validate(needs_browser)
    if problems:
        for problem in problems:
            logger.error("Config: %s", problem)
        logger.error("Fix the above in your .env file (see .env.example).")
        return EXIT_CONFIG

    day = datetime.now().strftime("%Y-%m-%d")
    state_path = Path(settings.state_path)
    # Dry runs and idle scheduler ticks leave today's report alone.
    acted = bool(args.propose or args.post is not None or args.if_due)

    if not args.if_due:
        keep_log(settings.naukri, "linkedin")
    try:
        if args.dry_run:
            code, _ = _propose(settings, day, save=False)
            return code
        if args.propose:
            code, _ = _propose(settings, day, save=True)
            return code
        if args.post is not None:
            return _post(settings, day, args.post or None)
        if args.if_due:
            if not is_due(datetime.now(), settings.post_time, load_state(state_path)):
                logger.debug("Nothing is due.")
                acted = False
                return EXIT_OK
            mark_day(state_path, day, done=False)
            keep_log(settings.naukri, "linkedin")
            if not settings.auto_post:
                code, _ = _propose(settings, day, save=True)
                if code == EXIT_OK:
                    mark_day(state_path, day, done=True)
                else:
                    send_alert(settings.naukri, "LinkedIn draft for %s could not be written" % day)
                return code
            return _post(settings, day, None)
    except KeyboardInterrupt:
        logger.warning("Interrupted.")
        return EXIT_FAILED
    finally:
        if acted and not args.dry_run:
            from common import report as report_module

            report_module.update_quietly(settings.naukri)

    parse_args(["--help"])
    return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
