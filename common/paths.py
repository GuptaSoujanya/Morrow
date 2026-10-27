"""Where a person's own files and the shared database live.

Morrow is public, so nothing personal is in this repo. Every file the bots read
or write for one person lives in that person's private repo, cloned to user/:

    user/inputs/      profile.yaml, answers.txt, accounts.md, company_sites.md
    user/resume/      base.tex and the compiled PDFs in out/
    user/db/          naukri_bot.db, the application ledger
    user/reports/     one folder per day, plus profile/ and studied.json
    user/worklists/   employer-site roles and unanswered questions
    user/memory/      the pipeline's checkpoint (progress.json, profiles.json, ...)
    user/research/    the day's briefing, the 90-day plan, resume-learning
    user/browser/     Chrome sessions, never committed

Material that is the same for everyone (the course site) lives in the shared
public repo Morrow-database, cloned to database/.

Both folders can be anywhere: MORROW_USER_DIR and MORROW_DATABASE_DIR in .env
(or the environment) point at them. Unset, they are user/ and database/ next
to this code, and the paths stay relative so a test that moves into a scratch
folder gets its own user/ there, as the bots always did with data/.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

USER_DIR_ENV = "MORROW_USER_DIR"
DATABASE_DIR_ENV = "MORROW_DATABASE_DIR"
DEFAULT_USER_DIR = "user"
DEFAULT_DATABASE_DIR = "database"

#: The two folder names a relative path in .env may begin with; load_settings
#: swaps them for the folders above, so PROFILE_PATH=user/inputs/profile.yaml
#: follows MORROW_USER_DIR wherever it points.
PREFIXES = (DEFAULT_USER_DIR, DEFAULT_DATABASE_DIR)

try:
    from dotenv import load_dotenv

    # Module-level folders below are fixed at import, before any CLI loads
    # .env, so take the two variables from the repo's .env here. Never
    # overrides a variable already in the environment.
    load_dotenv(dotenv_path=ROOT / ".env", override=False)
except ImportError:  # pragma: no cover - dotenv is a dependency
    pass


def _folder(variable: str, default: str) -> Path:
    value = os.getenv(variable, "").strip()
    return Path(value).expanduser() if value else Path(default)


def user_dir() -> Path:
    """The person's private repo: user/ unless MORROW_USER_DIR says otherwise."""
    return _folder(USER_DIR_ENV, DEFAULT_USER_DIR)


def database_dir() -> Path:
    """The shared Morrow-database clone: database/ unless MORROW_DATABASE_DIR says otherwise."""
    return _folder(DATABASE_DIR_ENV, DEFAULT_DATABASE_DIR)


def inputs_dir() -> Path:
    return user_dir() / "inputs"


def reports_dir() -> Path:
    return user_dir() / "reports"


def memory_dir() -> Path:
    return user_dir() / "memory"


def research_dir() -> Path:
    return user_dir() / "research"


def course_dir() -> Path:
    return database_dir() / "course"


def user(*parts: str) -> str:
    """A path under the user's repo as a string, for Settings defaults and .env values."""
    return str(user_dir().joinpath(*parts))


def database(*parts: str) -> str:
    return str(database_dir().joinpath(*parts))


def resolve(value: str, root: Path = ROOT) -> Path:
    """An absolute path for a setting: user/... and database/... follow the
    environment, any other relative path is under root."""
    if not value:
        return Path(value)
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0] == DEFAULT_USER_DIR:
        base = user_dir()
        path = base.joinpath(*parts[1:])
    elif parts and parts[0] == DEFAULT_DATABASE_DIR:
        base = database_dir()
        path = base.joinpath(*parts[1:])
    return path if path.is_absolute() else root / path
