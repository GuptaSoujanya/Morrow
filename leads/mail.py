"""leads:mail - read hiring mail in Gmail (All Mail and Spam) and answer it.

    python3 -m leads.mail [--days N] [--limit N] [--dry-run] [--no-send] [--env PATH] [-v]

Two ways in, chosen per inbox:

* an app password (GMAIL_APP_PASSWORD or REPLY_INBOXES=address:password): IMAP read-only,
  replies sent over SMTP, drafts appended to Gmail Drafts;
* no password: the bot's own signed-in browser profile (the same ones the funnel audit
  reads Gmail through), replies sent by the browser agent in the Gmail thread, drafts left
  through Gmail's compose window. Nothing to configure beyond being signed in once.

Per inbox it

1. lists every mail of the last LEADS_DAYS days in All Mail and Spam, classifies each with
   diagnose.mail_rules and records the hiring-positive ones as leads in user/inputs/leads.json;
2. for each lead still waiting, reads the body, asks the model for a reply written only from
   the saved facts (sites_bot.replies.draft_reply), and
   - sends it when LEADS_AUTO_REPLY is on and the draft has no gaps,
   - otherwise leaves it in Gmail Drafts and marks the lead needs_you,
   - never answers assessments (a test only you can take), automated senders, or job-board
     notifications (the board's own inbox stage answers those on the board);
3. writes every answer to user/reports/<day>/leads/mail-<slug>.txt.

A thread is answered once: the journal keeps its state.
"""

import argparse
import dataclasses
import logging
import re
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from common import paths
from common.models import Profile, Settings
from common.shared_files import atomic_write_text
from diagnose import gmail, gmail_browser, mail_rules
from leads import collect, store

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_S = 60
#: Mail from these platforms is a board notification: the board's inbox stage answers it on the board.
BOARD_PLATFORMS = ("naukri", "hirist", "instahyre", "cutshort", "wellfound", "linkedin", "foundit", "shine",
                   "indeed", "glassdoor", "iimjobs", "internshala", "unstop", "freshersworld", "apna")
#: Kinds nobody but the candidate can act on.
PERSON_KINDS = ("ASSESSMENT",)
SEND_REPORT = ('When you finish or stop, reply with ONE JSON object and nothing else:\n'
               '{"status": "done|needs_you|failed", "why": "one or two sentences", '
               '"blocker": "none|human_check|sign_in|transient|other"}')
#: A journal with no mail lead yet reads this far back, so replies that arrived before the stage existed are not lost.
FIRST_RUN_DAYS = 30
_THREAD_TEXT = """
const texts = [...document.querySelectorAll('div.a3s')].map(e => e.innerText || '');
const toast = document.querySelector('.bAq, [role="alert"]');
return texts.concat(toast ? [toast.innerText || ''] : []).join('\\n');
"""


@dataclass
class Transport:
    """How one inbox is read and written: fetch a lead's body, send a reply, leave a draft."""
    account: str
    via: str
    fetch_body: Callable[[Dict[str, Any]], str]
    send: Callable[[Any, str], str]
    draft: Callable[[Any, str], str]


# ---------------------------------------------------------------------------
# Reading over IMAP
# ---------------------------------------------------------------------------


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=max(int(days or 1), 1))


def read_leads(imap: Any, days: int) -> List[Dict[str, Any]]:
    """Every hiring-positive mail of the last `days` days, as leads; each carries the IMAP
    folder/uid/header it came from so the body can be fetched when it is answered."""
    seen_ids = set()
    located: Dict[str, Tuple[str, bytes, Dict[str, str]]] = {}
    records: List[Dict[str, Any]] = []
    since = _since(days)
    for folder in gmail.FOLDERS:
        for uid, header in gmail._fetch_headers(imap, gmail._uids(imap, folder, since)):
            message_id = header.get("message_id") or ""
            if message_id and message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            record = gmail.make_record(folder, header.get("from", ""), header.get("subject", ""),
                                       header.get("date", ""), bool(header.get("bulk")))
            record["message_id"] = message_id
            records.append(record)
            located[_record_key(record)] = (folder, uid, header)
    leads = collect.from_mail_records(records)
    for lead in leads:
        where = located.get(_lead_key(lead))
        if where:
            lead["_folder"], lead["_uid"], lead["_header"] = where
    return leads


def _record_key(record: Dict[str, Any]) -> str:
    return "%s|%s|%s" % (record.get("from", "")[:80], record.get("subject", "")[:120], record.get("date", "")[:40])


def _lead_key(lead: Dict[str, Any]) -> str:
    return "%s|%s|%s" % (lead.get("sender", "")[:80], lead.get("subject", "")[:120], lead.get("received_at", ""))


def _public(lead: Dict[str, Any]) -> Dict[str, Any]:
    """The lead without the IMAP handles (those never go into the journal)."""
    return {key: value for key, value in lead.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# Reading through the signed-in browser
# ---------------------------------------------------------------------------


def read_browser_leads(driver: Any, days: int) -> List[Dict[str, Any]]:
    """Every hiring-positive mail of the last `days` days in All Mail and Spam, via Gmail's search pages."""
    records: List[Dict[str, Any]] = []
    for folder, template in gmail_browser.QUERIES:
        for row in gmail_browser._rows_for(driver, template % max(int(days or 1), 1)):
            records.append(gmail.make_record(folder, gmail_browser._sender(row), row.get("subject") or "",
                                             row.get("date") or ""))
    return collect.from_mail_records(records)


def _thread_search(subject: str) -> str:
    return gmail_browser.GMAIL + "#search/" + quote('in:anywhere subject:"%s"' % subject[:60].replace('"', ""))


def browser_body(driver: Any, lead: Dict[str, Any]) -> str:
    """Open the newest message of the lead's thread in Gmail and read its text."""
    try:
        driver.get(_thread_search(lead.get("subject", "")))
        time.sleep(gmail_browser.WAIT_S)
        if not driver.execute_script(gmail_browser._OPEN, 0):
            return ""
        time.sleep(gmail_browser.WAIT_S / 2)
        return str(driver.execute_script(gmail_browser._BODY) or "")[:8000]
    except Exception as exc:  # A thread that will not open is answered from the row text instead.
        logger.debug("Could not open the Gmail thread for %s: %s", lead.get("subject"), exc)
        return ""


def _longest_line(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return max(lines, key=len) if lines else ""


def browser_send(driver: Any, settings: Settings, profile: Profile, mail: Any, text: str) -> str:
    """Reply in the Gmail thread through the browser agent; '' when the reply is visible in the thread."""
    from sites_bot import browser_agent

    if not browser_agent.reserve_task(settings):
        return "no browser-agent task left this run (BROWSER_AGENT off, its limit reached, or the model is out of quota)"
    url = _thread_search(mail.subject)
    try:
        driver.get(url)
        time.sleep(gmail_browser.WAIT_S)
    except Exception as exc:
        return "Gmail did not open: %s" % type(exc).__name__
    instruction = (
        "In this Gmail search, open the thread from %s with the subject %r. Click Reply (reply to the sender "
        "only), paste EXACTLY the text below as the whole reply body, and click Send. Do not change a word, "
        "do not add attachments, do not reply to anyone else and do not touch any other mail. If the thread "
        "already shows this reply after their last message, do nothing and report status done.\n\n"
        "The reply text:\n%s" % (mail.sender_name or mail.sender, mail.subject, text))
    prompt = browser_agent.task_prompt(instruction, url, "", profile.email or settings.email,
                                       has_password=False, report=SEND_REPORT)
    workdir = browser_agent.workdir_for(settings, "gmail reply %s" % (mail.sender_name or mail.sender))
    run = browser_agent.run_agent(driver, settings, prompt, workdir)
    report = run.report or {}
    if report.get("status") != "done":
        return str(report.get("why") or run.problem or "the agent did not send the reply")[:200]
    if not _reply_visible(driver, text):
        return "the agent said it sent the reply, but the reply is not visible in the thread"
    return ""


def _reply_visible(driver: Any, text: str) -> bool:
    """Whether the reply's longest line is in an open Gmail tab's thread or its 'Message sent' notice.

    browser_agent.quote_on_page skips mail.google.com tabs on purpose (a Gmail receipt is never
    proof of a company-site application), so a Gmail reply is checked here, on the Gmail tabs only."""
    wanted = " ".join(_longest_line(text).split()).casefold()
    if len(wanted) < 12:
        return False
    try:
        home = driver.current_window_handle
        handles = list(driver.window_handles)
    except Exception:
        return False
    found = False
    for handle in handles:
        try:
            driver.switch_to.window(handle)
            if "mail.google.com" not in str(driver.current_url or ""):
                continue
            page = " ".join(str(driver.execute_script(_THREAD_TEXT) or "").split()).casefold()
            if wanted in page:
                found = True
                break
        except Exception:
            continue
    try:
        driver.switch_to.window(home)
    except Exception:
        pass
    return found


def browser_draft(driver: Any, mail: Any, text: str) -> str:
    from sites_bot import gmail_web

    subject = mail.subject if mail.subject.lower().startswith("re:") else "Re: %s" % mail.subject
    return gmail_web.save_draft(driver, mail.sender, subject, text)


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


def decide(lead: Dict[str, Any], automated: bool, draft: Optional[Dict[str, Any]],
           auto_reply: bool = True) -> Tuple[str, str]:
    """(state, why) for one lead, given what the model drafted. Pure; no I/O."""
    kind = str(lead.get("kind") or "").upper()
    platform = str(lead.get("platform") or "")
    if kind in PERSON_KINDS:
        return "needs_you", "An assessment or test link: only you can take it. The mail is in %s." % (
            lead.get("folder") or "Gmail")
    if platform in BOARD_PLATFORMS:
        return "skipped", "A %s notification; the board's own inbox stage (inbox:%s) answers it on the board." % (
            platform, platform)
    if automated:
        return "skipped", "Sent by an automated address nobody reads replies to."
    if not draft or not str(draft.get("text") or "").strip():
        return "failed", "The model wrote no reply (no model, or it could not answer from the saved facts)."
    if draft.get("gaps"):
        return "needs_you", "Draft saved in Gmail Drafts; it needs facts you have not saved: %s" % (
            "; ".join(draft["gaps"])[:200])
    if not auto_reply:
        return "needs_you", "Draft saved in Gmail Drafts; LEADS_AUTO_REPLY is off, so nothing was sent."
    return "answered", "Replied from the saved facts."


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def _mail_for(lead: Dict[str, Any], body: str):
    from sites_bot.replies import Mail

    header = lead.get("_header") or {}
    name, address = parseaddr(lead.get("sender") or header.get("from", ""))
    return Mail(message_id=header.get("message_id") or lead["id"], sender=address or lead.get("sender", ""),
                sender_name=name or lead.get("who", ""), subject=lead.get("subject", ""), body=body,
                sent_at=lead.get("received_at", ""), references=header.get("message_id") or "",
                folder=lead.get("_folder") or lead.get("folder", ""))


def compose(account: str, mail: Any, text: str) -> EmailMessage:
    """The reply as a mail threaded under theirs."""
    message = EmailMessage()
    message["From"] = account
    message["To"] = mail.sender
    message["Subject"] = mail.subject if mail.subject.lower().startswith("re:") else "Re: %s" % mail.subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if str(mail.message_id).startswith("<"):
        message["In-Reply-To"] = mail.message_id
        message["References"] = " ".join(filter(None, (mail.references, mail.message_id)))
    message.set_content(text)
    return message


def send_message(account: str, password: str, message: EmailMessage) -> str:
    """Send over Gmail SMTP; '' when sent, else the reason."""
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(),
                              timeout=SMTP_TIMEOUT_S) as smtp:
            smtp.login(account, password.replace(" ", ""))
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
        return "SMTP refused the mail: %s" % str(exc).splitlines()[0][:200]
    return ""


def save_draft(settings: Settings, account: str, password: str, message: EmailMessage) -> str:
    from sites_bot.cold_email import gmail_draft

    return gmail_draft(message, account, password)


def imap_transport(imap: Any, account: str, password: str, settings: Settings) -> Transport:
    def fetch_body(lead: Dict[str, Any]) -> str:
        if lead.get("_uid") is None or not gmail._select(imap, lead.get("_folder") or gmail.SEARCH_FOLDER):
            return ""
        return gmail._fetch_body(imap, lead["_uid"])

    return Transport(account, "imap", fetch_body,
                     lambda mail, text: send_message(account, password, compose(account, mail, text)),
                     lambda mail, text: save_draft(settings, account, password, compose(account, mail, text)))


def browser_transport(driver: Any, account: str, settings: Settings, profile: Profile) -> Transport:
    return Transport(account, "browser", lambda lead: browser_body(driver, lead),
                     lambda mail, text: browser_send(driver, settings, profile, mail, text),
                     lambda mail, text: browser_draft(driver, mail, text))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "lead"


def answers_dir(settings: Settings, day: Optional[date] = None) -> Path:
    return Path(settings.report_dir or paths.user("reports")) / (day or date.today()).isoformat() / "leads"


def _keep(settings: Settings, lead: Dict[str, Any], text: str, state: str, why: str) -> Path:
    target = answers_dir(settings) / ("mail-%s-%s.txt" % (
        _slug("%s %s" % (lead.get("company") or lead.get("who"), lead.get("subject"))), lead["id"][-8:]))
    atomic_write_text(target, "LEAD: %s\nFROM: %s\nSUBJECT: %s\nSTATE: %s\nWHY: %s\n\n%s\n" % (
        lead["id"], lead.get("sender") or lead.get("who", ""), lead.get("subject", ""), state, why, text))
    return target


def answer(settings: Settings, profile: Profile, client: Any, transport: Transport, lead: Dict[str, Any],
           dry_run: bool) -> Tuple[str, str]:
    """Answer one lead; returns the (state, why) recorded."""
    from sites_bot import replies

    verdict = mail_rules.classify(lead.get("sender", ""), lead.get("subject", ""))
    text = ""
    mail = None
    # Without a draft, decide() settles only the cases that never need one: assessments,
    # board notifications and automated senders. Everything else comes back "failed" here.
    state, why = decide(lead, verdict.automated, None, settings.leads_auto_reply)
    if state == "failed":
        mail = _mail_for(lead, transport.fetch_body(lead) or lead.get("text", ""))
        application = {"title": lead.get("title") or "", "company": lead.get("company") or mail.sender_name}
        found = (replies.classify(client, mail, application) or {}) if client is not None else {}
        if found.get("kind") == "REJECTION":
            state, why = "skipped", "The mail is a rejection; nothing to answer."
        else:
            draft = replies.draft_reply(client, profile, mail, application, found) if client is not None else None
            state, why = decide(lead, verdict.automated, draft, settings.leads_auto_reply)
            text = str((draft or {}).get("text") or "")
    if dry_run:
        logger.info("[dry-run] %s <- %s: %s", lead.get("sender"), state, why)
        return state, why
    values: Dict[str, Any] = {"via": transport.via}
    if text and mail is not None:
        if state == "answered":
            problem = transport.send(mail, text)
            if problem:
                state, why = "needs_you", "Could not send it (%s); the reply is in Gmail Drafts." % problem
        if state == "needs_you":
            problem = transport.draft(mail, text)
            if problem:
                why = "%s (the draft could not be saved either: %s)" % (why, problem)
        values["answer_file"] = str(_keep(settings, lead, text, state, why))
    store.update(settings, lead["id"], state, why, answer=text, facts=_facts(profile, settings), **values)
    return state, why


def _facts(profile: Profile, settings: Settings) -> str:
    from common.answers import facts_fingerprint

    try:
        return facts_fingerprint(profile, settings)
    except Exception:  # The fingerprint only decides whether a needs_you lead is retried.
        return ""


# ---------------------------------------------------------------------------
# One inbox
# ---------------------------------------------------------------------------


def _empty_counts() -> Dict[str, int]:
    return {"scanned": 0, "new": 0, "answered": 0, "needs_you": 0, "skipped": 0, "failed": 0}


def answer_waiting(settings: Settings, profile: Profile, client: Any, transport: Transport,
                   leads: List[Dict[str, Any]], limit: int, dry_run: bool) -> Dict[str, int]:
    """Record the leads just read, then answer what is waiting (this read's and older open ones)."""
    counts = _empty_counts()
    counts["scanned"] = len(leads)
    if dry_run:
        for lead in leads:
            logger.info("[dry-run] lead %s %s <%s> %r", lead["kind"], lead.get("company"), lead.get("sender"),
                        lead.get("subject"))
        counts["new"] = len(leads)
    else:
        counts["new"] = store.record(settings, [_public(lead) for lead in leads])["new"]
    facts = _facts(profile, settings)
    by_id = {lead["id"]: lead for lead in leads}
    waiting = ([_public(lead) for lead in leads] if dry_run else
               store.open_leads(settings, "mail", states=store.OPEN_STATES + store.PERSON_STATES))
    done = 0
    for row in waiting:
        if done >= limit:
            break
        lead = dict(row)
        lead.update({k: v for k, v in by_id.get(lead["id"], {}).items() if k.startswith("_")})
        if not dry_run and not store.claim(settings, lead["id"], facts):
            continue
        if lead["id"] not in by_id and not lead.get("text") and transport.via == "imap":
            continue
        try:
            state, why = answer(settings, profile, client, transport, lead, dry_run)
        except Exception as exc:  # One bad thread must not stop the others.
            logger.exception("Lead %s could not be answered", lead["id"])
            state, why = "failed", "%s: %s" % (type(exc).__name__, str(exc)[:200])
            if not dry_run:
                store.update(settings, lead["id"], state, why)
        counts[state] = counts.get(state, 0) + 1
        if state in ("answered", "needs_you", "failed"):
            done += 1
    return counts


def run_inbox(settings: Settings, profile: Profile, client: Any, account: str, password: str,
              days: int, limit: int, dry_run: bool) -> Dict[str, int]:
    """One inbox over IMAP (app password)."""
    if not account or not password:
        logger.warning("No app password for %s; set GMAIL_APP_PASSWORD or REPLY_INBOXES=address:password.", account)
        return _empty_counts()
    imap = gmail._connect(account, password)
    if imap is None:
        logger.warning("Gmail sign-in failed for %s; its leads were not read.", account)
        return _empty_counts()
    try:
        leads = read_leads(imap, days)
        return answer_waiting(settings, profile, client, imap_transport(imap, account, password, settings),
                              leads, limit, dry_run)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def run_browser(settings: Settings, profile: Profile, client: Any, days: int, limit: int,
                dry_run: bool) -> Dict[str, int]:
    """The Gmail the bot's browser is signed in to; the first signed-in profile wins."""
    from common import connections

    counts = _empty_counts()
    profiles = gmail_browser.candidate_profiles(settings)
    if not profiles:
        logger.warning("No browser profile exists yet; connect Naukri or Google in the dashboard first.")
        return counts
    tried: List[str] = []
    for name, folder in profiles:
        try:
            driver = connections.create_driver(dataclasses.replace(settings, browser_profile_dir=str(folder)))
        except connections.BrowserProfileLocked:
            tried.append("%s: browser profile in use" % name)
            continue
        except Exception as exc:
            tried.append("%s: %s" % (name, type(exc).__name__))
            continue
        try:
            driver.get(gmail_browser.GMAIL)
            time.sleep(gmail_browser.WAIT_S)
            if not gmail_browser._signed_in(driver):
                tried.append("%s: Gmail not signed in" % name)
                continue
            account = str(driver.execute_script(gmail_browser._ACCOUNT) or "") or "(signed-in %s profile)" % name
            logger.info("Reading Gmail as %s through the %s browser profile", account, name)
            leads = read_browser_leads(driver, days)
            return answer_waiting(settings, profile, client, browser_transport(driver, account, settings, profile),
                                  leads, limit, dry_run)
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    logger.warning("No browser profile is signed in to Gmail (%s). Sign in to Google once in the dashboard's "
                   "Connections page, or set GMAIL_APP_PASSWORD.", "; ".join(tried))
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def first_run_days(settings: Settings, days: int) -> int:
    """LEADS_DAYS once the journal holds mail leads; at least FIRST_RUN_DAYS before that."""
    try:
        seen = any(lead.get("source") == "mail" for lead in store.load(settings).values())
    except ValueError:
        seen = True
    if seen:
        return days
    logger.info("No mail lead in the journal yet: reading the last %d days this once", max(days, FIRST_RUN_DAYS))
    return max(days, FIRST_RUN_DAYS)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m leads.mail", description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, help="how far back to read (default LEADS_DAYS)")
    parser.add_argument("--limit", type=int, help="answers per inbox this run (default LEADS_LIMIT)")
    parser.add_argument("--dry-run", action="store_true", help="list the leads, save and send nothing")
    parser.add_argument("--no-send", action="store_true", help="leave every reply in Gmail Drafts instead of sending")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common import config, llm, profile as profile_module, report
    from common.run import EXIT_CONFIG, EXIT_OK, configure_logging, keep_log
    from sites_bot import browser_agent
    from sites_bot.accounts import account_email
    from sites_bot.replies import inboxes

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env)
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    if args.no_send:
        settings = dataclasses.replace(settings, leads_auto_reply=False)
    keep_log(settings, "leads-mail")
    browser_agent.reset()
    client = llm.build_client(settings)
    days = args.days or first_run_days(settings, settings.leads_days)
    limit = args.limit if args.limit is not None else settings.leads_limit
    total: Dict[str, int] = {}
    with_password = [(address, password) for address, password in inboxes(settings, account_email(settings)) if password]
    for address, password in with_password:
        counts = run_inbox(settings, profile, client, address, password, days, limit, args.dry_run)
        logger.info("Leads in %s (IMAP): %s", address, ", ".join("%s %d" % item for item in counts.items()))
        for key, value in counts.items():
            total[key] = total.get(key, 0) + value
    if not with_password:
        counts = run_browser(settings, profile, client, days, limit, args.dry_run)
        logger.info("Leads in the browser's Gmail: %s", ", ".join("%s %d" % item for item in counts.items()))
        total = counts
    if not args.dry_run:
        report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
