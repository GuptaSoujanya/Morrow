"""LinkedIn poster settings, read from the same .env as naukri_bot."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import config as naukri_config
from common.models import Settings

DEFAULT_TOPICS = [
    "AI agent evaluation",
    "LLM benchmarks",
    "multi-agent systems",
    "LangChain",
    "Next.js",
]

HN_SEARCH_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?query=%s&tags=story&numericFilters=points>20"
)

DEFAULT_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/ai/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "https://huggingface.co/blog/feed.xml",
    "https://simonwillison.net/atom/everything/",
]


def hn_feeds(topics: List[str]) -> List[str]:
    from urllib.parse import quote_plus

    return [HN_SEARCH_URL % quote_plus(topic) for topic in topics]


@dataclass
class LinkedInSettings:
    linkedin_email: str = ""
    linkedin_password: str = ""
    topics: List[str] = field(default_factory=lambda: list(DEFAULT_TOPICS))
    feeds: List[str] = field(default_factory=list)
    post_time: str = "09:30"
    auto_post: bool = False
    carousel: bool = True
    max_age_days: int = 3
    state_path: str = "data/linkedin/state.json"
    draft_dir: str = "data/linkedin/drafts"
    #: Every prepared post gets its own folder here: <topic>/<date>/ with the
    #: image card, the post text, the carousel and the article it reacts to.
    post_dir: str = "data/linkedin_post"
    browser_profile_dir: str = "data/browser/linkedin"
    headless: bool = False
    #: Who writes, who reviews, who reads the full article, who designs the card:
    #: "claude" or "kiro" ("backend" writes with LLM_BACKEND; "none" skips a step;
    #: an image of "card" keeps the Pillow card).
    writer: str = "claude"
    critic: str = "kiro"
    research: str = "claude"
    image: str = "claude"
    ai_timeout_s: int = 600
    #: Driver, LLM and Telegram settings shared with naukri_bot.
    naukri: Settings = field(default_factory=Settings)

    def validate(self, needs_browser: bool) -> List[str]:
        problems = []  # type: List[str]
        if needs_browser and not self.naukri.session_only:
            if not self.linkedin_email:
                problems.append("LINKEDIN_EMAIL is not set")
            if not self.linkedin_password:
                problems.append("LINKEDIN_PASSWORD is not set")
        if parse_post_time(self.post_time) is None:
            problems.append("LINKEDIN_POST_TIME must look like HH:MM")
        if self.max_age_days < 1:
            problems.append("LINKEDIN_MAX_AGE_DAYS must be at least 1")
        if not self.topics:
            problems.append("LINKEDIN_TOPICS is empty")
        for key, value, allowed in (
            ("LINKEDIN_WRITER", self.writer, ("claude", "kiro", "backend")),
            ("LINKEDIN_CRITIC", self.critic, ("claude", "kiro", "none")),
            ("LINKEDIN_RESEARCH", self.research, ("claude", "kiro", "none")),
            ("LINKEDIN_IMAGE", self.image, ("claude", "kiro", "card")),
        ):
            if value not in allowed:
                problems.append("%s must be one of %s" % (key, ", ".join(allowed)))
        return problems


def parse_post_time(value: str) -> Optional[tuple]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return (hour, minute)


def load_settings(
    env_path: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> LinkedInSettings:
    """Load LINKEDIN_* keys and the companion naukri Settings from the same .env.

    The naukri Settings are never validated here: the poster must run without
    Naukri credentials, it only borrows the driver, the LLM backend and the
    Telegram alert configuration.
    """
    naukri = naukri_config.load_settings(env_path, {})
    repo_root = Path(__file__).resolve().parent.parent
    defaults = LinkedInSettings()

    topics = naukri_config._env_list("LINKEDIN_TOPICS", defaults.topics)
    feeds = naukri_config._env_list("LINKEDIN_FEEDS", [])
    if not feeds:
        feeds = hn_feeds(topics) + list(DEFAULT_FEEDS)

    values = {
        "linkedin_email": os.getenv("LINKEDIN_EMAIL", "").strip(),
        "linkedin_password": os.getenv("LINKEDIN_PASSWORD", ""),
        "topics": topics,
        "feeds": feeds,
        "post_time": os.getenv("LINKEDIN_POST_TIME", defaults.post_time).strip(),
        "auto_post": naukri_config._env_bool("LINKEDIN_AUTO_POST", defaults.auto_post),
        "carousel": naukri_config._env_bool("LINKEDIN_CAROUSEL", defaults.carousel),
        "max_age_days": naukri_config._env_int(
            "LINKEDIN_MAX_AGE_DAYS", defaults.max_age_days
        ),
        "state_path": os.getenv("LINKEDIN_STATE_PATH", defaults.state_path),
        "draft_dir": os.getenv("LINKEDIN_DRAFT_DIR", defaults.draft_dir),
        "post_dir": os.getenv("LINKEDIN_POST_DIR", defaults.post_dir),
        "browser_profile_dir": os.getenv(
            "LINKEDIN_BROWSER_PROFILE_DIR", defaults.browser_profile_dir
        ),
        "headless": naukri.headless,
        "writer": os.getenv("LINKEDIN_WRITER", defaults.writer).strip().lower(),
        "critic": os.getenv("LINKEDIN_CRITIC", defaults.critic).strip().lower(),
        "research": os.getenv("LINKEDIN_RESEARCH", defaults.research).strip().lower(),
        "image": os.getenv("LINKEDIN_IMAGE", defaults.image).strip().lower(),
        "ai_timeout_s": naukri_config._env_int("LINKEDIN_AI_TIMEOUT_S", defaults.ai_timeout_s),
    }  # type: Dict[str, Any]
    if overrides:
        values.update(overrides)
    for key in ("state_path", "draft_dir", "post_dir", "browser_profile_dir"):
        values[key] = naukri_config._absolute_path(values[key], repo_root)

    settings = LinkedInSettings(naukri=naukri, **values)
    # The driver reads these from the naukri Settings it is handed, so the
    # LinkedIn session must land in its own profile, never in Naukri's.
    naukri.browser_profile_dir = settings.browser_profile_dir
    from common.connections import managed_profile
    naukri.session_only = managed_profile(settings.browser_profile_dir)
    naukri.headless = settings.headless
    return settings
