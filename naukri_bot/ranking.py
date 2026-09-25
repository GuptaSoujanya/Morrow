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

from . import llm
from .llm import LLMClient
from .models import JobPosting, Profile, ScoredJob, Settings, Verdict


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
    if wrong_titles:
        score -= _WRONG_TITLE_PENALTY
        reasons.append("title contains '%s' (penalty)" % wrong_titles[0])
    elif title_matches:
        score += _TITLE_MATCH_BONUS
        reasons.append("title matches preferred role '%s'" % title_matches[0])
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
    """Lexically score every job and return the highest-scoring candidates."""
    scored: List[ScoredJob] = []
    for job in jobs:
        score, reasons = lexical_score(profile, job)
        scored.append(
            ScoredJob(job=job, score=score, lexical_score=score, reasons=reasons)
        )
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    return scored[: max(0, limit)]


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


def _tier_of(candidate: ScoredJob, settings: Settings) -> Optional[int]:
    """Return the preference tier a candidate belongs to, or None to drop it.

    Tier 1 is what the old hard filters allowed: good enough and fresh enough.
    Tier 2 keeps the quality bar but forgives age, because a job that cleared
    min_score four days ago is a better use of the quota than nothing at all.
    Tier 3 forgives score down to a floor, and exists only so that a thin day
    still reaches the target. Below the floor a candidate is dropped outright:
    a real application is sent under the user's name and is visible in their
    Naukri history forever, so padding the count with irrelevant roles costs
    more than falling short.
    """
    days = candidate.job.posted_days_ago
    fresh = days is None or days <= settings.max_days_old
    within_fallback = days is None or days <= settings.max_days_old_fallback

    if candidate.score >= settings.min_score:
        if fresh:
            return 1
        if within_fallback:
            return 2
        return None

    floor = settings.min_score_floor
    if floor > 0 and candidate.score >= floor and within_fallback:
        return 3
    return None


def select_for_application(
    ranked: List[ScoredJob], settings: Settings, is_already_applied
) -> List[ScoredJob]:
    """Order ranked jobs by preference tier so the apply loop can reach its target.

    The caller stops once target_applications have actually been *submitted*,
    so this returns every acceptable candidate rather than a fixed slice. Jobs
    that cannot be applied to through Naukri at all -- company-site redirects,
    unanswerable questionnaires -- are only discoverable once a job page is
    open, so the preferred tier is routinely too thin to fill the target on its
    own. Lower tiers sit behind it and are consumed only if it runs out.
    """
    tiers: Dict[int, List[ScoredJob]] = {1: [], 2: [], 3: []}
    dropped_applied = 0
    dropped_below_floor = 0
    dropped_stale = 0

    for candidate in ranked:
        if is_already_applied(candidate.job.job_id):
            dropped_applied += 1
            continue
        tier = _tier_of(candidate, settings)
        if tier is None:
            days = candidate.job.posted_days_ago
            if days is not None and days > settings.max_days_old_fallback:
                dropped_stale += 1
            else:
                dropped_below_floor += 1
            continue
        tiers[tier].append(candidate)

    # Each tier is already in descending score order because `ranked` is, so
    # concatenating preserves "best first" within every tier.
    selected = tiers[1] + tiers[2] + tiers[3]

    # With the floor disabled the bar that actually rejected these jobs is
    # min_score, and reporting "below the score floor of 0" was nonsense.
    effective_bar = (
        settings.min_score_floor if settings.min_score_floor > 0 else settings.min_score
    )
    logger.info(
        "Application selection dropped %d already applied, %d scoring under %.0f, "
        "and %d older than %d days",
        dropped_applied,
        dropped_below_floor,
        effective_bar,
        dropped_stale,
        settings.max_days_old_fallback,
    )
    logger.info(
        "Eligible for a target of %d: %d preferred (score >= %.0f, <= %d days), "
        "%d older but good enough, %d below score but above the floor; %d total",
        settings.target_applications,
        len(tiers[1]),
        settings.min_score,
        settings.max_days_old,
        len(tiers[2]),
        len(tiers[3]),
        len(selected),
    )
    if len(selected) < settings.target_applications:
        logger.warning(
            "Only %d jobs are eligible, short of the target of %d. Every one "
            "would have to be applicable to reach it, so expect fewer. Lower "
            "MIN_SCORE_FLOOR or raise MAX_DAYS_OLD_FALLBACK to widen the pool.",
            len(selected),
            settings.target_applications,
        )
    return selected


def tier_of(candidate: ScoredJob, settings: Settings) -> Optional[int]:
    """Public wrapper so the run log can show which tier a job came from."""
    return _tier_of(candidate, settings)


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
