"""The code or link a career site just emailed, read out of their Gmail.

Workday, Azure B2C, iCIMS and many company portals mail a one-time code or a
confirmation link before they let anyone reach the application form. There are two
ways to it: Gmail over IMAP when GMAIL_APP_PASSWORD is set, and otherwise the
Gmail account the bot's own Chrome profile is already signed in to, opened in a
tab of its own so the half-filled form keeps its tab. Nothing is sent, marked
read or deleted: the mailbox is only ever read.
"""

import email
import imaplib
import logging
import re
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Any, List, Optional, Tuple
from urllib.parse import quote

from selenium.common.exceptions import WebDriverException

from common.models import Settings


logger = logging.getLogger(__name__)

GMAIL_IMAP = "imap.gmail.com"
GMAIL_INBOX = "https://mail.google.com/mail/u/0/#inbox"
# A careers site's mail rarely lands in the Primary tab, and #inbox shows only that
# one: a Barclays Workday verification sat in Updates while the bot reported no mail
# had come. Gmail's own search reaches every tab, and in:anywhere adds spam too.
GMAIL_SEARCH = "https://mail.google.com/mail/u/0/#search/%s"
SEARCH_WINDOW = "newer_than:1d"
IMAP_TIMEOUT_S = 20.0
POLL_S = 3.0
NEWEST_MESSAGES = 20
# Gmail's list shows the newest mail first; a code further down than this is old
# enough that the site has almost certainly sent a newer one.
TOP_ROWS = 5


@dataclass
class Verification:
    code: str = ""
    link: str = ""
    subject: str = ""
    sender: str = ""
    why: str = ""


_URL = re.compile(r"https?://[^\s<>\"')]+")
_SUBJECT_WORDS = re.compile(
    r"verif|confirm|activat|validat|one[- ]?time|\botp\b|security code|access code|sign[- ]?in code"
    r"|your code|passcode|2-?step",
    re.I,
)
_CODE_CUE = re.compile(
    r"(?:verification|security|confirmation|activation|access|login|sign[- ]?in|one[- ]?time|single[- ]?use"
    r"|temporary|\botp\b|\bpin\b|passcode|code|password)",
    re.I,
)
_IS_YOUR = re.compile(r"^\W{0,4}(?:is|as)\s+(?:your|the)\b", re.I)
# "expires in 10 minutes", "valid for 24 hours": a duration is not a code.
_UNIT_AFTER = re.compile(r"^\W{0,3}(?:minutes?|mins?|hours?|hrs?|days?|seconds?|secs?|am|pm)\b", re.I)
# A whole token, so a run of digits inside a longer number or a domain never
# counts, while a code at the end of a sentence ("is 7281.") still does.
_TOKEN = re.compile(r"(?<![\w+-])(?<!\w\.)([A-Za-z0-9]{4,8})(?![\w+-])(?!\.\w)")
_DIGITS = re.compile(r"\d")
_LINK_WORDS = re.compile(r"verif|confirm|activat|validat|complete your|finish|get started|reset", re.I)
_NOT_A_LINK = re.compile(r"unsubscribe|privacy|terms|help|support|preferences|profile/settings|\.png|\.jpe?g", re.I)
_CUE_BEFORE_CHARS = 40
_CUE_AFTER_CHARS = 30


def looks_like_verification(subject: str, body: str) -> bool:
    """Whether this message is a site asking them to prove the address is theirs."""
    return bool(_SUBJECT_WORDS.search(subject or "") or _SUBJECT_WORDS.search((body or "")[:600]))


def extract_code(text: str) -> str:
    """The one-time code a message spells out; "" when it names none."""
    plain = _URL.sub(" ", text or "")
    best = ""
    best_distance = _CUE_BEFORE_CHARS + 1
    for match in _TOKEN.finditer(plain):
        token = match.group(1)
        if not _DIGITS.search(token):
            continue
        after = plain[match.end(): match.end() + _CUE_AFTER_CHARS]
        if _UNIT_AFTER.match(after):
            continue
        before = plain[max(0, match.start() - _CUE_BEFORE_CHARS): match.start()]
        cues = list(_CODE_CUE.finditer(before))
        distance = len(before) - cues[-1].end() if cues else _CUE_BEFORE_CHARS + 1
        if _IS_YOUR.match(after) and _CODE_CUE.search(after):
            distance = 0
        if distance > _CUE_BEFORE_CHARS:
            continue
        if token.isdigit() and 1900 <= int(token) <= 2100 and distance > 12:
            continue
        if distance < best_distance:
            best, best_distance = token, distance
    return best


def extract_link(text: str, domain: str = "") -> str:
    """The link a message offers for confirming the address; "" when it offers none."""
    host = (domain or "").casefold().lstrip("w.")
    best = ""
    for match in _URL.finditer(text or ""):
        url = match.group(0).rstrip(".,)>\"'")
        if _NOT_A_LINK.search(url):
            continue
        around = (text[max(0, match.start() - 120): match.start()]
                  + " " + text[match.end(): match.end() + 60])
        if not (_LINK_WORDS.search(url) or _LINK_WORDS.search(around)):
            continue
        if host and host in url.casefold():
            return url
        best = best or url
    return best


def _header(raw: Any) -> str:
    if not raw:
        return ""
    try:
        return " ".join(str(make_header(decode_header(str(raw)))).split())
    except (ValueError, UnicodeDecodeError):
        return " ".join(str(raw).split())


def _body(message: Any) -> str:
    """A message's readable text, preferring the plain part over the HTML one."""
    plain, html = "", ""
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        kind = (part.get_content_type() or "").lower()
        if kind not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
        except (AssertionError, LookupError, ValueError):
            continue
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if kind == "text/plain":
            plain = plain or text
        else:
            html = html or text
    if plain:
        return plain
    return re.sub(r"<[^>]+>", " ", html)


def _age_s(message: Any, now: datetime) -> Optional[float]:
    try:
        sent = parsedate_to_datetime(str(message.get("Date", "")))
    except (TypeError, ValueError):
        return None
    if sent is None:
        return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    return (now - sent).total_seconds()


def site_name(domain: str) -> str:
    """The employer's own word in a careers host: barclays.wd3.myworkdayjobs.com -> barclays."""
    return (domain or "").casefold().lstrip("w.").split(".")[0]


# Workday mail says "Workday", never "barclays.wd3.myworkdayjobs.com", so the host
# alone could not vouch for it and real verification mail was turned away.
_ATS_WORDS = {
    "myworkdayjobs": "workday", "workday": "workday", "icims": "icims",
    "smartrecruiters": "smartrecruiters", "greenhouse": "greenhouse", "lever": "lever",
    "successfactors": "successfactors", "taleo": "taleo", "oraclecloud": "oracle",
    "b2clogin": "microsoft", "zohorecruit": "zoho", "darwinbox": "darwinbox",
    "keka": "keka", "ripplehire": "ripplehire", "jobvite": "jobvite",
}


def site_words(domain: str, company: str) -> List[str]:
    """Every word a mail about this site may name it by: the employer and its hiring system."""
    words = [site_name(domain)]
    low = (domain or "").casefold()
    words += [word for fragment, word in _ATS_WORDS.items() if fragment in low]
    if company:
        words.append(company.casefold())
    return [word for word in words if word]


def _matches_site(text: str, domain: str, company: str) -> bool:
    low = text.casefold()
    return any(word in low for word in site_words(domain, company))


def search_url(domain: str = "", company: str = "") -> str:
    """Gmail's search for recent verification mail, across every tab and spam."""
    query = "in:anywhere %s (verify OR verification OR code OR confirm OR activate)" % SEARCH_WINDOW
    return GMAIL_SEARCH % quote(query, safe="")


def _read_imap(
    settings: Settings, account: str, within_s: float, domain: str, company: str,
) -> Tuple[Optional[Verification], str]:
    """The newest verification mail IMAP can see; (result, problem) with one of them set."""
    context = ssl.create_default_context()
    try:
        imap = imaplib.IMAP4_SSL(GMAIL_IMAP, ssl_context=context, timeout=IMAP_TIMEOUT_S)
    except (OSError, imaplib.IMAP4.error, ssl.SSLError) as exc:
        return None, "could not reach Gmail: %s" % exc
    try:
        imap.login(account, settings.gmail_app_password)
        # Read-only: a code the bot read must still look unread to them.
        imap.select("INBOX", readonly=True)
        since = (datetime.now(timezone.utc) - timedelta(seconds=max(within_s, 60.0) + 86400)).strftime("%d-%b-%Y")
        state, data = imap.search(None, "SINCE", since)
        if state != "OK" or not data or not data[0]:
            return None, "no mail in the last day"
        numbers = data[0].split()[-NEWEST_MESSAGES:]
        now = datetime.now(timezone.utc)
        fallback = ""
        for number in reversed(numbers):
            state, payload = imap.fetch(number, "(BODY.PEEK[])")
            if state != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(payload[0][1])
            subject, sender = _header(message.get("Subject")), _header(message.get("From"))
            body = _body(message)
            if not looks_like_verification(subject, body):
                continue
            age = _age_s(message, now)
            if age is not None and age > within_s:
                fallback = fallback or "the only verification mail is %.0f minutes old" % (age / 60.0)
                continue
            if (domain or company) and not _matches_site(" ".join((subject, sender, body[:1500])), domain, company):
                fallback = fallback or "a verification mail that does not mention %s" % (domain or company)
                continue
            found = Verification(code=extract_code(subject + "\n" + body),
                                 link=extract_link(body, domain), subject=subject, sender=sender)
            if found.code or found.link:
                logger.info("read the code Gmail got %.0fs ago from %s", age or 0.0, sender or "a sender")
                return found, ""
            fallback = fallback or "a verification mail with no code or link in it (%s)" % subject
        return None, fallback or "no verification mail in the inbox"
    except imaplib.IMAP4.error as exc:
        return None, "Gmail refused the app password or the search: %s" % exc
    except (OSError, ssl.SSLError) as exc:
        return None, "lost the connection to Gmail: %s" % exc
    finally:
        try:
            imap.logout()
        except (OSError, imaplib.IMAP4.error, ssl.SSLError):
            pass


_ROWS_SCRIPT = """
return [...document.querySelectorAll('tr.zA')].slice(0, arguments[0]).map(row => ({
  subject: (row.querySelector('.bog') || {}).innerText || '',
  snippet: (row.querySelector('.y2') || {}).innerText || '',
  stamp: ((row.querySelector('.xW span[title]') || {}).getAttribute
    ? row.querySelector('.xW span[title]').getAttribute('title') : '') || '',
  from: (row.querySelector('.yW span[email]') || {}).innerText || '',
}));
"""
_OPEN_ROW_SCRIPT = "const r = document.querySelectorAll('tr.zA')[arguments[0]]; if (r) { r.click(); return true; } return false;"
_MESSAGE_SCRIPT = """
const links = [...document.querySelectorAll('div.a3s a[href^="http"]')].map(a => a.getAttribute('href'));
const body = (document.querySelector('div.a3s') || document.body || {}).innerText || '';
return body + '\\n' + links.join('\\n');
"""
_SIGNED_OUT = re.compile(r"accounts\.google\.com|signin|ServiceLogin", re.I)


def _stamp_age_s(stamp: str) -> Optional[float]:
    """How long ago Gmail's own row says the mail came, in seconds; None when it cannot be read.

    Gmail writes those stamps in their local time, so they are compared with the
    local clock, not with UTC.
    """
    for shape in ("%a, %b %d, %Y, %I:%M %p", "%a, %d %b %Y, %I:%M %p", "%b %d, %Y, %I:%M %p"):
        try:
            sent = datetime.strptime(stamp.replace("\u202f", " ").replace("\u00a0", " ").strip(), shape)
        except ValueError:
            continue
        return (datetime.now() - sent).total_seconds()
    return None


def _read_browser(driver: Any, within_s: float, domain: str, company: str) -> Tuple[Optional[Verification], str]:
    """The newest verification mail in the signed-in Gmail, read in a tab of its own."""
    try:
        start = driver.current_window_handle
        keep = list(driver.window_handles)
    except WebDriverException as exc:
        return None, "the browser did not answer (%s)" % type(exc).__name__
    try:
        driver.switch_to.new_window("tab")
    except WebDriverException as exc:
        return None, "could not open a tab for Gmail (%s)" % type(exc).__name__
    try:
        driver.get(search_url(domain, company))
        time.sleep(POLL_S)
        if _SIGNED_OUT.search(driver.current_url or ""):
            return None, "the bot's browser is not signed in to Gmail"
        rows = driver.execute_script(_ROWS_SCRIPT, TOP_ROWS) or []
        fallback = ""
        for index, row in enumerate(rows):
            subject = str(row.get("subject") or "")
            snippet = str(row.get("snippet") or "")
            if not looks_like_verification(subject, snippet):
                continue
            age = _stamp_age_s(str(row.get("stamp") or ""))
            if age is not None and age > within_s:
                fallback = fallback or "the only verification mail is %.0f minutes old" % (age / 60.0)
                continue
            if (domain or company) and not _matches_site(" ".join((subject, snippet, str(row.get("from") or ""))),
                                                        domain, company):
                fallback = fallback or "a verification mail that does not mention %s" % (domain or company)
                continue
            code = extract_code(subject + "\n" + snippet)
            text = ""
            if not code and driver.execute_script(_OPEN_ROW_SCRIPT, index):
                time.sleep(POLL_S)
                text = str(driver.execute_script(_MESSAGE_SCRIPT) or "")
                code = extract_code(subject + "\n" + text)
            found = Verification(code=code, link=extract_link(text or snippet, domain),
                                 subject=subject, sender=str(row.get("from") or ""))
            if found.code or found.link:
                logger.info("read the code from the Gmail the browser is signed in to (%s)", subject)
                return found, ""
            fallback = fallback or "a verification mail with no code or link in it (%s)" % subject
        return None, fallback or "no verification mail at the top of the inbox"
    except WebDriverException as exc:
        return None, "could not read Gmail in the browser (%s)" % type(exc).__name__
    finally:
        _back_to(driver, start, keep)


def _back_to(driver: Any, start: str, keep: List[str]) -> None:
    """Close the Gmail tab and put the tab the form is in back in front."""
    try:
        for handle in [handle for handle in driver.window_handles if handle not in keep]:
            driver.switch_to.window(handle)
            driver.close()
        driver.switch_to.window(start if start in driver.window_handles else driver.window_handles[0])
    except (WebDriverException, IndexError) as exc:
        logger.warning("Could not get back to the application tab: %s", type(exc).__name__)


def verification(
    settings: Settings,
    driver: Any = None,
    *,
    domain: str = "",
    company: str = "",
    within_s: float = 300.0,
    wait_s: float = 60.0,
) -> Verification:
    """The code or link a site just emailed them, waiting up to `wait_s` for it to arrive."""
    from .accounts import account_email

    account = account_email(settings)
    if not account:
        return Verification(why="no email address for career-site accounts (set COMPANY_SITE_EMAIL in .env)")
    if not settings.gmail_app_password and driver is None:
        return Verification(why="no GMAIL_APP_PASSWORD and no browser to read Gmail in")
    deadline = time.monotonic() + max(wait_s, 0.0)
    problem = ""
    while True:
        if settings.gmail_app_password:
            found, problem = _read_imap(settings, account, within_s, domain, company)
            if found is not None:
                return found
        if driver is not None:
            found, browser_problem = _read_browser(driver, within_s, domain, company)
            if found is not None:
                return found
            problem = problem or browser_problem
        if time.monotonic() >= deadline:
            return Verification(why=problem or "nothing arrived in %.0fs" % wait_s)
        time.sleep(POLL_S)
