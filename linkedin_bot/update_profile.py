"""Keep the LinkedIn profile in step with the resume, through the Playwright browser agent.

    python3 -m linkedin_bot.update_profile --dry-run   # sign in, open the profile, change nothing
    python3 -m linkedin_bot.update_profile             # the agent checks and saves the profile

The browser signs in the same way the poster does (linkedin_bot.cli), then hands
the session to the browser agent the job boards use (sites_bot.platforms.update_profile).
It compares headline, about, experience and skills with the facts from the resume
and profile.yaml, fixes what is out of date and saves. Nothing is posted.

Exit codes: 0 ok, 1 configuration problem, 2 login needs a human, 3 update failed.
"""

import argparse
import logging
import sys
from typing import List, Optional

from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_LOGIN, EXIT_OK, configure_logging, keep_log
from sites_bot.board import Board

logger = logging.getLogger(__name__)

# /in/me/ redirects to the signed-in member's own profile.
PROFILE_URL = "https://www.linkedin.com/in/me/"

# Only the profile fields matter; LinkedIn is not one of the apply boards.
PROFILE_BOARD = Board(name="linkedin", label="LinkedIn", home="https://www.linkedin.com/", feeds=(), search="",
                      job_link="", job_id="", apply="", applied="", profile_url=PROFILE_URL)

# LinkedIn's sections and rules (no network posts, no Open to Work) are in its system prompt:
# sites_bot/skills/profile-update/boards/linkedin.md.


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="linkedin_bot.update_profile",
        description="Bring the LinkedIn profile in step with the resume through the Playwright browser agent.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Sign in and open the profile, then stop without changing anything.")
    parser.add_argument("--env", default=None, metavar="PATH", help="Path to the .env file.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    from common import profile as profile_module
    from sites_bot import platforms

    from . import cli
    from . import config as config_module

    try:
        settings = config_module.load_settings(args.env)
        profile = profile_module.load_profile(settings.naukri)
    except Exception as exc:
        logger.error("Could not load settings or profile facts: %s", exc)
        return EXIT_CONFIG
    keep_log(settings.naukri, "linkedin-profile")

    try:
        with cli.signed_in_browser(settings) as driver:
            saved = platforms.update_profile(driver, PROFILE_BOARD, settings.naukri, profile,
                                             dry_run=args.dry_run)
    except cli._NeedsHuman as exc:
        logger.error("LinkedIn login needs a human: %s", exc)
        return EXIT_LOGIN
    except Exception as exc:
        logger.error("LinkedIn profile update failed: %s", exc)
        return EXIT_FAILED
    return EXIT_OK if saved else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
