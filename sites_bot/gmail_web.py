"""Gmail through the bot's own signed-in browser: read recent mail and save drafts. Never sends.

The no-password route. The browser profile keeps the Google session in its
cookies, so the startup bot and the reply reader use Gmail the way a person
would, with no GMAIL_APP_PASSWORD. Gmail's compose window saves a draft by
itself; this module waits for "Draft saved" and closes the window. It never
touches the Send button.
"""

import logging
import time
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote, urlencode

from selenium.common.exceptions import WebDriverException

logger = logging.getLogger(__name__)

INBOX = "https://mail.google.com/mail/u/0/"
WAIT_S = 4.0
SAVE_WAIT_S = 20.0
UPLOAD_WAIT_S = 60.0

_ROWS = """
return [...document.querySelectorAll('tr.zA')].slice(0, arguments[0]).map(row => {
  const who = row.querySelector('.yW span[email]');
  return {from: who ? who.getAttribute('email') : '', name: who ? (who.getAttribute('name') || who.innerText) : '',
          subject: (row.querySelector('.bog') || {}).innerText || ''};
});
"""
_OPEN = "const r = document.querySelectorAll('tr.zA')[arguments[0]]; if (r) { r.click(); return true; } return false;"
_MESSAGE = """
const all = [...document.querySelectorAll('div[data-legacy-message-id]')];
const last = all[all.length - 1];
if (!last) return null;
const body = last.querySelector('div.a3s');
return {id: last.getAttribute('data-legacy-message-id') || '', body: body ? body.innerText : ''};
"""
_FILE_INPUT = "input[type=file][name=Filedata]"


def signed_in(driver: Any) -> bool:
    url = driver.current_url or ""
    return "mail.google.com" in url and "accounts.google.com" not in url


def read_recent(driver: Any, days: int = 21, limit: int = 60) -> List[Any]:
    """Inbox mail from the last `days` days, newest first, as replies.Mail; [] when Gmail is not signed in."""
    from .replies import Mail

    query = "in:inbox newer_than:%dd -category:promotions -category:social -category:forums" % days
    mails = []  # type: List[Any]
    try:
        driver.get(INBOX + "#search/" + quote(query))
        time.sleep(WAIT_S)
        if not signed_in(driver):
            logger.warning("Gmail in the bot's browser is not signed in; sign in once and it stays signed in")
            return []
        rows = driver.execute_script(_ROWS, limit) or []
        for index, row in enumerate(rows):
            if not driver.execute_script(_OPEN, index):
                continue
            time.sleep(WAIT_S / 2)
            found = driver.execute_script(_MESSAGE) or {}
            if found.get("id"):
                mails.append(Mail(message_id="gmail:%s" % found["id"], sender=str(row.get("from") or ""),
                                  sender_name=str(row.get("name") or ""), subject=str(row.get("subject") or ""),
                                  body=str(found.get("body") or "")[:20000]))
            driver.back()
            time.sleep(WAIT_S / 2)
    except WebDriverException as exc:
        logger.warning("Stopped reading Gmail in the browser: %s", type(exc).__name__)
    logger.info("Read %d mail(s) from the Gmail the browser is signed in to", len(mails))
    return mails


def save_draft(driver: Any, to: str, subject: str, body: str, attachment: Optional[Path] = None) -> str:
    """Leave one draft in Gmail's Drafts; '' when saved, else what went wrong. Never sends."""
    try:
        start = driver.current_window_handle
        keep = list(driver.window_handles)
        driver.switch_to.new_window("tab")
    except WebDriverException as exc:
        return "could not open a tab for Gmail (%s)" % type(exc).__name__
    try:
        driver.get(INBOX + "?" + urlencode({"view": "cm", "fs": "1", "tf": "1", "to": to, "su": subject, "body": body}))
        time.sleep(WAIT_S)
        if not signed_in(driver):
            return "Gmail in the bot's browser is not signed in"
        if attachment is not None and attachment.is_file():
            inputs = driver.find_elements("css selector", _FILE_INPUT)
            if not inputs:
                return "Gmail's compose window had no attachment button"
            inputs[0].send_keys(str(attachment.resolve()))
            if not _wait_for(driver, lambda text: attachment.name in text and "Uploading" not in text, UPLOAD_WAIT_S):
                return "the resume did not finish uploading"
        # Gmail saves a draft a few seconds after the last change.
        if not _wait_for(driver, lambda text: "Draft saved" in text or "Saved" in text, SAVE_WAIT_S):
            return "Gmail did not say the draft was saved"
        return ""
    except WebDriverException as exc:
        return "could not write the draft in Gmail (%s)" % type(exc).__name__
    finally:
        try:
            for handle in [h for h in driver.window_handles if h not in keep]:
                driver.switch_to.window(handle)
                driver.close()
            driver.switch_to.window(start if start in driver.window_handles else driver.window_handles[0])
        except (WebDriverException, IndexError):
            pass


def _wait_for(driver: Any, ready: Any, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            text = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        except WebDriverException:
            text = ""
        if ready(text):
            return True
        time.sleep(1.0)
    return False
