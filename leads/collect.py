"""Turn what the readers see into leads for the journal.

Two sources, two shapes:

* a job board's own inbox, as `diagnose.pages.summarise` parses it: messages with
  {"date", "who", "about", "text", "action", "rejection"};
* Gmail, as `diagnose.gmail.make_record` describes one mail: {"date", "from", "subject",
  "platform", "kind", "folder", "bulk", "noise", ...}.

Only what asks something of the candidate becomes a lead. Rejections, job alerts, promo
and bulk mail do not.
"""

import re
from typing import Any, Dict, Iterable, List, Tuple

from diagnose import mail_rules
from leads import store

#: `action` names from diagnose.pages.ACTION_WORDS (and Naukri's apply-invitation) -> lead kind.
ACTION_KINDS = {
    "questionnaire": "QUESTION",
    "assessment": "ASSESSMENT",
    "interview": "INTERVIEW",
    "reply": "REPLY",
    "apply-invitation": "RECRUITER_OUTREACH",
}

#: Where each board shows its threads; the lead's url when the page gives no thread link.
INBOX_URLS = {
    "naukri": "https://www.naukri.com/mnjuser/inbox",
    "hirist": "https://www.hirist.tech/chats",
    "instahyre": "https://www.instahyre.com/candidate/inbox/",
    "cutshort": "https://cutshort.io/profile/candidate-conversations?i=all",
    "wellfound": "https://wellfound.com/jobs/messages",
}

_ABOUT_SPLIT = re.compile(r"\s+(?:at|@|-|–|—|,)\s+")


def _company_title(message: Dict[str, Any]) -> Tuple[str, str]:
    """'Software Engineer II at GreyOrange' -> ('GreyOrange', 'Software Engineer II'); best effort."""
    about = " ".join(str(message.get("about") or "").split())
    if not about:
        return "", ""
    match = re.match(r"^(?P<title>.+?)\s+(?:at|@)\s+(?P<company>.+)$", about, re.I)
    if match:
        return match.group("company").strip(), match.group("title").strip()
    parts = _ABOUT_SPLIT.split(about, maxsplit=1)
    if len(parts) == 2:
        return parts[1].strip(), parts[0].strip()
    return "", about


def from_board_summary(site: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Leads in one board's parsed pages: every message asking for something, no rejections."""
    leads: List[Dict[str, Any]] = []
    seen = set()
    for message in (summary or {}).get("messages") or []:
        if message.get("rejection"):
            continue
        action = str(message.get("action") or "")
        text = str(message.get("text") or "")
        who = str(message.get("who") or "")
        if not action and not who:
            continue
        kind = ACTION_KINDS.get(action, "REPLY")
        company, title = _company_title(message)
        lead = store.make_lead("board", site, kind, company=company, title=title, who=who,
                               text=text, url=str(message.get("url") or INBOX_URLS.get(site, "")),
                               received_at=str(message.get("date") or ""),
                               key=store.thread_key(who, company, title, "", text if not (who or company or title) else ""))
        if lead["id"] in seen:
            continue
        seen.add(lead["id"])
        leads.append(lead)
    return leads


def _mail_company(record: Dict[str, Any]) -> str:
    sender = str(record.get("from") or "")
    name = re.sub(r"<.*?>", "", sender).strip().strip('"')
    domain = mail_rules.sender_domain(sender)
    platform = record.get("platform") or mail_rules.platform_of(sender)
    if platform in ("employer", "ats") and domain:
        return domain.split(".")[0].capitalize() if domain.count(".") <= 1 else domain.split(".")[-2].capitalize()
    return name


def from_mail_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Leads among Gmail records: the hiring-positive, non-bulk, non-noise mails, one per thread."""
    leads: List[Dict[str, Any]] = []
    seen = set()
    for record in records or []:
        kind = str(record.get("kind") or "").upper()
        if kind not in mail_rules.POSITIVE or record.get("bulk") or record.get("noise"):
            continue
        sender = str(record.get("from") or "")
        subject = str(record.get("subject") or "")
        who = re.sub(r"<.*?>", "", sender).strip().strip('"') or sender
        lead = store.make_lead("mail", record.get("platform") or mail_rules.platform_of(sender), kind,
                               company=_mail_company(record), who=who, subject=subject,
                               text=str(record.get("summary") or ""), received_at=str(record.get("date") or ""),
                               key=store.thread_key(who=mail_rules.sender_domain(sender) or who, subject=subject))
        lead["sender"] = sender[:120]
        lead["folder"] = str(record.get("folder") or "")
        if lead["id"] in seen:
            continue
        seen.add(lead["id"])
        leads.append(lead)
    return leads
