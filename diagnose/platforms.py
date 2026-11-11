"""Read each job board's own account pages: applied, viewed, shortlisted, inbox.

Strictly read-only. Every site is opened in the browser profile the bots
already signed in with (the Naukri profile, or the site's lane profile), via
the strict driver that refuses to run when that profile is in use. Pages are
loaded by URL only — no clicking, typing or form submission — and the visible
text of each is saved under the day's report folder as evidence.
"""

import dataclasses
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import browser_lanes, connections, paths
from common.browser import human_pause, safe_get
from common.models import Settings
from common.shared_files import atomic_write_text
from diagnose import pages

logger = logging.getLogger(__name__)

SITES = ("naukri", "hirist", "instahyre", "cutshort", "wellfound")
PAGE_TEXT = "return document.body ? document.body.innerText.slice(0, 120000) : ''"
LINKS = ("return Array.from(document.querySelectorAll('a[href]')).map(a => [a.href, (a.innerText||'').trim()])"
         ".filter(p => p[1] && p[1].length < 60).slice(0, 400)")
MAX_PAGES = 7

#: Seed pages, then link text that is worth following from them (read-only GET of the href).
_PLAN: Dict[str, Dict[str, Any]] = {
    "naukri": {
        "seeds": ("https://www.naukri.com/mnjuser/homepage",
                  "https://www.naukri.com/mnjuser/profile",
                  "https://www.naukri.com/mnjuser/performance",
                  "https://www.naukri.com/mnjuser/performance#recruiterActions",
                  "https://www.naukri.com/myapply/historypage",
                  "https://www.naukri.com/mnjuser/inbox"),
        "follow": re.compile(r"^$"),
        "labels": ("Search appearances", "Recruiter actions", "Applies", "Profile views", "Viewed", "Not viewed",
                   "Shortlisted", "Contacted", "Resume downloaded", "Awaiting recruiter action", "Rejected",
                   "Profile performance", "Last updated"),
    },
    "hirist": {
        "seeds": ("https://www.hirist.tech/myprofile", "https://www.hirist.tech/applied-jobs",
                  "https://www.hirist.tech/chats", "https://www.hirist.tech/recruiterview"),
        "follow": re.compile(r"applied|chat|message|recruiter|viewed|shortlist", re.I),
        "labels": ("Applied", "Viewed", "Shortlisted", "Rejected", "Unread", "Recruiter viewed", "Profile views",
                   "Chats", "Messages"),
    },
    "instahyre": {
        "seeds": ("https://www.instahyre.com/candidate/profile/", "https://www.instahyre.com/candidate/activity/",
                  "https://www.instahyre.com/candidate/inbox/", "https://www.instahyre.com/candidate/opportunities/"),
        "follow": re.compile(r"interview|message|inbox|interested|applied|activity", re.I),
        "labels": ("Interested", "Interviews", "Messages", "Shortlisted", "Applied", "Views", "Matches", "Pending"),
    },
    "cutshort": {
        "seeds": ("https://cutshort.io/profile/candidate-dashboard",
                  "https://cutshort.io/profile/candidate-conversations?i=all",
                  "https://cutshort.io/profile/candidate-conversations?i=all&stage=awaiting"),
        "follow": re.compile(r"conversation|applied|interview|questionnaire|message|shortlist", re.I),
        "labels": ("Awaiting", "Shortlisted", "Rejected", "Interview", "Questionnaire", "In conversation", "Applied",
                   "Profile views", "Not selected"),
    },
    "wellfound": {
        "seeds": ("https://wellfound.com/profile/edit", "https://wellfound.com/jobs/applications",
                  "https://wellfound.com/jobs/messages", "https://wellfound.com/jobs/matches"),
        "follow": re.compile(r"application|applied|message|inbox|interview|match", re.I),
        "labels": ("Applied", "Viewed", "In review", "Interviewing", "Not selected", "Rejected", "Archived",
                   "Messages", "Matches", "Pending"),
    },
}

#: Words whose count on an applications page is itself a funnel number.
STATUS_WORDS = ("viewed", "not viewed", "shortlisted", "rejected", "not selected", "awaiting", "interview",
                "in review", "contacted", "downloaded", "unread", "declined", "closed", "expired")


class SiteResult(dict):
    """{'site', 'state', 'message', 'pages': [...], 'signals': {...}, 'evidence': [...]}"""


def _profile_for(site: str, settings: Settings) -> Path:
    if site == "naukri":
        return Path(settings.browser_profile_dir)
    lane = browser_lanes.profile_dir(site, settings.browser_profile_dir)
    if lane is None:
        return Path(settings.browser_profile_dir)
    return lane


def _slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.split("//", 1)[-1].lower()).strip("-")[:70]


def _numbers_near(text: str, labels: Tuple[str, ...]) -> Dict[str, int]:
    found: Dict[str, int] = {}
    for label in labels:
        pattern = re.escape(label)
        match = re.search(r"(\d[\d,]*)\s*\n?\s*%s\b" % pattern, text, re.I) or re.search(
            r"\b%s\s*[:(]?\s*\n?\s*(\d[\d,]*)" % pattern, text, re.I)
        if match:
            try:
                found[label] = int(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return found


def _status_counts(text: str) -> Dict[str, int]:
    lower = text.lower()
    return {word: lower.count(word) for word in STATUS_WORDS if lower.count(word)}


def _signed_in(driver: Any, site: str) -> Tuple[bool, str]:
    if site == "naukri":
        from naukri_bot.auth import is_logged_in
        ok = is_logged_in(driver, trust_url=False)
        return ok, "" if ok else "Naukri shows the signed-out page in the saved browser profile."
    state = connections.verify(driver, connections.PROVIDERS[site])
    return state.get("state") == "connected", state.get("message", "")


def evidence_dir(settings: Settings, day: Optional[date] = None) -> Path:
    day = day or date.today()
    return Path(settings.report_dir or paths.user("reports")) / day.isoformat() / "diagnostics"


def read_site(site: str, settings: Settings, folder: Path, seeds: Optional[Tuple[str, ...]] = None) -> SiteResult:
    """Load the site's account pages (or just `seeds`) in its saved profile and return what they show."""
    plan = _PLAN[site]
    result = SiteResult(site=site, state="skipped", message="", pages=[], signals={}, evidence=[])
    profile = _profile_for(site, settings)
    if not (profile / "chrome").is_dir():
        result.update(state="no_profile", message="No saved browser profile at %s; connect the site first." % profile)
        return result
    site_settings = dataclasses.replace(settings, browser_profile_dir=str(profile))
    try:
        driver = connections.create_driver(site_settings)
    except connections.BrowserProfileLocked as exc:
        result.update(state="locked", message=str(exc).splitlines()[0])
        return result
    except Exception as exc:  # Driver start-up failures are environmental; report, don't crash the audit.
        result.update(state="browser_error", message="%s: %s" % (type(exc).__name__, str(exc).splitlines()[0][:200]))
        return result
    try:
        queue: List[str] = list(seeds or plan["seeds"])
        visited = set()
        signed_in_checked = False
        while queue and len(result["pages"]) < MAX_PAGES:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if not safe_get(driver, url):
                result["pages"].append({"url": url, "error": "navigation failed"})
                continue
            human_pause(1.5, 3.0)
            if not signed_in_checked:
                ok, message = _signed_in(driver, site)
                signed_in_checked = True
                if not ok:
                    result.update(state="needs_sign_in", message=message or "Not signed in.")
                    return result
                result["state"] = "read"
            text = str(driver.execute_script(PAGE_TEXT) or "")
            page = {
                "url": url, "final_url": driver.current_url, "chars": len(text),
                "numbers": _numbers_near(text, plan["labels"]), "status_words": _status_counts(text),
                "parsed": pages.parse(site, driver.current_url, text),
            }
            path = folder / ("%s-%s.txt" % (site, _slug(url)))
            atomic_write_text(path, "URL: %s\nFINAL: %s\n\n%s" % (url, driver.current_url, text))
            page["evidence"] = str(path)
            result["pages"].append(page)
            result["evidence"].append(str(path))
            for label, value in page["numbers"].items():
                result["signals"].setdefault(label, value)
            try:
                links = driver.execute_script(LINKS) or []
            except Exception:
                links = []
            for href, label in links:
                if plan["follow"].search(label or "") and connections.allowed_host(href, connections.PROVIDERS[site]) \
                        and href not in visited and href not in queue:
                    queue.append(href)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    result["summary"] = pages.summarise(site, result["pages"])
    return result


def read_sites(settings: Settings, sites: Tuple[str, ...] = SITES, day: Optional[date] = None) -> Dict[str, Any]:
    folder = evidence_dir(settings, day)
    folder.mkdir(parents=True, exist_ok=True)
    results = {}
    for site in sites:
        if site not in _PLAN:
            continue
        logger.info("Reading %s account pages (read-only)", site)
        results[site] = read_site(site, settings, folder)
        logger.info("%s: %s %s", site, results[site]["state"], results[site].get("message", ""))
    return results
