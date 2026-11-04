"""Apply to startup jobs: python3 -m startup_bot [--limit N] [--dry-run] [--no-tailor] [--headless].

Its own bot, apart from Naukri and the boards. Each run:

1. reads Y Combinator's job posts and this month's Hacker News "Who is hiring?"
   thread (sites_bot.startup_jobs), keeping India and remote-for-India posts;
2. ranks them with the same scorer as every other bot, skipping jobs already
   applied to, held for your answers, or possibly sent already;
3. for a post with an apply link, opens it in this bot's own browser and
   applies like a company site (sites_bot.external), with the tailored resume;
4. for a post with only a hiring address, writes an email draft for you to
   send (sites_bot.cold_email; drafts only, never sent).

Whatever stops for you is listed in user/inputs/startup_jobs.md, kept apart from
Naukri's company_sites.md.
"""

import argparse
import logging
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import paths
from common.models import ApplyResult, ApplyStatus, JobPosting, Settings
from sites_bot import startup_jobs
from sites_bot.startup_jobs import StartupPost

logger = logging.getLogger(__name__)

PENDING_FILE = "startup_jobs.md"
#: apply_on_site's status when the site only takes email and a draft was written instead.
EMAILED = "emailed"
_ACCESS_NEEDED = re.compile(
    r"\bsign[ -]?in\b|\blog[ -]?in\b|\bsigned out\b|\bpassword\b|\botp\b|\bcaptcha\b"
    r"|\b(?:human|browser) verification\b|\b(?:verification|security|one[- ]time) code\b"
    r"|\bcreate (?:an? )?account\b|\baccount (?:creation|registration)\b", re.I)


def emailed_to(driver: Any, settings: Settings, profile: Any) -> str:
    """Only a visible, published application mailto can supply a draft recipient.

    Agent diagnostics often contain the candidate's own sign-in address. They
    are not evidence that the employer accepts applications at that address.
    """
    from sites_bot.application_brain import mailbox

    address = mailbox(driver).strip().lower()
    own = {str(value).strip().lower() for value in (
        settings.email, settings.google_email, settings.company_site_email,
        settings.cold_email_from, getattr(profile, "email", "")) if value}
    if address in own or re.match(r"(?:no-?reply|privacy|legal|support|press|sales)@", address):
        return ""
    return address


def _drafted_jobs(settings: Settings) -> set:
    """Saved drafts are unfinished applications, not new work for another run."""
    from sites_bot.cold_email import read_records

    return {(str(row.get("job_url", "")).strip(), " ".join(str(row.get("title", "")).casefold().split()))
            for row in read_records(settings) if isinstance(row, dict)
            and row.get("job_url") and row.get("title") and row.get("email")
            and row.get("drafted_at") and (row.get("eml") or row.get("gmail_draft"))}


def _record_attempt(ledger: Any, result: Any, job: JobPosting, profile: Any, settings: Settings) -> None:
    """Keep answer-dependent stops held until facts change, but allow access fixes."""
    from common.answers import facts_fingerprint

    facts = facts_fingerprint(profile, settings)
    detail = " ".join([result.detail or "", *list(result.missing or [])])
    if result.status == ApplyStatus.EXTERNAL_MANUAL:
        if _ACCESS_NEEDED.search(detail):
            # Signing in changes the browser session, not the saved profile facts.
            facts = ""
        elif result.missing or re.search(r"\bneeds[_ ]you\b", detail, re.I):
            if "needs you for" not in (result.detail or "").casefold():
                result = replace(result, detail="needs you for: " + (result.detail or "; ".join(result.missing)))
    ledger.record_attempt(result.to_apply_result(job), title=job.title, company=job.company, facts=facts)


def _record_draft(ledger: Any, job: JobPosting, address: str, profile: Any, settings: Settings) -> None:
    from common.answers import facts_fingerprint

    ledger.record_attempt(ApplyResult(job_id=job.job_id, url=job.url, status=ApplyStatus.EXTERNAL_MANUAL,
        detail="needs you for: Review the saved email draft to %s. No application has been submitted." % address),
        title=job.title, company=job.company, facts=facts_fingerprint(profile, settings))


def choose(settings: Settings, profile: Any, ledger: Any, client: Any, limit: int,
           fetch: Any = startup_jobs.fetch_json) -> List[Tuple[StartupPost, float]]:
    """The posts worth applying to today, best first, with their scores."""
    from common import answers as answers_module, guardrails
    from naukri_bot import ranking
    from sites_bot.application_brain import blocked

    posts = {post.job.job_id: post for post in startup_jobs.collect(profile, fetch)}
    jobs = [post.job for post in posts.values()]
    for job in jobs:
        ledger.record_seen(job)
    drafts = _drafted_jobs(settings)
    held = ledger.waiting_on_you(answers_module.facts_fingerprint(profile, settings)) | ledger.sent_unconfirmed()
    jobs = [job for job in jobs if job.job_id not in held and not blocked(settings, job)
            and (job.url.strip(), " ".join(job.title.casefold().split())) not in drafts]
    jobs, own_company = guardrails.drop_own_company(jobs, profile, source="Startup jobs")
    jobs, _ = ranking.drop_stale_candidates(jobs, settings, source="Startup jobs")
    ranked = ranking.rank(profile, jobs, client, settings, source="Startup jobs")
    for scored in ranked:
        ledger.record_seen(scored.job, scored.score, scored.gaps)
    selected = ranking.select_for_application(ranked, replace(settings, target_applications=limit),
                                              ledger.has_applied, source="Startup jobs")
    chosen = [(posts[s.job.job_id], s.score) for s in selected[:limit]]
    logger.info("Startup jobs: %d found, %d ranked, %d chosen", len(posts), len(ranked), len(chosen))
    choose.last = {"collected": len(posts), "ranked": len(ranked), "eligible": len(chosen),
                   "own_company": own_company}
    return chosen


def record_pending(settings: Settings, job: JobPosting, site: str, status: str, detail: str,
                   missing: Optional[List[str]] = None) -> Path:
    """Add or replace this job's entry in user/inputs/startup_jobs.md."""
    path = Path(settings.data_dir or paths.user("inputs")) / PENDING_FILE
    header = ("# Startup applications that need you\n\n"
              "From Y Combinator and Hacker News \"Who is hiring?\". The bot filled what it could and\n"
              "stopped short. Finish each one by hand, or answer the open questions in answers.txt\n"
              "and the next `python3 -m startup_bot` run tries it again. Delete an entry once applied.\n")
    marker = "- Post: %s" % (job.url or "-")
    entry = "\n".join([
        "## %s | %s | %s" % (datetime.now().strftime("%Y-%m-%d %H:%M"), job.company or "Unknown company",
                             job.title or "Role"),
        "- Status: %s" % ("needs you" if status == ApplyStatus.EXTERNAL_MANUAL else status),
        "- Why: %s" % (detail or "-"),
        "- Site: %s" % (site or "-"),
        marker,
    ] + (["- Left for you: %s" % "; ".join(missing)] if missing else [])) + "\n"
    text = path.read_text(encoding="utf-8") if path.exists() else header
    head, _, rest = text.partition("\n## ")
    blocks = [("## " + block).rstrip() + "\n" for block in rest.split("\n## ")] if rest else []
    blocks = [block for block in blocks if marker + "\n" not in block + "\n"] + [entry]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n\n" + "\n".join(blocks), encoding="utf-8")
    return path


def forget_pending(settings: Settings, job: JobPosting) -> None:
    path = Path(settings.data_dir or paths.user("inputs")) / PENDING_FILE
    if not path.exists():
        return
    head, _, rest = path.read_text(encoding="utf-8").partition("\n## ")
    marker = "- Post: %s\n" % (job.url or "-")
    blocks = [("## " + block).rstrip() + "\n" for block in rest.split("\n## ")] if rest else []
    path.write_text(head.rstrip() + "\n\n" + "\n".join(b for b in blocks if marker not in b + "\n"),
                    encoding="utf-8")


def apply_on_site(driver: Any, settings: Settings, profile: Any, engine: Any, client: Any, ledger: Any,
                  post: StartupPost, dry_run: bool, no_tailor: bool) -> str:
    """Apply on the post's own page; the status it ended with."""
    from common import guardrails
    from sites_bot import application_brain, browser_agent
    from sites_bot import external as ext

    job = post.job
    own = guardrails.guard_job(profile, job) or guardrails.own_company(profile, url=post.apply_url)
    if own:
        logger.warning("      -> %s (%s)", ApplyStatus.OWN_COMPANY, guardrails.refusal(own))
        return ApplyStatus.OWN_COMPANY
    prior = application_brain.blocked(settings, job)
    if prior or job.job_id in ledger.sent_unconfirmed():
        logger.info("      -> skipped: a saved application outcome needs review before retrying")
        return ApplyStatus.ALREADY_APPLIED if prior == "confirmed" else ApplyStatus.EXTERNAL_MANUAL
    engine.set_job_context(job)
    resume_pdf = ext.resume_to_attach(settings, client, job, no_tailor)
    if not ext.safe_get(driver, post.apply_url):
        record_pending(settings, job, post.apply_url, ApplyStatus.ERROR, "the page did not open")
        return ApplyStatus.ERROR
    ext.human_pause(1.5, 3.0)
    result = ext.apply_here(driver, job, profile, engine, settings, resume_pdf, dry_run)
    result = browser_agent.take_over(driver, job, profile, settings, resume_pdf, dry_run, result)
    logger.info("      -> %s (%s)", result.status, (result.detail or "")[:250])
    address = emailed_to(driver, settings, profile)
    if (address and result.status == ApplyStatus.EXTERNAL_MANUAL
            and not application_brain.blocked(settings, job)
            and job.job_id not in ledger.sent_unconfirmed()):
        # The site says "email us": that is the application, so it becomes a draft for you to send.
        post.contacts.insert(0, startup_jobs.Contact(address, "hiring"))
        drafted = draft_emails(settings, profile, client, [post], dry_run, driver).get("drafted", 0)
        logger.info("      -> takes applications by email: %s draft for %s", "a" if drafted else "no", address)
        if drafted:
            if not dry_run:
                _record_draft(ledger, job, address, profile, settings)
                forget_pending(settings, job)
            return EMAILED
    if dry_run:
        return result.status
    if job.job_id in ledger.sent_unconfirmed():
        # A concurrent saved uncertainty must remain the latest ledger entry.
        return ApplyStatus.EXTERNAL_MANUAL
    _record_attempt(ledger, result, job, profile, settings)
    if result.status in (ApplyStatus.APPLIED_EXTERNAL, ApplyStatus.ALREADY_APPLIED, ext.GONE):
        forget_pending(settings, job)
    else:
        record_pending(settings, job, result.url or post.apply_url, result.status, result.detail,
                       list(result.missing))
    return result.status


def draft_emails(settings: Settings, profile: Any, client: Any, posts: List[StartupPost],
                 dry_run: bool, driver: Any = None) -> Dict[str, int]:
    """An email draft to each post's hiring address. Drafts only: nothing is sent."""
    from sites_bot import cold_email

    if not posts:
        return {}
    leads = []
    for post in posts:
        job = post.job
        if not dry_run:
            cold_email.record_contacts(settings, job, "Apply by email: %s\n\n%s" % (post.hiring_email, post.text),
                                       job.source)
        leads.append(cold_email.Lead(post.hiring_email.lower(), job.company, job.title, job.url,
                                     job.source, job.description))
    return cold_email.draft_all(settings, profile, client, leads, len(leads), dry_run, driver=driver)


def run(settings: Settings, profile: Any, ledger: Any, client: Any, engine: Any, limit: int, dry_run: bool,
        no_tailor: bool = False, open_browser: Any = None, fetch: Any = startup_jobs.fetch_json,
        check_replies: bool = False) -> Dict[str, int]:
    # The dashboard reads the bot's history from runs: board "startups" is this bot's card.
    start_run = getattr(ledger, "start_run", None)
    run_id = start_run() if callable(start_run) else None
    counts = {}  # type: Dict[str, int]
    try:
        counts = _run(settings, profile, ledger, client, engine, limit, dry_run, no_tailor, open_browser, fetch,
                      check_replies)
    finally:
        if run_id is not None:
            found = getattr(choose, "last", {})
            ledger.finish_run(run_id, {
                "board": "startups", "dry_run": dry_run,
                "collected": found.get("collected", 0), "ranked": found.get("ranked", 0),
                "eligible": found.get("eligible", 0), "own_company": found.get("own_company", 0),
                "attempted": counts.get("applied", 0) + counts.get("need you", 0),
                "applied": counts.get("applied", 0), "applied_external": 0,
                "external_manual": counts.get("need you", 0), "emails_drafted": counts.get("emails drafted", 0),
            })
    return counts


def _replies(settings: Settings, profile: Any, client: Any, ledger: Any, dry_run: bool, driver: Any) -> int:
    """Employers' answers to what was sent, read in the same signed-in Gmail; reply drafts written."""
    from sites_bot import replies
    from sites_bot.cold_email import read_contacts, read_records

    try:
        applications = ledger.recent_applications(limit=1000)
        contacts = read_contacts(settings) + [{"email": r.get("email"), "company": r.get("company"),
                                               "job_url": r.get("job_url")} for r in read_records(settings)]
        found = replies.check(settings, profile, client, applications, contacts, 21, dry_run, driver=driver)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - replies must not cost the applications
        logger.warning("Could not check employer replies: %s", " ".join(str(exc).split())[:200])
        return 0
    logger.info("Employer replies: %s", ", ".join("%s %d" % item for item in found.items()))
    return found.get("drafted", 0)


def _run(settings: Settings, profile: Any, ledger: Any, client: Any, engine: Any, limit: int, dry_run: bool,
         no_tailor: bool, open_browser: Any, fetch: Any, check_replies: bool = False) -> Dict[str, int]:
    chosen = choose(settings, profile, ledger, client, limit, fetch)
    by_email = [post for post, _ in chosen if post.hiring_email]
    on_site = [(post, score) for post, score in chosen if not post.hiring_email and post.apply_url]
    counts = {"chosen": len(chosen), "emails drafted": 0, "applied": 0, "need you": 0,
              "no way to apply": len(chosen) - len(by_email) - len(on_site)}
    if not (on_site or by_email or check_replies):
        return counts
    from common import browser
    from common.ledger import company_key

    # The same cap the Naukri and board loops keep: open applications per company, every bot counted.
    per_company = ledger.open_per_company()
    # One browser for everything: its saved Google session is the Gmail it drafts in and reads.
    driver = (open_browser or browser.create_driver)(settings)
    try:
        counts["emails drafted"] = draft_emails(settings, profile, client, by_email, dry_run, driver).get("drafted", 0)
        for number, (post, score) in enumerate(on_site, 1):
            logger.info("[startup %d of %d] %s @ %s (%.0f): %s", number, len(on_site), post.job.title,
                        post.job.company, score, post.apply_url)
            key = company_key(post.job.company)
            if settings.max_per_company > 0 and key and per_company.get(key, 0) >= settings.max_per_company:
                logger.info("      -> skipped: %d applications already open at this company (cap %d)",
                            per_company[key], settings.max_per_company)
                counts["at the company cap"] = counts.get("at the company cap", 0) + 1
                continue
            try:
                status = apply_on_site(driver, settings, profile, engine, client, ledger, post,
                                       dry_run, no_tailor)
            except Exception as exc:  # noqa: BROAD_EXCEPT_OK - one site's failure costs that site only
                logger.warning("      -> failed: %s", " ".join(str(exc).split())[:200])
                record_pending(settings, post.job, post.apply_url, ApplyStatus.ERROR, str(exc)[:200])
                status = ApplyStatus.ERROR
            if status == EMAILED:
                counts["emails drafted"] += 1
            elif status == "dry_run":
                counts["filled, not sent (dry run)"] = counts.get("filled, not sent (dry run)", 0) + 1
            else:
                counts["applied" if status == ApplyStatus.APPLIED_EXTERNAL else "need you"] += 1
            if status == ApplyStatus.APPLIED_EXTERNAL and key:
                per_company[key] = per_company.get(key, 0) + 1
        if check_replies:
            counts["replies drafted"] = _replies(settings, profile, client, ledger, dry_run, driver)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    logger.info("Startup bot: %s%s", ", ".join("%s %d" % item for item in counts.items()),
                " (dry run)" if dry_run else "")
    return counts


def own_browser(settings: Settings) -> Settings:
    """This bot's own browser profile (lanes/startups), so it never waits on Naukri's open browser.

    The pipeline and the dashboard already hand it that profile; run by hand it is prepared here,
    seeded once from the main profile so existing Google sign-ins carry over.
    """
    from common import browser_lanes

    base = (settings.browser_profile_dir or "").strip()
    if not base or Path(base).name == "startups":
        return settings
    try:
        overrides = browser_lanes.prepare("startups", base)
    except (OSError, ValueError) as exc:
        logger.warning("Using the main browser profile: the startup lane could not be prepared (%s)", exc)
        return settings
    folder = overrides.get("BROWSER_PROFILE_DIR")
    return replace(settings, browser_profile_dir=folder) if folder else settings


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m startup_bot", description=__doc__.split("\n\n")[0])
    parser.add_argument("--limit", type=int, help="how many startup jobs to apply to (default PLATFORM_LIMIT)")
    parser.add_argument("--dry-run", action="store_true", help="fill forms and write drafts to the log, submit nothing")
    parser.add_argument("--ignore-window", action="store_true", help="apply now even outside RUN_WINDOW / RUN_DAYS (default 10:00-18:00 IST, weekdays)")
    parser.add_argument("--no-tailor", action="store_true", help="attach the base resume instead of a tailored one")
    parser.add_argument("--headless", action="store_true", help="run the browser without a window")
    parser.add_argument("--no-replies", action="store_true",
                        help="skip reading employers' replies in the browser's Gmail")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common import config, ledger as ledger_module, llm, profile as profile_module, report
    from common.answers import AnswerEngine
    from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, configure_logging, keep_log, outside_run_window

    args = parse_args(argv)
    configure_logging(args.verbose)
    overrides = {"dry_run": True} if args.dry_run else {}  # type: Dict[str, Any]
    if args.headless:
        overrides["headless"] = True
    try:
        settings = config.load_settings(args.env, overrides)
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    if not args.ignore_window and not settings.dry_run:
        closed = outside_run_window(settings)
        if closed:
            logger.info("Not applying now: %s. Pass --ignore-window to run anyway.", closed)
            return EXIT_OK
    keep_log(settings, "startups")
    settings = own_browser(settings)
    ledger = ledger_module.open_ledger(settings)
    client = llm.build_client(settings)
    engine = AnswerEngine(ledger, client, profile, settings)
    try:
        run(settings, profile, ledger, client, engine,
            args.limit if args.limit is not None else settings.platform_limit, args.dry_run, args.no_tailor,
            check_replies=not args.no_replies)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - CLI boundary
        logger.exception("Startup bot failed: %s", exc)
        return EXIT_FAILED
    finally:
        ledger.close()
    if not args.dry_run:
        report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
