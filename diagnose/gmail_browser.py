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
from diagnose import gmail, mail_rules

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
        time.sleep(WAIT_S)
        if not _signed_in(driver):
            return rows
        found = driver.execute_script(_ROWS) or []
        fresh = [row for row in found if (row.get("from"), row.get("subject"), row.get("date")) not in seen]
        if not fresh:
            break
        for row in fresh:
            seen.add((row.get("from"), row.get("subject"), row.get("date")))
            rows.append(row)
        if len(found) < 20:
            break
    return rows


def _sender(row: Dict[str, str]) -> str:
    name, address = row.get("name") or "", row.get("from") or ""
    return "%s <%s>" % (name, address) if name and address else address or name


def audit(settings: Settings, days: int, llm_client: Any = None) -> Dict[str, Any]:
    """Same result shape as gmail.audit, read from the first signed-in browser profile."""
    result: Dict[str, Any] = {
        "account": "", "days": days, "folders": {}, "scanned": 0, "by_platform": {}, "positives": [],
        "spam_hiring": [], "unplaced": [], "llm_used": 0, "error": "", "via": "browser",
    }
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
            _sweep(driver, result, days, llm_client)
            return _finish(result)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    result["error"] = "No browser profile is signed in to Gmail (%s). Open the dashboard's Connections page, sign in to Google once, and re-run." % "; ".join(tried)
    return result


def _sweep(driver: Any, result: Dict[str, Any], days: int, llm_client: Any) -> None:
    per_platform: Dict[str, Dict[str, int]] = result["by_platform"]
    unplaced: List[Tuple[str, Dict[str, str]]] = []
    for folder, template in QUERIES:
        query = template % days
        rows = _rows_for(driver, query)
        result["folders"][folder] = len(rows)
        for row in rows:
            result["scanned"] += 1
            sender = _sender(row)
            verdict = mail_rules.classify(sender, row.get("subject") or "")
            counts = per_platform.setdefault(verdict.platform, {})
            counts[verdict.kind] = counts.get(verdict.kind, 0) + 1
            record = {"date": row.get("date") or "", "from": sender[:80], "subject": (row.get("subject") or "")[:120],
                      "platform": verdict.platform, "kind": verdict.kind, "folder": folder, "rule": verdict.rule}
            if verdict.positive:
                result["positives"].append(record)
            if folder.endswith("spam") and verdict.hiring_related and not mail_rules.is_noise(verdict):
                result["spam_hiring"].append(record)
            if verdict.kind == "OTHER" and verdict.hiring_related:
                unplaced.append((query, row))
    if llm_client is None or not llm_client.available():
        return
    failures = 0
    for query, row in unplaced[-gmail.MAX_BODY_FETCHES:]:
        if failures >= gmail.MAX_LLM_FAILURES:
            logger.warning("The model failed %d times in a row; the remaining %d unplaced mails stay OTHER.",
                           failures, len(unplaced))
            break
        subject = row.get("subject") or ""
        driver.get(GMAIL + "#search/" + quote('%s subject:"%s"' % (query, subject[:60].replace('"', ""))))
        time.sleep(WAIT_S)
        if not driver.execute_script(_OPEN, 0):
            continue
        time.sleep(WAIT_S / 2)
        body = str(driver.execute_script(_BODY) or "")[:4000]
        header = {"from": _sender(row), "date": row.get("date") or "", "subject": subject}
        judged = gmail._llm_kind(llm_client, header, body)
        if not judged:
            failures += 1
            continue
        failures = 0
        result["llm_used"] += 1
        kind = str(judged["kind"]).upper()
        platform = mail_rules.platform_of(header["from"])
        counts = per_platform.setdefault(platform, {})
        counts["OTHER"] = max(0, counts.get("OTHER", 0) - 1)
        counts[kind] = counts.get(kind, 0) + 1
        record = {"date": header["date"], "from": header["from"][:80], "subject": subject[:120], "platform": platform,
                  "kind": kind, "folder": "search", "rule": "llm", "summary": str(judged.get("summary", ""))[:200]}
        (result["positives"] if kind in mail_rules.POSITIVE else result["unplaced"]).append(record)


def _finish(result: Dict[str, Any]) -> Dict[str, Any]:
    result["by_platform"] = {platform: dict(sorted(kinds.items(), key=lambda kv: -kv[1]))
                             for platform, kinds in sorted(result["by_platform"].items())}
    result["positives"].sort(key=lambda item: item["date"], reverse=True)
    result["positive_total"] = len(result["positives"])
    result["positive_by_platform"] = gmail._count(result["positives"], "platform")
    result["positive_by_kind"] = gmail._count(result["positives"], "kind")
    return result
