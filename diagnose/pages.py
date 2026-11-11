"""Pull the funnel numbers and the unanswered messages out of a board page's visible text.

Pure functions over innerText, so each parser is testable from a saved
evidence file. Every parser returns the same shape:

    {"applications": [{"title", "date", "status", "views", "applicants", "recruiter_actions"}],
     "status_counts": {...}, "messages": [{"date", "who", "about", "text", "action"}],
     "facts": {...}}

`action` names what the message asks the candidate to do (questionnaire,
assessment, interview, reply) and is empty when it asks nothing.
"""

import re
from collections import Counter
from typing import Any, Dict, List

ACTION_WORDS = (
    ("questionnaire", re.compile(r"questionnaire|fill (in|out) (the|this) form", re.I)),
    ("assessment", re.compile(r"assessment|assignment|coding (test|challenge)|take[- ]home|hackerrank|codility", re.I)),
    ("interview", re.compile(r"interview|schedule (a )?(call|meeting)|book a slot|calendly", re.I)),
    ("reply", re.compile(r"please (share|send|confirm|reply|revert)|could you (share|send|confirm)|let (me|us) know", re.I)),
)
REJECTION_WORDS = re.compile(r"not (fulfilling|meeting|suitable|shortlisted|selected|accepted)|eligibility criteria|regret|unfortunately", re.I)


def _lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _empty() -> Dict[str, Any]:
    return {"applications": [], "status_counts": {}, "messages": [], "facts": {}}


def _action(text: str) -> str:
    for name, pattern in ACTION_WORDS:
        if pattern.search(text):
            return name
    return ""


def hirist_applied(text: str) -> Dict[str, Any]:
    out = _empty()
    lines = _lines(text)
    date_re = re.compile(r"^\d{2}-\d{2}-\d{4}$")
    for index, line in enumerate(lines):
        if not date_re.match(line) or index == 0 or index + 4 >= len(lines):
            continue
        views, applicants, actions, status = lines[index + 1:index + 5]
        if not (views.isdigit() and applicants.isdigit() and actions.isdigit()):
            continue
        out["applications"].append({
            "title": lines[index - 1], "date": line, "views": int(views), "applicants": int(applicants),
            "recruiter_actions": int(actions), "status": status,
        })
    out["status_counts"] = dict(Counter(item["status"] for item in out["applications"]))
    if out["applications"]:
        applicants = sorted(item["applicants"] for item in out["applications"])
        out["facts"] = {
            "applied_listed": len(out["applications"]),
            "median_applicants_per_job": applicants[len(applicants) // 2],
            "jobs_with_zero_recruiter_actions": sum(1 for item in out["applications"] if item["recruiter_actions"] == 0),
            "viewed_or_better": sum(1 for item in out["applications"] if item["status"] not in ("Applied/Sent",)),
        }
    return out


def hirist_chats(text: str) -> Dict[str, Any]:
    out = _empty()
    for line in _lines(text):
        match = re.match(r"^([A-Z][\w .]{1,40}): (.{20,})$", line)
        if match and "iBot" not in match.group(1) and not match.group(2).startswith("http"):
            out["messages"].append({"date": "", "who": match.group(1), "about": "", "text": match.group(2)[:400],
                                    "action": _action(match.group(2)),
                                    "rejection": bool(REJECTION_WORDS.search(match.group(2)))})
    return out


def hirist_recruiter_view(text: str) -> Dict[str, Any]:
    out = _empty()
    lines = _lines(text)
    for label, key in (("Experience", "experience"), ("Notice Period", "notice_period"), ("Location", "location"),
                       ("Preferred Location", "preferred_locations"), ("Annual Current Salary", "current_ctc"),
                       ("Expected Annual Salary", "expected_ctc")):
        if label in lines:
            index = lines.index(label)
            if index + 1 < len(lines):
                out["facts"][key] = lines[index + 1]
    return out


def instahyre_activity(text: str) -> Dict[str, Any]:
    out = _empty()
    for label in ("Viewed", "Contacted", "Not Shortlisted", "Shortlisted", "Interested"):
        match = re.search(r"(?<!Not )\b%s \((\d+)\)" % re.escape(label), text)
        if match:
            out["status_counts"][label] = int(match.group(1))
    for match in re.finditer(r"^(.+?) from (.+?) viewed your resume\n(.+?)\n(?:for (.+?)\n)?", text, re.M):
        out["applications"].append({"title": match.group(4) or "", "date": match.group(3), "status": "Viewed",
                                    "views": 1, "applicants": 0, "recruiter_actions": 1, "who": "%s, %s" % (match.group(1), match.group(2))})
    out["facts"]["recruiters_viewed"] = len(out["applications"])
    return out


def instahyre_inbox(text: str) -> Dict[str, Any]:
    out = _empty()
    lines = _lines(text)
    month = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}$")
    for index, line in enumerate(lines):
        if month.match(line) and index + 3 < len(lines) and ":" in lines[index + 3]:
            snippet = lines[index + 3].split(":", 1)[1].strip()
            out["messages"].append({"date": line, "who": lines[index + 1], "about": lines[index + 2], "text": snippet[:400],
                                    "action": _action(snippet) or _action(text), "rejection": bool(REJECTION_WORDS.search(snippet))})
    unread = re.search(r"Unread \((\d+)\)", text)
    if unread:
        out["facts"]["unread"] = int(unread.group(1))
    return out


def cutshort_dashboard(text: str) -> Dict[str, Any]:
    out = _empty()
    for label in ("Conversations with companies", "Companies interested in you", "Applications pending",
                  "Applications shortlisted", "Applications rejected"):
        match = re.search(r"(\d+)\s*\n\s*%s" % re.escape(label), text)
        if match:
            out["status_counts"][label] = int(match.group(1))
    match = re.search(r"Employer actions on your (\d+) applications", text)
    if match:
        out["facts"]["applications"] = int(match.group(1))
    match = re.search(r"([\d.]+) years fulltime", text)
    if match:
        out["facts"]["experience_shown"] = match.group(1) + " years"
    return out


def cutshort_conversations(text: str) -> Dict[str, Any]:
    """The conversations list: a company line, 'For job TITLE', when, then the preview ('[Questionnaire]' or words)."""
    out = _empty()
    lines = _lines(text)
    for index, line in enumerate(lines):
        match = re.match(r"^For job\s+(.+)$", line)
        if not match or index == 0:
            continue
        company = lines[index - 1]
        if company == "Agency job" and index >= 2:
            company = lines[index - 2]
        when = lines[index + 1] if index + 1 < len(lines) else ""
        preview = lines[index + 2] if index + 2 < len(lines) else ""
        if re.match(r"^For job\s", preview) or preview in ("Agency job",):
            preview = ""
        title = match.group(1).strip()
        questionnaire = "[questionnaire]" in preview.casefold()
        snippet = ("Pending questionnaire for %s" % title) if questionnaire else preview[:400]
        out["messages"].append({"date": when, "who": company, "about": "%s at %s" % (title, company), "text": snippet,
                                "action": "questionnaire" if questionnaire else _action(preview),
                                "rejection": bool(REJECTION_WORDS.search(preview))})
    return out


def wellfound_applications(text: str) -> Dict[str, Any]:
    out = _empty()
    lines = _lines(text)
    statuses = ("Pending", "Not Accepted", "Status Updates Offsite", "Interviewing", "Archived", "Accepted", "Reviewed")
    navigation = ("Ongoing", "Archived", "Applications", "Applied", "Messages", "Jobs", "Home", "Profile")
    for index, line in enumerate(lines):
        if line in statuses and index >= 2 and lines[index - 1] not in navigation:
            out["applications"].append({"title": lines[index - 1], "company": lines[index - 2], "status": line,
                                        "date": lines[index + 1] if index + 1 < len(lines) else "",
                                        "views": 0, "applicants": 0, "recruiter_actions": 0 if line == "Pending" else 1})
    out["status_counts"] = dict(Counter(item["status"] for item in out["applications"]))
    return out


def wellfound_messages(text: str) -> Dict[str, Any]:
    out = _empty()
    lines = _lines(text)
    for index, line in enumerate(lines):
        if re.search(r"\b(Hi|Hello|Dear|Thank)\b", line) and len(line) > 60 and index >= 2:
            who = lines[index - 1]
            out["messages"].append({"date": re.sub(r"^.*?([A-Z]{3}\s?\d{1,2})$", r"\1", who), "who": who,
                                    "about": lines[index - 2], "text": line[:400], "action": _action(line),
                                    "rejection": bool(REJECTION_WORDS.search(line))})
    return out


def naukri_homepage(text: str) -> Dict[str, Any]:
    out = _empty()
    for label, key in (("Search appearances", "search_appearances"), ("Recruiter actions", "recruiter_actions")):
        match = re.search(r"%s\s*\n\s*(\d[\d,]*)" % label, text) or re.search(r"(\d[\d,]*)\s*\n\s*%s" % label, text)
        if match:
            out["facts"][key] = int(match.group(1).replace(",", ""))
    if "search_appearances" in out["facts"]:
        out["status_counts"]["Search appearances"] = out["facts"]["search_appearances"]
    if "recruiter_actions" in out["facts"]:
        out["status_counts"]["Recruiter actions"] = out["facts"]["recruiter_actions"]
    return out


def naukri_profile(text: str) -> Dict[str, Any]:
    out = _empty()
    lines = _lines(text)
    for index, line in enumerate(lines):
        if line.startswith("Resume headline") and index + 1 < len(lines) and len(lines[index + 1]) > 20:
            out["facts"]["headline"] = lines[index + 1][:200]
        elif line.startswith("Key skills") and index + 1 < len(lines):
            out["facts"]["key_skills_text"] = lines[index + 1][:300]
        elif re.match(r"^\d+ Years? \d+ Months?$", line) or re.match(r"^\d+ Years?$", line):
            out["facts"]["experience"] = line
        elif "notice period" in line.lower():
            out["facts"]["notice_period"] = line
        elif line.startswith("Uploaded on"):
            out["facts"]["resume_uploaded"] = line.replace("Uploaded on", "").strip()
        elif re.match(r"^Profile last updated", line):
            out["facts"]["profile_updated"] = line.split("-", 1)[-1].strip()
    return out


def naukri_performance(text: str) -> Dict[str, Any]:
    out = _empty()
    for label, key in (("Search appearances", "search_appearances"), ("Recruiter actions", "recruiter_actions")):
        match = re.search(r"%s\s*\n\s*(\d[\d,]*)" % label, text) or re.search(r"(\d[\d,]*)\s*\n\s*%s" % label, text)
        if match:
            out["facts"][key] = int(match.group(1).replace(",", ""))
    compact = re.search(r"(\d[\d,]*)Search appearances(\d[\d,]*)Recruiter actions", text)
    if compact:
        out["facts"]["search_appearances"] = int(compact.group(1).replace(",", ""))
        out["facts"]["recruiter_actions"] = int(compact.group(2).replace(",", ""))
    week = re.search(r"(\d+) Search appearances in last\s*\n?\s*7 Days", text)
    if week:
        out["facts"]["search_appearances_7_days"] = int(week.group(1))
    for match in re.finditer(r"(NVite sent|Viewed|Downloaded|Contacted|Saved|Shortlisted|Mail sent)\((\d+)\)", text):
        out["status_counts"]["Recruiter action: %s" % match.group(1)] = int(match.group(2))
    for label in ("viewed your profile", "downloaded your resume", "contacted you", "shortlisted", "saved your profile",
                  "sent you a mail", "viewed your contact"):
        count = len(re.findall(re.escape(label), text, re.I))
        if count:
            out["status_counts"][label] = count
    for match in re.finditer(r"^(.{3,80}?)\n(viewed your profile|downloaded your resume|contacted you|shortlisted you|saved your profile)",
                             text, re.I | re.M):
        out["messages"].append({"date": "", "who": match.group(1).strip(), "about": match.group(2).lower(),
                                "text": "%s %s" % (match.group(1).strip(), match.group(2).lower()), "action": "", "rejection": False})
    return out


def naukri_history(text: str) -> Dict[str, Any]:
    out = _empty()
    for label in ("Applied", "Viewed by recruiter", "Resume downloaded", "Shortlisted", "Contacted", "Awaiting recruiter action",
                  "Not viewed", "Rejected", "Application sent", "Application viewed"):
        count = len(re.findall(r"\b%s\b" % re.escape(label), text, re.I))
        if count:
            out["status_counts"][label] = count
    for pattern, key in ((r"(\d+)Total\s*\n?\s*applies", "total_applies"), (r"applies(\d+)Application\s*\n?\s*updates", "application_updates"),
                         (r"Recruiter Actions\s*\n?\s*\((\d+)\)", "recruiter_actions_on_applies"),
                         (r"Applies on Naukri\s*\n?\s*\((\d+)\)", "applies_on_naukri"),
                         (r"Applies on External Site\s*\n?\s*\((\d+)\)", "applies_on_external_site")):
        match = re.search(pattern, text)
        if match:
            out["facts"][key] = int(match.group(1))
    return out


def naukri_inbox(text: str) -> Dict[str, Any]:
    out = _empty()
    match = re.search(r"All \((\d+)\)", text)
    if match:
        out["facts"]["nvites"] = int(match.group(1))
        out["status_counts"]["NVites (invitations to apply)"] = int(match.group(1))
    lines = _lines(text)
    years = re.compile(r"^\d+ ?- ?\d+ Years")
    for index, line in enumerate(lines):
        if years.match(line) and index >= 2:
            title, city = lines[index - 2], lines[index - 1]
            if len(title) < 80 and not title.startswith(("Become", "Access", "Naukri", "Top rated", "Trusted", "Posted by", "Hiring for")):
                out["messages"].append({"date": "", "who": "Naukri NVite", "about": "%s, %s" % (title, city),
                                        "text": "A recruiter invited you to apply: %s (%s, %s)" % (title, city, line),
                                        "action": "apply-invitation", "rejection": False})
    return out


PARSERS = (
    ("naukri", re.compile(r"naukri\.com/mnjuser/homepage"), naukri_homepage),
    ("naukri", re.compile(r"naukri\.com/mnjuser/profile"), naukri_profile),
    ("naukri", re.compile(r"naukri\.com/mnjuser/performance"), naukri_performance),
    ("naukri", re.compile(r"naukri\.com/myapply/historypage"), naukri_history),
    ("naukri", re.compile(r"naukri\.com/mnjuser/inbox"), naukri_inbox),
    ("hirist", re.compile(r"hirist\.tech/applied-jobs"), hirist_applied),
    ("hirist", re.compile(r"hirist\.tech/chats"), hirist_chats),
    ("hirist", re.compile(r"hirist\.tech/recruiterview"), hirist_recruiter_view),
    ("instahyre", re.compile(r"instahyre\.com/candidate/activity"), instahyre_activity),
    ("instahyre", re.compile(r"instahyre\.com/candidate/inbox"), instahyre_inbox),
    ("cutshort", re.compile(r"cutshort\.io/profile/candidate-dashboard"), cutshort_dashboard),
    ("cutshort", re.compile(r"cutshort\.io/profile/candidate-conversations"), cutshort_conversations),
    ("wellfound", re.compile(r"wellfound\.com/jobs/applications"), wellfound_applications),
    ("wellfound", re.compile(r"wellfound\.com/jobs/messages"), wellfound_messages),
)


def parse(site: str, url: str, text: str) -> Dict[str, Any]:
    for name, pattern, parser in PARSERS:
        if name == site and pattern.search(url):
            return parser(text)
    return _empty()


def summarise(site: str, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge every parsed page of one site into applications, statuses, messages and facts."""
    merged = _empty()
    seen_titles = set()
    seen_messages = set()
    for page in pages:
        parsed = page.get("parsed") or {}
        for item in parsed.get("applications", []):
            key = (item.get("title"), item.get("date"))
            if key not in seen_titles:
                seen_titles.add(key)
                merged["applications"].append(item)
        for message in parsed.get("messages", []):
            key = (message.get("who"), message.get("text", "")[:80])
            if key not in seen_messages:
                seen_messages.add(key)
                merged["messages"].append(message)
        for status, count in parsed.get("status_counts", {}).items():
            merged["status_counts"][status] = max(merged["status_counts"].get(status, 0), count)
        merged["facts"].update(parsed.get("facts", {}))
    merged["facts"]["applications_listed"] = len(merged["applications"])
    merged["facts"]["messages_needing_action"] = sum(1 for m in merged["messages"] if m.get("action"))
    merged["facts"]["rejections_in_messages"] = sum(1 for m in merged["messages"] if m.get("rejection"))
    if site == "hirist" and merged["applications"]:
        merged["facts"]["applied_listed"] = len(merged["applications"])
    return merged
