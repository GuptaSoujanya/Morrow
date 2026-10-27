"""Load user-authored facts and resume text into the shared Profile contract."""

import datetime
import logging
import re
import shutil
import subprocess
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

# Fallbacks for a profile.yaml without `skills` or `titles`: the ones of these
# the resume mentions. Broad on purpose; the first run (common.onboard) writes
# the person's own lists, which are always better than this.
_SKILL_KEYWORDS = [
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++", "C#", "Kotlin", "Swift",
    "Scala", "Ruby", "PHP", "SQL", "React", "Next.js", "Angular", "Vue", "Node.js", "Express",
    "Django", "Flask", "FastAPI", "Spring Boot", ".NET", "Rails", "GraphQL", "REST APIs",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Kafka", "RabbitMQ", "Spark",
    "Airflow", "Pandas", "NumPy", "Scikit-learn", "PyTorch", "TensorFlow", "machine learning",
    "deep learning", "NLP", "computer vision", "LLM", "RAG", "LangChain", "prompt engineering",
    "fine-tuning", "embeddings", "vector search", "Docker", "Kubernetes", "Terraform", "AWS",
    "GCP", "Azure", "CI/CD", "Linux", "Git", "pytest", "microservices", "system design",
]

_TITLE_KEYWORDS = [
    "Software Engineer",
    "Backend Engineer",
    "Frontend Engineer",
    "Full Stack Developer",
    "Data Engineer",
    "Data Scientist",
    "Machine Learning Engineer",
    "AI Engineer",
    "DevOps Engineer",
    "Site Reliability Engineer",
]

_LATEX_WRAPPER = re.compile(
    r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}"
)
_LATEX_ENV_LINE = re.compile(r"^\s*\\(?:begin|end)\{[^}]+\}\s*$")
_LATEX_COMMAND = re.compile(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?")

PDF_MAX_BYTES = 10 * 1024 * 1024
PDF_MAX_PAGES = 20
PDF_MAX_TEXT = 1024 * 1024


def extract_pdf_text(content: bytes) -> str:
    """Read an uploaded PDF with Poppler, without writing extracted text to disk."""
    if not isinstance(content, bytes) or not content.startswith(b"%PDF-") or len(content) > PDF_MAX_BYTES:
        raise ProfileError("Upload a valid resume PDF no larger than 10 MB.")
    parser = shutil.which("pdftotext")
    if not parser:
        raise ProfileError("PDF text extraction is unavailable on this computer. Install Poppler (pdftotext), then finish setup again.")
    try:
        result = subprocess.run(
            [parser, "-f", "1", "-l", str(PDF_MAX_PAGES + 1), "-enc", "UTF-8", "-", "-"],
            input=content, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ProfileError("This PDF took too long to read. Export a simpler PDF with selectable text and upload it again.") from None
    except OSError:
        raise ProfileError("The PDF reader could not start. Check Poppler is installed, then finish setup again.") from None
    if result.returncode != 0:
        raise ProfileError("The resume PDF could not be read. Export an unlocked PDF with selectable text and upload it again.")
    if len(result.stdout) > PDF_MAX_TEXT or result.stdout.count(b"\f") > PDF_MAX_PAGES:
        raise ProfileError("Use a resume PDF with no more than 20 pages and less than 1 MB of text.")
    text = result.stdout.decode("utf-8", errors="replace").replace("\f", "\n").strip()
    if not text or not re.search(r"[^\W\d_]", text, flags=re.UNICODE):
        raise ProfileError("This PDF has no readable text. Export a PDF with selectable text instead of a scanned image, then upload it again.")
    return text


def extract_resume_text(path: str) -> str:
    """Read PDF, plain-text or LaTeX resume content without interpreting binary as text."""
    resume_path = Path(path)
    if resume_path.suffix.lower() == ".pdf":
        try:
            if resume_path.stat().st_size > PDF_MAX_BYTES:
                raise ProfileError("Upload a valid resume PDF no larger than 10 MB.")
            return extract_pdf_text(resume_path.read_bytes())
        except OSError:
            raise ProfileError("The resume PDF is missing or unreadable. Select it again in setup.") from None
    try:
        with resume_path.open("r", encoding="utf-8") as resume_file:
            text = resume_file.read()
    except UnicodeError as exc:
        raise ProfileError(
            "Could not read resume at %s: it is not text. Use a PDF with selectable text, "
            "a .tex source, or a .txt file." % path
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
