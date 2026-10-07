"""Environment-backed runtime configuration."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Settings


logger = logging.getLogger(__name__)


def _env_int(key: str, default: int) -> int:
    """Read an integer environment value, retaining the default if invalid."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer for %s: %r; using default %r", key, value, default)
        return default


def _env_float(key: str, default: float) -> float:
    """Read a float environment value, retaining the default if invalid."""
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Invalid float for %s: %r; using default %r", key, value, default)
        return default


def _env_bool(key: str, default: bool) -> bool:
    """Read a conventional boolean environment value."""
    value = os.getenv(key)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    logger.warning("Invalid boolean for %s: %r; using default %r", key, value, default)
    return default


def _env_list(key: str, default: List[str]) -> List[str]:
    """Read a comma-separated list, retaining the default when missing."""
    value = os.getenv(key)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _absolute_path(value: str, repo_root: Path) -> str:
    if not value:
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return str(path.resolve())


def load_settings(
    env_path: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Settings:
    """Load settings from dotenv, the environment, and final CLI overrides."""
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise ImportError(
            "python-dotenv is required to load settings; install it with "
            "`pip install python-dotenv`."
        ) from exc

    if env_path is None:
        load_dotenv()
    else:
        load_dotenv(dotenv_path=env_path)

    defaults = Settings()
    values: Dict[str, Any] = {
        "email": os.getenv("NAUKRI_EMAIL", defaults.email),
        "password": os.getenv("NAUKRI_PASSWORD", defaults.password),
        "profile_path": os.getenv("PROFILE_PATH", defaults.profile_path),
        "resume_path": os.getenv("RESUME_PATH", defaults.resume_path),
        "db_path": os.getenv("DB_PATH", defaults.db_path),
        "daily_quota": _env_int("DAILY_QUOTA", defaults.daily_quota),
        "target_applications": _env_int(
            "TARGET_APPLICATIONS", defaults.target_applications
        ),
        "max_candidates": _env_int("MAX_CANDIDATES", defaults.max_candidates),
        "llm_rank_top_n": _env_int("LLM_RANK_TOP_N", defaults.llm_rank_top_n),
        "min_score": _env_float("MIN_SCORE", defaults.min_score),
        "max_days_old": _env_int("MAX_DAYS_OLD", defaults.max_days_old),
        "max_per_company": _env_int("MAX_PER_COMPANY", defaults.max_per_company),
        "max_empty_searches": _env_int(
            "MAX_EMPTY_SEARCHES", defaults.max_empty_searches
        ),
        "user_agent": os.getenv("USER_AGENT", defaults.user_agent),
        "max_answer_chars": _env_int(
            "MAX_ANSWER_CHARS", defaults.max_answer_chars
        ),
        "browser_profile_dir": os.getenv(
            "BROWSER_PROFILE_DIR", defaults.browser_profile_dir
        ),
        "apply_delay_min_s": _env_float(
            "APPLY_DELAY_MIN_S", defaults.apply_delay_min_s
        ),
        "apply_delay_max_s": _env_float(
            "APPLY_DELAY_MAX_S", defaults.apply_delay_max_s
        ),
        "min_llm_rank_coverage": _env_float(
            "MIN_LLM_RANK_COVERAGE", defaults.min_llm_rank_coverage
        ),
        "default_skill_experience_years": _env_float(
            "DEFAULT_SKILL_EXPERIENCE_YEARS",
            defaults.default_skill_experience_years,
        ),
        "llm_rank_batch_size": _env_int(
            "LLM_RANK_BATCH_SIZE", defaults.llm_rank_batch_size
        ),
        "keywords": _env_list("KEYWORDS", defaults.keywords),
        "location": os.getenv("LOCATION", defaults.location),
        "pages_per_keyword": _env_int(
            "PAGES_PER_KEYWORD", defaults.pages_per_keyword
        ),
        "headless": _env_bool("HEADLESS", defaults.headless),
        "dry_run": _env_bool("DRY_RUN", defaults.dry_run),
        "llm_backend": os.getenv("LLM_BACKEND", defaults.llm_backend),
        "llm_model": os.getenv("LLM_MODEL", defaults.llm_model),
        "llm_timeout_s": _env_int("LLM_TIMEOUT_S", defaults.llm_timeout_s),
        "answer_mode": os.getenv("ANSWER_MODE", defaults.answer_mode),
    }
    if overrides:
        values.update(overrides)

    repo_root = Path(__file__).resolve().parent.parent
    for path_key in ("profile_path", "resume_path", "db_path"):
        path_value = values[path_key]
        if not isinstance(path_value, str):
            raise TypeError("%s override must be a string" % path_key)
        values[path_key] = _absolute_path(path_value, repo_root)
    return Settings(**values)
