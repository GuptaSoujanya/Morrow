"""Who the user is, in the words the bots write with: user/inputs/persona.yaml.

profile.yaml holds the facts a screening form asks for. persona.yaml holds what
the writing stages need instead: a one-line headline, the pronouns the agent
prompts use, the facts a LinkedIn post may draw on, how the person writes, the
topics they post about, and the areas of their resume to study. Every one of
these used to be a constant in the code, written for one person; now the first
run (common.onboard) derives them from the resume and the file is the only
source.

A missing file gives a neutral Persona: nothing about any particular person,
so a bot started before onboarding never writes under someone else's name.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import paths

logger = logging.getLogger(__name__)

FILE_NAME = "persona.yaml"

#: Pronoun sets the prompts can be written with: subject, object, possessive.
_PRONOUNS = {
    "they/them": ("they", "them", "their"),
    "she/her": ("she", "her", "her"),
    "he/him": ("he", "him", "his"),
}
DEFAULT_PRONOUNS = "they/them"


@dataclass
class StudyArea:
    """One resume-learning file: NN-<slug>.md about <title>."""

    slug: str
    title: str


@dataclass
class Persona:
    name: str = ""
    pronouns: str = DEFAULT_PRONOUNS
    #: One line: "software engineer at X in Y, working on Z".
    headline: str = ""
    experience_years: Optional[float] = None
    employer: str = ""
    location: str = ""
    site: str = ""
    #: What the person works on, for prompts that ask "why it matters for you".
    focus: str = ""
    #: The facts a post may use, each a sentence the resume supports.
    facts: List[str] = field(default_factory=list)
    #: How the person writes, as instructions ("first person, plain words...").
    voice: str = ""
    #: A short passage in their own words, for register.
    voice_sample: str = ""
    #: LinkedIn topics; LINKEDIN_TOPICS in .env overrides.
    topics: List[str] = field(default_factory=list)
    #: The areas of the resume the 90-day study stage writes a file for.
    study_areas: List[StudyArea] = field(default_factory=list)
    #: What the study plan is for ("senior interview level in ...").
    goal: str = ""
    path: Optional[Path] = None

    @property
    def is_set(self) -> bool:
        return bool(self.name or self.headline or self.facts)

    def forms(self) -> Tuple[str, str, str]:
        """(subject, object, possessive), e.g. ("she", "her", "her")."""
        return _PRONOUNS.get(self.pronouns.strip().lower(), _PRONOUNS[DEFAULT_PRONOUNS])

    @property
    def they(self) -> str:
        return self.forms()[0]

    @property
    def them(self) -> str:
        return self.forms()[1]

    @property
    def their(self) -> str:
        return self.forms()[2]

    def learner_line(self) -> str:
        """"a software engineer in India (about 2 years, LLM evaluation)", for the study prompts."""
        who = self.headline or "a software engineer"
        if not who.lower().startswith(("a ", "an ")):
            who = ("an " if who[:1].lower() in "aeiou" else "a ") + who
        bits = []
        if self.experience_years is not None:
            bits.append("about %s years of experience" % _years(self.experience_years))
        if self.focus:
            bits.append(self.focus)
        return who + (" (%s)" % ", ".join(bits) if bits else "")

    def voice_block(self) -> str:
        """The VOICE text the LinkedIn writer is given: facts, then register."""
        lines = ["Facts about the author (the only facts a post may use):"]
        if self.name:
            lines.append("- %s%s." % (self.name, (", " + self.headline) if self.headline else ""))
        elif self.headline:
            lines.append("- %s." % self.headline.capitalize())
        lines += ["- %s" % fact.rstrip(".") + "." for fact in self.facts]
        if self.site:
            lines.append("- Site: %s" % self.site)
        if len(lines) == 1:
            lines.append("- (none given: write about the article only and claim nothing about the author)")
        how = self.voice.strip() or "first person, plain words, short paragraphs, concrete, never salesy."
        lines += ["", "How %s writes: %s" % (self.they, how)]
        if self.voice_sample.strip():
            lines.append('For register, in %s own words: "%s"' % (self.their, self.voice_sample.strip()))
        return "\n".join(lines) + "\n"


def _years(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else "%.1f" % value


def default_path() -> Path:
    return paths.inputs_dir() / FILE_NAME


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if _text(item)]
    return []


def _areas(value: Any) -> List[StudyArea]:
    areas = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            slug, title = _text(item.get("slug")), _text(item.get("title"))
        else:
            slug, title = "", _text(item)
        if title:
            areas.append(StudyArea(slug or slugify(title), title))
    return areas


def slugify(title: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return "-".join(slug.split("-")[:5]) or "area"


def from_mapping(data: Dict[str, Any], path: Optional[Path] = None) -> Persona:
    years = data.get("experience_years")
    try:
        years = float(years) if years not in (None, "") else None
    except (TypeError, ValueError):
        years = None
    return Persona(
        name=_text(data.get("name")),
        pronouns=_text(data.get("pronouns")) or DEFAULT_PRONOUNS,
        headline=_text(data.get("headline")),
        experience_years=years,
        employer=_text(data.get("employer")),
        location=_text(data.get("location")),
        site=_text(data.get("site")),
        focus=_text(data.get("focus")),
        facts=_list(data.get("facts")),
        voice=_text(data.get("voice")),
        voice_sample=_text(data.get("voice_sample")),
        topics=_list(data.get("topics")),
        study_areas=_areas(data.get("study_areas")),
        goal=_text(data.get("goal")),
        path=path,
    )


def to_mapping(persona: Persona) -> Dict[str, Any]:
    return {
        "name": persona.name,
        "pronouns": persona.pronouns,
        "headline": persona.headline,
        "experience_years": persona.experience_years,
        "employer": persona.employer,
        "location": persona.location,
        "site": persona.site,
        "focus": persona.focus,
        "facts": list(persona.facts),
        "voice": persona.voice,
        "voice_sample": persona.voice_sample,
        "topics": list(persona.topics),
        "study_areas": [{"slug": area.slug, "title": area.title} for area in persona.study_areas],
        "goal": persona.goal,
    }


_cache: Dict[str, Persona] = {}


def load_persona(path: Optional[Path] = None) -> Persona:
    """The persona at path (user/inputs/persona.yaml by default); neutral when there is none."""
    path = Path(path) if path is not None else default_path()
    key = str(path.resolve()) if path.exists() else str(path)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return Persona()
    cached = _cache.get(key)
    if cached is not None and getattr(cached, "_stamp", None) == stamp:
        return cached
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a bad persona must not stop a run
        logger.warning("Could not read %s (%s); writing without a persona.", path, exc)
        return Persona()
    persona = from_mapping(loaded if isinstance(loaded, dict) else {}, path)
    persona._stamp = stamp  # type: ignore[attr-defined]
    _cache[key] = persona
    return persona


def save_persona(persona: Persona, path: Optional[Path] = None) -> Path:
    import yaml

    path = Path(path) if path is not None else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Who you are, in the words the bots write with. Written by the first run\n"
        "# (python3 -m pipeline onboard) from your resume; edit freely. See\n"
        "# common/persona.example.yaml for what each field does.\n"
    )
    body = yaml.safe_dump(to_mapping(persona), sort_keys=False, allow_unicode=True, width=100)
    path.write_text(header + body, encoding="utf-8")
    _cache.pop(str(path.resolve()), None)
    return path
