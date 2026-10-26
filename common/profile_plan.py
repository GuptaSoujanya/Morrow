"""Plan the whole job-board profile from the resume, profile.yaml and answers.txt.

The profile agents used to get only "fix what is out of date". This module asks the
LLM once for the profile a recruiter should see -- headline, designation, summary,
key skills, preferred roles -- grounded in her own facts, scores the resume for ATS
keyword coverage and structure, and hands the agent the exact text to write.

    python3 -m common.profile_plan            # print the ATS score and the planned profile
    python3 -m common.profile_plan --fresh    # ask the LLM again even if the facts did not change

Every word of the plan is written by the LLM; there is no template fallback. With no
model, or no usable answer after a retry, build_plan raises PlanError and the profile
agents do not run, rather than write canned text onto her profile.

Nothing here invents facts: skills the resume and facts never mention are dropped,
and headline or summary sentences with numbers the facts do not contain are cut.
The plan is cached in .memory/profile-plan.json until the facts change.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Profile, Settings

logger = logging.getLogger(__name__)

PLAN_FILE = Path(".memory") / "profile-plan.json"
HEADLINE_CHARS = 220   # LinkedIn's limit; Naukri allows 250
SUMMARY_CHARS = 1000   # Naukri's profile summary limit
ABOUT_CHARS = 2000     # LinkedIn About allows 2600
MAX_SKILLS = 25
_PROMPT_FACTS_CHARS = 12000
#: LLM calls per plan before giving up (a timeout or unparseable answer gets one retry).
_ATTEMPTS = 2


class PlanError(RuntimeError):
    """No LLM-written plan could be made."""

_SECTIONS = {
    "experience": r"\b(?:experience|employment|work history)\b",
    "education": r"\beducation\b",
    "skills": r"\b(?:skills|technologies|tech stack)\b",
}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d\s-]{8,}\d)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# "40%", "2 million events", "5 engineers": a figure with what it counts, not a date or phone.
_IMPACT = re.compile(r"(?<![\d-])\d+(?:\.\d+)?\s*(?:%|\+|x\b|[kKmM]\b|[A-Za-z]{3,})")


@dataclass
class AtsReport:
    score: int                                    # 0-100
    keyword_score: int                            # 0-100: target keywords the resume contains
    structure_score: int                          # 0-100: contact, sections, length, numbers
    matched: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)


@dataclass
class ProfilePlan:
    headline: str = ""
    designation: str = ""
    summary: str = ""
    about: str = ""
    key_skills: List[str] = field(default_factory=list)
    target_roles: List[str] = field(default_factory=list)
    target_keywords: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    source: str = "llm"
    ats: Optional[AtsReport] = None


# ---------------------------------------------------------------------------
# ATS score: deterministic, so it is the same every run for the same resume
# ---------------------------------------------------------------------------


def _mentions(text: str, term: str) -> bool:
    return bool(term) and re.search(r"(?<!\w)%s(?!\w)" % re.escape(term), text, re.IGNORECASE) is not None


def ats_report(resume_text: str, keywords: List[str]) -> AtsReport:
    """Score keyword coverage (60%) and parse-friendly structure (40%) of the resume."""
    text = resume_text or ""
    terms = _unique(keywords)
    matched = [term for term in terms if _mentions(text, term)]
    missing = [term for term in terms if term not in matched]
    keyword_score = round(100 * len(matched) / len(terms)) if terms else 0

    issues = []
    if not _EMAIL.search(text):
        issues.append("No email address the parser can read.")
    if not _PHONE.search(text):
        issues.append("No phone number the parser can read.")
    for name, pattern in _SECTIONS.items():
        if not re.search(pattern, text, re.IGNORECASE):
            issues.append("No '%s' section heading." % name.title())
    words = len(text.split())
    if words < 300:
        issues.append("Only %d words; most ATS rank resumes under 300 words low." % words)
    elif words > 1200:
        issues.append("%d words; trim to two pages (under about 1200 words)." % words)
    quantified = sum(1 for line in text.splitlines() if _IMPACT.search(line))
    if quantified < 3 and len(text.splitlines()) > 5:
        issues.append("Few quantified results (%d lines with numbers); add impact figures." % quantified)
    checks = 2 + len(_SECTIONS) + 2
    structure_score = round(100 * (checks - len(issues)) / checks)
    if missing:
        issues.append("Missing keywords recruiters search for: %s." % ", ".join(missing[:15]))
    score = round(0.6 * keyword_score + 0.4 * structure_score) if terms else structure_score
    return AtsReport(score=score, keyword_score=keyword_score, structure_score=structure_score,
                     matched=matched, missing=missing, issues=issues)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

_SCHEMA = (
    '{"headline": "...", "designation": "...", "summary": "...", "about": "...", '
    '"key_skills": ["..."], "target_roles": ["..."], "target_keywords": ["..."], "suggestions": ["..."]}'
)

_INSTRUCTIONS = """You are an expert technical recruiter and ATS specialist. Write the job-board
profile this candidate should have, using ONLY the facts below (her profile.yaml, her own answers
to screening questions, and her resume). Never invent an employer, title, number, skill, degree or
certification that the facts do not state.

- headline: at most %(headline)d characters; her target role, years of experience if stated, and the
  4-6 strongest skills recruiters search for, separated by " | ". No first person.
- designation: her current job title exactly as the facts give it.
- summary: at most %(summary)d characters, 3-5 sentences, first person, keyword-rich: role, years,
  domains, strongest skills, two concrete achievements taken from the resume, what she wants next.
- about: at most %(about)d characters, the longer LinkedIn "About" version of the summary; short
  paragraphs, achievements with the resume's own numbers.
- key_skills: up to %(skills)d skills, most searched first, each one named in the facts.
- target_roles: 3-5 job titles she fits, from her titles and experience.
- target_keywords: 15-25 keywords and phrases recruiters' ATS filters use for those roles (these may
  include ones her resume lacks; they are used to score the resume, not to describe her).
- suggestions: up to 6 concrete edits that would raise her resume's ATS score, honestly."""


def _unique(items: List[str]) -> List[str]:
    seen, kept = set(), []
    for item in items:
        text = " ".join(str(item).split()).strip(" ,.;")
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            kept.append(text)
    return kept


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split()) if "\n" not in str(text or "") else str(text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(" | "))
    return (cut[:end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0]).strip(" |")


def _grounded_numbers(text: str, facts: str) -> str:
    """Drop sentences whose numbers appear nowhere in the facts: the model made them up."""
    known = set(_NUMBER.findall(facts))
    parts = re.split(r"(?<=[.!?])\s+|(?<=\n)", text)
    kept = [part for part in parts if all(number in known for number in _NUMBER.findall(part))]
    return " ".join(part.strip() for part in kept if part.strip()) if "\n" not in text else \
        "\n".join(part.rstrip() for part in kept).strip()


def _years(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(number)


def _parse(raw: Dict[str, Any], profile: Profile, facts: str) -> ProfilePlan:
    def strings(key: str) -> List[str]:
        value = raw.get(key)
        return _unique([item for item in value if isinstance(item, str)]) if isinstance(value, list) else []

    # Where the model left a list empty, her own facts fill it; prose comes only from the model.
    skills = [skill for skill in strings("key_skills") if _mentions(facts, skill)][:MAX_SKILLS]
    headline = _clip(_grounded_numbers(str(raw.get("headline") or ""), facts), HEADLINE_CHARS)
    summary = _clip(_grounded_numbers(str(raw.get("summary") or ""), facts), SUMMARY_CHARS)
    about = _clip(_grounded_numbers(str(raw.get("about") or ""), facts), ABOUT_CHARS)
    designation = " ".join(str(raw.get("designation") or "").split())
    if not designation or not _mentions(facts, designation):
        designation = (profile.titles or [""])[0]
    return ProfilePlan(
        headline=headline,
        designation=designation,
        summary=summary,
        about=about or summary,
        key_skills=skills or profile.skills[:MAX_SKILLS],
        target_roles=strings("target_roles")[:5] or profile.titles[:5],
        target_keywords=strings("target_keywords")[:25] or _unique(profile.titles + profile.skills),
        suggestions=strings("suggestions")[:6],
        source="llm",
    )


def _key(facts: str) -> str:
    return hashlib.sha256(facts.encode("utf-8")).hexdigest()[:16]


def _load_cached(path: Path, key: str) -> Optional[ProfilePlan]:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or saved.get("key") != key or not isinstance(saved.get("plan"), dict):
        return None
    if saved["plan"].get("source") != "llm":  # an old template plan: write it again with the model
        return None
    data = dict(saved["plan"])
    ats = data.pop("ats", None)
    try:
        plan = ProfilePlan(**data)
        plan.ats = AtsReport(**ats) if isinstance(ats, dict) else None
    except TypeError:
        return None
    return plan


def _save(path: Path, key: str, plan: ProfilePlan) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "made": datetime.now().isoformat(timespec="seconds"),
                                    "plan": asdict(plan)}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save the profile plan to %s: %s", path, exc)


def build_plan(profile: Profile, settings: Settings, facts: Optional[str] = None, client: Any = None,
               path: Path = PLAN_FILE, fresh: bool = False) -> ProfilePlan:
    """The LLM-written profile with its ATS report; cached until the facts change.

    Raises PlanError when no model is available or it gives no usable plan after a retry.
    """
    if facts is None:
        from sites_bot.browser_agent import facts_text
        facts = facts_text(profile, settings)
    key = _key(facts)
    if not fresh:
        cached = _load_cached(path, key)
        if cached is not None:
            return cached
    if client is None:
        from .llm import build_client
        # One long answer, not a quick yes/no: give the model more than the default 90 s.
        client = build_client(replace(settings, llm_timeout_s=max(settings.llm_timeout_s, 300)))
    if not client.available():
        raise PlanError("no LLM is available (LLM_BACKEND=%s); the profile is planned only by the model"
                        % getattr(settings, "llm_backend", "?"))
    limits = {"headline": HEADLINE_CHARS, "summary": SUMMARY_CHARS, "about": ABOUT_CHARS, "skills": MAX_SKILLS}
    prompt = "%s\n\nThe facts:\n%s" % (_INSTRUCTIONS % limits, facts[:_PROMPT_FACTS_CHARS])
    plan = None
    for attempt in range(1, _ATTEMPTS + 1):
        logger.info("Asking the LLM to plan the profile from the resume and answers (try %d)...", attempt)
        raw = client.complete_json(prompt, _SCHEMA)
        if isinstance(raw, dict):
            plan = _parse(raw, profile, facts)
            if plan.headline and plan.summary:
                break
            logger.warning("The LLM's plan had no headline or summary after grounding; asking again.")
            plan = None
    if plan is None:
        raise PlanError("the LLM gave no usable profile plan after %d tries" % _ATTEMPTS)
    plan.ats = ats_report(profile.resume_text, plan.target_keywords or profile.skills)
    _save(path, key, plan)
    return plan


def agent_brief(plan: ProfilePlan) -> str:
    """The exact text the browser agent should write, appended to its profile task."""
    lines = [
        "Planned profile (written from her resume and answers; use this exact text, trimming only to fit "
        "a field's length limit, and do not add anything the facts do not support):",
    ]
    if plan.headline:
        lines.append("- Headline / resume headline: %s" % plan.headline)
    if plan.designation:
        lines.append("- Current designation / profession: %s" % plan.designation)
    if plan.summary:
        lines.append("- Profile summary (short fields, e.g. Naukri): %s" % plan.summary)
    if plan.about and plan.about != plan.summary:
        lines.append("- About (long fields, e.g. LinkedIn):\n%s" % plan.about)
    if plan.key_skills:
        lines.append("- Key skills, most important first (add the missing ones; remove skills she does not "
                     "list only if the board has a limit): %s" % ", ".join(plan.key_skills))
    if plan.target_roles:
        lines.append("- Preferred / desired roles: %s" % ", ".join(plan.target_roles))
    lines.append("Fill every other empty profile section the facts can answer (employment, education, "
                 "career profile, locations, salary, notice period, IT skills with years). Update a field only "
                 "when the planned text differs in meaning or the field is empty.")
    report = plan.ats
    if report is not None:
        lines += ["", "ATS: her resume scores %d/100 (keyword coverage %d, structure %d) for these roles."
                  % (report.score, report.keyword_score, report.structure_score)]
        if report.matched:
            lines.append("- Keywords recruiters search that she has; each must appear in the headline, skills or "
                         "summary on this board: %s" % ", ".join(report.matched))
        if report.missing:
            lines.append("- Keywords her resume does not mention; add one only when the facts plainly cover it (e.g. as an "
                         "abbreviation), never as a new claim: %s"
                         % ", ".join(report.missing))
    return "\n".join(lines)


def ats_text(plan: ProfilePlan) -> str:
    report = plan.ats
    if report is None:
        return "No ATS report."
    lines = ["ATS score %d/100 (keywords %d, structure %d)." % (report.score, report.keyword_score,
                                                               report.structure_score)]
    lines += ["- " + issue for issue in report.issues]
    lines += ["- Suggestion: " + tip for tip in plan.suggestions]
    return "\n".join(lines)


def plan_for(profile: Optional[Profile], settings: Settings) -> Optional[ProfilePlan]:
    """build_plan for the profile agents; None (and a warning) when it cannot be made."""
    if profile is None:
        return None
    try:
        plan = build_plan(profile, settings)
    except Exception as exc:
        logger.error("Could not plan the profile with the LLM: %s", exc)
        return None
    logger.info("Profile plan (%s): %s", plan.source, ats_text(plan).replace("\n", " "))
    return plan


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="common.profile_plan",
                                     description="Print the ATS score and the profile planned from the resume.")
    parser.add_argument("--fresh", action="store_true", help="Ask the LLM again even if the facts did not change.")
    parser.add_argument("--env", default=None, metavar="PATH", help="Path to the .env file.")
    parser.add_argument("--json", action="store_true", help="Print the plan as JSON.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from . import config
    from .profile import load_profile

    try:
        settings = config.load_settings(args.env)
        profile = load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile facts: %s", exc)
        return 1
    try:
        plan = build_plan(profile, settings, fresh=args.fresh)
    except PlanError as exc:
        logger.error("%s", exc)
        return 1
    if args.json:
        print(json.dumps(asdict(plan), indent=2, ensure_ascii=False))
    else:
        print(ats_text(plan))
        print()
        print(agent_brief(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
