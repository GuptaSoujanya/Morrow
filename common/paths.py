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

import hashlib
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)

#: macOS lets each app into these folders (and iCloud Drive) only once a person
#: has allowed it. A Chrome started by the dashboard never gets asked, so a
#: profile kept there fails to open and Chrome sits in an error dialog;
#: browser_home() keeps the profiles out of them.
MAC_PROTECTED = ("Desktop", "Documents", "Downloads", "Library/Mobile Documents")

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


def browser_dir() -> Path:
    return user_dir() / "browser"


def mac_protected(path: Path) -> bool:
    if sys.platform != "darwin":
        return False
    try:
        relative = path.resolve().relative_to(Path.home())
    except (OSError, ValueError):
        return False
    return any(relative.is_relative_to(folder) for folder in MAC_PROTECTED)


def private_support_dir(root: Path = ROOT) -> Path:
    key = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return Path.home() / "Library" / "Application Support" / "Morrow" / key


def private_browser_home(root: Path = ROOT) -> Path:
    return private_support_dir(root) / "browser"


def readable_upload(path: Path, root: Path = ROOT) -> Path:
    """A copy of a file a Chrome started by Morrow can read; the file itself when it already can.

    macOS lets that Chrome see a file in a protected folder's name and size but not its bytes.
    The resume looked attached and the employer's own upload then failed with
    net::ERR_ACCESS_DENIED, which their forms show as "Failed to fetch", so several
    applications were filled in completely and never sent. The copy sits beside the browser
    profiles, which are kept out of those folders for the same reason.
    """
    path = Path(path)
    if not mac_protected(path):
        return path
    try:
        source = path.stat()
        copy = private_support_dir(root) / "uploads" / path.name
        copy.parent.mkdir(parents=True, exist_ok=True)
        fresh = copy.exists() and copy.stat().st_size == source.st_size and copy.stat().st_mtime >= source.st_mtime
        if not fresh:
            shutil.copy2(str(path), str(copy))
    except OSError as exc:
        logger.warning("Could not copy %s somewhere this browser may read it (%s); using the original.", path, exc)
        return path
    return copy


def _chrome_running_in(folder: Path) -> bool:
    locks = list(folder.glob("*/chrome/SingletonLock")) + list(folder.glob("lanes/*/chrome/SingletonLock"))
    for lock in locks:
        try:
            pid = int(os.readlink(lock).rsplit("-", 1)[1])
            os.kill(pid, 0)
        except (OSError, ValueError, IndexError):
            continue
        return True
    return False


def browser_home(root: Path = ROOT) -> Path:
    """user/browser; on macOS a link to a folder under ~/Library when user/ sits in a protected folder."""
    folder = browser_dir() if browser_dir().is_absolute() else root / browser_dir()
    if not mac_protected(folder):
        return folder
    target = private_browser_home(root)
    if folder.exists():
        if _chrome_running_in(folder):
            logger.warning("Browser sessions in %s cannot be moved while a browser is open there.", folder)
            return folder
        if target.exists():
            logger.warning("Both %s and %s hold browser sessions; %s is used. Move or remove the other one by hand.",
                           folder, target, folder)
            return folder
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), str(target))
    else:
        target.mkdir(parents=True, exist_ok=True)
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.symlink_to(target)
    logger.info("Browser sessions are kept in %s; %s links to it, because macOS would stop a Chrome started by "
                "Morrow from opening a profile there.", target, folder)
    return folder
