"""The first run: everything Morrow needs to know about one person, written under user/.

    python3 -m pipeline onboard                       # interactive, the normal way
    python3 -m common.onboard --resume ~/cv.pdf       # the same
    python3 -m common.onboard --yes --resume cv.pdf --answers facts.json   # no prompts

Morrow is public and holds nothing personal; the bots read one person's files
from user/ (common/paths.py). Until now those files were written by hand from
templates, and a handful of things about the owner (the LinkedIn voice, the
study areas, the pronouns in the agent prompts) lived in the code itself. This
module replaces both: it reads the resume, asks the model to pull the facts out
of it, asks the person for what a resume cannot say, and writes every input
file the bots and the pipeline read:

    .env                          credentials, boards, the model backend (from .env.example)
    user/inputs/profile.yaml      the facts screening questions are answered from
    user/inputs/persona.yaml      who the person is, for the writing stages (common/persona.py)
    user/inputs/answers.txt       the facts again as Q:/A: lines, plus the marker the bots append under
    user/inputs/accounts.md       career-site accounts the bot makes (empty table)
    user/inputs/company_sites.md  employer-site applications left for the person (empty)
    user/resume/base.tex          the resume as LaTeX, converted from a PDF when needed
    user/memory/*.json            the pipeline's empty checkpoint

The first `python3 -m pipeline` after this derives the rest (the profile plan,
the study files, the 90-day plan) from these files; nothing in the output is
specific to any other person.

Nothing is invented: a fact the model could not read off the resume is asked
for, and a question left blank stays blank, which the bots treat as unknown.
"""

import argparse
import getpass
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import paths, persona as persona_module
from .config import load_settings, write_env_value
from .models import LLMBackend

logger = logging.getLogger(__name__)

TEMPLATE_TEX = Path(__file__).with_name("resume_template.tex")
RESUME_TEXT_CHARS = 12000

ACCOUNTS_MD = """# Career-site accounts the bot signed in to or created

Every account uses the email below and the password saved as COMPANY_SITE_PASSWORD in .env.

| Date | Site | Email | What happened |
|---|---|---|---|
"""

COMPANY_SITES_MD = """# Applications on company websites that need you

The bot opened these from Naukri's "Apply on company site" button, filled
what it could and stopped short of submitting. Finish each one by hand, or
answer the open questions in answers.txt and run
`python3 -m naukri_bot.external --url <site link> --title "..." --company "..."`.
Delete an entry once you have applied; the bot drops it itself when it
finishes one, and replaces it when it tries the same job again.
"""

ANSWERS_HEADER = """# Your own answers to screening questions, in your own words.
#
# A block is one or more Q: lines (different wordings of the same question)
# followed by one A: line. The bot sends the A: text as it stands, so every
# answer here is one you are prepared to stand behind. Lines starting with #
# are comments. An A: left blank means "unknown": the bot skips that question.
#
# Written by the first run from your profile.yaml; edit freely.
"""
UNANSWERED_MARKER = "# ----- questions the bot could not answer are added below this line"

USER_GITIGNORE = """# Logged-in browser sessions (cookies, tokens) and runner secrets stay on this
# computer only.
browser/
docker/browser/
private/connections/
private/runner/

# SQLite scratch files; the .db holds everything after a checkpoint.
*.db-wal
*.db-shm
*.db-journal

# Lock files only exist while a run holds them.
*.lock
.DS_Store
__pycache__/
"""

USER_FOLDERS = ("inputs", "resume/out", "db", "reports", "memory", "research", "worklists",
                "logs", "screenshots", "browser", "linkedin", "linkedin_post")


class OnboardError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Asking the person
# ---------------------------------------------------------------------------


class Prompter:
    """Questions on the terminal; with yes=True every answer is the default (or the one given)."""

    def __init__(self, answers: Optional[Dict[str, Any]] = None, yes: bool = False,
                 ask: Callable[[str], str] = input, secret: Callable[[str], str] = getpass.getpass,
                 out: Callable[[str], None] = print):
        self.answers = dict(answers or {})
        self.yes = yes
        self._ask, self._secret, self.say = ask, secret, out

    def ask(self, key: str, question: str, default: Any = "", secret: bool = False, hint: str = "") -> Any:
        if key in self.answers:
            return self.answers[key]
        if self.yes:
            return default
        shown = "" if secret or default in ("", None, []) else " [%s]" % _show(default)
        if hint:
            self.say("  " + hint)
        try:
            raw = (self._secret if secret else self._ask)("%s%s: " % (question, shown))
        except EOFError:
            raw = ""
        raw = raw.strip()
        return default if raw == "" else raw

    def confirm(self, key: str, question: str, default: bool = True) -> bool:
        value = self.ask(key, question + (" (Y/n)" if default else " (y/N)"), default)
        return _bool(value, default)

    def section(self, title: str) -> None:
        self.say("\n== %s ==" % title)


def _show(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("y", "yes", "true", "1"):
        return True
    if text in ("n", "no", "false", "0"):
        return False
    return default


def _list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _number(value: Any) -> Optional[float]:
    if value in ("", None):
        return None
    try:
        number = float(str(value).strip().rstrip("+"))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


# ---------------------------------------------------------------------------
# What the model reads off the resume
# ---------------------------------------------------------------------------


_PROFILE_SCHEMA = json.dumps({
    "full_name": "", "first_name": "", "last_name": "", "email": "", "phone": "",
    "current_location": "", "total_experience_years": 0, "highest_qualification": "",
    "titles": [], "skills": [], "current_company": "", "current_designation": "",
    "employment_history": "", "degree": "", "university": "", "graduation_year": "",
    "certifications": "", "github_url": "", "linkedin_url": "", "portfolio_url": "",
})

_PROFILE_PROMPT = """Read this resume and fill the JSON below with ONLY what the resume states.
Leave a value empty ("" or [] or 0) when the resume does not say; never guess, round or infer.
- full_name as written in the header; first_name and last_name split from it.
- total_experience_years: the number of years of professional work experience the dated roles
  add up to (internships count), as a number; 0 when there are no dated roles.
- titles: 3 to 5 job titles this person would apply for, closest to their current title first.
- skills: the 15 to 25 most prominent technologies, tools and methods, each as written.
- employment_history: one sentence naming every employer with its dates, current one first.
- highest_qualification: degree, field, institution and year on one line.
- certifications: comma-separated, or empty.
- links: the GitHub, LinkedIn and personal-site URLs if printed.

RESUME:
%s"""

_PERSONA_SCHEMA = json.dumps({
    "headline": "", "employer": "", "location": "", "focus": "", "facts": [],
    "topics": [], "study_areas": [{"slug": "", "title": ""}], "voice_sample": "",
})

_PERSONA_PROMPT = """Read this resume and describe its owner for the tools that will write on their behalf
(a LinkedIn poster and a study-plan generator). Use ONLY what the resume states.
- headline: one line, no "I am", of the form "<current title> at <employer> in <city>, working on <what>".
- employer and location: the current ones, or empty.
- focus: in 5 to 10 words, what their work is about (the area, not the tools).
- facts: 4 to 7 sentences a social post could draw on, each a thing the resume shows they built, ran or
  know, with the resume's own numbers and names. Each starts with a past-tense verb and names no person:
  "Grew the X benchmark into ...", never "Gupta grew" or "She grew". No adjectives.
- topics: 5 subjects they would post about, each 1 to 4 words, from the resume's main technologies
  and themes.
- study_areas: 8 to 12 areas of this resume an interviewer would probe, in order of weight. Each has a
  "slug" (lowercase words joined by hyphens, at most 5 words) and a "title" (the area plus the concrete
  things from the resume it covers, in one line).
- voice_sample: the resume's summary paragraph verbatim if it is written in the first person, else empty.

RESUME:
%s"""

_TEX_SCHEMA = json.dumps({"tex": ""})

_TEX_PROMPT = """Convert this resume into LaTeX using EXACTLY the template below: keep its preamble, macros and
section layout, and replace only the placeholder content. Rules:
- Every fact, number, date, employer, project and skill comes from the resume text; add nothing,
  drop nothing of substance, do not reword bullet points beyond fixing extraction line breaks.
- The header name in capitals; the subtitle line is the resume's title or tagline.
- Keep \\section{Summary} as ONE paragraph followed by a blank line, and \\section{Skills} as
  "{\\bfseries Category:} items" lines followed by a blank line, as the template shows.
- Escape &, %%, #, _ as \\&, \\%%, \\#, \\_ in text. No \\usepackage additions.
- Return the full document as the "tex" string.

TEMPLATE:
%s

RESUME TEXT:
%s"""


def _extract(client: Any, prompt: str, schema: str) -> Dict[str, Any]:
    if client is None or not client.available():
        return {}
    try:
        payload = client.complete_json(prompt, schema)
    except Exception as exc:  # noqa: BLE001 - the model is optional here
        logger.warning("The model could not read the resume: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class Onboarding:
    root: Path = paths.ROOT
    user_dir: Path = field(default_factory=paths.user_dir)
    env_path: Optional[Path] = None
    resume: Optional[Path] = None
    prompter: Prompter = field(default_factory=Prompter)
    client: Any = None  # an LLMClient; built from .env when None
    written: List[Path] = field(default_factory=list)
    resume_text: str = ""
    resume_setting: str = ""
    tailoring: bool = True
    profile: Dict[str, Any] = field(default_factory=dict)
    persona: Optional[persona_module.Persona] = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.user_dir = Path(self.user_dir)
        if not self.user_dir.is_absolute():
            self.user_dir = self.root / self.user_dir
        self.env_path = Path(self.env_path) if self.env_path else self.root / ".env"

    # -- helpers ---------------------------------------------------------------

    @property
    def inputs(self) -> Path:
        return self.user_dir / "inputs"

    def say(self, text: str) -> None:
        self.prompter.say(text)

    def _write(self, path: Path, text: str, mode: Optional[int] = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if mode is not None:
            os.chmod(path, mode)
        self.written.append(path)
        return path

    def _env(self, key: str, value: str) -> None:
        write_env_value(str(self.env_path), key, value)

    def _user_setting(self, *parts: str) -> str:
        """user/inputs/x as the .env spells it: relative when user/ is the default folder."""
        default = (self.root / paths.DEFAULT_USER_DIR).resolve()
        if self.user_dir.resolve() == default:
            return "/".join((paths.DEFAULT_USER_DIR,) + parts)
        return str(self.user_dir.joinpath(*parts))

    # -- steps -----------------------------------------------------------------

    def run(self) -> int:
        self.say("Morrow first run: your files go under %s and nothing leaves this computer." % self.user_dir)
        self.layout()
        self.environment()
        self.client = self.client or self._client()
        self.collect_resume()
        self.collect_profile()
        self.build_persona()
        self.write_answers()
        self.write_worklists()
        self.write_memory()
        self.finish()
        return 0

    def layout(self) -> None:
        for folder in USER_FOLDERS:
            (self.user_dir / folder).mkdir(parents=True, exist_ok=True)
        ignore = self.user_dir / ".gitignore"
        if not ignore.exists():
            self._write(ignore, USER_GITIGNORE)

    def environment(self) -> None:
        self.prompter.section("Accounts and settings (.env)")
        if not self.env_path.exists():
            example = self.root / ".env.example"
            if not example.exists():
                raise OnboardError("neither %s nor .env.example exists" % self.env_path)
            shutil.copy(example, self.env_path)
            os.chmod(self.env_path, 0o600)
            self.written.append(self.env_path)
            self.say("Wrote %s from .env.example." % self.env_path)
        if self.user_dir.resolve() != (self.root / paths.DEFAULT_USER_DIR).resolve():
            self._env(paths.USER_DIR_ENV, str(self.user_dir))
        current = load_settings(str(self.env_path))
        ask = self.prompter.ask
        email = ask("naukri_email", "Naukri sign-in email",
                    current.email if "@" in current.email and not current.email.endswith("@example.com") else "")
        if email:
            self._env("NAUKRI_EMAIL", email)
            password = ask("naukri_password", "Naukri password (kept only in .env, blank to keep as is)", "", secret=True)
            if password:
                self._env("NAUKRI_PASSWORD", password)
        platforms = _list(ask("platforms", "Other boards to run, comma-separated (hirist, instahyre, cutshort, wellfound)",
                              current.platforms or ["hirist", "instahyre"]))
        self._env("PLATFORMS", ",".join(platforms))
        backend = str(ask("llm_backend", "Model backend for answers and writing",
                          _default_backend(current.llm_backend),
                          hint="claude-cli and kiro-cli use the CLI on your PATH; anthropic needs ANTHROPIC_API_KEY; "
                               "none answers only from your own words.")).strip()
        self._env("LLM_BACKEND", backend)
        if backend == LLMBackend.ANTHROPIC and not os.getenv("ANTHROPIC_API_KEY"):
            key = ask("anthropic_api_key", "ANTHROPIC_API_KEY", "", secret=True)
            if key:
                self._env("ANTHROPIC_API_KEY", key)

    def _client(self) -> Any:
        from .llm import build_client

        client = build_client(load_settings(str(self.env_path)))
        if not client.available():
            self.say("No model backend is available: the resume will not be read for you, so the "
                     "questions below start empty.")
        return client

    def collect_resume(self) -> None:
        from .profile import ProfileError, extract_resume_text

        self.prompter.section("Resume")
        source = self.resume
        if source is None:
            raw = self.prompter.ask("resume", "Path to your resume (.pdf, .tex, .txt or .md)", "")
            source = Path(str(raw)).expanduser() if raw else None
        base = self.user_dir / "resume" / "base.tex"
        if source is None or not Path(source).is_file():
            if source is not None:
                self.say("No file at %s." % source)
            if base.is_file():
                self.say("Keeping the resume already at %s." % base)
                source = base
            else:
                self.say("No resume: the bots cannot rank or apply until RESUME_PATH points at one.")
                self.tailoring = False
                return
        source = Path(source)
        try:
            self.resume_text = extract_resume_text(str(source))
        except ProfileError as exc:
            raise OnboardError(str(exc))
        if source.suffix.lower() == ".tex":
            if source.resolve() != base.resolve():
                base.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source, base)
                self.written.append(base)
            self.resume_setting = self._user_setting("resume", "base.tex")
            self.say("Resume: %s" % base)
            return
        copied = self.user_dir / "resume" / source.name
        if source.resolve() != copied.resolve():
            shutil.copy(source, copied)
            self.written.append(copied)
        self.resume_setting = self._user_setting("resume", source.name)
        self.tailoring = False
        if base.is_file() and not self.prompter.confirm("replace_tex", "%s exists; rewrite it from this file?" % base, False):
            self.resume_setting = self._user_setting("resume", "base.tex")
            self.tailoring = True
            return
        tex = self._convert_to_tex()
        if tex:
            self._write(base, tex)
            self.resume_setting = self._user_setting("resume", "base.tex")
            self.tailoring = True
            self.say("Wrote %s from %s; read it over once, the bots compile and tailor it from now on." % (base, source.name))
        else:
            self.say("Kept %s as the resume; tailoring stays off until user/resume/base.tex exists." % source.name)

    def _convert_to_tex(self) -> str:
        """The resume as LaTeX in the template's shape, or "" when the model cannot produce one."""
        from .resume import ResumeError, _HEADER_NAME, parse_sections, unsafe_tex

        if self.client is None or not self.client.available():
            return ""
        self.say("Asking the model to lay the resume out as LaTeX (this takes a minute)...")
        template = TEMPLATE_TEX.read_text(encoding="utf-8")
        for attempt in (1, 2):
            payload = _extract(self.client, _TEX_PROMPT % (template, self.resume_text[:RESUME_TEXT_CHARS]), _TEX_SCHEMA)
            tex = str(payload.get("tex") or "").strip()
            if not tex:
                continue
            try:
                parse_sections(tex)
            except ResumeError as exc:
                logger.warning("Attempt %d: the LaTeX does not fit the template (%s)", attempt, exc)
                continue
            if _HEADER_NAME.search(tex) is None or "\\end{document}" not in tex:
                logger.warning("Attempt %d: the LaTeX has no header name or no end", attempt)
                continue
            if unsafe_tex(tex):
                logger.warning("Attempt %d: the LaTeX uses %s, which a resume never needs", attempt, unsafe_tex(tex))
                continue
            return tex + ("\n" if not tex.endswith("\n") else "")
        return ""

    def collect_profile(self) -> None:
        self.prompter.section("Your facts (user/inputs/profile.yaml)")
        read = {}
        if self.resume_text and self.client is not None and self.client.available():
            self.say("Reading the resume for your facts...")
            read = _extract(self.client, _PROFILE_PROMPT % self.resume_text[:RESUME_TEXT_CHARS], _PROFILE_SCHEMA)
        existing = self._existing_profile()
        extra_existing = existing.get("extra_facts") if isinstance(existing.get("extra_facts"), dict) else {}

        def prior(key: str, fallback: Any = "") -> Any:
            for source in (existing, extra_existing, read):
                value = source.get(key)
                if value not in (None, "", [], 0):
                    return value
            return fallback

        ask = self.prompter.ask
        self.say("Press Enter to keep a value in brackets; leave a question blank when you do not want to say.")
        facts = {}  # type: Dict[str, Any]
        facts["full_name"] = _person_case(ask("full_name", "Full name", _person_case(prior("full_name"))))
        names = str(facts["full_name"]).split()
        facts["first_name"] = ask("first_name", "First name", prior("first_name", names[0] if names else ""))
        facts["last_name"] = ask("last_name", "Last name", prior("last_name", names[-1] if len(names) > 1 else ""))
        facts["email"] = ask("email", "Email on applications", prior("email"))
        facts["phone"] = ask("phone", "Phone", prior("phone"))
        facts["current_location"] = ask("current_location", "Current city", prior("current_location"))
        facts["preferred_locations"] = _list(ask("preferred_locations", "Cities you would work in, comma-separated",
                                                 prior("preferred_locations", [facts["current_location"], "Remote"] if facts["current_location"] else ["Remote"])))
        facts["total_experience_years"] = _number(ask("total_experience_years", "Total years of experience",
                                                      prior("total_experience_years")))
        facts["highest_qualification"] = ask("highest_qualification", "Highest qualification (degree, institution, year)",
                                             prior("highest_qualification"))
        facts["titles"] = _list(ask("titles", "Job titles you want, comma-separated", prior("titles", [])))
        facts["skills"] = _list(ask("skills", "Skills to match jobs on, comma-separated", prior("skills", [])))
        facts["work_authorization"] = ask("work_authorization", "Work authorisation (e.g. Indian citizen, no sponsorship needed)",
                                          prior("work_authorization"))
        self.say("Salary and notice: blank means the bot abstains on that question rather than guessing.")
        facts["current_ctc_lpa"] = _number(ask("current_ctc_lpa", "Current CTC in lakhs per year", prior("current_ctc_lpa")))
        facts["expected_ctc_lpa"] = _number(ask("expected_ctc_lpa", "Expected CTC in lakhs per year", prior("expected_ctc_lpa")))
        notice = _number(ask("notice_period_days", "Notice period in days", prior("notice_period_days", 30)))
        facts["notice_period_days"] = int(notice) if notice is not None else None
        facts["serving_notice"] = _bool(ask("serving_notice", "Serving notice now? (y/N)", prior("serving_notice", False)), False)
        facts["willing_to_relocate"] = _bool(ask("willing_to_relocate", "Willing to relocate? (Y/n)", prior("willing_to_relocate", True)), True)
        facts["has_passport"] = _bool(ask("has_passport", "Have a passport? (Y/n)", prior("has_passport", True)), True)

        extra = {}  # type: Dict[str, Any]
        self.say("Everything else employers ask. Add more under extra_facts in the file later.")
        for key, question, default in (
            ("gender", "Gender, as forms ask it", prior("gender")),
            ("date_of_birth", "Date of birth (YYYY-MM-DD)", prior("date_of_birth")),
            ("languages_known", "Languages known, comma-separated", prior("languages_known")),
            ("current_company", "Current employer", prior("current_company")),
            ("current_designation", "Current job title", prior("current_designation")),
            ("employment_history", "Employment history in one sentence (every employer, with dates)", prior("employment_history")),
            ("degree", "Degree", prior("degree")),
            ("university", "University", prior("university")),
            ("graduation_year", "Graduation year", prior("graduation_year")),
            ("certifications", "Certifications, comma-separated", prior("certifications")),
            ("earliest_joining", "Earliest joining", prior("earliest_joining",
                                                          "%d days from the date of offer" % facts["notice_period_days"] if facts["notice_period_days"] else "")),
            ("work_mode_preference", "Work mode (office, hybrid, remote, flexible)", prior("work_mode_preference", "Flexible - open to office, hybrid or fully remote")),
            ("willing_night_shifts", "Willing to work night shifts? (y/N)", prior("willing_night_shifts", False)),
            ("willing_rotational_shifts", "Willing to work rotational shifts? (y/N)", prior("willing_rotational_shifts", False)),
            ("willing_virtual_interview", "Virtual interviews", prior("willing_virtual_interview", "Yes, available for a virtual or online interview")),
            ("willing_in_person_interview", "In-person interviews: where would you attend one?", prior("willing_in_person_interview")),
            ("attend_walk_in", "Walk-in drives: where would you attend one?", prior("attend_walk_in")),
            ("willing_to_sign_bond", "Willing to sign a bond? (y/N)", prior("willing_to_sign_bond", False)),
            ("open_to_startup", "Open to startups?", prior("open_to_startup", "Yes, open to working at a startup")),
            ("github_url", "GitHub URL", prior("github_url")),
            ("linkedin_url", "LinkedIn URL", prior("linkedin_url")),
            ("portfolio_url", "Personal site or portfolio URL", prior("portfolio_url")),
        ):
            value = ask(key, question, default)
            if key in ("willing_night_shifts", "willing_rotational_shifts", "willing_to_sign_bond"):
                value = _bool(value, False)
            if value not in ("", None):
                extra[key] = value
        extra.setdefault("job_discovery_source",
                         "Found this role on the Naukri.com job portal. If Naukri is not one of the offered "
                         "choices, any of Company Website or LinkedIn is acceptable - there is no preference "
                         "and this does not need to be exact.")
        if facts["total_experience_years"]:
            extra.setdefault("skill_experience_years",
                             "%s years of hands-on experience with any individual skill, technology, tool, "
                             "framework or role title named in a question." % _show(facts["total_experience_years"]))
        for key, value in extra_existing.items():
            extra.setdefault(key, value)  # facts added by hand earlier are kept
        facts["extra_facts"] = extra
        self.profile = facts
        self._write(self.inputs / "profile.yaml", _profile_yaml(facts), mode=0o600)
        self._env("PROFILE_PATH", self._user_setting("inputs", "profile.yaml"))
        if self.resume_setting:
            self._env("RESUME_PATH", self.resume_setting)
        self._env("TAILOR_RESUME", "true" if self.tailoring else "false")

    def _existing_profile(self) -> Dict[str, Any]:
        path = self.inputs / "profile.yaml"
        if not path.is_file():
            return {}
        try:
            import yaml

            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        if isinstance(loaded, dict) and loaded.get("full_name") not in ("", "Your Full Name", None):
            return loaded
        return {}

    def build_persona(self) -> None:
        self.prompter.section("How the bots write as you (user/inputs/persona.yaml)")
        path = self.inputs / persona_module.FILE_NAME
        current = persona_module.load_persona(path) if path.is_file() else persona_module.Persona()
        read = {}
        if self.resume_text and self.client is not None and self.client.available():
            self.say("Reading the resume for your voice, topics and study areas...")
            read = _extract(self.client, _PERSONA_PROMPT % self.resume_text[:RESUME_TEXT_CHARS], _PERSONA_SCHEMA)
        extra = self.profile.get("extra_facts") or {}

        def prior(key: str, fallback: Any = "") -> Any:
            value = getattr(current, key, None)
            if value not in (None, "", []):
                return value
            value = read.get(key)
            return value if value not in (None, "", []) else fallback

        ask = self.prompter.ask
        name = self.profile.get("full_name") or current.name
        pronouns = str(ask("pronouns", "Your pronouns (they/them, she/her, he/him)", current.pronouns)).strip().lower()
        headline = ask("headline", "One line on what you do (no \"I am\")", prior("headline"))
        site = ask("site", "Personal site shown on LinkedIn cards (blank for none)",
                   prior("site", _bare(extra.get("portfolio_url", ""))))
        focus = ask("focus", "What your work is about, in a few words", prior("focus"))
        facts = _semicolons(ask("facts", "Facts a LinkedIn post may use about you (separate with ;)",
                                "; ".join(_without_name(fact, name) for fact in prior("facts", []))))
        voice = ask("voice", "How you write, as instructions to the model",
                    prior("voice", "first person, plain words, short paragraphs, concrete, a little dry, never salesy"))
        sample = ask("voice_sample", "A short passage in your own words, for register (your summary works)",
                     prior("voice_sample"))
        topics = _list(ask("topics", "LinkedIn topics, comma-separated", prior("topics", [])))
        areas_read = read.get("study_areas") if isinstance(read.get("study_areas"), list) else []
        areas = current.study_areas or persona_module._areas(areas_read)
        if not areas:
            areas = _areas_from_skills(self.profile.get("skills") or [])
        goal = ask("goal", "What the 90-day study plan is for",
                   prior("goal", "senior interview level in High-Level System Design and ML / Generative AI"))
        years = self.profile.get("total_experience_years")
        self.persona = persona_module.Persona(
            name=str(name), pronouns=pronouns or persona_module.DEFAULT_PRONOUNS, headline=str(headline),
            experience_years=float(years) if years not in (None, "") else None,
            employer=str(prior("employer", extra.get("current_company", ""))),
            location=str(prior("location", self.profile.get("current_location", ""))),
            site=str(site), focus=str(focus), facts=facts, voice=str(voice), voice_sample=str(sample),
            topics=topics, study_areas=areas, goal=str(goal),
        )
        self.written.append(persona_module.save_persona(self.persona, path))
        if topics:
            self._env("LINKEDIN_TOPICS", "")  # the persona file is the source; .env only overrides

    def write_answers(self) -> None:
        path = self.inputs / "answers.txt"
        if path.is_file() and path.stat().st_size > len(ANSWERS_HEADER):
            self.say("Keeping your %s." % path)
            return
        self._write(path, answers_text(self.profile), mode=0o600)

    def write_worklists(self) -> None:
        for name, text in (("accounts.md", ACCOUNTS_MD), ("company_sites.md", COMPANY_SITES_MD)):
            path = self.inputs / name
            if not path.is_file():
                self._write(path, text)

    def write_memory(self) -> None:
        from . import memory

        folder = self.user_dir / "memory"
        for name, text in (("progress.json", json.dumps({"days": {}}, indent=1) + "\n"),
                           ("profiles.json", "{}\n"), ("README.md", memory._README)):
            path = folder / name
            if not path.is_file():
                self._write(path, text)
        if not (folder / "learning.json").is_file():
            try:
                from . import learning_memory

                learning_memory.transact(self.root)
                self.written.append(folder / "learning.json")
            except Exception as exc:  # noqa: BLE001 - the pipeline creates it later anyway
                logger.warning("learning.json not written now (%s); the pipeline writes it.", exc)

    def finish(self) -> None:
        self.say("\nWritten:")
        for path in self.written:
            self.say("  " + str(path))
        self.say("\nNext:")
        self.say("  python3 -m pipeline          # today's run: profiles, applications, study plan")
        self.say("  python3 -m pipeline learn    # the study plan only")
        self.say("Edit %s and %s whenever a fact or your voice changes." % (self.inputs / "profile.yaml", self.inputs / "persona.yaml"))


# ---------------------------------------------------------------------------
# Rendering the files
# ---------------------------------------------------------------------------


_PRONOUN_STARTS = ("she", "he", "they", "the candidate", "the author")


def _without_name(fact: str, name: str) -> str:
    """'Gupta grew X' or 'She grew X' -> 'Grew X': a fact names no person."""
    words = fact.strip()
    starts = sorted([part for part in str(name).split() if len(part) > 1] + [str(name).strip()]
                    + list(_PRONOUN_STARTS), key=len, reverse=True)
    for start in starts:
        if start and words.lower().startswith(start.lower() + " "):
            words = words[len(start) + 1:].lstrip()
            break
    return words[:1].upper() + words[1:] if words else words


def _person_case(name: str) -> str:
    """A name a PDF header shouts (ASHA RAO) in title case; anything else as given."""
    text = str(name).strip()
    return " ".join(part.capitalize() if part.isupper() else part for part in text.split()) if text.isupper() else text


def _bare(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", str(url or "")).rstrip("/")


def _semicolons(value: Any) -> List[str]:
    if isinstance(value, list):
        return _list(value)
    return [part.strip() for part in str(value or "").split(";") if part.strip()]


def _default_backend(current: str) -> str:
    if current and current != LLMBackend.CLAUDE_CLI:
        return current
    if shutil.which("claude"):
        return LLMBackend.CLAUDE_CLI
    if shutil.which("kiro-cli"):
        return LLMBackend.KIRO_CLI
    if os.getenv("ANTHROPIC_API_KEY"):
        return LLMBackend.ANTHROPIC
    return current or LLMBackend.NONE


def _areas_from_skills(skills: Sequence[str]) -> List[persona_module.StudyArea]:
    """Without the model: one study area per three skills, in the order given."""
    areas = []
    for start in range(0, min(len(skills), 24), 3):
        group = [skill for skill in skills[start:start + 3] if skill]
        if group:
            areas.append(persona_module.StudyArea(persona_module.slugify(" ".join(group)), ", ".join(group)))
    return areas


def _profile_yaml(facts: Dict[str, Any]) -> str:
    import yaml

    header = (
        "# Your facts, written by the first run (python3 -m pipeline onboard). The bots\n"
        "# answer screening questions ONLY from what is here and in the resume; a blank\n"
        "# or missing fact makes the bot skip that question rather than guess. See\n"
        "# common/profile.example.yaml for every field and how it is used. Never commit\n"
        "# this file anywhere public: it holds your phone number and salary.\n"
    )
    ordered = {key: facts[key] for key in (
        "full_name", "first_name", "last_name", "email", "phone", "current_location", "preferred_locations",
        "total_experience_years", "highest_qualification", "titles", "skills", "work_authorization",
        "current_ctc_lpa", "expected_ctc_lpa", "notice_period_days", "serving_notice", "willing_to_relocate",
        "has_passport", "extra_facts") if key in facts}
    return header + yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=100)


def answers_text(facts: Dict[str, Any]) -> str:
    """answers.txt from the facts: the questions seen most, each answered from one fact."""
    extra = facts.get("extra_facts") or {}
    years = facts.get("total_experience_years")
    notice = facts.get("notice_period_days")
    blocks = []  # type: List[tuple]

    def block(section: str, questions: Sequence[str], answer: Any) -> None:
        if answer in (None, "", []):
            return
        blocks.append((section, list(questions), _show(answer) if not isinstance(answer, bool) else ("Yes" if answer else "No")))

    block("experience", ("How many years of experience do you have?", "Total years of experience", "Years of relevant experience"),
          "%s years" % _show(years) if years not in (None, "") else "")
    block("experience", ("What is your current designation?", "Current job title"), extra.get("current_designation"))
    block("experience", ("Which company do you work for currently?", "Current employer"), extra.get("current_company"))
    block("money and notice", ("What is your current CTC?", "Current salary (LPA)"),
          "%s LPA" % _show(facts["current_ctc_lpa"]) if facts.get("current_ctc_lpa") not in (None, "") else "")
    block("money and notice", ("What is your expected CTC?", "Expected salary (LPA)"),
          "%s LPA" % _show(facts["expected_ctc_lpa"]) if facts.get("expected_ctc_lpa") not in (None, "") else "")
    block("money and notice", ("What is your notice period?", "Notice period in days"),
          "%s days" % notice if notice not in (None, "") else "")
    block("money and notice", ("Are you serving notice?",), facts.get("serving_notice"))
    block("location", ("What is your current location?", "Current city"), facts.get("current_location"))
    block("location", ("Are you willing to relocate?", "Open to relocation"), facts.get("willing_to_relocate"))
    block("location", ("Which locations do you prefer?", "Preferred locations"), facts.get("preferred_locations"))
    block("availability", ("When can you join?", "Earliest joining date", "How soon can you join?"), extra.get("earliest_joining"))
    block("availability", ("Are you comfortable with night shifts?",), extra.get("willing_night_shifts"))
    block("availability", ("Are you comfortable with rotational shifts?",), extra.get("willing_rotational_shifts"))
    block("availability", ("Are you available for a virtual interview?",), extra.get("willing_virtual_interview"))
    block("availability", ("Are you available for an in-person interview?",), extra.get("willing_in_person_interview"))
    block("availability", ("Will you attend the walk-in?",), extra.get("attend_walk_in"))
    block("education and background", ("What is your highest qualification?", "Highest education"), facts.get("highest_qualification"))
    block("education and background", ("Which year did you graduate?", "Year of passing"), extra.get("graduation_year"))
    block("education and background", ("Do you have a passport?",), facts.get("has_passport"))
    block("education and background", ("What languages do you know?",), extra.get("languages_known"))
    block("links", ("GitHub profile", "GitHub URL"), extra.get("github_url"))
    block("links", ("LinkedIn profile", "LinkedIn URL"), extra.get("linkedin_url"))
    block("links", ("Portfolio or personal website",), extra.get("portfolio_url"))
    block("about the role", ("Why do you want to join us?", "Why are you interested in this role?", "Cover letter"),
          "[AI writes this for each job]")
    block("about the role", ("How did you hear about us?",), extra.get("job_discovery_source"))

    lines = [ANSWERS_HEADER.rstrip("\n")]
    section = None
    for name, questions, answer in blocks:
        if name != section:
            lines += ["", "# ----- " + name]
            section = name
        lines.append("")
        lines += ["Q: " + question for question in questions]
        lines.append("A: " + " ".join(str(answer).split()))
    lines += ["", "", UNANSWERED_MARKER, ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def needs_onboarding(user_dir: Optional[Path] = None) -> bool:
    """True until user/inputs/profile.yaml exists with a name in it."""
    path = Path(user_dir or paths.user_dir()) / "inputs" / "profile.yaml"
    if not path.is_file():
        return True
    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - load_profile reports the real problem later
        return False
    return not (isinstance(loaded, dict) and loaded.get("full_name") not in (None, "", "Your Full Name"))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set Morrow up for one person: the files under user/ and .env.")
    parser.add_argument("--resume", help="your resume (.pdf, .tex, .txt or .md); asked for when omitted")
    parser.add_argument("--answers", help="a JSON file of answers to the questions, keyed by field name")
    parser.add_argument("--yes", action="store_true", help="no prompts: the model's reading and the defaults stand")
    parser.add_argument("--user-dir", help="where the files go (default: MORROW_USER_DIR or user/)")
    parser.add_argument("--env", help="the .env to write (default: the repo's)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    answers = {}
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        if not isinstance(answers, dict):
            print("--answers must be a JSON object", file=sys.stderr)
            return 2
    run = Onboarding(
        user_dir=Path(args.user_dir) if args.user_dir else paths.user_dir(),
        env_path=Path(args.env) if args.env else None,
        resume=Path(args.resume).expanduser() if args.resume else None,
        prompter=Prompter(answers, yes=args.yes),
    )
    try:
        return run.run()
    except OnboardError as exc:
        print("Setup stopped: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped; run it again any time, what was written is kept.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
