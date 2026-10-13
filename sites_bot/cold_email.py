"""Cold emails to recruiters, written in her voice and left as drafts for her to send.

Addresses come only from where a company published them: a posting's text
("share your CV at ..."), a career page the bot or the browser agent read, or
a Naukri job page. Nothing is guessed or looked up elsewhere. Each email is
written from her resume and that posting, checked like the tailored summary
(no claim the resume does not make, no filler words), signed with her real
contact details, and saved as a draft: an .eml file under
data/reports/<date>/emails/, and in Gmail's Drafts folder when GMAIL_APP_PASSWORD
is set. Nothing is ever sent. Every draft is recorded in data/inputs/cold_emails.jsonl
so no address is written to twice.

    python3 -m sites_bot.cold_email [--scan-naukri] [--limit 10] [--dry-run]
"""

import argparse
import imaplib
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from common.models import JobPosting, Profile, Settings

logger = logging.getLogger(__name__)

RECORDS_NAME = "cold_emails.jsonl"
REWRITE_DAYS = 30
MIN_WORDS = 70
MAX_WORDS = 190
CONTEXT_CHARS = 140
GMAIL_IMAP = "imap.gmail.com"
GMAIL_DRAFT_FOLDERS = ('"[Gmail]/Drafts"', '"[Google Mail]/Drafts"')

_EMAIL = re.compile(r"(?<![\w.+-])([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")
_NOT_A_PERSON = re.compile(
    r"^(?:no-?reply|donotreply|do-not-reply|mailer-daemon|postmaster|abuse|privacy|security|legal|unsubscribe"
    r"|support|help|helpdesk|feedback|press|media|sales|billing|webmaster|grievance|compliance|dpo)\b",
    re.I,
)
_NOT_MAIL = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|js|css|ico)$", re.I)
_PLACEHOLDER_DOMAINS = ("example.com", "example.org", "domain.com", "email.com", "yourcompany.com", "naukri.com",
                        "sentry.io", "wixpress.com", "w3.org", "schema.org", "company.com")
_HIRING_WORDS = re.compile(r"resume|\bcv\b|apply|application|send|share|mail|reach|contact|\bhr\b|hiring|recruit|career|interested", re.I)
_HIRING_MAILBOX = re.compile(r"hr|career|job|recruit|talent|hiring|people|resume|cv|apply", re.I)
_PLACEHOLDERS = re.compile(r"\[[^\]]+\]|\{[^}]+\}|<[^>]+>|\bdear hiring manager\b", re.I)


def find_addresses(text: str) -> List[str]:
    """Addresses a company printed for applications, in the order they appear."""
    found = []  # type: List[str]
    for match in _EMAIL.finditer(text or ""):
        address = match.group(1).strip(".").lower()
        local, _, domain = address.partition("@")
        if _NOT_MAIL.search(address) or domain in _PLACEHOLDER_DOMAINS or _NOT_A_PERSON.match(local):
            continue
        around = text[max(0, match.start() - CONTEXT_CHARS): match.end() + CONTEXT_CHARS]
        if not (_HIRING_WORDS.search(around) or _HIRING_MAILBOX.search(local)):
            continue
        if address not in found:
            found.append(address)
    return found


@dataclass
class Lead:
    email: str
    company: str
    title: str
    job_url: str
    source: str
    posting: str = ""

    def job(self) -> JobPosting:
        return JobPosting(job_id=self.job_url or self.email, url=self.job_url, title=self.title,
                          company=self.company, description=self.posting)


# ---------------------------------------------------------------------------
# Where addresses come from
# ---------------------------------------------------------------------------


def _posting_header(text: str) -> Dict[str, str]:
    header = {}
    for line in text.splitlines()[:12]:
        key, sep, value = line.partition(": ")
        if sep and key in ("Title", "Company", "URL"):
            header[key] = value.strip()
    return header


def leads_from_files(settings: Settings) -> List[Lead]:
    """Postings saved with tailored resumes, browser-agent reports, and data/inputs/company_sites.md."""
    leads = []  # type: List[Lead]
    tailored = Path(settings.resume_out_dir or "data/resume/out") / "tailored"
    for posting in sorted(tailored.glob("*/posting.txt")):
        text = posting.read_text(encoding="utf-8", errors="replace")
        header = _posting_header(text)
        for address in find_addresses(text):
            leads.append(Lead(address, header.get("Company", ""), header.get("Title", ""), header.get("URL", ""),
                              "posting saved in %s" % posting.parent.name, text))
    for record_path in sorted(Path(settings.report_dir or "data/reports").glob("*/agent/*/report.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        report = record.get("report") or {}
        text = " ".join(str(part) for part in (report.get("why"), report.get("notes"), record.get("detail")) if part)
        job = record.get("job") or {}
        for address in find_addresses(text):
            leads.append(Lead(address, job.get("company", ""), job.get("title", ""), job.get("naukri", ""),
                              "read by the browser agent on %s" % record.get("site", "the career page"), text))
    from .external import pending_company_sites

    for entry in pending_company_sites(settings):
        text = " ".join(entry.get(key, "") for key in ("why", "left for you"))
        for address in find_addresses(text):
            leads.append(Lead(address, entry.get("company", ""), entry.get("title", ""), entry.get("naukri", ""),
                              "company_sites.md", text))
    return leads


_PAGE_SCRIPT = """
const mails = [...document.querySelectorAll('a[href^="mailto:"]')].map(a => a.getAttribute('href').slice(7).split('?')[0]);
return (document.body ? document.body.innerText : '') + '\\n' + mails.join('\\n');
"""


def leads_from_naukri(driver: Any, settings: Settings, ledger: Any, days: int, limit: int) -> List[Lead]:
    """Open recent well-scored Naukri job pages and keep any address their text or mailto links show."""
    from common.browser import safe_get

    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = ledger._connection.execute(
        """SELECT url, title, company FROM jobs_seen
           WHERE job_id NOT LIKE '%:%' AND last_seen >= ? AND score >= ?
           ORDER BY score DESC LIMIT ?""",
        (since, settings.min_score, limit),
    ).fetchall()
    leads = []  # type: List[Lead]
    for url, title, company in rows:
        if not url or not safe_get(driver, url):
            continue
        time.sleep(2.0)
        try:
            text = driver.execute_script(_PAGE_SCRIPT) or ""
        except Exception as exc:
            logger.info("Could not read %s: %s", url, str(exc).split("\n")[0])
            continue
        for address in find_addresses(text):
            leads.append(Lead(address, company or "", title or "", url, "Naukri job page", text[:6000]))
    return leads


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def records_path(settings: Settings) -> Path:
    return Path(settings.data_dir or "data/inputs") / RECORDS_NAME


def read_records(settings: Settings) -> List[Dict[str, Any]]:
    path = records_path(settings)
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def already_written(records: Iterable[Dict[str, Any]], email: str, now: Optional[datetime] = None) -> bool:
    """Whether a draft to this address was made in the last REWRITE_DAYS days."""
    cutoff = (now or datetime.now()) - timedelta(days=REWRITE_DAYS)
    for record in records:
        if record.get("email", "").lower() != email.lower():
            continue
        try:
            if datetime.fromisoformat(record.get("drafted_at", "")) >= cutoff:
                return True
        except ValueError:
            return True
    return False


def _record(settings: Settings, lead: Lead, subject: str, eml: Path, gmail: bool, now: datetime) -> None:
    path = records_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(asdict(lead), subject=subject, eml=str(eml), gmail_draft=gmail,
                 drafted_at=now.isoformat(timespec="seconds"))
    entry.pop("posting", None)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Writing the email
# ---------------------------------------------------------------------------

_PROMPT = """Write a short cold email from a job seeker to a company's recruiter, in her own voice.

Her resume (the only source of facts about her):
%s

The role: %s at %s
The posting, as the company published it (may be empty):
%s
%s
Rules:
- First person, plain and direct, %d to %d words for the body. No greeting name you do not know:
  start with "Hi," or "Hello %s team,".
- Say which role she is writing about, two or three concrete things from her resume that fit this
  posting, and ask whether they would consider her application. Mention that her resume is attached.
- Use only facts from the resume and the posting. No numbers, employers, tools or titles they do not name.
- No buzzwords (passionate, results-driven, synergy, leverage, cutting-edge, delve, thrilled, excited to
  share), no em or en dashes, no exclamation marks, no emojis, no bullet lists, no placeholders.
- Do not sign it; her signature is added after your text.

Reply with JSON: {"can_write": true, "subject": "...", "body": "..."}. Set can_write to false when the
posting gives nothing to write about."""
_SCHEMA = '{"can_write": true, "subject": "", "body": ""}'


def write_email(client: Any, base: Any, lead: Lead) -> Optional[Tuple[str, str]]:
    """(subject, body) from her resume and the posting; None when it cannot be made clean in two tries."""
    from common.resume import _lint, _terms, ungrounded_terms

    if client is None or not client.available():
        return None
    known = frozenset(_terms(" ".join((lead.title, lead.company, lead.posting))))
    problems = []  # type: List[str]
    for _ in range(2):
        feedback = "\nYour last draft was refused; fix these: %s.\n" % "; ".join(problems) if problems else ""
        prompt = _PROMPT % (base.plain_text[:8000], lead.title or "a role", lead.company or "the company",
                            (lead.posting or "")[:3000], feedback, MIN_WORDS, MAX_WORDS - 30,
                            lead.company or "hiring")
        reply = client.complete_json(prompt, _SCHEMA)
        if not reply or reply.get("can_write") is False:
            return None
        subject = " ".join(str(reply.get("subject", "")).split())
        body = str(reply.get("body", "")).strip()
        problems = _lint(body, "the email") + _lint(subject, "the subject")
        problems += ["it names %s, which neither the resume nor the posting does" % term
                     for term in ungrounded_terms(body + " " + subject, base, known)]
        words = len(body.split())
        if not MIN_WORDS <= words <= MAX_WORDS:
            problems.append("the body has %d words, outside %d to %d" % (words, MIN_WORDS, MAX_WORDS))
        if not subject or len(subject) > 90:
            problems.append("the subject is missing or longer than 90 characters")
        if _PLACEHOLDERS.search(body + subject):
            problems.append("it has a placeholder or a made-up greeting")
        if not problems:
            return subject, body
    logger.info("No cold email for %s: %s", lead.email, "; ".join(problems))
    return None


def signature(profile: Profile) -> str:
    extra = profile.extra_facts or {}
    lines = [profile.full_name or ""]
    if profile.phone:
        lines.append(profile.phone)
    for key in ("linkedin_url", "portfolio_url", "github_url"):
        if extra.get(key):
            lines.append(str(extra[key]))
    return "\n".join(line for line in lines if line)


def build_message(sender: str, lead: Lead, subject: str, body: str, profile: Profile,
                  attachment: Optional[Path]) -> EmailMessage:
    message = EmailMessage()
    message["From"] = "%s <%s>" % (profile.full_name, sender) if profile.full_name else sender
    message["To"] = lead.email
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    # Apple Mail and Outlook open a message with this header as a draft to edit and send.
    message["X-Unsent"] = "1"
    message.set_content("%s\n\n%s\n" % (body.strip(), signature(profile)))
    if attachment is not None and attachment.is_file():
        message.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf",
                               filename=attachment.name)
    return message


def save_eml(message: EmailMessage, folder: Path, lead: Lead) -> Path:
    from common.resume import _folder_name

    folder.mkdir(parents=True, exist_ok=True)
    name = _folder_name("%s - %s" % (lead.company or "Company", lead.title or "Role")) or "email"
    path = folder / ("%s (%s).eml" % (name, lead.email))
    path.write_bytes(bytes(message))
    return path


def gmail_draft(message: EmailMessage, account: str, app_password: str) -> str:
    """Put the message in Gmail's Drafts folder; '' when done, else what went wrong."""
    try:
        imap = imaplib.IMAP4_SSL(GMAIL_IMAP)
    except OSError as exc:
        return "could not reach Gmail: %s" % exc
    try:
        imap.login(account, app_password)
        for folder in GMAIL_DRAFT_FOLDERS:
            status, _ = imap.append(folder, "\\Draft", imaplib.Time2Internaldate(time.time()), bytes(message))
            if status == "OK":
                return ""
        return "Gmail has no Drafts folder under the usual names"
    except imaplib.IMAP4.error as exc:
        return "Gmail refused the app password or the draft: %s" % exc
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def attachment_for(settings: Settings, lead: Lead) -> Optional[Path]:
    """The resume tailored for that job when there is one, else the base resume."""
    from common import resume as resume_module

    folder = resume_module.tailored_dir(settings, lead.job())
    tailored = sorted(folder.glob("*.pdf")) if folder.is_dir() else []
    if tailored:
        return tailored[0]
    try:
        return resume_module.build_base_pdf(settings)
    except resume_module.ResumeError:
        return None


def own_addresses(settings: Settings, profile: Profile) -> set:
    return {value.lower() for value in (settings.email, settings.google_email, settings.company_site_email,
                                        settings.cold_email_from, profile.email) if value}


def unique_leads(settings: Settings, profile: Profile, leads: List[Lead]) -> List[Lead]:
    """One lead per address, never her own; the posting saved for that job is used when there is one."""
    from common.resume import tailored_dir

    own = own_addresses(settings, profile)
    kept = {}  # type: Dict[str, Lead]
    for lead in leads:
        if lead.email in own:
            continue
        saved = tailored_dir(settings, lead.job()) / "posting.txt" if lead.company or lead.title else None
        if saved is not None and saved.is_file():
            lead.posting = saved.read_text(encoding="utf-8", errors="replace")
        current = kept.get(lead.email)
        if current is None or (len(lead.posting) > len(current.posting) and lead.title):
            kept[lead.email] = lead
    return list(kept.values())


def draft_all(settings: Settings, profile: Profile, client: Any, leads: List[Lead], limit: int,
              dry_run: bool, now: Optional[datetime] = None) -> Dict[str, int]:
    """Write a draft for each new address, up to `limit`; counts of what happened."""
    from common import resume as resume_module

    now = now or datetime.now()
    counts = {"drafted": 0, "in gmail": 0, "already written": 0, "not written": 0}
    records = read_records(settings)
    sender = settings.cold_email_from or settings.google_email or settings.email
    base = resume_module.load_base(settings.resume_path)
    folder = Path(settings.report_dir or "data/reports") / now.strftime("%Y-%m-%d") / "emails"
    for lead in unique_leads(settings, profile, leads):
        if counts["drafted"] >= limit:
            break
        if already_written(records, lead.email, now):
            counts["already written"] += 1
            continue
        written = write_email(client, base, lead)
        if written is None:
            counts["not written"] += 1
            continue
        subject, body = written
        if dry_run:
            logger.info("[dry run] to %s (%s): %s\n%s", lead.email, lead.source, subject, body)
            counts["drafted"] += 1
            continue
        message = build_message(sender, lead, subject, body, profile, attachment_for(settings, lead))
        eml = save_eml(message, folder, lead)
        problem = gmail_draft(message, sender, settings.gmail_app_password) if settings.gmail_app_password else "no app password"
        if not problem:
            counts["in gmail"] += 1
        elif settings.gmail_app_password:
            logger.warning("Gmail draft not made for %s: %s (the .eml is saved)", lead.email, problem)
        _record(settings, lead, subject, eml, not problem, now)
        counts["drafted"] += 1
        logger.info("Draft to %s about %s at %s: %s", lead.email, lead.title or "a role", lead.company or "?", eml)
    return counts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m sites_bot.cold_email",
        description="Write cold emails to recruiters whose address a company published; leave them as drafts.",
    )
    parser.add_argument("--scan-naukri", action="store_true",
                        help="also open recent well-scored Naukri job pages and read any address they show")
    parser.add_argument("--days", type=int, default=7, help="how far back --scan-naukri looks (default 7)")
    parser.add_argument("--pages", type=int, default=30, help="most Naukri pages --scan-naukri opens (default 30)")
    parser.add_argument("--limit", type=int, help="drafts this run (default COLD_EMAIL_LIMIT)")
    parser.add_argument("--to", help="write one draft to this address (use with --company, --title, --url)")
    parser.add_argument("--company", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--url", default="", help="the posting the email is about")
    parser.add_argument("--dry-run", action="store_true", help="print the emails, save nothing")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common import config, llm, profile as profile_module, report
    from common.run import EXIT_CONFIG, EXIT_OK, configure_logging, keep_log

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env)
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    keep_log(settings, "cold-email")
    limit = args.limit if args.limit is not None else settings.cold_email_limit
    if args.to:
        leads = [Lead(args.to.lower(), args.company, args.title, args.url, "given by hand")]
    else:
        leads = leads_from_files(settings)
        if args.scan_naukri:
            from common import browser, ledger as ledger_module

            ledger = ledger_module.open_ledger(settings)
            driver = browser.create_driver(settings)
            try:
                leads += leads_from_naukri(driver, settings, ledger, args.days, args.pages)
            finally:
                driver.quit()
                ledger.close()
    found = sorted({lead.email for lead in unique_leads(settings, profile, leads)})
    logger.info("Addresses found: %d (%s)", len(found), ", ".join(found) or "none")
    counts = draft_all(settings, profile, llm.build_client(settings), leads, limit, args.dry_run)
    logger.info("Cold emails: %s", ", ".join("%s %d" % item for item in counts.items()))
    if not settings.gmail_app_password and counts["drafted"] and not args.dry_run:
        logger.info("Drafts are .eml files only; set GMAIL_APP_PASSWORD to also get them in Gmail's Drafts.")
    if not args.dry_run:
        report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
