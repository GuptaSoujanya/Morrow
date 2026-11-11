"""python3 -m diagnose [--days 45] [--skip-mail] [--skip-browser] [--sites naukri,hirist] [--no-llm] [--env PATH] [-v]"""

import argparse
import logging
import sys
from typing import Any, Dict, List, Optional

from common import config
from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, configure_logging

logger = logging.getLogger("diagnose")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="diagnose", description=__doc__)
    parser.add_argument("--env", default=None, help="Path to a .env file (default: ./.env)")
    parser.add_argument("--days", type=int, default=45, help="How far back to read the mailbox (default 45)")
    parser.add_argument("--skip-mail", action="store_true", help="Do not read Gmail over IMAP")
    parser.add_argument("--skip-browser", action="store_true", help="Do not open any job board in the saved browser profiles")
    parser.add_argument("--sites", default="naukri,hirist,instahyre,cutshort,wellfound",
                        help="Comma-separated boards to read (default all five)")
    parser.add_argument("--no-llm", action="store_true", help="Classify mail by rules only; never call the model")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _mail(settings, days: int, use_llm: bool) -> Dict[str, Any]:
    from common import llm
    from diagnose import gmail
    from sites_bot.accounts import account_email
    from sites_bot.replies import inboxes

    account = account_email(settings)
    boxes = inboxes(settings, account)
    client = llm.build_client(settings) if use_llm else None
    merged: Optional[Dict[str, Any]] = None
    readable = [(address, password) for address, password in boxes if address and password]
    if not readable:
        from diagnose import gmail_browser

        logger.info("No Gmail app password; reading Gmail through the signed-in browser profile instead")
        result = gmail_browser.audit(settings, days, client)
        if result.get("error"):
            result["error"] += " (Or set GMAIL_APP_PASSWORD in .env to read over IMAP without a browser.)"
        return result
    skipped = [address for address, password in boxes if not password]
    for address, password in readable:
        result = gmail.audit(settings, address, password, days, client)
        if merged is None:
            merged = result
            if skipped:
                merged["skipped_accounts"] = skipped
            continue
        if result.get("error"):
            merged["partial_errors"] = merged.get("partial_errors", []) + [result["error"]]
            continue
        merged["scanned"] += result["scanned"]
        merged["positives"] += result["positives"]
        merged["spam_hiring"] += result["spam_hiring"]
        merged["unplaced"] += result["unplaced"]
        merged["llm_used"] += result["llm_used"]
        merged["account"] = "%s, %s" % (merged["account"], result["account"])
        for folder, count in result["folders"].items():
            merged["folders"][folder] = merged["folders"].get(folder, 0) + count
        for platform, kinds in result["by_platform"].items():
            target = merged["by_platform"].setdefault(platform, {})
            for kind, count in kinds.items():
                target[kind] = target.get(kind, 0) + count
        merged["positive_total"] = len(merged["positives"])
        merged["positive_by_platform"] = gmail._count(merged["positives"], "platform")
        merged["positive_by_kind"] = gmail._count(merged["positives"], "kind")
    return merged or {"error": "No mailbox configured.", "positive_total": 0}


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG
    from diagnose import local, platforms, report, resume, rootcause

    try:
        logger.info("Reading local ledgers, answers, profile, replies")
        local_data = local.analyse(settings)
        resume_data = resume.analyse(settings, local_data["applications"], local_data["profile"])
        mail_data = None
        if not args.skip_mail:
            logger.info("Reading the mailbox (read-only; IMAP with an app password, else the signed-in browser)")
            mail_data = _mail(settings, args.days, not args.no_llm)
        sites_data = None
        if not args.skip_browser:
            wanted = tuple(s.strip() for s in args.sites.split(",") if s.strip())
            sites_data = platforms.read_sites(settings, wanted)
        causes = rootcause.rank(local_data, mail_data, sites_data, resume_data, settings.email)
        written = report.write(settings, local_data, mail_data, sites_data, resume_data, causes)
    except KeyboardInterrupt:
        logger.error("Stopped.")
        return EXIT_FAILED
    except Exception as exc:
        logger.exception("The audit failed: %s", exc)
        return EXIT_FAILED
    print("Report: %s" % written["markdown"])
    print("Data:   %s" % written["json"])
    print()
    for index, cause in enumerate(causes[:8], 1):
        print("%d. [%s] %s" % (index, cause["severity"].upper(), cause["title"]))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
