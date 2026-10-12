"""Command-line entry point: one command, run once each morning.

    python3 -m naukri_bot --dry-run        # see what it WOULD apply to
    python3 -m naukri_bot                  # actually apply

The pipeline, in order:

    1. load settings (.env + CLI overrides) and the profile (facts YAML + resume)
    2. open the ledger and ask how much of today's 50-application quota is left
    3. start a verified browser session (fail loudly if login cannot be confirmed)
    4. collect a large candidate pool: freshness-sorted keyword searches derived
       from the resume, plus Naukri's recommended feed as one source among many
    5. rank the pool against the resume -- our score, not Naukri's ordering
    6. drop anything already applied to, stale, or below the score floor
    7. apply one by one, debiting quota only for verified Naukri-native applies,
       abandoning any application whose screening questions cannot be answered
       from the user's own stated facts

Exit codes: 0 ok, 1 configuration problem, 2 login needs a human, 3 run failed.
"""

import argparse
import logging
import random
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

from common.models import (
    ApplyResult,
    ApplyStatus,
    JobPosting,
    Profile,
    RunSummary,
    ScoredJob,
    Settings,
)
from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_LOGIN, EXIT_OK, configure_logging, keep_log

logger = logging.getLogger(__name__)

_EXTERNAL_JOBS_FILE = "data/worklists/external_jobs.md"

# How long a run waits at the start for a person to finish a Google sign-in
# (passkey, phone prompt) before going on without it.
GOOGLE_LOGIN_WAIT_S = 120.0
# One refusal can be a hiccup; two in a row and Naukri has closed for the day.
REFUSALS_BEFORE_STOP = 2

# Generic resume words that make terrible job-search keywords on their own.
_WEAK_KEYWORDS = {
    "python",
    "sql",
    "git",
    "linux",
    "docker",
    "ci/cd",
    "pandas",
    "numpy",
    "aws",
}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="naukri_bot",
        description=(
            "Find the freshest jobs that actually match your resume and apply to "
            "them, without burning your 50/day Naukri quota on bad matches."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Rank and report, but never click Apply. Consumes zero quota.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Apply to at most N jobs this run (never exceeds remaining quota).",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        metavar="S",
        help="Score floor, 0-100. Jobs below this are never applied to.",
    )
    parser.add_argument(
        "--max-days-old",
        type=int,
        default=None,
        metavar="D",
        help="Ignore postings older than D days. Unknown age is kept, not dropped.",
    )
    parser.add_argument(
        "--keywords",
        default=None,
        metavar="K1,K2",
        help="Override the search keywords (default: derived from your resume).",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="Override the search location.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser headless. Login is more likely to be challenged.",
    )
    parser.add_argument(
        "--answer-mode",
        choices=["auto", "propose", "ask"],
        default=None,
        help=(
            "auto: submit grounded answers. propose: log what it would answer and "
            "abstain (recommended for the first few runs). ask: pause for a human."
        ),
    )
    parser.add_argument(
        "--llm-backend",
        choices=["claude-cli", "anthropic", "none"],
        default=None,
        help="Which LLM to use for scoring and screening answers.",
    )
    parser.add_argument(
        "--env",
        default=None,
        metavar="PATH",
        help="Path to the .env file (default: .env beside the package).",
    )
    parser.add_argument(
        "--early-access",
        action="store_true",
        help=(
            "Share interest on Naukri's Early Access roles before applying. "
            "These are saved recruiter searches, not postings, so this costs "
            "none of the 50/day apply quota."
        ),
    )
    parser.add_argument(
        "--early-access-limit",
        type=int,
        default=20,
        metavar="N",
        help=(
            "Maximum Early Access roles to share interest on per run "
            "(default: 20; the listing typically holds ~70)."
        ),
    )
    parser.add_argument(
        "--early-access-only",
        action="store_true",
        help=(
            "Share Early Access interest and stop. No job search, no "
            "applications, no apply quota spent."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Debug logging.",
    )
    return parser.parse_args(argv)


def build_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    """CLI flags win over .env. Only flags the user actually passed appear here."""
    overrides = {}  # type: Dict[str, Any]
    if args.dry_run:
        overrides["dry_run"] = True
    if args.limit is not None:
        overrides["target_applications"] = args.limit
    if args.min_score is not None:
        overrides["min_score"] = args.min_score
    if args.max_days_old is not None:
        overrides["max_days_old"] = args.max_days_old
    if args.keywords is not None:
        overrides["keywords"] = [
            k.strip() for k in args.keywords.split(",") if k.strip()
        ]
    if args.location is not None:
        overrides["location"] = args.location
    if args.headless:
        overrides["headless"] = True
    if args.answer_mode is not None:
        overrides["answer_mode"] = args.answer_mode
    if args.llm_backend is not None:
        overrides["llm_backend"] = args.llm_backend
    return overrides


def derive_keywords(profile: Profile, settings: Settings) -> List[str]:
    """Search terms for the candidate pool.

    Explicit configuration wins. Otherwise the resume decides: job titles first
    (they match how postings are actually worded), then distinctive skills.
    Generic words like "python" are skipped -- they return tens of thousands of
    irrelevant postings and dilute the pool we later have to rank.
    """
    if settings.keywords:
        return settings.keywords

    keywords = []  # type: List[str]
    seen = set()  # type: set

    for title in profile.titles:
        cleaned = title.strip()
        if cleaned and cleaned.lower() not in seen:
            keywords.append(cleaned)
            seen.add(cleaned.lower())

    for skill in profile.skills:
        if len(keywords) >= 8:
            break
        cleaned = skill.strip()
        lowered = cleaned.lower()
        if not cleaned or lowered in seen or lowered in _WEAK_KEYWORDS:
            continue
        # Multi-word skills ("LLM evaluation") are specific enough to search on.
        if " " in cleaned:
            keywords.append(cleaned)
            seen.add(lowered)

    if not keywords:
        logger.warning(
            "No keywords configured and none could be derived from the resume; "
            "falling back to the recommended feed only."
        )
    return keywords


def _pause_between_applications(settings: Settings) -> None:
    """Wait a random interval after an application.

    Applying back to back is the most machine-like thing the run does. Naukri
    does not permit automation at all, so the cost of looking like a person
    browsing is a few minutes and the cost of not doing so is the account.
    """
    low = max(0.0, settings.apply_delay_min_s)
    high = max(low, settings.apply_delay_max_s)
    if high <= 0.0:
        return
    delay = random.uniform(low, high)
    logger.info("Pausing %.0fs before the next job.", delay)
    time.sleep(delay)


def _company_key(company: Optional[str]) -> str:
    """Normalise a company name enough to group its postings together.

    Naukri prints the same employer inconsistently ("Soul Ai", "Soul AI",
    "Soul Ai  "), so the cap has to compare something steadier than the raw
    string. Suffixes like Pvt Ltd are dropped for the same reason.
    """
    if not company:
        return ""
    name = " ".join(company.split()).casefold()
    for suffix in (
        " private limited", " pvt ltd", " pvt. ltd.", " pvt limited",
        " limited", " ltd.", " ltd", " inc.", " inc", " llp", " llc",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip(" .,-")


_EXTERNAL_ARCHIVE_FILE = "data/worklists/external_archive.md"
_EXTERNAL_OPENED_FILE = "data/worklists/external_opened.tsv"
_EXTERNAL_MAX_OPENS = 3
_EXTERNAL_STALE_DAYS = 10


def _read_opened_counts() -> Dict[str, int]:
    """How many times each role has been opened by open-external-jobs.sh.

    Opening a role is the only signal available that the user has dealt with
    it: whether they then applied happens on the employer's own site, which
    nothing here can see. Asking them to maintain a list by hand was the
    alternative, and it would not have been kept up.
    """
    counts: Dict[str, int] = {}
    try:
        with open(_EXTERNAL_OPENED_FILE, "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2 and parts[0].startswith("http"):
                    try:
                        counts[parts[0]] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        pass
    return counts


def _days_since(timestamp: str) -> Optional[int]:
    try:
        seen = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if seen.tzinfo is not None:
        seen = seen.replace(tzinfo=None)
    return max(0, (datetime.now() - seen).days)


def _external_row(scored: ScoredJob, first_seen: str, opens: int) -> str:
    return "| %.1f | %s | %s | %s | %s | %d | %s |" % (
        scored.score,
        (scored.job.title or "-").replace("|", "/"),
        (scored.job.company or "-").replace("|", "/"),
        (scored.job.posted_label or "-").replace("|", "/"),
        first_seen[:10] if first_seen else "-",
        opens,
        scored.job.url,
    )


def _parse_external_rows(path: str) -> Dict[str, Dict[str, str]]:
    """Read the worklist back, accepting both the old and current column counts.

    Roles the bot did not reach in this run must survive: the apply loop stops
    once the target is met, so a role still listed on Naukri can be absent from
    a given run without having gone away. Rebuilding the file from one run's
    findings alone would quietly discard them.
    """
    rows: Dict[str, Dict[str, str]] = {}
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            if not line.startswith("| ") or line.startswith("| score "):
                continue
            # Split from the right: titles contain pipes ("Walk-in || GenAI").
            for fields in (7, 5):
                cells = [
                    cell.strip()
                    for cell in line.strip().strip("|").rsplit("|", fields - 1)
                ]
                if len(cells) != fields or not cells[-1].startswith("http"):
                    continue
                # A five-column row whose title contains pipes also splits into
                # seven, so the wider reading is only accepted when the column
                # that should hold an open count actually holds a number.
                if fields == 7 and not cells[5].isdigit():
                    continue
                if True:
                    url = cells[-1]
                    rows[url] = {
                        "score": cells[0],
                        "title": cells[1],
                        "company": cells[2],
                        "posted": cells[3],
                        "first_seen": cells[4] if fields == 7 else "",
                        "opened": cells[5] if fields == 7 else "0",
                        "url": url,
                    }
                    break
    return rows


def _write_external_jobs(
    jobs: List[ScoredJob],
    history: Optional[Dict[str, Any]] = None,
    announce: bool = True,
) -> None:
    """Merge company-site roles into the worklist, newest first.

    The file is cleared by hand most mornings, so on its own it cannot remember
    which roles have already been offered -- the same ones reappear in Naukri's
    listings day after day and looked new every time. The ledger does remember,
    so roles first seen in this run are listed separately from ones carried
    over, and a role retires itself once it has been opened a few times or once
    Naukri stops listing it.
    """
    if not jobs:
        return

    history = history or {}
    opened = _read_opened_counts()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = _parse_external_rows(_EXTERNAL_JOBS_FILE)

    added = 0
    for scored in jobs:
        url = scored.job.url
        if url not in rows:
            added += 1
        record = history.get(url, {})
        rows[url] = {
            "score": "%.1f" % scored.score,
            "title": (scored.job.title or "-").replace("|", "/"),
            "company": (scored.job.company or "-").replace("|", "/"),
            "posted": (scored.job.posted_label or "-").replace("|", "/"),
            "first_seen": (record.get("first_seen") or today)[:10],
            "opened": str(opened.get(url, 0)),
            "url": url,
        }

    fresh, carried, archived = [], [], []
    for url, row in rows.items():
        recorded = row.get("opened") or "0"
        opens = opened.get(url, int(recorded) if recorded.isdigit() else 0)
        row["opened"] = str(opens)
        last_seen = (history.get(url, {}).get("last_seen") or row["first_seen"])
        stale = _days_since(last_seen)
        if opens >= _EXTERNAL_MAX_OPENS or (
            stale is not None and stale > _EXTERNAL_STALE_DAYS
        ):
            archived.append(row)
        elif row["first_seen"] == today:
            fresh.append(row)
        else:
            carried.append(row)

    def _render(row: Dict[str, str]) -> str:
        return "| %s | %s | %s | %s | %s | %s | %s |" % (
            row["score"], row["title"], row["company"], row["posted"],
            row["first_seen"], row["opened"], row["url"],
        )

    def _by_score(row: Dict[str, str]) -> float:
        try:
            return float(row["score"])
        except ValueError:
            return 0.0

    header = ("| score | role | company | posted | first seen | opened | link |\n"
              "|---|---|---|---|---|---|---|\n")
    try:
        Path(_EXTERNAL_JOBS_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(_EXTERNAL_JOBS_FILE, "w", encoding="utf-8") as handle:
            handle.write(
                "# Roles that apply on the company site\n\n"
                "These cannot be submitted through Naukri and use none of the daily\n"
                "quota. Apply by hand. Updated %s.\n\n"
                "Run ./open-external-jobs.sh to open the new ones. A role retires to\n"
                "%s once it has been opened %d times, or once Naukri has stopped\n"
                "listing it for %d days.\n"
                % (datetime.now().strftime("%Y-%m-%d %H:%M"), _EXTERNAL_ARCHIVE_FILE,
                   _EXTERNAL_MAX_OPENS, _EXTERNAL_STALE_DAYS)
            )
            for label, group in (("New in this run", fresh), ("Seen before", carried)):
                if label == "New in this run" or group:
                    handle.write("\n## %s (%d)\n\n" % (label, len(group)))
                    handle.write(header)
                    for row in sorted(group, key=_by_score, reverse=True):
                        handle.write(_render(row) + "\n")
    except OSError as exc:
        logger.warning("Could not write %s: %s", _EXTERNAL_JOBS_FILE, exc)
        return

    if archived:
        try:
            with open(_EXTERNAL_ARCHIVE_FILE, "a", encoding="utf-8") as handle:
                handle.write("\n## Retired %s (%d)\n\n" % (today, len(archived)))
                handle.write(header)
                for row in sorted(archived, key=_by_score, reverse=True):
                    handle.write(_render(row) + "\n")
        except OSError as exc:
            logger.warning("Could not write %s: %s", _EXTERNAL_ARCHIVE_FILE, exc)

    if announce:
        logger.info(
            "%d company-site role(s) this run, %d new to the list; worklist now "
            "holds %d new and %d carried over, %d retired to %s",
            len(jobs), added, len(fresh), len(carried), len(archived),
            _EXTERNAL_ARCHIVE_FILE,
        )


def _report_plan(
    selected: List[ScoredJob], ranking_module: Any, settings: Settings
) -> None:
    # A dry run exists to be read, so it prints the whole queue including
    # the fallback tiers. A real run prints only what it expects to reach.
    shown = (
        selected
        if settings.dry_run
        else selected[: max(0, settings.target_applications)]
    )
    logger.info(
        "--- application plan (%d shown of %d eligible, best first) ---",
        len(shown),
        len(selected),
    )
    for position, scored in enumerate(shown, start=1):
        logger.info(
            "%2d. [%5.1f] %s @ %s (%s)",
            position,
            scored.score,
            scored.job.title or "<no title>",
            scored.job.company or "<no company>",
            scored.job.posted_label or "age unknown",
        )
        logger.info("      %s", ranking_module.explain(scored))
        logger.info("      via %s", scored.job.source or "unknown source")
        logger.info("      %s", scored.job.url)


def _log_summary(summary: RunSummary, settings: Settings) -> None:
    logger.info("=" * 70)
    if settings.dry_run:
        logger.info("DRY RUN -- nothing was submitted and no quota was used.")
    logger.info("collected            : %d", summary.collected)
    logger.info("ranked               : %d", summary.ranked)
    from common.report import funnel_text

    funnel = funnel_text(_summary_record(summary, settings))
    if funnel:
        logger.info("funnel               : %s", funnel)
    logger.info("attempted            : %d", summary.attempted)
    logger.info("applied (verified)   : %d", summary.applied)
    logger.info("applied, company site: %d", summary.applied_external)
    logger.info("company site, for you: %d", summary.external_manual)
    logger.info("skipped, already done: %d", summary.skipped_already_applied)
    logger.info("skipped, external    : %d", summary.skipped_external)
    logger.info("skipped, unanswerable: %d", summary.skipped_abstained)
    logger.info("errors               : %d", summary.errors)
    logger.info(
        "quota                : %d used before, %d used after (of %d)",
        summary.quota_before,
        summary.quota_after,
        settings.daily_quota,
    )
    if summary.skipped_abstained:
        logger.info(
            "Tip: %d application(s) were abandoned because a screening question "
            "could not be answered from your facts file. Add those facts to %s "
            "and they will go through tomorrow.",
            summary.skipped_abstained,
            settings.profile_path,
        )
    if summary.external_manual:
        logger.info(
            "%d company-site application(s) stopped short of submitting. They are "
            "listed in %s/company_sites.md, and the open questions wait in %s/answers.txt.",
            summary.external_manual,
            settings.data_dir,
            settings.data_dir,
        )
    logger.info("=" * 70)


def _tally(summary: RunSummary, result: ApplyResult) -> None:
    summary.results.append(result)
    summary.attempted += 1
    if result.status == ApplyStatus.APPLIED:
        summary.applied += 1
    elif result.status == ApplyStatus.APPLIED_EXTERNAL:
        summary.applied_external += 1
    elif result.status == ApplyStatus.EXTERNAL_MANUAL:
        summary.external_manual += 1
    elif result.status == ApplyStatus.ALREADY_APPLIED:
        summary.skipped_already_applied += 1
    elif result.status == ApplyStatus.EXTERNAL_SKIPPED:
        summary.skipped_external += 1
    elif result.status == ApplyStatus.ABSTAINED:
        summary.skipped_abstained += 1
    elif result.status in (ApplyStatus.ERROR, ApplyStatus.NO_APPLY_BUTTON):
        summary.errors += 1


def run(
    settings: Settings,
    profile: Profile,
    early_access: bool = False,
    early_access_limit: int = 20,
    early_access_only: bool = False,
) -> RunSummary:
    """Execute one full morning run. Imports are local so that --help and
    configuration errors do not require Selenium to be installed."""
    from . import apply as apply_module
    from common import answers as answers_module
    from . import auth
    from common import browser
    from . import early_access as early_access_module
    from sites_bot import external as external_module
    from common import ledger as ledger_module
    from common import llm
    from . import ranking
    from common import resume as resume_module
    from . import sources

    summary = RunSummary()
    external_module.browser_agent.reset()
    ledger = ledger_module.open_ledger(settings)
    run_id = ledger.start_run()
    driver = None
    profile_resume_changed = False
    resume_tab = None  # type: Optional[_ResumeTab]

    try:
        summary.quota_before = ledger.quota_used()
        remaining = ledger.quota_remaining(settings.daily_quota)
        logger.info(
            "Quota: %d of %d used in the last 24h, %d remaining.",
            summary.quota_before,
            settings.daily_quota,
            remaining,
        )
        if remaining <= 0 and not settings.dry_run:
            if not settings.external_apply or settings.external_apply_limit <= 0:
                logger.warning("Daily quota already exhausted. Nothing to do today.")
                summary.quota_after = summary.quota_before
                return summary
            logger.warning(
                "Daily quota already exhausted; this run applies on company sites only "
                "(up to %d).", settings.external_apply_limit,
            )

        wanted = settings.target_applications
        # Never plan more applications than we are allowed to make.
        budget = min(settings.target_applications, max(remaining, 0))
        if settings.dry_run:
            budget = settings.target_applications
        settings.target_applications = budget

        client = llm.build_client(settings)
        if not client.available():
            logger.warning(
                "No LLM backend available. Ranking falls back to lexical scoring "
                "and every screening question will be abstained on."
            )

        driver = browser.create_driver(settings)

        login_result = auth.ensure_logged_in(driver, settings)
        if not login_result.ok:
            if login_result.needs_manual:
                raise _NeedsHuman(login_result.reason)
            raise RuntimeError("login failed: %s" % login_result.reason)
        logger.info("Login verified.")

        if early_access:
            ea_summary = early_access_module.share_all(
                driver,
                settings,
                ledger,
                limit=early_access_limit,
                dry_run=settings.dry_run,
            )
            logger.info(
                "Early access: %d roles listed, %d shared, %d already shared, "
                "%d failed, %d skipped. No apply quota was used.",
                ea_summary.found,
                ea_summary.shared,
                ea_summary.already_shared,
                ea_summary.failed,
                ea_summary.skipped,
            )
            if ea_summary.aborted_reason:
                logger.warning(
                    "Early access pass stopped early: %s",
                    ea_summary.aborted_reason,
                )
            if early_access_only:
                summary.quota_after = summary.quota_before
                return summary

        keywords = derive_keywords(profile, settings)
        logger.info("Searching with keywords: %s", ", ".join(keywords) or "(none)")

        candidates = sources.collect_candidates(
            driver, settings, keywords, settings.location
        )  # type: List[JobPosting]
        summary.collected = len(candidates)
        logger.info("Collected %d unique candidate postings.", summary.collected)
        if not candidates:
            logger.warning(
                "No postings collected. Naukri's markup may have changed again, or "
                "the search returned nothing. Nothing was applied to."
            )
            summary.quota_after = ledger.quota_used()
            return summary

        for job in candidates:
            ledger.record_seen(job)

        # Age is a hard gate, so applying it before ranking rather than after
        # keeps the LLM budget on jobs that can actually be applied to.
        candidates, dropped_stale = ranking.drop_stale_candidates(candidates, settings)
        summary.too_old = dropped_stale
        if not candidates:
            logger.warning(
                "Every one of the %d collected postings is older than %d days. "
                "Nothing was applied to.",
                summary.collected,
                settings.max_days_old,
            )
            summary.quota_after = ledger.quota_used()
            return summary

        ranked = ranking.rank(profile, candidates, client, settings)
        summary.ranked = len(ranked)
        summary.not_ranked = len(candidates) - len(ranked)
        for scored in ranked:
            ledger.record_seen(scored.job, scored.score)
            if ledger.has_applied(scored.job.job_id):
                summary.already_applied += 1
            elif scored.score < settings.min_score:
                summary.below_score += 1

        rated = sum(1 for scored in ranked if scored.llm_score is not None)
        coverage = (rated / len(ranked)) if ranked else 0.0
        logger.info(
            "LLM ranking covered %d of %d jobs (%.0f%%)",
            rated,
            len(ranked),
            coverage * 100,
        )
        if (
            not settings.dry_run
            and settings.min_llm_rank_coverage > 0
            and coverage < settings.min_llm_rank_coverage
        ):
            # A lexical score and a blended score are different quantities, so
            # min_score no longer means what the user chose and the shortlist is
            # not the one they asked for. Stopping costs a run; applying anyway
            # spends quota on jobs that were never really ranked.
            logger.error(
                "Only %.0f%% of jobs carry an LLM score, below the required %.0f%%. "
                "Ranking is effectively lexical, so min_score means something "
                "different and no application will be sent. Re-run when the LLM "
                "backend is working, or set MIN_LLM_RANK_COVERAGE=0 to accept "
                "lexical-only ranking.",
                coverage * 100,
                settings.min_llm_rank_coverage * 100,
            )
            summary.quota_after = ledger.quota_used()
            return summary

        selected = ranking.select_for_application(
            ranked, settings, ledger.has_applied
        )
        facts = answers_module.facts_fingerprint(profile, settings)
        waiting = ledger.waiting_on_you(facts)
        held = [scored for scored in selected if scored.job.job_id in waiting]
        summary.held_back = len(held)
        if held:
            selected = [scored for scored in selected if scored.job.job_id not in waiting]
            logger.info(
                "Held back %d job(s) that stopped at a question you have not answered "
                "since; fill it in %s or %s and they are tried again.",
                len(held),
                answers_module.answers_file_path(settings),
                settings.profile_path,
            )
        unconfirmed = ledger.sent_unconfirmed()
        sent_before = [scored for scored in selected if scored.job.job_id in unconfirmed]
        if sent_before:
            selected = [scored for scored in selected if scored.job.job_id not in unconfirmed]
            summary.held_back += len(sent_before)
            logger.info(
                "Held back %d company-site job(s) where Submit was already clicked without a "
                "confirmation (%s); check them by hand so nothing is sent twice.",
                len(sent_before),
                ", ".join(scored.job.company or scored.job.title for scored in sent_before),
            )
        summary.eligible = len(selected)
        if not selected:
            logger.warning(
                "Nothing cleared the bar (min score %.0f, max age %d days). "
                "No quota spent.",
                settings.min_score,
                settings.max_days_old,
            )
            summary.quota_after = ledger.quota_used()
            return summary

        _report_plan(selected, ranking, settings)

        if settings.dry_run:
            logger.info("Dry run: stopping before the first click.")
            summary.quota_after = summary.quota_before
            return summary

        answer_engine = answers_module.AnswerEngine(
            ledger, client, profile, settings
        )

        external_jobs: List[ScoredJob] = []
        external_history = ledger.external_history()
        per_company: Dict[str, int] = {}
        tailoring = settings.tailor_resume and not settings.dry_run
        if tailoring:
            resume_tab = _ResumeTab(driver)
        from sites_bot.accounts import google_login, google_refused_today

        if settings.external_apply and settings.google_email and not settings.dry_run and not google_refused_today(settings):
            signed_in, how = google_login(driver, settings, timeout_s=GOOGLE_LOGIN_WAIT_S)
            (logger.info if signed_in else logger.warning)(
                "Google: %s%s", how, "" if signed_in else "; company sites will use email sign-in"
            )
        company_site_tries = 0
        refused_in_a_row = 0
        base_pdf = None  # type: Optional[Path]
        # Naukri's limit is not the employers': once Naukri is closed for the
        # day, company-site postings are still worth applying to.
        naukri_open = settings.target_applications > 0
        # Ten Accenture postings met the same sign-up wall one after another and
        # used up every company-site try; one meeting per company is enough.
        walled: Set[str] = set()

        def sites_left() -> bool:
            return settings.external_apply and company_site_tries < settings.external_apply_limit

        for scored in selected:
            if naukri_open:
                closed = ""
                if summary.applied >= settings.target_applications:
                    logger.info(
                        "Reached the target of %d applications.",
                        settings.target_applications,
                    )
                    if summary.applied >= wanted:
                        break
                    closed = "Naukri's daily quota is used up"
                elif ledger.quota_remaining(settings.daily_quota) <= 0:
                    closed = "Naukri's daily quota is used up"
                if closed:
                    naukri_open = False
                    if not sites_left():
                        logger.warning("%s. Stopping cleanly.", closed)
                        break
                    logger.warning("%s; going on with company sites only.", closed)
            if not naukri_open and not sites_left():
                logger.info("Tried %d company sites; stopping.", company_site_tries)
                break

            # One prolific poster can list a dozen near-identical roles, each
            # scoring well. Left uncapped they take a large share of the day.
            company_key = _company_key(scored.job.company)
            if (
                settings.max_per_company > 0
                and company_key
                and per_company.get(company_key, 0) >= settings.max_per_company
            ):
                logger.info(
                    "Skipping %s @ %s: already applied to %d roles at this company",
                    scored.job.title,
                    scored.job.company,
                    per_company[company_key],
                )
                continue

            if not naukri_open:
                kind = apply_module.apply_button_kind(driver, scored.job)
                if kind == "signed_out":
                    logger.warning("Signed out of Naukri. Stopping.")
                    break
                if kind != "external" or company_key in walled:
                    continue
                company_site_tries += 1
                logger.info(
                    "[company site %d of %d] %s @ %s",
                    company_site_tries,
                    settings.external_apply_limit,
                    scored.job.title,
                    scored.job.company,
                )
                site_pdf = (
                    _tailored_pdf_only(settings, client, scored.job, resume_module)
                    if tailoring
                    else None
                )
                if site_pdf is None and base_pdf is None:
                    base_pdf = _base_pdf(settings, resume_module)
                result = external_module.apply_on_company_site(
                    driver, scored.job, profile, answer_engine, settings,
                    site_pdf or base_pdf,
                ).to_apply_result(scored.job)
            else:
                result = None  # type: Optional[ApplyResult]
            if result is None:
                logger.info(
                    "[%d of %d applied] %s @ %s",
                    summary.applied,
                    settings.target_applications,
                    scored.job.title,
                    scored.job.company,
                )
                tailored_pdf = None  # type: Optional[Path]
                if tailoring:
                    tailored_pdf = _upload_tailored_resume(
                        driver, settings, client, scored.job, resume_module, resume_tab
                    )
                    profile_resume_changed = profile_resume_changed or tailored_pdf is not None
                result = apply_module.apply_to_job(
                    driver, scored.job, profile, answer_engine, settings
                )
            if (
                naukri_open
                and result.status == ApplyStatus.EXTERNAL_SKIPPED
                and sites_left()
                and company_key not in walled
            ):
                company_site_tries += 1
                if tailored_pdf is None and base_pdf is None:
                    base_pdf = _base_pdf(settings, resume_module)
                result = external_module.apply_on_company_site(
                    driver, scored.job, profile, answer_engine, settings,
                    tailored_pdf or base_pdf,
                ).to_apply_result(scored.job)
            if (
                result.status == ApplyStatus.EXTERNAL_MANUAL
                and "the site asks for an account" in (result.detail or "")
                and company_key
            ):
                walled.add(company_key)
            ledger.record_attempt(
                result, title=scored.job.title or "", company=scored.job.company or "",
                facts=facts,
            )
            _tally(summary, result)
            logger.info("      -> %s (%s)", result.status, result.detail or "-")
            sent = result.status in (ApplyStatus.APPLIED, ApplyStatus.APPLIED_EXTERNAL)
            if sent and company_key:
                per_company[company_key] = per_company.get(company_key, 0) + 1
            if (
                sent
                and not settings.dry_run
                and summary.applied < settings.target_applications
            ):
                _pause_between_applications(settings)

            if result.status in (ApplyStatus.EXTERNAL_SKIPPED, ApplyStatus.EXTERNAL_MANUAL):
                external_jobs.append(scored)
                _write_external_jobs(
                    [scored], external_history, announce=False
                )

            if result.status in ApplyStatus.TERMINAL:
                logger.warning(
                    "Naukri reports the daily quota is exhausted. Stopping."
                )
                break
            refused_in_a_row = (
                refused_in_a_row + 1
                if result.status == ApplyStatus.NAUKRI_REFUSED
                else 0
            )
            if naukri_open and refused_in_a_row >= REFUSALS_BEFORE_STOP:
                naukri_open = False
                logger.warning(
                    "Naukri refused %d applications in a row (%r). That is its "
                    "limit for the day; %s",
                    refused_in_a_row,
                    result.detail,
                    "going on with company sites only." if sites_left()
                    else "stopping. Run again tomorrow.",
                )
                if not sites_left():
                    break

        if external_jobs:
            _write_external_jobs(external_jobs, external_history)
        summary.quota_after = ledger.quota_used()
        return summary

    finally:
        if driver is not None and profile_resume_changed:
            # Also on a crash mid-loop: one employer's tailored resume must not
            # stay on the profile for every other recruiter to download.
            try:
                _restore_base_resume(driver, settings, resume_module, resume_tab)
            except Exception as exc:  # must not mask the error that ended the run
                logger.warning(
                    "Could not put the base resume back on the profile (%s). "
                    "Run `python3 -m common.resume --upload`.",
                    exc,
                )
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:  # driver teardown must never mask a real error
                logger.debug("Ignoring driver teardown error: %s", exc)
        try:
            ledger.finish_run(run_id, _summary_record(summary, settings))
        finally:
            ledger.close()


class _ResumeTab:
    """A second tab that stays on the Naukri profile for resume uploads.

    The job page stays loaded in the first tab, so an upload never navigates
    away from it, and each tab can be watched doing its own job.
    """

    def __init__(self, driver: Any) -> None:
        self.driver = driver
        self.handle = None  # type: Optional[str]

    @contextmanager
    def active(self) -> Iterator[None]:
        from selenium.common.exceptions import WebDriverException

        driver = self.driver
        back = driver.current_window_handle
        try:
            if self.handle in driver.window_handles:
                driver.switch_to.window(self.handle)
            else:
                driver.switch_to.new_window("tab")
                self.handle = driver.current_window_handle
                logger.info("      resume: opened a separate tab for the Naukri profile")
        except WebDriverException as exc:
            logger.warning("      resume: no separate tab (%s); uploading from this one", exc)
            self.handle = None
            driver.switch_to.window(back)
        try:
            yield
        finally:
            driver.switch_to.window(back)


def _upload_tailored_resume(
    driver: Any,
    settings: Settings,
    client: Any,
    job: JobPosting,
    resume_module: Any,
    tab: Optional[_ResumeTab] = None,
) -> Optional[Path]:
    """Put a resume tailored to `job` on the profile; its PDF when the profile changed."""
    try:
        pdf, notes = resume_module.build_tailored_pdf(settings, client, job)
        for note in notes:
            logger.info("      resume: %s", note)
        if tab is None:
            resume_module.upload_resume(driver, pdf)
        else:
            with tab.active():
                resume_module.upload_resume(driver, pdf)
    except resume_module.ResumeError as exc:
        logger.warning(
            "      resume: %s; applying with the resume already on the profile", exc
        )
        return None
    logger.info("      resume: uploaded %s", pdf)
    return pdf


def _tailored_pdf_only(
    settings: Settings, client: Any, job: JobPosting, resume_module: Any
) -> Optional[Path]:
    """The resume tailored to `job`, built for a company site and not put on Naukri."""
    try:
        pdf, notes = resume_module.build_tailored_pdf(settings, client, job)
    except resume_module.ResumeError as exc:
        logger.warning("      resume: %s; sending the base resume", exc)
        return None
    for note in notes:
        logger.info("      resume: %s", note)
    return pdf


def _base_pdf(settings: Settings, resume_module: Any) -> Optional[Path]:
    """The untailored resume to attach on company sites, or None without one."""
    try:
        return resume_module.build_base_pdf(settings)
    except resume_module.ResumeError as exc:
        logger.warning("      resume: %s; company sites will get no attachment", exc)
        return None


def _summary_record(summary: RunSummary, settings: Settings) -> Dict[str, Any]:
    """What the runs table keeps for the daily report."""
    return {
        "dry_run": settings.dry_run,
        "collected": summary.collected,
        "ranked": summary.ranked,
        "attempted": summary.attempted,
        "applied": summary.applied,
        "applied_external": summary.applied_external,
        "external_manual": summary.external_manual,
        "skipped_already_applied": summary.skipped_already_applied,
        "skipped_external": summary.skipped_external,
        "skipped_abstained": summary.skipped_abstained,
        "errors": summary.errors,
        "too_old": summary.too_old,
        "not_ranked": summary.not_ranked,
        "below_score": summary.below_score,
        "already_applied": summary.already_applied,
        "held_back": summary.held_back,
        "eligible": summary.eligible,
        "min_score": settings.min_score,
        "target": settings.target_applications,
        "quota_before": summary.quota_before,
        "quota_after": summary.quota_after,
    }


def _restore_base_resume(
    driver: Any, settings: Settings, resume_module: Any, tab: Optional[_ResumeTab] = None
) -> None:
    """Leave the untailored resume on the profile once the run is over."""
    try:
        pdf = resume_module.build_base_pdf(settings)
        if tab is None:
            resume_module.upload_resume(driver, pdf)
        else:
            with tab.active():
                resume_module.upload_resume(driver, pdf)
    except resume_module.ResumeError as exc:
        logger.warning(
            "Could not put the base resume back on the profile (%s); the last "
            "tailored one is still there. Run `python3 -m common.resume --upload`.",
            exc,
        )
        return
    logger.info("Base resume restored on the profile: %s", pdf.name)


class _NeedsHuman(Exception):
    """Login hit a captcha or OTP -- no amount of retrying will fix it."""


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    from common import config
    from common import profile as profile_module

    try:
        settings = config.load_settings(args.env, build_overrides(args))
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG

    problems = settings.validate()
    if problems:
        for problem in problems:
            logger.error("Config: %s", problem)
        logger.error("Fix the above in your .env file (see .env.example).")
        return EXIT_CONFIG
    keep_log(settings, "naukri")
    from common import assist

    assist.run_pass(settings, write=not settings.dry_run)

    try:
        profile = profile_module.load_profile(settings)
    except profile_module.ProfileError as exc:
        logger.error("Could not load your profile: %s", exc)
        # Two different first-run mistakes end up here, and blaming the wrong
        # file sends a new user to edit something that is already correct.
        if "resume" in str(exc).casefold():
            logger.error(
                "RESUME_PATH in your .env points at %s. Set it to a resume "
                "file that exists, in .tex or .txt form.",
                settings.resume_path,
            )
            return EXIT_CONFIG
        logger.error(
            "Copy profile.example.yaml to %s and fill it in.", settings.profile_path
        )
        return EXIT_CONFIG

    logger.info(
        "Profile: %s | %s | %s",
        profile.full_name or "<unnamed>",
        profile.current_location or "<no location>",
        "%.1f yrs experience" % profile.total_experience_years
        if profile.total_experience_years is not None
        else "experience not stated",
    )

    try:
        summary = run(
            settings,
            profile,
            early_access=args.early_access or args.early_access_only,
            early_access_limit=args.early_access_limit,
            early_access_only=args.early_access_only,
        )
    except _NeedsHuman as exc:
        logger.error("Login needs a human: %s", exc)
        logger.error(
            "Run again without --headless, sign in manually when the window "
            "opens, and the session will be reused."
        )
        return EXIT_LOGIN
    except KeyboardInterrupt:
        logger.warning("Interrupted. Applications already made are recorded.")
        return EXIT_FAILED
    except Exception as exc:
        logger.exception("Run failed: %s", exc)
        return EXIT_FAILED

    summary.finished_at = datetime.now().isoformat(timespec="seconds")
    _log_summary(summary, settings)
    assist.run_pass(settings, write=not settings.dry_run)
    from common import report

    report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
