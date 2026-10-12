"""Load user-authored facts and resume text into the shared Profile contract."""

import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from .models import Profile, Settings


logger = logging.getLogger(__name__)


class ProfileError(Exception):
    """A profile or resume could not be loaded safely."""


_PROFILE_KEYS = {
    "full_name",
    "first_name",
    "last_name",
    "email",
    "phone",
    "current_location",
    "preferred_locations",
    "total_experience_years",
    "current_ctc_lpa",
    "expected_ctc_lpa",
    "notice_period_days",
    "serving_notice",
    "willing_to_relocate",
    "work_authorization",
    "has_passport",
    "highest_qualification",
    "skills",
    "titles",
    "extra_facts",
}

_SKILL_KEYWORDS = [
    "Python", "C++", "SQL", "LLM evaluation", "LLM benchmarking",
    "agentic AI", "multi-agent orchestration", "prompt engineering", "RAG",
    "hybrid retrieval", "embeddings", "vector search", "RLHF", "fine-tuning",
    "OpenAI API", "Anthropic API", "LangChain", "LiteLLM", "OpenHands",
    "Hugging Face Transformers", "PyTorch", "FastAPI", "pytest", "spaCy",
    "Pandas", "NumPy", "Scikit-learn", "PySpark", "AWS Bedrock", "AWS EC2",
    "AWS S3", "Docker", "Git", "Git LFS", "CI/CD", "PostgreSQL", "FAISS",
    "pgvector", "Linux",
]

_TITLE_KEYWORDS = [
    "AI Engineer",
    "AI Research Engineer",
    "Machine Learning Engineer",
    "LLM Engineer",
    "Applied Scientist",
    "Software Engineer - AI",
]

_LATEX_WRAPPER = re.compile(
    r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}"
)
_LATEX_ENV_LINE = re.compile(r"^\s*\\(?:begin|end)\{[^}]+\}\s*$")
_LATEX_COMMAND = re.compile(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?")


def extract_resume_text(path: str) -> str:
    """Read resume text, simplifying LaTeX while preserving plain text."""
    resume_path = Path(path)
    try:
        with resume_path.open("r", encoding="utf-8") as resume_file:
            text = resume_file.read()
    except UnicodeError as exc:
        # A PDF or DOCX resume, which is what most people have. Reading it as
        # text yields binary noise, and noise in the resume silently degrades
        # every lexical score, so say what to do instead of guessing.
        raise ProfileError(
            "Could not read resume at %s: it is not text (%s). Only .tex and "
            ".txt are supported -- export or copy your resume to a .txt file "
            "and point RESUME_PATH at that." % (path, exc)
        ) from exc
    except OSError as exc:
        raise ProfileError("Could not read resume at %s: %s" % (path, exc)) from exc

    extension = resume_path.suffix.lower()
    if extension == ".txt":
        return text
    if extension != ".tex":
        logger.warning("Unsupported resume extension %s; reading as plain text", extension)
        return text

    body = re.search(r"\\begin\{document\}(.*?)(?:\\end\{document\}|\Z)", text, re.S)
    if body:
        text = body.group(1)
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        if _LATEX_ENV_LINE.match(line):
            continue
        lines.append(line)
    simplified = "\n".join(lines)
    while _LATEX_WRAPPER.search(simplified):
        simplified = _LATEX_WRAPPER.sub(r"\1", simplified)
    simplified = _LATEX_COMMAND.sub(" ", simplified)
    simplified = simplified.replace("{", " ").replace("}", " ")
    simplified = simplified.replace("~", " ")
    return " ".join(simplified.split())


def _derive_keywords(resume_text: str, candidates: List[str]) -> List[str]:
    derived = []
    for candidate in candidates:
        pattern = r"(?<!\w)%s(?!\w)" % re.escape(candidate)
        if re.search(pattern, resume_text, flags=re.IGNORECASE):
            derived.append(candidate)
    return derived


def _yaml_list(facts: Dict[str, Any], key: str) -> List[str]:
    value = facts.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProfileError("Profile field %s must be a YAML list of strings" % key)
    return list(value)


def _dates_as_text(value: Any) -> Any:
    """YAML reads an unquoted 2003-04-05 as a date object; keep it as the text typed."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _dates_as_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_dates_as_text(item) for item in value]
    return value


def load_profile(settings: Settings) -> Profile:
    """Load the configured YAML facts and resume without inventing facts."""
    try:
        import yaml
    except ImportError as exc:
        raise ProfileError(
            "PyYAML is required to load the profile; install it with `pip install PyYAML`."
        ) from exc

    profile_path = Path(settings.profile_path)
    if not profile_path.is_file():
        raise ProfileError(
            "Profile file not found at %s. Copy common/profile.example.yaml there "
            "and fill it in." % settings.profile_path
        )
    try:
        with profile_path.open("r", encoding="utf-8") as profile_file:
            loaded = yaml.safe_load(profile_file)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ProfileError(
            "Could not load profile YAML at %s: %s" % (settings.profile_path, exc)
        ) from exc

    if loaded is None:
        facts: Dict[str, Any] = {}
    elif isinstance(loaded, dict):
        facts = _dates_as_text(loaded)
    else:
        raise ProfileError("Profile YAML must contain a mapping of fact names to values")

    resume_text = extract_resume_text(settings.resume_path)
    skills = (
        _yaml_list(facts, "skills")
        if "skills" in facts
        else _derive_keywords(resume_text, _SKILL_KEYWORDS)
    )
    titles = (
        _yaml_list(facts, "titles")
        if "titles" in facts
        else _derive_keywords(resume_text, _TITLE_KEYWORDS)
    )
    preferred_locations = _yaml_list(facts, "preferred_locations")

    configured_extra = facts.get("extra_facts")
    if configured_extra is None:
        extra_facts: Dict[str, Any] = {}
    elif isinstance(configured_extra, dict):
        extra_facts = dict(configured_extra)
    else:
        raise ProfileError("Profile field extra_facts must be a YAML mapping")
    extra_facts.update(
        {key: value for key, value in facts.items() if key not in _PROFILE_KEYS}
    )

    return Profile(
        full_name=facts.get("full_name", ""),
        first_name=facts.get("first_name", ""),
        last_name=facts.get("last_name", ""),
        email=facts.get("email", ""),
        phone=facts.get("phone", ""),
        current_location=facts.get("current_location", ""),
        preferred_locations=preferred_locations,
        total_experience_years=facts.get("total_experience_years"),
        current_ctc_lpa=facts.get("current_ctc_lpa"),
        expected_ctc_lpa=facts.get("expected_ctc_lpa"),
        notice_period_days=facts.get("notice_period_days"),
        serving_notice=facts.get("serving_notice"),
        willing_to_relocate=facts.get("willing_to_relocate"),
        work_authorization=facts.get("work_authorization", ""),
        has_passport=facts.get("has_passport"),
        highest_qualification=facts.get("highest_qualification", ""),
        skills=skills,
        titles=titles,
        resume_text=resume_text,
        extra_facts=extra_facts,
    )
