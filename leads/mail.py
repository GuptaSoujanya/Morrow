"""leads:mail - read hiring mail in Gmail (All Mail and Spam) and answer it.

    python3 -m leads.mail [--days N] [--limit N] [--dry-run] [--no-send] [--env PATH] [-v]

What it does, per inbox in REPLY_INBOXES (and the account's own, when GMAIL_APP_PASSWORD is set):

1. lists every mail of the last LEADS_DAYS days in [Gmail]/All Mail and [Gmail]/Spam over IMAP
   (read-only), classifies each with diagnose.mail_rules and records the hiring-positive ones
   as leads in user/inputs/leads.json;
2. for each lead still waiting, reads the body, asks the model for a reply written only from
   the saved facts (sites_bot.replies.draft_reply), and
   - sends it over SMTP when LEADS_AUTO_REPLY is on and the draft has no gaps,
   - otherwise leaves it in Gmail Drafts and marks the lead needs_you,
   - never answers assessments (a test only you can take), automated senders, or job-board
     notifications (the board's own inbox stage answers those on the board);
3. writes every answer to user/reports/<day>/leads/mail-<slug>.txt.

A thread is answered once: the journal keeps its state.
"""

import argparse
import logging
import re
import smtplib
import ssl
import sys
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import paths
from common.models import Profile, Settings
from common.shared_files import atomic_write_text
from diagnose import gmail, mail_rules
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


# ---------------------------------------------------------------------------
# Reading
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


def answer(settings: Settings, profile: Profile, client: Any, imap: Any, account: str, password: str,
           lead: Dict[str, Any], dry_run: bool) -> Tuple[str, str]:
    """Answer one lead; returns the (state, why) recorded."""
    from sites_bot import replies

    verdict = mail_rules.classify(lead.get("sender", ""), lead.get("subject", ""))
    text = ""
    mail = None
    # Without a draft, decide() settles only the cases that never need one: assessments,
    # board notifications and automated senders. Everything else comes back "failed" here.
    state, why = decide(lead, verdict.automated, None, settings.leads_auto_reply)
    if state == "failed":
        body = ""
        if imap is not None and lead.get("_uid") is not None and gmail._select(imap, lead.get("_folder") or gmail.SEARCH_FOLDER):
            body = gmail._fetch_body(imap, lead["_uid"])
        mail = _mail_for(lead, body or lead.get("text", ""))
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
    values: Dict[str, Any] = {}
    if text and mail is not None:
        message = compose(account, mail, text)
        if state == "answered":
            problem = send_message(account, password, message)
            if problem:
                state, why = "failed", problem
        if state == "needs_you":
            problem = save_draft(settings, account, password, message)
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


def run_inbox(settings: Settings, profile: Profile, client: Any, account: str, password: str,
              days: int, limit: int, dry_run: bool) -> Dict[str, int]:
    counts = {"scanned": 0, "new": 0, "answered": 0, "needs_you": 0, "skipped": 0, "failed": 0}
    if not account or not password:
        logger.warning("No app password for %s; set GMAIL_APP_PASSWORD or REPLY_INBOXES=address:password.", account)
        return counts
    imap = gmail._connect(account, password)
    if imap is None:
        logger.warning("Gmail sign-in failed for %s; its leads were not read.", account)
        return counts
    try:
        leads = read_leads(imap, days)
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
            if lead["id"] not in by_id and not lead.get("text"):
                continue
            try:
                state, why = answer(settings, profile, client, imap, account, password, lead, dry_run)
            except Exception as exc:  # One bad thread must not stop the others.
                logger.exception("Lead %s could not be answered", lead["id"])
                state, why = "failed", "%s: %s" % (type(exc).__name__, str(exc)[:200])
                if not dry_run:
                    store.update(settings, lead["id"], state, why)
            counts[state] = counts.get(state, 0) + 1
            if state in ("answered", "needs_you", "failed"):
                done += 1
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
    import dataclasses

    from common import config, llm, profile as profile_module, report
    from common.run import EXIT_CONFIG, EXIT_OK, configure_logging, keep_log
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
    account = account_email(settings)
    client = llm.build_client(settings)
    days = args.days or settings.leads_days
    limit = args.limit if args.limit is not None else settings.leads_limit
    total: Dict[str, int] = {}
    for address, password in inboxes(settings, account):
        counts = run_inbox(settings, profile, client, address, password, days, limit, args.dry_run)
        logger.info("Leads in %s: %s", address, ", ".join("%s %d" % item for item in counts.items()))
        for key, value in counts.items():
            total[key] = total.get(key, 0) + value
    if not total:
        logger.warning("No inbox to read: set GMAIL_APP_PASSWORD or REPLY_INBOXES.")
    if not args.dry_run:
        report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
