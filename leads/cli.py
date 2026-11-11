"""`python3 -m leads` - answer every recruiter lead: Gmail first, then each board's inbox.

    python3 -m leads [--dry-run] [--env PATH] [-v] [--only mail|naukri|hirist|...]...

The daily pipeline runs the same two modules as stages (leads:mail, inbox:<board>); this entry
point is for running them by hand. Each board gets its own browser profile the way the lanes do.
"""

import argparse
import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m leads", description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", default=[], metavar="NAME",
                        help="mail or a board name; repeatable (default: mail, then every board in PLATFORMS and naukri)")
    parser.add_argument("--limit", type=int, help="answers per inbox / board (default LEADS_LIMIT)")
    parser.add_argument("--dry-run", action="store_true", help="read and list, answer nothing")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common import browser_lanes, config
    from common.run import EXIT_CONFIG, EXIT_OK, configure_logging
    from leads import boards, mail

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG
    common = (["--env", args.env] if args.env else []) + (["-v"] if args.verbose else [])
    common += ["--dry-run"] if args.dry_run else []
    common += ["--limit", str(args.limit)] if args.limit is not None else []
    wanted = [name.lower() for name in args.only] or ["mail", "naukri", *settings.platforms]
    worst = EXIT_OK
    for name in wanted:
        if name == "mail":
            code = mail.main(list(common))
        elif name in boards.SITES:
            saved = dict(os.environ)
            try:
                if name in browser_lanes.BOARD_LANES and settings.browser_profile_dir:
                    os.environ.update(browser_lanes.prepare(name, settings.browser_profile_dir))
                code = boards.main(list(common) + ["--board", name])
            finally:
                os.environ.clear()
                os.environ.update(saved)
        else:
            logger.error("Unknown lead source %r; use mail or one of %s", name, ", ".join(boards.SITES))
            code = EXIT_CONFIG
        logger.info("leads %s -> exit %d", name, code)
        worst = max(worst, code)
    return worst


if __name__ == "__main__":
    sys.exit(main())
