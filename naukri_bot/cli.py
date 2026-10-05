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
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    ApplyResult,
    ApplyStatus,
    JobPosting,
    Profile,
    RunSummary,
    ScoredJob,
    Settings,
)

logger = logging.getLogger(__name__)

_EXTERNAL_JOBS_FILE = "external_jobs.md"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_LOGIN = 2
EXIT_FAILED = 3

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


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Selenium and urllib3 are noisy at DEBUG and tell us nothing useful.
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("WDM").setLevel(logging.WARNING)


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


def _write_external_jobs(jobs: List[ScoredJob], announce: bool = True) -> None:
    """Merge this run's company-site roles into the standing to-do list.

    The file is a worklist the user works through by hand over several days,
    not a per-run log, so the same role surfacing in three runs must appear
    once. Existing rows are read back and keyed on URL, which is stable across
    runs in a way the title is not.
    """
    if not jobs:
        return

    rows: Dict[str, str] = {}
    try:
        with open(_EXTERNAL_JOBS_FILE, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("| ") or line.startswith("| score "):
                    continue
                # Split from the right: Naukri titles contain pipes
                # ("Walk-in || GenAI Developer"), which produced more than five
                # fields and silently dropped the row on the next merge. Three
                # saved roles were lost this way before it was noticed.
                cells = [cell.strip() for cell in line.strip().strip("|").rsplit("|", 4)]
                if len(cells) == 5 and cells[4].startswith("http"):
                    rows[cells[4]] = line.rstrip("\n")
    except OSError:
        pass  # first run, or unreadable: start from what this run found

    added = 0
    for scored in jobs:
        url = scored.job.url
        if url in rows:
            continue
        # Escape pipes on the way in so a title cannot break the table either.
        rows[url] = "| %.1f | %s | %s | %s | %s |" % (
            scored.score,
            (scored.job.title or "-").replace("|", "/"),
            (scored.job.company or "-").replace("|", "/"),
            (scored.job.posted_label or "-").replace("|", "/"),
            url,
        )
        added += 1

    def _score_of(row: str) -> float:
        try:
            return float(row.strip().strip("|").split("|", 1)[0].strip())
        except ValueError:
            return 0.0

    ordered = sorted(rows.values(), key=_score_of, reverse=True)
    try:
        with open(_EXTERNAL_JOBS_FILE, "w", encoding="utf-8") as handle:
            handle.write(
                "# Roles that apply on the company site\n\n"
                "These cannot be submitted through Naukri and use none of the\n"
                "daily quota. Apply by hand. Updated %s.\n\n"
                % datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            handle.write("| score | role | company | posted | link |\n")
            handle.write("|---|---|---|---|---|\n")
            for row in ordered:
                handle.write(row + "\n")
    except OSError as exc:
        logger.warning("Could not write %s: %s", _EXTERNAL_JOBS_FILE, exc)
        return

    if announce:
        logger.info(
            "%d company-site role(s) this run, %d new; %s now lists %d to apply to by hand",
            len(jobs),
            added,
            _EXTERNAL_JOBS_FILE,
            len(ordered),
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
            "%2d. [%5.1f] [tier %s] %s @ %s (%s)",
            position,
            scored.score,
            ranking_module.tier_of(scored, settings) or "-",
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
    logger.info("attempted            : %d", summary.attempted)
    logger.info("applied (verified)   : %d", summary.applied)
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
    logger.info("=" * 70)


def _tally(summary: RunSummary, result: ApplyResult) -> None:
    summary.results.append(result)
    summary.attempted += 1
    if result.status == ApplyStatus.APPLIED:
        summary.applied += 1
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
    from . import answers as answers_module
    from . import auth
    from . import browser
    from . import early_access as early_access_module
    from . import ledger as ledger_module
    from . import llm
    from . import ranking
    from . import sources

    summary = RunSummary()
    ledger = ledger_module.open_ledger(settings)
    driver = None

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
            logger.warning("Daily quota already exhausted. Nothing to do today.")
            summary.quota_after = summary.quota_before
            return summary

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

        login_result = auth.login(driver, settings)
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
        if not candidates:
            logger.warning(
                "Every one of the %d collected postings is older than %d days. "
                "Nothing was applied to.",
                summary.collected,
                max(settings.max_days_old, settings.max_days_old_fallback),
            )
            summary.quota_after = ledger.quota_used()
            return summary

        ranked = ranking.rank(profile, candidates, client, settings)
        summary.ranked = len(ranked)

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
        per_company: Dict[str, int] = {}

        for scored in selected:
            if summary.applied >= settings.target_applications:
                logger.info(
                    "Reached the target of %d applications.",
                    settings.target_applications,
                )
                break
            if ledger.quota_remaining(settings.daily_quota) <= 0:
                logger.warning("Quota exhausted mid-run. Stopping cleanly.")
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

            logger.info(
                "[%d of %d applied] [tier %s] %s @ %s",
                summary.applied,
                settings.target_applications,
                ranking.tier_of(scored, settings) or "-",
                scored.job.title,
                scored.job.company,
            )
            result = apply_module.apply_to_job(
                driver, scored.job, profile, answer_engine, settings
            )
            ledger.record_attempt(result)
            _tally(summary, result)
            if result.status == ApplyStatus.APPLIED and company_key:
                per_company[company_key] = per_company.get(company_key, 0) + 1
            logger.info("      -> %s (%s)", result.status, result.detail or "-")

            if result.status == ApplyStatus.EXTERNAL_SKIPPED:
                external_jobs.append(scored)
                _write_external_jobs([scored], announce=False)

            if result.status in ApplyStatus.TERMINAL:
                logger.warning(
                    "Naukri reports the daily quota is exhausted. Stopping."
                )
                break

        if external_jobs:
            _write_external_jobs(external_jobs)
        summary.quota_after = ledger.quota_used()
        return summary

    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:  # driver teardown must never mask a real error
                logger.debug("Ignoring driver teardown error: %s", exc)
        ledger.close()


class _NeedsHuman(Exception):
    """Login hit a captcha or OTP -- no amount of retrying will fix it."""


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    from . import config
    from . import profile as profile_module

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

    try:
        profile = profile_module.load_profile(settings)
    except profile_module.ProfileError as exc:
        logger.error("Could not load your profile: %s", exc)
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
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
