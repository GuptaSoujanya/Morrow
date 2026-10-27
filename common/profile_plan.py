"""Plan the whole job-board profile from the resume, profile.yaml and answers.txt.

The profile agents used to get only "fix what is out of date". This module asks the
LLM for the profile a recruiter should see -- headline, designation, summary, About,
key skills, every employment's job profile, projects, IT skills, certifications and
preferred roles -- grounded in her own facts, scores the resume for ATS keyword
coverage and structure, and hands the agent the exact text to write on every board.

    python3 -m common.profile_plan            # print the ATS score, the review and the planned profile
    python3 -m common.profile_plan --fresh    # ask the LLM again even if the facts did not change

The writing is held to a recruiter's rubric (quality_report): a hook instead of "I am
a ...", figures from the resume, the stack named, a line on what she wants, no filler
words, length limits per board. A draft that fails it goes back to the model once with
the reviewer's notes; the better of the two drafts is kept and its remaining notes are
saved with it.

Every word of the plan is written by the LLM; there is no template fallback. With no
model, or no usable answer after a retry, build_plan raises PlanError and the profile
agents do not run, rather than write canned text onto her profile.

Nothing here invents facts: skills, employers, projects, links and certifications the
resume and facts never mention are dropped, and sentences with numbers the facts do
not contain are cut. The plan is cached in .memory/profile-plan.json until the facts
(or this planner) change.
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
from typing import Any, Dict, List, Optional, Tuple

from .models import Profile, Settings
from . import paths

logger = logging.getLogger(__name__)

PLAN_FILE = paths.memory_dir() / "profile-plan.json"
#: Bump when the prompt or the plan's shape changes: cached plans are then written again.
PLAN_VERSION = 3
HEADLINE_CHARS = 220        # LinkedIn's limit; Naukri allows 250
HEADLINE_MIN_CHARS = 60
SUMMARY_CHARS = 1000        # Naukri's profile summary limit
SUMMARY_MIN_CHARS = 600
SHORT_SUMMARY_CHARS = 300   # one-paragraph fields (Instahyre, Wellfound bio)
ABOUT_CHARS = 2600          # LinkedIn About
ABOUT_MIN_CHARS = 1500
HOOK_CHARS = 200            # what LinkedIn shows before "see more"
JOB_PROFILE_CHARS = 4000    # Naukri's job profile per employment
JOB_PROFILE_MIN_WORDS = 15  # below this Naukri does not count the job profile as filled
PROJECT_CHARS = 1000        # Naukri's project description
MAX_SKILLS = 25
MIN_SKILLS_IN_SUMMARY = 6
MAX_IT_SKILLS = 10          # Naukri's IT skills table holds 10 entries
_PROMPT_FACTS_CHARS = 40000
#: LLM calls per draft before giving up (a timeout or unparseable answer gets one retry).
_ATTEMPTS = 2

#: Filler recruiters skim past; a draft using one goes back to the model.
BANNED_PHRASES = (
    "passionate", "results-driven", "results driven", "results-oriented", "leverag", "cutting-edge",
    "cutting edge", "state-of-the-art", "dynamic", "motivated", "hard-working", "hardworking", "team player",
    "quick learner", "challenging role", "challenging opportunity", "utilize", "utilise", "drive innovation",
    "delve", "spearhead", "robust", "seamless", "transformative", "synergy", "game-changer", "game changer",
    "ever-evolving", "proven track record", "highly skilled", "responsible for",
)


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
_RESUME_MARKER = "Her resume (plain text):"


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
    short_summary: str = ""
    about: str = ""
    key_skills: List[str] = field(default_factory=list)
    #: One entry per role: title, company, location, start, end, description (the job profile), skills.
    experience: List[Dict[str, str]] = field(default_factory=list)
    #: One entry per project: name, role, description, skills, url.
    projects: List[Dict[str, str]] = field(default_factory=list)
    #: Naukri's IT skills table: name, years, last_used.
    it_skills: List[Dict[str, str]] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    target_roles: List[str] = field(default_factory=list)
    target_keywords: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    #: The reviewer's notes the final draft still fails (quality_report); [] when it passed.
    review: List[str] = field(default_factory=list)
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
    '{"headline": "...", "designation": "...", "summary": "...", "short_summary": "...", "about": "...", '
    '"key_skills": ["..."], '
    '"experience": [{"title": "", "company": "", "location": "", "start": "Mar 2024", "end": "Present", '
    '"description": "", "skills": ""}], '
    '"projects": [{"name": "", "role": "", "client": "", "start": "", "end": "", "description": "", '
    '"skills": "", "url": ""}], '
    '"it_skills": [{"name": "", "years": "", "last_used": ""}], '
    '"certifications": ["..."], "links": ["..."], '
    '"target_roles": ["..."], "target_keywords": ["..."], "suggestions": ["..."]}'
)

_INSTRUCTIONS = """You are a senior technical recruiter who writes candidate profiles that get recruiter calls,
and an ATS specialist. Write the job-board profile this candidate should have (Naukri, LinkedIn, Hirist,
Cutshort, Instahyre, Wellfound), using ONLY the facts below: her resume first, then her facts file and her
own answers to screening questions. Never invent an employer, title, number, date, skill, degree,
certification or link the facts do not state; every number you write must appear in the facts.

How recruiters read a profile: they keyword-search the headline, skills, summary, designation and IT skills,
open the profile, and read the first two lines of the summary and of the current job before deciding. So:
- Lead with what she builds and the proof, never with "I am a ..."; the first sentence must stand alone and
  carry a number from the resume.
- Specific beats general: name the systems, the scale, the models, the stack, using the resume's own figures
  (counts, percentages, limits, dates). Every sentence should tell a recruiter something she did.
- No filler: never write passionate, results-driven, leverage, cutting-edge, state-of-the-art, dynamic,
  motivated, hard-working, team player, quick learner, seeking a challenging role, utilize, drive innovation,
  delve, spearhead, robust, seamless, transformative, synergy, proven track record, highly skilled or
  responsible for. No adjective triplets, no em dashes.
- Spell an acronym out once where it first appears, e.g. "retrieval-augmented generation (RAG)", so both
  search forms match.
- Vary sentence length. Short paragraphs. First person in the summary and About; no first person in the
  headline.

Fields:
- headline: %(headline_min)d-%(headline)d characters, "Role | 4-6 skills recruiters search | years | one proof
  or domain", with the role and first keyword in the first 60 characters. No availability, no qualities.
- designation: her current job title exactly as the facts give it.
- summary: %(summary_min)d-%(summary)d characters, first person, 4-6 sentences in this order: the hook (what she
  builds, the domain, one number), two or three proofs with figures from the resume, one sentence naming
  the stack (at least %(skills_in_summary)d of the key skills), one sentence on what she wants next (roles,
  locations or remote; the notice period only if the facts state it).
- short_summary: at most %(short)d characters: the hook plus one proof, for boards with a one-paragraph field.
- about: %(about_min)d-%(about)d characters, the LinkedIn About: the hook as its own first paragraph (under
  %(hook)d characters), then two or three short paragraphs of proof, a stack line, and what she wants; a
  blank line between paragraphs.
- key_skills: 18-%(skills)d skills, most searched first, exact tool or skill names only, one tag each
  ("LangChain", "RAG", "FastAPI"), no soft skills; every one named in the facts.
- experience: every role in the resume, newest first: title, company, location, start, end ("Present" when
  current), description (the job profile: 3-5 lines of "verb + what + figure + stack" from the resume's
  bullets for that role, %(job_words)d words to %(job)d characters, strongest line first since it shows
  before "see more"), skills (comma-separated skills used in that role, from the resume).
- projects: every project the resume names: name, role, description (1-3 sentences with the project's own
  figures, at most %(project)d characters), skills (comma-separated), and client, start, end and url only
  when the facts give them (boards ask for a client and a start month; leave them "" rather than guess).
- it_skills: up to %(it)d software or skill names for Naukri's IT skills table (it holds %(it)d), most
  searched first, each with years (from the
  facts' years per skill, or her total experience when the resume shows the skill through the whole
  tenure) and last_used (the current year for skills in the current role).
- certifications: exactly as the facts name them.
- links: her portfolio, GitHub and LinkedIn URLs from the facts.
- target_roles: 3-5 job titles she fits, from her titles and experience.
- target_keywords: 15-25 keywords and phrases recruiters' ATS filters use for those roles (these may include
  ones her resume lacks; they score the resume, they do not describe her).
- suggestions: up to 6 concrete, honest edits that would raise her resume's ATS score."""

_EDITOR = """You are the editor of a job-board profile. Below are the facts (the candidate's resume, facts file
and answers), the draft profile as JSON, and the reviewer's notes on it. Rewrite the fields the notes name so
every note is resolved, keep every other field exactly as it is, and return the whole JSON object. The
writing rules still hold: only facts and figures from the facts below, no invented employer, title, number,
date, skill or link; lead with what she builds, not "I am a"; no filler words (passionate, results-driven,
leverage, cutting-edge, dynamic, motivated, robust, seamless, utilize, responsible for...); first person in the
summary and About, none in the headline.

Reviewer's notes:
%(notes)s

The draft:
%(draft)s"""

_LIMITS = {
    "headline": HEADLINE_CHARS, "headline_min": HEADLINE_MIN_CHARS, "summary": SUMMARY_CHARS,
    "summary_min": SUMMARY_MIN_CHARS, "short": SHORT_SUMMARY_CHARS, "about": ABOUT_CHARS,
    "about_min": ABOUT_MIN_CHARS, "hook": HOOK_CHARS, "skills": MAX_SKILLS,
    "skills_in_summary": MIN_SKILLS_IN_SUMMARY, "job": JOB_PROFILE_CHARS, "job_words": JOB_PROFILE_MIN_WORDS,
    "project": PROJECT_CHARS, "it": MAX_IT_SKILLS,
}


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


def _words(value: Any) -> str:
    return " ".join(str(value or "").split())


def _in_facts(facts: str, value: str) -> bool:
    return bool(value) and value.casefold() in facts.casefold()


def _skill_list(value: Any, facts: str) -> str:
    items = value if isinstance(value, list) else str(value or "").split(",")
    return ", ".join(skill for skill in _unique([str(item) for item in items]) if _mentions(facts, skill))


def _experience(raw: Any, facts: str) -> List[Dict[str, str]]:
    """The roles the model listed, kept only when the facts name the employer and the title."""
    roles = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        company, title = _words(item.get("company")), _words(item.get("title"))
        if not (company and title and _mentions(facts, title)
                and (_mentions(facts, company) or _mentions(facts, company.split(" (")[0]))):
            continue
        roles.append({
            "title": title, "company": company, "location": _words(item.get("location")),
            "start": _grounded_numbers(_words(item.get("start")), facts),
            "end": _grounded_numbers(_words(item.get("end")), facts),
            "description": _clip(_grounded_numbers(str(item.get("description") or "").strip(), facts),
                                 JOB_PROFILE_CHARS),
            "skills": _skill_list(item.get("skills"), facts),
        })
    return roles


def _projects(raw: Any, facts: str) -> List[Dict[str, str]]:
    projects = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _words(item.get("name"))
        if not name or not _in_facts(facts, name):
            continue
        url, client = _words(item.get("url")), _words(item.get("client"))
        projects.append({
            "name": name, "role": _words(item.get("role")),
            "client": client if _in_facts(facts, client) else "",
            "start": _grounded_numbers(_words(item.get("start")), facts),
            "end": _grounded_numbers(_words(item.get("end")), facts),
            "description": _clip(_grounded_numbers(_words(item.get("description")), facts), PROJECT_CHARS),
            "skills": _skill_list(item.get("skills"), facts),
            "url": url if _in_facts(facts, url.replace("https://", "").replace("http://", "")) else "",
        })
    return projects


def _it_skills(raw: Any, facts: str, profile: Profile) -> List[Dict[str, str]]:
    total = _years(profile.total_experience_years) if profile.total_experience_years else ""
    skills, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _words(item.get("name"))
        if not name or name.casefold() in seen or not _mentions(facts, name):
            continue
        seen.add(name.casefold())
        years = _words(item.get("years"))
        if not _grounded_numbers(years, facts):   # a figure the facts do not hold: her total experience instead
            years = total
        last_used = _words(item.get("last_used"))
        if last_used != str(datetime.now().year) and not _grounded_numbers(last_used, facts):
            last_used = ""   # a year the facts never give, and not this one
        skills.append({"name": name, "years": years, "last_used": last_used})
        if len(skills) == MAX_IT_SKILLS:
            break
    return skills


def _parse(raw: Dict[str, Any], profile: Profile, facts: str) -> ProfilePlan:
    def strings(key: str) -> List[str]:
        value = raw.get(key)
        return _unique([item for item in value if isinstance(item, str)]) if isinstance(value, list) else []

    # Where the model left a list empty, her own facts fill it; prose comes only from the model.
    skills = [skill for skill in strings("key_skills") if _mentions(facts, skill)][:MAX_SKILLS]
    headline = _clip(_grounded_numbers(str(raw.get("headline") or ""), facts), HEADLINE_CHARS)
    summary = _clip(_grounded_numbers(str(raw.get("summary") or ""), facts), SUMMARY_CHARS)
    short = _clip(_grounded_numbers(str(raw.get("short_summary") or ""), facts), SHORT_SUMMARY_CHARS)
    about = _clip(_grounded_numbers(str(raw.get("about") or ""), facts), ABOUT_CHARS)
    designation = _words(raw.get("designation"))
    if not designation or not _mentions(facts, designation):
        designation = (profile.titles or [""])[0]
    return ProfilePlan(
        headline=headline,
        designation=designation,
        summary=summary,
        short_summary=short,
        about=about or summary,
        key_skills=skills or profile.skills[:MAX_SKILLS],
        experience=_experience(raw.get("experience"), facts),
        projects=_projects(raw.get("projects"), facts),
        it_skills=_it_skills(raw.get("it_skills"), facts, profile),
        certifications=[cert for cert in strings("certifications") if _in_facts(facts, cert)],
        links=[link for link in strings("links")
               if _in_facts(facts, link.replace("https://", "").replace("http://", "").rstrip("/"))],
        target_roles=strings("target_roles")[:5] or profile.titles[:5],
        target_keywords=strings("target_keywords")[:25] or _unique(profile.titles + profile.skills),
        suggestions=strings("suggestions")[:6],
        source="llm",
    )


# ---------------------------------------------------------------------------
# The reviewer: what a recruiter would send back
# ---------------------------------------------------------------------------


def _filler(name: str, text: str) -> List[str]:
    low = text.casefold()
    found = [phrase for phrase in BANNED_PHRASES if phrase in low]
    notes = ["%s: uses filler (%s); say what she did instead." % (name, ", ".join(found[:4]))] if found else []
    if "\u2014" in text:
        notes.append("%s: has an em dash; use a comma, colon or full stop." % name)
    return notes


def quality_report(plan: ProfilePlan) -> List[str]:
    """The reviewer's notes on a plan: [] when it reads the way a recruiter wants."""
    notes = []
    for name, text in (("headline", plan.headline), ("summary", plan.summary), ("short_summary", plan.short_summary),
                       ("about", plan.about)):
        notes += _filler(name, text)
    skills = plan.key_skills

    if not plan.headline:
        notes.append("headline: missing.")
    else:
        if len(plan.headline) < HEADLINE_MIN_CHARS:
            notes.append("headline: only %d characters; write %d-%d with the role, 4-6 searched skills and years."
                         % (len(plan.headline), HEADLINE_MIN_CHARS, HEADLINE_CHARS))
        if " | " not in plan.headline:
            notes.append("headline: separate the role, skills and years with ' | '.")
        if sum(1 for skill in skills if _mentions(plan.headline, skill)) < 3:
            notes.append("headline: names fewer than 3 of the key skills.")
        if plan.target_roles and not any(plan.headline.casefold().startswith(role.casefold())
                                         for role in plan.target_roles):
            notes.append("headline: start with one of her target roles (%s) so a title search matches it."
                         % ", ".join(plan.target_roles[:3]))
        if re.search(r"\b(?:looking for|open to|seeking|available|immediate)\b", plan.headline, re.IGNORECASE):
            notes.append("headline: no availability; put what she builds there.")

    if not plan.summary:
        notes.append("summary: missing.")
    else:
        if re.match(r"\s*(?:I am|I'm|I’m)\s+an?\b", plan.summary):
            notes.append("summary: opens with 'I am a'; lead with what she builds and one figure.")
        figures = set(_NUMBER.findall(plan.summary))
        if len(figures) < 2:
            notes.append("summary: carries %d figure(s); use at least 2 from the resume (scale, counts, "
                         "percentages)." % len(figures))
        named = sum(1 for skill in skills if _mentions(plan.summary, skill))
        if named < min(MIN_SKILLS_IN_SUMMARY, len(skills)):
            notes.append("summary: names only %d of the key skills; name at least %d in a stack sentence."
                         % (named, MIN_SKILLS_IN_SUMMARY))
        if not re.search(r"\b(?:looking for|open to|want|next|interested in|seeking)\b", plan.summary, re.IGNORECASE):
            notes.append("summary: no sentence on what she wants next (roles, locations or remote).")
        if len(plan.summary) < SUMMARY_MIN_CHARS:
            notes.append("summary: only %d characters; write %d-%d." % (len(plan.summary), SUMMARY_MIN_CHARS,
                                                                        SUMMARY_CHARS))
        if plan.summary.count(".") < 3:
            notes.append("summary: fewer than 4 sentences.")

    if plan.about and plan.about != plan.summary:
        hook = plan.about.strip().split("\n")[0]
        if len(hook) > HOOK_CHARS:
            notes.append("about: the first paragraph (the hook) is %d characters; keep it under %d so it shows "
                         "before 'see more'." % (len(hook), HOOK_CHARS))
        if "\n" not in plan.about.strip():
            notes.append("about: one block of text; split it into short paragraphs.")
        if len(plan.about) < ABOUT_MIN_CHARS:
            notes.append("about: only %d characters; write %d-%d." % (len(plan.about), ABOUT_MIN_CHARS, ABOUT_CHARS))
    elif plan.summary:
        notes.append("about: missing; write the LinkedIn About (%d-%d characters, hook first)."
                     % (ABOUT_MIN_CHARS, ABOUT_CHARS))

    if not plan.short_summary:
        notes.append("short_summary: missing (the hook plus one proof, under %d characters)." % SHORT_SUMMARY_CHARS)

    if not plan.experience:
        notes.append("experience: no roles; list every role in the resume with its job profile.")
    for number, role in enumerate(plan.experience):
        label = "experience '%s'" % (role.get("company") or role.get("title"))
        words = len(role.get("description", "").split())
        if words < JOB_PROFILE_MIN_WORDS:
            notes.append("%s: job profile has %d words; write 3-5 lines of what she did there, %d words or more."
                         % (label, words, JOB_PROFILE_MIN_WORDS))
        elif number == 0 and not _NUMBER.search(role.get("description", "")):
            # The current role is what recruiters read; an old internship may have no figures to give.
            notes.append("%s: job profile has no figure; use the resume's own numbers." % label)
        notes += _filler(label, role.get("description", ""))
        if not role.get("skills"):
            notes.append("%s: no skills used." % label)
    for project in plan.projects:
        if len(project.get("description", "").split()) < 8:
            notes.append("project '%s': description is too thin; say what it does and with what." % project["name"])
    if not plan.it_skills:
        notes.append("it_skills: empty; list her tools with years for Naukri's IT skills table.")
    if len(skills) < 10:
        notes.append("key_skills: only %d; list 18-%d searched skills from the facts." % (len(skills), MAX_SKILLS))
    return notes


# ---------------------------------------------------------------------------
# Building, caching
# ---------------------------------------------------------------------------


def planner_facts(profile: Profile, facts: str) -> str:
    """What the model reads: the whole resume first, then the facts file and answers.

    facts_text puts the resume last and the answer key before it, and a cut at a character
    limit used to leave the model the answers and a few lines of the resume; the plan then
    read like the answer key.
    """
    rest = facts.split("\n" + _RESUME_MARKER, 1)[0] if _RESUME_MARKER in facts else facts
    parts = []
    if profile.resume_text.strip():
        parts.append(_RESUME_MARKER + "\n" + profile.resume_text.strip())
    parts.append("Her facts file and her own answers to screening questions:\n" + rest.strip()[:_PROMPT_FACTS_CHARS])
    return "\n\n".join(parts)


def _key(facts: str) -> str:
    return hashlib.sha256(("v%d\n%s" % (PLAN_VERSION, facts)).encode("utf-8")).hexdigest()[:16]


def _read_saved(path: Path) -> Optional[Tuple[str, ProfilePlan]]:
    """The saved plan and the facts key it was made from; None for no file or an old template plan."""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or not isinstance(saved.get("plan"), dict):
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
    return str(saved.get("key") or ""), plan


def _load_cached(path: Path, key: str) -> Optional[ProfilePlan]:
    saved = _read_saved(path)
    return saved[1] if saved is not None and saved[0] == key else None


def _rank(plan: ProfilePlan) -> Tuple[int, int]:
    # Reviewer notes first: the ATS score follows the plan's own keyword list, which a thin plan
    # with two keywords can top; a plan the reviewer passes is the better one at any score.
    return -len(plan.review), plan.ats.score if plan.ats is not None else -1


def _keep_better(path: Path, fresh: ProfilePlan, profile: Profile, known: str) -> ProfilePlan:
    """The saved plan once more when it still holds against today's facts and scores at least as well.

    The model writes a different headline and summary every time it is asked, and one added line
    in the answers file is a new facts key. Without this, that line rebuilt the plan, the ATS
    score fell from 90 to 86 and every board was given a new headline for nothing.
    """
    saved = _read_saved(path)
    if saved is None:
        return fresh
    data = asdict(saved[1])
    data.pop("ats", None)
    data.pop("review", None)
    old = _parse(data, profile, known)
    old.review = quality_report(old)
    old.ats = ats_report(profile.resume_text, old.target_keywords or profile.skills)
    if _rank(old) < _rank(fresh):
        return fresh
    logger.info("Keeping the saved profile plan: ATS %d/100 with %d reviewer note(s), against the new draft's "
                "%d/100 with %d.", old.ats.score, len(old.review), fresh.ats.score if fresh.ats else -1,
                len(fresh.review))
    return old


def _save(path: Path, key: str, plan: ProfilePlan) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "made": datetime.now().isoformat(timespec="seconds"),
                                    "plan": asdict(plan)}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save the profile plan to %s: %s", path, exc)


def _draft(client: Any, prompt: str, profile: Profile, known: str, what: str) -> Optional[ProfilePlan]:
    for attempt in range(1, _ATTEMPTS + 1):
        logger.info("Asking the LLM to %s (try %d)...", what, attempt)
        raw = client.complete_json(prompt, _SCHEMA)
        if isinstance(raw, dict):
            plan = _parse(raw, profile, known)
            if plan.headline and plan.summary:
                return plan
            logger.warning("The LLM's plan had no headline or summary after grounding; asking again.")
    return None


def _draft_json(plan: ProfilePlan) -> str:
    data = asdict(plan)
    for key in ("review", "source", "ats"):
        data.pop(key, None)
    return json.dumps(data, indent=1, ensure_ascii=False)


def build_plan(profile: Profile, settings: Settings, facts: Optional[str] = None, client: Any = None,
               path: Path = PLAN_FILE, fresh: bool = False) -> ProfilePlan:
    """The LLM-written profile with its review and ATS report; cached until the facts change.

    The first draft is checked against quality_report; when the reviewer has notes, the model
    rewrites the named fields once and the draft with fewer notes is kept.

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
    reading = planner_facts(profile, facts)
    known = facts + "\n" + profile.resume_text      # what a number, skill or employer must be found in
    plan = _draft(client, "%s\n\nThe facts:\n%s" % (_INSTRUCTIONS % _LIMITS, reading), profile, known,
                  "plan the profile from the resume and answers")
    if plan is None:
        raise PlanError("the LLM gave no usable profile plan after %d tries" % _ATTEMPTS)
    plan.review = quality_report(plan)
    if plan.review:
        logger.info("The reviewer sent the draft back with %d note(s): %s", len(plan.review),
                    " ".join(plan.review[:3]))
        notes = "\n".join("- " + note for note in plan.review)
        revised = _draft(client, "%s\n\nThe facts:\n%s" % (_EDITOR % {"notes": notes, "draft": _draft_json(plan)},
                                                              reading), profile, known, "revise the profile")
        if revised is not None:
            revised.review = quality_report(revised)
            if len(revised.review) <= len(plan.review):
                plan = revised
        if plan.review:
            logger.warning("The profile plan still has %d reviewer note(s): %s", len(plan.review),
                           " ".join(plan.review))
    plan.ats = ats_report(profile.resume_text, plan.target_keywords or profile.skills)
    if not fresh:
        plan = _keep_better(path, plan, profile, known)
    _save(path, key, plan)
    return plan


# ---------------------------------------------------------------------------
# What the agents read
# ---------------------------------------------------------------------------


def _role_line(number: int, role: Dict[str, str]) -> str:
    when = " - ".join(part for part in (role.get("start"), role.get("end")) if part)
    head = ", ".join(part for part in (role.get("title"), role.get("company"), role.get("location"), when) if part)
    lines = ["  %d. %s" % (number, head)]
    if role.get("skills"):
        lines.append("     Skills used: %s" % role["skills"])
    if role.get("description"):
        lines.append("     Job profile / description:")
        lines += ["       " + line for line in role["description"].splitlines() if line.strip()]
    return "\n".join(lines)


def _project_line(number: int, project: Dict[str, str]) -> str:
    head = project["name"] + (" (%s)" % project["skills"] if project.get("skills") else "")
    if project.get("role"):
        head += ", role: " + project["role"]
    if project.get("client"):
        head += ", client: " + project["client"]
    when = " - ".join(part for part in (project.get("start"), project.get("end")) if part)
    if when:
        head += ", " + when
    lines = ["  %d. %s" % (number, head)]
    if project.get("description"):
        lines.append("     " + project["description"])
    if project.get("url"):
        lines.append("     URL: " + project["url"])
    return "\n".join(lines)


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
        lines.append("- Profile summary (fields up to about %d characters, e.g. Naukri): %s"
                     % (SUMMARY_CHARS, plan.summary))
    if plan.short_summary:
        lines.append("- Short summary (one-paragraph fields and bios, e.g. Instahyre, Wellfound): %s"
                     % plan.short_summary)
    if plan.about and plan.about != plan.summary:
        lines.append("- About (long fields, e.g. LinkedIn; keep the paragraph breaks):\n%s" % plan.about)
    if plan.key_skills:
        lines.append("- Key skills, most important first (add the missing ones; remove skills she does not "
                     "list only if the board has a limit): %s" % ", ".join(plan.key_skills))
    if plan.target_roles:
        lines.append("- Preferred / desired roles: %s" % ", ".join(plan.target_roles))
    if plan.experience:
        lines.append("- Employment, newest first (title, company and dates must match; the job profile is the "
                     "description to enter; 'Skills used' when the board asks for them):")
        lines += [_role_line(number, role) for number, role in enumerate(plan.experience, 1)]
    if plan.projects:
        lines.append("- Projects (add the ones the board lacks with this text; never delete one):")
        lines += [_project_line(number, project) for number, project in enumerate(plan.projects, 1)]
    if plan.it_skills:
        lines.append("- IT skills (name, years of experience, last used): %s" % "; ".join(
            "%s, %s yrs%s" % (skill["name"], skill.get("years") or "?",
                              ", last used %s" % skill["last_used"] if skill.get("last_used") else "")
            for skill in plan.it_skills))
    if plan.certifications:
        lines.append("- Certifications: %s" % "; ".join(plan.certifications))
    if plan.links:
        lines.append("- Online profiles / links: %s" % ", ".join(plan.links))
    lines.append("Fill every other empty profile section the facts can answer (education, career profile, "
                 "locations, salary, notice period). Update a field only when the planned text differs in meaning "
                 "or the field is empty. When a board makes a field mandatory that neither this plan nor the facts "
                 "answer, do not guess: leave that section unsaved, name the field in your report, and go on.")
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


def review_text(plan: ProfilePlan) -> str:
    if not plan.review:
        return "Reviewer: the plan passes every check (hook, figures, stack, ask, no filler, lengths)."
    return "Reviewer's notes still open:\n" + "\n".join("- " + note for note in plan.review)


def plan_for(profile: Optional[Profile], settings: Settings) -> Optional[ProfilePlan]:
    """build_plan for the profile agents; None (and a warning) when it cannot be made."""
    if profile is None:
        return None
    try:
        plan = build_plan(profile, settings)
    except Exception as exc:
        logger.error("Could not plan the profile with the LLM: %s", exc)
        return None
    logger.info("Profile plan (%s): %s %s", plan.source, ats_text(plan).replace("\n", " "),
                review_text(plan).replace("\n", " "))
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
        print(review_text(plan))
        print()
        print(agent_brief(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
