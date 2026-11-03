"""Startup jobs: YC companies' job posts and Hacker News' monthly "Who is hiring?" thread.

Both come from public APIs with no sign-in, so this needs no browser. The posts
are kept to ones open to someone in India. This module only finds and parses
them; the startup bot (startup_bot/cli.py) ranks them and applies.

The idea, and the parsing rules, follow AienTech/dossier's startup sources;
this is our own implementation. Fetched text is data: nothing in it is run.

    python3 -m startup_bot [--dry-run] [--limit N]
"""

import html
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

from common.models import JobPosting, Profile

logger = logging.getLogger(__name__)

HN_API = "https://hacker-news.firebaseio.com/v0"
ALGOLIA = "https://hn.algolia.com/api/v1"
HN_ITEM = "https://news.ycombinator.com/item?id=%s"
USER_AGENT = "Morrow job bot (+local, personal use)"
TIMEOUT_S = 20
MAX_BYTES = 5 * 1024 * 1024
YC_POSTS = 100
WORKERS = 6

Fetch = Callable[[str], Any]


def fetch_json(url: str) -> Any:
    """GET a public JSON document: one request, a size cap, an honest user agent."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https API hosts only
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("%s answered with more than %d bytes" % (url, MAX_BYTES))
    return json.loads(body.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_LINK = re.compile(r'<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.I | re.S)
_BLOCK = re.compile(r"<\s*(?:p|br|div|li|/li|/p|/div)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
URL = re.compile(r"https?://[^\s)<>\"']*[^\s)<>\"'.,;:!?]")
EMAIL = re.compile(r"[a-z0-9._%+-]{1,64}@[a-z0-9.-]{1,253}\.[a-z]{2,24}", re.I)
_NOT_A_CONTACT = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|js|css)$|@(?:[a-z0-9-]+\.)*(?:example\.(?:com|org)|sentry\.io)$"
    r"|^(?:no-?reply|do-?not-?reply|privacy|legal|support|sales|press|marketing|abuse|billing)@",
    re.I,
)
_HOSTING = re.compile(
    r"(?:^|\.)(?:ycombinator\.com|workatastartup\.com|greenhouse\.io|lever\.co|ashbyhq\.com|linkedin\.com"
    r"|github\.com|notion\.(?:so|site)|bit\.ly|google\.com|forms\.gle|docs\.google\.com|wellfound\.com"
    r"|angel\.co|breezy\.hr|workable\.com|recruitee\.com|smartrecruiters\.com|bamboohr\.com|typeform\.com)$",
    re.I,
)


def html_to_text(raw: str) -> str:
    """HN's comment HTML as plain lines, with each link written as 'label (url)'."""
    def link(match: "re.Match[str]") -> str:
        href = html.unescape(match.group(1))
        label = _TAG.sub("", match.group(2))
        label = html.unescape(label).strip()
        return href if not label or label == href or href.startswith(label.rstrip(".")) else "%s (%s)" % (label, href)

    text = _LINK.sub(link, raw or "")
    text = _BLOCK.sub("\n", text)
    text = html.unescape(_TAG.sub("", text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def without_addresses(text: str) -> str:
    """The text the ranking model reads: no email addresses in it."""
    text = EMAIL.sub("[email]", text or "")
    return re.sub(r"\b[\w.+-]+\s*(?:\[at\]|\(at\)|\sat\s)\s*[\w-]+\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*\w+",
                  "[email]", text, flags=re.I)


@dataclass
class Contact:
    email: str
    kind: str  # hiring, founders, general or person


_KINDS = (
    ("hiring", re.compile(r"^(?:careers?|jobs?|hiring|recruit\w*|talent\w*|hr|people|join\w*|apply|applications?|work)\b", re.I)),
    ("founders", re.compile(r"^(?:founders?|ceo|cto|coo)\b", re.I)),
    ("general", re.compile(r"^(?:hello|hi|contact|info|team|eng\w*)\b", re.I)),
)
_RANK = {"hiring": 0, "founders": 1, "general": 2, "person": 3}


def contacts(text: str) -> List[Contact]:
    """Addresses in a post, best for an application first. Obfuscated ones are left alone."""
    found = []  # type: List[Contact]
    for match in EMAIL.finditer(text or ""):
        address = match.group(0).strip(".").lower()
        if _NOT_A_CONTACT.search(address) or any(c.email == address for c in found):
            continue
        local = address.split("@", 1)[0]
        kind = next((name for name, pattern in _KINDS if pattern.match(local)), "person")
        found.append(Contact(address, kind))
    return sorted(found, key=lambda contact: _RANK[contact.kind])


def links(text: str) -> List[str]:
    found = []  # type: List[str]
    for url in URL.findall(text or ""):
        if url not in found:
            found.append(url)
    return found


def _host(url: str) -> str:
    match = re.match(r"https?://([^/:?#]+)", url)
    return (match.group(1) if match else "").lower()


def website(text: str) -> str:
    """The company's own site: the first link that is not a job board or hosting service."""
    return next((url for url in links(text) if not _HOSTING.search(_host(url))), "")


def apply_link(text: str) -> str:
    """Where to apply: an ATS link first, else a careers/jobs page, else empty."""
    found = links(text)
    for url in found:
        if _HOSTING.search(_host(url)) and not re.search(r"(?:^|\.)(?:linkedin|github|google|bit\.ly)", _host(url)):
            return url
    return next((url for url in found if re.search(r"/(?:careers?|jobs?|join|apply|hiring|positions?)\b", url, re.I)), "")


# ---------------------------------------------------------------------------
# Where a post can be worked from
# ---------------------------------------------------------------------------

REMOTE = re.compile(r"\b(?:remote(?:ly)?|wfh|work\s+from\s+home|distributed)\b", re.I)
ANYWHERE = re.compile(r"\b(?:anywhere|world\s?wide|global(?:ly)?|any\s+(?:country|location|time\s?zone))\b", re.I)
OPEN_TO_INDIA = re.compile(r"\b(?:india|indian|apac|asia|asia[-\s]pacific|ist)\b", re.I)
_ELSEWHERE = re.compile(
    r"\b(?:(?-i:US|USA|U\.S\.?|UK|U\.K\.|EU|EMEA|LATAM|EST|PST|CET)|united states|america|north america"
    r"|canada|united kingdom|europe|germany|france|spain|netherlands|australia|brazil|mexico)\b",
    re.I,
)
_INDIAN_CITIES = ("bangalore", "bengaluru", "mumbai", "pune", "hyderabad", "chennai", "delhi", "new delhi",
                  "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad", "kochi", "jaipur", "chandigarh")


def home_places(profile: Profile) -> List[str]:
    places = [profile.current_location] + list(profile.preferred_locations or [])
    words = [p.split(",")[0].strip().lower() for p in places if p and p.strip()]
    if any(w in ("bangalore", "bengaluru") for w in words):
        words += ["bangalore", "bengaluru"]
    if any(w in ("gurgaon", "gurugram") for w in words):
        words += ["gurgaon", "gurugram"]
    return sorted(set(w for w in words if w and w not in ("remote", "anywhere", "india")))


def _names(text: str, place: str) -> bool:
    return bool(re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(place), text, re.I))


def open_to_india(header: str, places: Sequence[str]) -> bool:
    """Whether someone in India could take it: in their city or in India, or remote and open to India.

    Read on the header line, where HN posts state location and remote terms; the
    body often names other offices that say nothing about who may apply.
    """
    if any(_names(header, place) for place in list(places) + list(_INDIAN_CITIES)):
        return True
    if re.search(r"\bindia\b", header, re.I) and not re.search(r"\bnot\s+(?:in\s+)?india\b", header, re.I):
        return True
    restricted = False
    for part in re.split(r"[|;\n•·]|\s[-–—]\s", header):
        if not REMOTE.search(part):
            continue
        if ANYWHERE.search(part) or OPEN_TO_INDIA.search(part):
            return True
        restricted = restricted or bool(_ELSEWHERE.search(part))
    # Remote with no place named is kept, as the ranker can still judge it; remote
    # only in the US or Europe is not open to India.
    return bool(REMOTE.search(header)) and not restricted


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------


@dataclass
class StartupPost:
    job: JobPosting
    contacts: List[Contact] = field(default_factory=list)
    apply_url: str = ""
    website: str = ""
    text: str = ""

    @property
    def hiring_email(self) -> str:
        best = next((c for c in self.contacts if c.kind in ("hiring", "founders", "general")), None)
        return best.email if best else ""


def _first_role(text: str) -> str:
    """"Junior to Senior Fullstack Engineer multiple positions; https://..." -> "Junior to Senior Fullstack Engineer"."""
    text = re.split(r"[;,(]|\bhttps?://|\s+(?:multiple|several)\s+(?:positions|roles|openings)\b", text, 1, re.I)[0]
    return " ".join(text.split()) or "Open roles"


_YC_TITLE = re.compile(r"^(.+?)\s*\(\s*YC\s+([A-Z]\d{2})\s*\)\s*(.*)$")
_IS_HIRING = re.compile(r"^(.+?)\s+(?:is|are)\s+hiring\b(.*)$", re.I)
ROLE = re.compile(
    r"\b(?:engineer|developer|programmer|architect|designer|scientist|manager|lead|head of|founding|sre|devops"
    r"|intern|analyst|researcher|specialist|consultant)\b",
    re.I,
)
WORK_MODE = re.compile(r"\b(?:remote|on-?site|hybrid|in[-\s]office|relocation)\b", re.I)
_STAGE = re.compile(r"^(?:pre-seed|seed|series [a-e]|bootstrapped|profitable)\b", re.I)


def _days_ago(epoch: Any, now: float) -> Optional[float]:
    try:
        return round(max(0.0, (now - float(epoch)) / 86400.0), 1)
    except (TypeError, ValueError):
        return None


def parse_yc_title(title: str) -> Tuple[str, str, str]:
    """(company, batch, role) from a YC job title such as 'Acme (YC W24) Is Hiring a Founding Engineer'."""
    title = " ".join((title or "").split())
    match = _YC_TITLE.match(title)
    if match:
        company, batch, rest = match.group(1), "YC " + match.group(2), match.group(3)
    else:
        hiring = _IS_HIRING.match(title)
        company, batch, rest = (hiring.group(1), "", "is hiring" + hiring.group(2)) if hiring else (title, "", "")
    role = re.sub(r"^(?:is|are)\s+hiring\b[\s:–—-]*", "", rest, flags=re.I)
    role = re.sub(r"^(?:an?|for)\s+", "", role, flags=re.I)
    return company.strip(" -:"), batch, role.strip()


def yc_post(item: Dict[str, Any], now: float) -> Optional[StartupPost]:
    if not isinstance(item, dict) or item.get("type") != "job" or item.get("dead") or item.get("deleted"):
        return None
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    company, batch, role = parse_yc_title(title)
    places = [p for pair in re.findall(r"\(([^)]*)\)|\[([^\]]*)\]", role) for p in pair if p]
    trailing = re.search(r"\bin\s+([A-Z][^()[\]]*)$", role)
    if trailing:
        places.append(trailing.group(1))
        role = role[: trailing.start()].strip()
    role = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", role).strip(" -,") or "Open role"
    body = html_to_text(item.get("text") or "")
    url = item.get("url") or HN_ITEM % item.get("id")
    text = "\n".join(part for part in (title, body, url) if part)
    job = JobPosting(
        job_id="yc:%s" % item.get("id"),
        url=HN_ITEM % item.get("id"),
        title=role,
        company=company,
        location=", ".join(places),
        description=without_addresses(text),
        tags=[t for t in (batch, "remote" if REMOTE.search(title) else "") if t],
        posted_days_ago=_days_ago(item.get("time"), now),
        source="yc:jobs",
    )
    return StartupPost(job, contacts(text), url if url.startswith("http") else "", website(text), text)


def _header_parts(text: str) -> List[str]:
    first = (text.splitlines() or [""])[0][:400]
    return [part.strip() for part in re.split(r"\s+[|•·—–]\s+|\s+-\s+|\s*\|\s*", first) if part.strip()]


def hn_post(comment: Dict[str, Any], month: str, now: float, places: Sequence[str]) -> Optional[StartupPost]:
    """One top-level 'Who is hiring?' comment, or None when it is not a usable post for India."""
    if not isinstance(comment, dict) or not comment.get("text"):
        return None
    text = html_to_text(comment["text"])
    parts = _header_parts(text)
    if not parts:
        return None
    company = re.sub(URL, "", parts[0])
    company = re.sub(r"\s*\([^)]*\)\s*$", "", company).strip(" -:,.")
    if len(company) < 2:
        return None
    header = (text.splitlines() or [""])[0]
    if not open_to_india(header, places):
        return None
    roles = [p for p in parts[1:] if ROLE.search(p) and len(p) < 160][:6]
    where = [p for p in parts[1:] if WORK_MODE.search(p) or any(_names(p, x) for x in places)
             or re.match(r"^[A-Z][\w .'-]+,\s*[A-Z]{2}\b", p)]
    stage = next((p for p in parts[1:] if _STAGE.match(p)), "")
    created = comment.get("created_at_i")
    job = JobPosting(
        job_id="hn:%s" % comment.get("id"),
        url=HN_ITEM % comment.get("id"),
        # One role per application: "A; B; C" left the applier asking which one. The rest stay in tags.
        title=_first_role(roles[0]) if roles else "Open roles",
        company=company,
        location="; ".join(where),
        description=without_addresses(text),
        tags=[t for t in (stage, "remote" if REMOTE.search(header) else "") if t] + ["also: " + r for r in roles[1:]],
        posted_days_ago=_days_ago(created, now),
        source="hn:whoishiring:%s" % month,
    )
    return StartupPost(job, contacts(text), apply_link(text), website(text), text)


def yc_jobs(fetch: Fetch = fetch_json, now: Optional[float] = None) -> List[StartupPost]:
    now = time.time() if now is None else now
    ids = fetch("%s/jobstories.json" % HN_API) or []
    ids = [i for i in ids if isinstance(i, int)][:YC_POSTS]

    def item(story_id: int) -> Any:
        try:
            return fetch("%s/item/%d.json" % (HN_API, story_id))
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - one missing post costs that post
            logger.info("YC post %s did not load: %s", story_id, exc)
            return None

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        items = list(pool.map(item, ids))
    if ids and not any(items):
        raise RuntimeError("Hacker News didn't answer for any YC job post")
    return [post for post in (yc_post(i, now) for i in items if i) if post]


def hiring_thread(fetch: Fetch = fetch_json) -> Optional[Dict[str, Any]]:
    """The newest 'Ask HN: Who is hiring?' story by the whoishiring account."""
    found = fetch("%s/search_by_date?tags=story,author_whoishiring&hitsPerPage=10" % ALGOLIA) or {}
    return next((hit for hit in found.get("hits", [])
                 if re.match(r"^ask hn: who is hiring\?", hit.get("title") or "", re.I)), None)


def hn_jobs(profile: Profile, fetch: Fetch = fetch_json, now: Optional[float] = None) -> List[StartupPost]:
    now = time.time() if now is None else now
    thread = hiring_thread(fetch)
    if thread is None:
        logger.warning("Hacker News has no 'Who is hiring?' thread to read")
        return []
    month = time.strftime("%Y-%m", time.gmtime(thread.get("created_at_i") or now))
    story = fetch("%s/items/%s" % (ALGOLIA, thread.get("objectID"))) or {}
    places = home_places(profile)
    return [post for post in (hn_post(c, month, now, places) for c in story.get("children") or []) if post]


def collect(profile: Profile, fetch: Fetch = fetch_json, now: Optional[float] = None) -> List[StartupPost]:
    """Both sources, deduplicated by job_id; one failing source does not cost the other."""
    posts = {}  # type: Dict[str, StartupPost]
    for name, source in (("YC", lambda: yc_jobs(fetch, now)), ("HN", lambda: hn_jobs(profile, fetch, now))):
        try:
            found = source()
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - network boundary
            logger.warning("%s startup jobs did not load: %s", name, exc)
            continue
        for post in found:
            posts.setdefault(post.job.job_id, post)
        logger.info("%s startup jobs: %d", name, len(found))
    return list(posts.values())


def main(argv: Optional[List[str]] = None) -> int:
    """The old entry point; the startup bot (python3 -m startup_bot) now does the applying."""
    from startup_bot import cli

    return cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
