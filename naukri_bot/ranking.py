"""Deterministic job ranking before the daily application quota is spent.

The lexical score starts from a 20-point neutral baseline.  It then assigns up
to 40 points for skill overlap, 15 for a preferred-title match, 10 for
experience fit, 5 for location fit, and 10 for freshness.  Clearly wrong
titles receive a 35-point penalty, severe experience mismatches a 10-point
penalty, and non-preferred locations a 3-point penalty.  Unknown freshness is
neutral (5 of 10 points).  Freshness decays from 10 points at 0--1 days to zero
at ``Settings.max_days_old`` (the model default, because the public lexical
scoring contract intentionally has no settings argument).
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from common import llm
from common.llm import LLMClient
from common.models import JobPosting, Profile, ScoredJob, Settings, Verdict


logger = logging.getLogger(__name__)


_BASE_SCORE = 20.0
_SKILL_WEIGHT = 40.0
_TITLE_MATCH_BONUS = 15.0
_WRONG_TITLE_PENALTY = 35.0
_EXPERIENCE_FIT_BONUS = 10.0
_EXPERIENCE_MISMATCH_PENALTY = 10.0
_LOCATION_MATCH_BONUS = 5.0
_LOCATION_MISMATCH_PENALTY = 3.0
_FRESHNESS_WEIGHT = 10.0
_UNKNOWN_FRESHNESS_SCORE = 5.0
_LEXICAL_MAX_DAYS_OLD = Settings().max_days_old

_WRONG_TITLES = (
    "sales",
    "bpo",
    "recruiter",
    "hr",
    "manual testing",
    "field",
    "telecaller",
    "insurance",
    "bde",
)
_REMOTE_TERMS = ("remote", "work from home", "wfh")


def _phrase_pattern(phrase: str) -> re.Pattern:
    """Build a case-insensitive, word-bounded pattern for a phrase."""
    return re.compile(r"\b%s\b" % re.escape(phrase.strip()), re.IGNORECASE)


def _parse_experience_range(value: str) -> Optional[Tuple[float, float]]:
    """Parse a Naukri experience label, returning None when it is ambiguous."""
    match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:yrs?|years?)\b",
        value,
        re.IGNORECASE,
    )
    if match is None:
        return None
    minimum = float(match.group(1))
    maximum = float(match.group(2))
    if minimum > maximum:
        return None
    return minimum, maximum


def _is_remote(value: str) -> bool:
    normalised = " ".join(value.casefold().split())
    return any(term in normalised for term in _REMOTE_TERMS)


def lexical_score(profile: Profile, job: JobPosting) -> Tuple[float, List[str]]:
    """Score one job without network access and explain every component."""
    score = _BASE_SCORE
    reasons: List[str] = []
    text = job.text_blob()

    unique_skills = list(
        dict.fromkeys(skill.strip() for skill in profile.skills if skill.strip())
    )
    matched_skills = [skill for skill in unique_skills if _phrase_pattern(skill).search(text)]
    if unique_skills:
        score += _SKILL_WEIGHT * len(matched_skills) / len(unique_skills)
    if matched_skills:
        reasons.append(
            "%d skill matches: %s" % (len(matched_skills), ", ".join(matched_skills))
        )
    else:
        reasons.append("no profile skill matches")

    title_matches = [
        title.strip()
        for title in profile.titles
        if title.strip() and _phrase_pattern(title).search(job.title)
    ]
    wrong_titles = [title for title in _WRONG_TITLES if _phrase_pattern(title).search(job.title)]
    # A preferred-title match is the stronger signal and wins. The penalty list
    # mixes role words that genuinely disqualify, like telecaller, with domain
    # words like insurance or hr, and an AI Engineer at an insurance company is
    # exactly the kind of job wanted. Previously the penalty fired and the bonus
    # was skipped, so "Senior AI Engineer (Insurance Domain)" scored 17 where the
    # same job titled "AI Engineer" scored 67, and it was rejected even when the
    # model rated it 80 out of 100.
    if title_matches:
        score += _TITLE_MATCH_BONUS
        if wrong_titles:
            reasons.append(
                "title matches preferred role '%s'; '%s' treated as a domain, "
                "not the role" % (title_matches[0], wrong_titles[0])
            )
        else:
            reasons.append("title matches preferred role '%s'" % title_matches[0])
    elif wrong_titles:
        score -= _WRONG_TITLE_PENALTY
        reasons.append("title contains '%s' (penalty)" % wrong_titles[0])
    else:
        reasons.append("no preferred title match")

    experience_range = _parse_experience_range(job.experience)
    years = profile.total_experience_years
    if years is None:
        reasons.append("candidate experience is unknown (neutral)")
    elif experience_range is None:
        reasons.append("experience range '%s' is unparseable (neutral)" % job.experience)
    else:
        minimum, maximum = experience_range
        if minimum <= years <= maximum:
            score += _EXPERIENCE_FIT_BONUS
            reasons.append("experience %s fits %g yrs" % (job.experience, years))
        elif minimum - years > 1.5 or years - maximum > 3.0:
            score -= _EXPERIENCE_MISMATCH_PENALTY
            reasons.append("experience %s mismatches %g yrs (penalty)" % (job.experience, years))
        else:
            reasons.append("experience %s is near %g yrs (neutral)" % (job.experience, years))

    preferred_locations = [location.strip() for location in profile.preferred_locations if location.strip()]
    location_casefold = job.location.casefold()
    location_matches = [
        location
        for location in preferred_locations
        if location.casefold() in location_casefold
        or (_is_remote(location) and _is_remote(job.location))
    ]
    if not preferred_locations:
        reasons.append("no preferred locations supplied (neutral)")
    elif location_matches:
        score += _LOCATION_MATCH_BONUS
        reasons.append("location matches '%s'" % location_matches[0])
    else:
        score -= _LOCATION_MISMATCH_PENALTY
        reasons.append("location '%s' is outside preferences (penalty)" % job.location)

    days = job.posted_days_ago
    if days is None:
        score += _UNKNOWN_FRESHNESS_SCORE
        reasons.append("posting age is unknown (neutral)")
    elif days <= 1.0:
        score += _FRESHNESS_WEIGHT
        reasons.append("posted %g day%s ago" % (days, "" if days == 1 else "s"))
    else:
        decay_span = max(1.0, float(_LEXICAL_MAX_DAYS_OLD) - 1.0)
        freshness = _FRESHNESS_WEIGHT * max(
            0.0, 1.0 - (days - 1.0) / decay_span
        )
        score += freshness
        reasons.append("posted %g days ago" % days)

    return round(max(0.0, min(100.0, score)), 2), reasons


def prefilter(profile: Profile, jobs: List[JobPosting], limit: int) -> List[ScoredJob]:
    """Lexically score every job and return the highest-scoring candidates.

    When this cuts, it cuts on lexical score alone, and the final score is
    0.4 lexical + 0.6 LLM -- so a job the lexical rules treat harshly can still
    clear min_score once the model has seen it. A job cut here never gets that
    chance, and the cut was silent, so say when it happens and how good the
    best dropped job looked.
    """
    scored: List[ScoredJob] = []
    for job in jobs:
        score, reasons = lexical_score(profile, job)
        scored.append(
            ScoredJob(job=job, score=score, lexical_score=score, reasons=reasons)
        )
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    keep = max(0, limit)
    if len(scored) > keep:
        dropped = scored[keep:]
        logger.warning(
            "LLM_RANK_TOP_N=%d cut %d of %d candidates before ranking; the best "
            "one dropped scored %.1f lexically against %.1f for the last one "
            "kept. Raise LLM_RANK_TOP_N if those are close.",
            limit,
            len(dropped),
            len(scored),
            dropped[0].score,
            scored[keep - 1].score if keep else 0.0,
        )
    return scored[:keep]


def rank(
    profile: Profile,
    jobs: List[JobPosting],
    client: LLMClient,
    settings: Settings,
) -> List[ScoredJob]:
    """Rank the lexical shortlist, blending optional LLM scores when available."""
    shortlist = prefilter(profile, jobs, settings.llm_rank_top_n)
    llm_results: Dict[str, Dict[str, Any]] = {}
    try:
        client_available = client.available()
        if client_available:
            llm_results = llm.score_jobs(client, profile, [item.job for item in shortlist])
    except Exception as error:  # noqa: BROAD_EXCEPT_OK - optional boundary must not stop applications
        logger.warning("LLM ranking failed; ranking is lexical-only: %s", error)
        client_available = False
        llm_results = {}

    if not client_available:
        logger.warning("LLM unavailable; ranking is lexical-only")
    elif not llm_results:
        logger.warning("LLM returned no scores; ranking is lexical-only")

    for candidate in shortlist:
        llm_result = llm_results.get(candidate.job.job_id)
        if llm_result is not None:
            raw_score = llm_result.get("score")
            try:
                llm_score = max(0.0, min(100.0, float(raw_score)))
            except (TypeError, ValueError):
                llm_score = None
            if llm_score is not None:
                candidate.llm_score = llm_score
                candidate.score = round(0.4 * candidate.lexical_score + 0.6 * llm_score, 2)
                raw_reasons = llm_result.get("reasons")
                if isinstance(raw_reasons, list):
                    candidate.reasons.extend(
                        "LLM: %s" % reason
                        for reason in raw_reasons
                        if isinstance(reason, str)
                    )

        if candidate.score >= 75.0:
            candidate.verdict = Verdict.STRONG
        elif candidate.score >= settings.min_score:
            candidate.verdict = Verdict.POSSIBLE
        else:
            candidate.verdict = Verdict.WEAK

    shortlist.sort(
        key=lambda candidate: (
            -candidate.score,
            candidate.job.posted_days_ago is None,
            candidate.job.posted_days_ago
            if candidate.job.posted_days_ago is not None
            else float("inf"),
        )
    )
    return shortlist


def drop_stale_candidates(
    jobs: List[JobPosting], settings: Settings
) -> Tuple[List[JobPosting], int]:
    """Remove jobs too old to be applied to, before they are sent to the LLM.

    Age is a hard gate, so applying it here rather than after ranking keeps the
    LLM budget on jobs that can actually be applied to: on 25 September that was
    556 of 900 postings scored and then discarded. Because max_candidates is a
    hard cap, those postings also displaced fresher ones from the pool.

    Jobs whose age could not be parsed are kept, because selection treats an
    unknown age as acceptable and a large share of selected jobs have no
    readable age.
    """
    limit = settings.max_days_old
    kept = [
        job
        for job in jobs
        if job.posted_days_ago is None or job.posted_days_ago <= limit
    ]
    dropped = len(jobs) - len(kept)
    if dropped:
        logger.info(
            "Dropped %d of %d candidates older than %d days before ranking; "
            "%d go to the LLM",
            dropped,
            len(jobs),
            limit,
            len(kept),
        )
    return kept, dropped


def select_for_application(
    ranked: List[ScoredJob], settings: Settings, is_already_applied
) -> List[ScoredJob]:
    """Return every applicable candidate, best score first.

    One rule: clear min_score and be no older than max_days_old. The caller
    stops once target_applications have been *submitted*, so this returns
    everything acceptable rather than a fixed slice -- company-site redirects
    and unanswerable questionnaires are only discoverable with a job page open,
    so the queue has to be longer than the target.

    This replaced a three-tier scheme that preferred fresher jobs over
    higher-scoring stale ones. It was removed because the orders it produced
    were identical to plain score ordering, and because freshness already earns
    up to ten points inside the score, so the tiers were counting it twice.
    """
    selected: List[ScoredJob] = []
    dropped_applied = 0
    dropped_score = 0
    dropped_stale = 0

    for candidate in ranked:
        if is_already_applied(candidate.job.job_id):
            dropped_applied += 1
            continue
        if candidate.score < settings.min_score:
            dropped_score += 1
            continue
        days = candidate.job.posted_days_ago
        if days is not None and days > settings.max_days_old:
            dropped_stale += 1
            continue
        selected.append(candidate)

    selected.sort(key=lambda candidate: candidate.score, reverse=True)

    logger.info(
        "Application selection dropped %d already applied, %d scoring under "
        "%.0f, and %d older than %d days; %d eligible for a target of %d",
        dropped_applied,
        dropped_score,
        settings.min_score,
        dropped_stale,
        settings.max_days_old,
        len(selected),
        settings.target_applications,
    )
    _report_near_misses(ranked, settings, is_already_applied)

    if len(selected) < settings.target_applications:
        logger.warning(
            "Only %d jobs are eligible, short of the target of %d. Every one "
            "would have to be applicable to reach it, so expect fewer. Lower "
            "MIN_SCORE or raise MAX_DAYS_OLD to widen the pool.",
            len(selected),
            settings.target_applications,
        )
    return selected


def _report_near_misses(
    ranked: List[ScoredJob], settings: Settings, is_already_applied, margin: float = 10.0
) -> None:
    """Log the jobs that only just failed the score bar.

    Selection reports how many jobs it dropped but never which, so a run that
    rejected 79 of 121 left no way to tell whether anything good was lost. These
    are the ones worth a human glance, and the reasons show which component sank
    each of them.
    """
    bar = settings.min_score
    near = [
        candidate
        for candidate in ranked
        if candidate.score < bar
        and candidate.score >= bar - margin
        and not is_already_applied(candidate.job.job_id)
    ]
    if not near:
        return
    logger.info(
        "--- %d job(s) within %.0f points below the bar of %.0f, best first ---",
        len(near),
        margin,
        bar,
    )
    for candidate in near[:20]:
        logger.info(
            "    [%5.1f] %s @ %s (%s)",
            candidate.score,
            candidate.job.title or "<no title>",
            candidate.job.company or "<no company>",
            candidate.job.posted_label or "age unknown",
        )
        logger.info("        %s", "; ".join(
            " ".join(reason.split()) for reason in candidate.reasons
        )[:400])
    if len(near) > 20:
        logger.info("    ... and %d more", len(near) - 20)


def explain(scored: ScoredJob) -> str:
    """Return a one-line summary suitable for the run log."""
    reasons = "; ".join(" ".join(reason.split()) for reason in scored.reasons)
    company = " at %s" % scored.job.company if scored.job.company else ""
    return "%s%s: %.1f/100 (%s) - %s" % (
        scored.job.title or scored.job.job_id,
        company,
        scored.score,
        scored.verdict,
        reasons,
    )
