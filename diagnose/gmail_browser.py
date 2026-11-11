"""Read Gmail through a browser profile that is already signed in: no app password.

Gmail's search box reaches every folder at once (`in:anywhere` covers All Mail,
Spam and Trash), and each result row carries sender, subject and the full date
in its tooltip, so the sweep reads list pages only. A message body is opened
only for the few hiring-looking mails the rules could not place, and only when
a model is available to read it. Nothing is clicked except result rows and
page links; no mail is opened in a way that changes it beyond Gmail marking it
read when a body is shown.
"""

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from common import browser_lanes, connections
from common.models import Settings
from diagnose import gmail, llm_review
from diagnose.trail import Trail

logger = logging.getLogger(__name__)

GMAIL = "https://mail.google.com/mail/u/0/"
WAIT_S = 3.0
PAGE_CAP = 80
QUERIES = (("search:all-mail", "newer_than:%dd"), ("search:in:spam", "in:spam newer_than:%dd"))

_ROWS = """
return [...document.querySelectorAll('tr.zA')].map(row => {
  const who = row.querySelector('.yW span[email]');
  const when = row.querySelector('.xW span[title]') || row.querySelector('td.xW span');
  return {from: who ? who.getAttribute('email') : '', name: who ? (who.getAttribute('name') || who.innerText) : '',
          subject: (row.querySelector('.bog') || {}).innerText || '',
          date: when ? (when.getAttribute('title') || when.innerText) : '',
          id: row.getAttribute('id') || row.querySelector('[data-legacy-thread-id]')?.getAttribute('data-legacy-thread-id') || ''};
});
"""
_ACCOUNT = """
const sources = [document.title, ...[...document.querySelectorAll('a[aria-label]')].map(a => a.getAttribute('aria-label'))];
for (const text of sources) {
  const m = (text || '').match(/[\\w.+-]+@[\\w.-]+\\.\\w+/);
  if (m) return m[0];
}
return '';
"""
_OPEN = "const r = document.querySelectorAll('tr.zA')[arguments[0]]; if (r) { r.click(); return true; } return false;"
_BODY = """
const all = [...document.querySelectorAll('div[data-legacy-message-id]')];
const last = all[all.length - 1];
const body = last ? last.querySelector('div.a3s') : null;
return body ? body.innerText : '';
"""


def candidate_profiles(settings: Settings) -> List[Tuple[str, Path]]:
    """Profiles that may hold a Google session, most likely first."""
    base = Path(settings.browser_profile_dir)
    found = [("naukri", base)]
    startups = browser_lanes.profile_dir("startups", settings.browser_profile_dir)
    if startups is not None:
        found.append(("startups", startups))
    found.append(("linkedin", base.parent / "linkedin"))
    return [(name, path) for name, path in found if (path / "chrome").is_dir()]


def _signed_in(driver: Any) -> bool:
    url = driver.current_url or ""
    return "mail.google.com" in url and "accounts.google.com" not in url


def _rows_for(driver: Any, query: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for page in range(1, PAGE_CAP + 1):
        suffix = "" if page == 1 else "/p%d" % page
        driver.get(GMAIL + "#search/" + quote(query) + suffix)
        found = _settled_rows(driver)
        if not _signed_in(driver):
            return rows
        fresh = [row for row in found if (row.get("from"), row.get("subject"), row.get("date")) not in seen]
        if not fresh:
            break
        for row in fresh:
            seen.add((row.get("from"), row.get("subject"), row.get("date")))
            rows.append(row)
    return rows


def _settled_rows(driver: Any, timeout_s: float = 10.0) -> List[Dict[str, str]]:
    """The result rows once Gmail has stopped adding them (two identical reads in a row)."""
    deadline = time.monotonic() + timeout_s
    previous: List[Dict[str, str]] = []
    time.sleep(WAIT_S / 2)
    while True:
        found = driver.execute_script(_ROWS) or []
        if found and len(found) == len(previous):
            return found
        previous = found
        if time.monotonic() > deadline:
            return found
        time.sleep(1.0)


def _sender(row: Dict[str, str]) -> str:
    name, address = row.get("name") or "", row.get("from") or ""
    return "%s <%s>" % (name, address) if name and address else address or name


def audit(settings: Settings, days: int, llm_client: Any = None, local: Optional[Dict[str, Any]] = None,
          trail: Optional[Trail] = None) -> Dict[str, Any]:
    """Same result shape as gmail.audit, read from the first signed-in browser profile."""
    result = gmail.empty_result("", days)
    result["via"] = "browser"
    trail = trail if trail is not None else Trail()
    profiles = candidate_profiles(settings)
    if not profiles:
        result["error"] = "No browser profile exists yet; connect Naukri or Google in the dashboard first."
        return result
    tried: List[str] = []
    for name, profile in profiles:
        site_settings = dataclasses.replace(settings, browser_profile_dir=str(profile))
        try:
            driver = connections.create_driver(site_settings)
        except connections.BrowserProfileLocked:
            tried.append("%s: browser profile in use" % name)
            continue
        except Exception as exc:
            tried.append("%s: %s" % (name, type(exc).__name__))
            continue
        try:
            driver.get(GMAIL)
            time.sleep(WAIT_S)
            if not _signed_in(driver):
                tried.append("%s: Gmail not signed in" % name)
                continue
            result["account"] = str(driver.execute_script(_ACCOUNT) or "") or ("(signed-in %s profile)" % name)
            result["profile"] = name
            return _sweep(driver, result, days, llm_client, local or {}, trail)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    result["error"] = "No browser profile is signed in to Gmail (%s). Open the dashboard's Connections page, sign in to Google once, and re-run." % "; ".join(tried)
    return result


def _sweep(driver: Any, result: Dict[str, Any], days: int, llm_client: Any, local: Dict[str, Any], trail: Trail) -> Dict[str, Any]:
    """Folder sweep, targeted searches, model verification, body reads for the rest; then one tally of every record."""
    model = llm_review.as_model(llm_client)
    records: List[Dict[str, Any]] = []
    for folder, template in QUERIES:
        rows = _rows_for(driver, template % days)
        result["folders"][folder] = len(rows)
        for row in rows:
            records.append(gmail.make_record(folder, _sender(row), row.get("subject") or "", row.get("date") or ""))

    def fetch_rows(query: str) -> List[Dict[str, str]]:
        return [{"from": _sender(row), "subject": row.get("subject") or "", "date": row.get("date") or ""}
                for row in _rows_for(driver, query)]

    queries = llm_review.propose_queries(model, local, days, trail)
    result["queries"] = llm_review.run_queries(fetch_rows, queries, records, gmail.make_record, trail)
    result["verification"] = llm_review.verify_kinds(model, records, trail)

    def fetch_body(record: Dict[str, Any]) -> str:
        subject = record["subject"][:60].replace('"', "")
        driver.get(GMAIL + "#search/" + quote('in:anywhere subject:"%s"' % subject))
        time.sleep(WAIT_S)
        if not driver.execute_script(_OPEN, 0):
            return ""
        time.sleep(WAIT_S / 2)
        return str(driver.execute_script(_BODY) or "")[:4000]

    gmail.read_bodies(model, records, fetch_body, result, trail)
    result["model"] = model.status() if model else "no model configured"
    return gmail.tally(result, records)
