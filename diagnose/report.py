"""Write the audit as user/reports/<date>/diagnostics.md and diagnostics.json.

The daily report.md is rebuilt whole by common/report.py, so this writes its own
files next to it, under the same lock-and-replace discipline.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from common import paths
from common.models import Settings
from common.shared_files import atomic_write_text, locked_file

MD_NAME = "diagnostics.md"
JSON_NAME = "diagnostics.json"

SOURCES = (
    "Cold-apply interview rate 2-3% (meta-analysis of 27 studies, noxjobs/uppl.ai summary); Ashby Q1 2026: 3.6% of "
    "technical applications reach an interview; Stepstone Oct 2025: median 20 applications per 3 interviews, 54% never "
    "answered; Naukri shortlist 2.78% (76/2734) vs LinkedIn 15.2%, Indeed 4.7% (IJCOPE 2(10), doi 10.55041/ijcope.v2i10.143); "
    "keyword match <50% -> 0.9% callback, >=85% -> 11.4% (Jobloo, vendor data)."
)


def grouped_positives(positives: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per (platform, kind, sender, subject), newest first, with how many mails it covers."""
    groups: Dict[tuple, Dict[str, Any]] = {}
    for record in positives:
        subject = " ".join(str(record.get("subject", "")).split()).casefold()
        key = (record.get("platform"), record.get("kind"), str(record.get("from", ""))[:40].casefold(), subject)
        group = groups.setdefault(key, dict(record, count=0))
        group["count"] += 1
        if str(record.get("date", "")) > str(group.get("date", "")):
            group["date"] = record.get("date", "")
    return sorted(groups.values(), key=lambda g: (-g["count"], str(g.get("date", ""))), reverse=False)


def _expected(submitted: int):
    return ("%d" % int(submitted * 0.02), "%d" % int(submitted * 0.03))


def _signal_sentence(mail: Optional[Dict[str, Any]], sites: Optional[Dict[str, Any]],
                     leads: Optional[Dict[str, Any]] = None) -> str:
    parts = []
    if leads and leads.get("total"):
        parts.append("%d recruiter threads in the leads journal (%d answered, %d still open)" % (
            leads["total"], leads.get("answered", 0), leads.get("waiting", 0) + leads.get("needs_you", 0)))
    if mail and not mail.get("error"):
        parts.append("%d hiring-positive mails among %d scanned" % (mail.get("positive_total", 0), mail.get("scanned", 0)))
    elif mail:
        parts.append("a mailbox that could not be read")
    if sites:
        waiting = sum((data.get("summary") or {}).get("facts", {}).get("messages_needing_action", 0)
                      for data in sites.values() if data.get("state") == "read")
        read = [site for site, data in sites.items() if data.get("state") == "read"]
        parts.append("%d recruiter messages waiting for an answer on %s" % (waiting, ", ".join(read) or "no board"))
    return " and ".join(parts) or "no reply data (mail and boards were skipped)"


def report_dir(settings: Settings, day: Optional[date] = None) -> Path:
    day = day or date.today()
    return Path(settings.report_dir or paths.user("reports")) / day.isoformat()


def _table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "_none_\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines) + "\n"


PLAIN_WORDS = {
    "unanswered-messages": "Recruiters did write back on the job boards. Nobody saw it, because the bots apply but never read a board's inbox.",
    "calls-exist": "There is positive mail in Gmail that the reply reader never surfaced.",
    "low-fit": "Most applications went to jobs the bot's own scoring called a poor match, because MIN_SCORE is set too low and the board lanes ignore it.",
    "bad-answers": "The saved Naukri answer for current location is 'Others', so every Naukri apply fails a recruiter's city filter.",
    "title-mismatch": "Hundreds of applications went to Senior, Lead, Manager, Data Scientist, DevOps and mobile roles that a 2.9-year profile cannot pass.",
    "experience-filter": "The profile is under the 3-year line while most target roles ask 3+ or 4+ years.",
    "recruiter-said-why": "A recruiter wrote the reason: the profile does not meet the eligibility criteria of the roles applied to.",
    "naukri-performance": "Naukri shows the profile in search often but recruiters almost never act on it, and the invitations it does get are for unrelated roles. The headline and key skills are the problem.",
    "resume": "The resume does not use the words the postings use, has almost no numbers, and describes projects as mock or prototype work.",
    "volume": "Hundreds of applications a day with one untailored resume.",
    "spam": "Hiring mail is going to Spam.",
    "naukri-mail-missing": "Naukri sends nothing to this mailbox although it records many applies.",
    "leads-waiting": "Recruiters wrote on the boards or by mail and some of those threads still have no answer; the Leads section lists each one.",
    "leads-need-you": "Some recruiter threads need something only you can give: an assessment to take, a fact missing from profile.yaml, or a Gmail draft to finish.",
}

TODAY_KINDS = ("manual",)
WEEK_KINDS = ("env", "answers", "profile", "resume", "skill")
CODE_KINDS = ("code",)
#: rootcause marks a positive mail the leads bot already answered with this; the plan does not ask for it again.
LEADS_ANSWERED = "answered by the leads bot"
LEAD_COLUMNS = ["received", "platform", "kind", "company / role", "from", "state", "answered", "why"]


def action_plan(causes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Three lists: what to do by hand today, what to change this week, what to change in the bots."""
    plan: Dict[str, List[str]] = {"today": [], "week": [], "code": []}

    def add(group: str, lines) -> None:
        for line in lines:
            if line not in plan[group]:
                plan[group].append(line)

    for cause in causes:
        if cause["id"] in ("silence-confirmed", "too-early", "leads-answered"):
            continue
        fixes = cause["fix"]
        if cause["id"] == "unanswered-messages":
            add("today", ["Answer: %s" % line for line in cause.get("evidence", []) if line.startswith("[")])
        if cause["id"] == "calls-exist":
            add("today", ["Answer: %s" % line for line in cause.get("evidence", [])[1:-1] if LEADS_ANSWERED not in line])
        if cause["fix_kind"] in TODAY_KINDS:
            add("today", fixes)
        elif cause["fix_kind"] in CODE_KINDS:
            add("today", (f for f in fixes if f.lower().startswith("today")))
            add("code", (f for f in fixes if not f.lower().startswith("today")))
        else:
            add("week", (f for f in fixes if not f.lower().startswith("code:")))
            add("code", (f for f in fixes if f.lower().startswith("code:")))
    return plan


def model_review_lines(review: Optional[Dict[str, Any]], trail: Optional[List[Dict[str, Any]]]) -> List[str]:
    """The model's second opinion, or the plain statement that there was none."""
    out = ["## Model review\n"]
    if not review or not review.get("used"):
        reason = ""
        for step in trail or []:
            if step.get("name") == "Model review of the ranked causes":
                reason = step.get("check", "")
        out.append("The model did not review this run (%s). Every cause above comes from the rules and the numbers they quote.\n" % (
            reason or "no model available"))
        return out
    out.append("The model read the same numbers and the ranked causes. Verdict: %s\n" % (review.get("verdict") or "(none given)"))
    out.append("It agreed with %d causes, disagreed with %d, and added %d of its own (kept only when they quote a number from the data; %d rejected).\n" % (
        review.get("agreed", 0), review.get("disagreed", 0), review.get("added", 0), review.get("rejected_additions", 0)))
    if review.get("first_three_actions"):
        out.append("Its first three actions:")
        for index, action in enumerate(review["first_three_actions"], 1):
            out.append("%d. %s" % (index, action))
        out.append("")
    return out


def trail_lines(trail: Optional[List[Dict[str, Any]]]) -> List[str]:
    out = ["## How each step was checked\n"]
    if not trail:
        out.append("No model steps ran.\n")
        return out
    out.append("Every model-assisted step went research → verify → check → execute; a step whose check failed kept the rules' result.\n")
    out.append(_table(["step", "researched", "verified before asking", "accuracy check", "executed", "passed"],
                      [[s["name"], s["research"], s["verify"], s["check"], s["execute"], "yes" if s.get("ok") else "**no**"] for s in trail]))
    return out


def _cell(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text.replace("|", "\\|") or "-"


def leads_lines(leads: Optional[Dict[str, Any]]) -> List[str]:
    """The leads journal: its counts, the newest threads with what was done about each, and the boards they came from."""
    out = ["## Leads: recruiter threads and what was done\n"]
    if leads is None:
        out.append("The leads journal was not read for this audit.\n")
        return out
    if leads.get("error"):
        out.append("The leads journal could not be read: %s\n" % leads["error"])
        return out
    total = int(leads.get("total") or 0)
    if not total:
        out.append("No lead recorded yet; the inbox:<board> and leads:mail stages fill this.\n")
        return out
    today = leads.get("today") or {}
    out.append("The journal holds %d recruiter threads: %d waiting for the bots, %d waiting for you and %d answered, "
               "%d of them today; %d came in today.\n" % (
                   total, leads.get("waiting", 0), leads.get("needs_you", 0), leads.get("answered", 0),
                   today.get("answered", 0), today.get("new", 0)))
    rows = []
    for item in (leads.get("items") or [])[:40]:
        role = " · ".join(part for part in (item.get("company"), item.get("title") or item.get("subject")) if part)
        rows.append([_cell(item.get("received_at") or str(item.get("first_seen") or "")[:10], 16), _cell(item.get("platform"), 16),
                     _cell(str(item.get("kind") or "").lower(), 18), _cell(role, 70), _cell(item.get("who"), 30),
                     _cell(item.get("state"), 10), _cell(str(item.get("answered_at") or "")[:16].replace("T", " "), 16),
                     _cell(item.get("why"), 90)])
    out.append(_table(LEAD_COLUMNS, rows))
    if total > len(rows):
        out.append("The newest %d of %d are listed; the dashboard's Leads tab shows every one.\n" % (len(rows), total))
    platforms = sorted((leads.get("by_platform") or {}).items(), key=lambda kv: (-int(kv[1].get("total") or 0), kv[0]))
    out.append("By platform:\n")
    out.append(_table(["platform", "total", "waiting", "answered", "needs you"],
                      [[_cell(name, 20), counts.get("total", 0), counts.get("waiting", 0), counts.get("answered", 0),
                        counts.get("needs_you", 0)] for name, counts in platforms]))
    return out


def build_markdown(local: Dict[str, Any], mail: Optional[Dict[str, Any]], sites: Optional[Dict[str, Any]],
                   resume: Dict[str, Any], causes: List[Dict[str, Any]], review: Optional[Dict[str, Any]] = None,
                   trail: Optional[List[Dict[str, Any]]] = None) -> str:
    funnel = local["funnel_all"]
    live = local["funnel_live"]
    out: List[str] = []
    out.append("# Why nobody is calling — funnel audit %s\n" % local["generated_at"][:16].replace("T", " "))
    out.append("## The root cause, in plain words\n")
    out.append("%d applications were submitted in %d days. In the same time the job boards and the mailbox show %s." % (
        funnel["submitted_total"], funnel["days_running"], _signal_sentence(mail, sites, local.get("leads"))))
    out.append("")
    top = [c for c in causes if c["severity"] in ("critical", "high")]
    for index, cause in enumerate(top[:6], 1):
        out.append("%d. **%s** %s" % (index, cause["title"] + ".", cause.get("plain") or PLAIN_WORDS.get(cause["id"], "")))
    out.append("")
    out.append("The silence is not bad luck: with normal fit, %d submissions would produce roughly %s to %s interviews. "
               "Each of the points above cuts the chance of a call to near zero on its own, and all of them are present at once.\n" % (
                   funnel["submitted_total"], *_expected(funnel["submitted_total"])))
    out.extend(model_review_lines(review, trail))
    plan = action_plan(causes)
    out.append("## What to do, in order\n")
    out.append("### Today, by hand\n")
    for line in plan["today"]:
        out.append("- %s" % line)
    out.append("\n### This week: settings, answers, profile and resume\n")
    for line in plan["week"]:
        out.append("- %s" % line)
    out.append("\n### Code changes for the bots\n")
    for line in plan["code"]:
        out.append("- %s" % line.replace("Code: ", "", 1))
    out.append("\nThen apply for two weeks at the lower volume and run `python3 -m diagnose` again; the Naukri recruiter actions, "
               "Hirist 'Viewed' count and board inboxes are the numbers that should move first.\n")
    out.extend(leads_lines(local.get("leads")))
    out.append("## Every cause with its evidence\n")
    for index, cause in enumerate(causes, 1):
        out.append("### %d. [%s] %s\n" % (index, cause["severity"].upper(), cause["title"]))
        out.append("Evidence:")
        for line in cause["evidence"]:
            out.append("- %s" % line)
        out.append("\nFix (%s):" % cause["fix_kind"])
        for line in cause["fix"]:
            out.append("- %s" % line)
        if cause.get("where"):
            out.append("\nWhere: %s" % ", ".join("`%s`" % w for w in cause["where"]))
        if cause.get("model_note"):
            out.append("\n_%s_ (confidence now %.2f)" % (cause["model_note"], float(cause.get("confidence", 0))))
        out.append("")
    out.append("## What was read\n")
    out.append(_table(["Ledger", "rows", "new rows merged"],
                      [[p, v["rows"], v["new_rows"]] for p, v in local["ledgers"].items()]))
    out.append("Company-site ledger: %s rows, states %s\n" % (local["company_sites"].get("rows"), local["company_sites"].get("states")))
    out.append("## Funnel (all ledgers, %d days, %s to %s)\n" % (funnel["days_running"], funnel["first_at"][:10], funnel["last_at"][:10]))
    out.append(_table(["status", "count"], [[k, v] for k, v in funnel["status_counts"].items()]))
    out.append("Submitted: **%d** (%s). Live ledger alone: %d.\n" % (
        funnel["submitted_total"], ", ".join("%s %d" % kv for kv in funnel["submitted_by_status"].items()), live["submitted_total"]))
    out.append(_table(["channel", "submitted"], [[k, v] for k, v in funnel["submitted_by_channel"].items()]))
    out.append(_table(["day", "submitted"], [[d, sum(c.values())] for d, c in funnel["submitted_by_day"].items()]))
    fit = local["fit"]
    out.append("## Fit of what was applied to\n")
    out.append(_table(["score band", "submissions"], [[k, v] for k, v in sorted(fit["score_bands"].items())]))
    out.append("Median score %s; %d below MIN_SCORE %s; %d mismatched titles.\n" % (
        fit["median_score"], fit["below_min_score"], fit["min_score"], fit["mismatched_titles"]))
    out.append(_table(["gap named by the ranker", "submissions"], [[g, c] for g, c in fit["top_gaps"][:15]]))
    out.append("## Saved answers\n")
    out.append("%d answers saved, %d never marked used.\n" % (local["answers"]["rows"], local["answers"]["never_used"]))
    out.append(_table(["question", "answer", "why it hurts"],
                      [[a["question"][:60], a["answer"], a["why"]] for a in local["answers"]["suspicious"]]))
    out.append("## Replies already recorded\n")
    out.append("%d mails in employer_replies.jsonl: %s; senders %s; contacts known %d, cold mails sent %d.\n" % (
        local["replies"]["rows"], local["replies"]["kinds"], local["replies"]["sender_platforms"],
        local["replies"]["contacts_known"], local["replies"]["cold_emails_sent"]))
    out.append("## Mailbox sweep\n")
    if mail is None:
        out.append("Skipped (--skip-mail).\n")
    elif mail.get("error"):
        out.append("Not read: %s\n" % mail["error"])
    else:
        out.append("%s, last %d days, %d messages in %s; model read %d bodies; model: %s.\n" % (
            mail["account"], mail["days"], mail["scanned"], mail["folders"], mail["llm_used"], mail.get("model", "not used")))
        rows = []
        for platform, kinds in mail["by_platform"].items():
            rows.append([platform, sum(kinds.values()), ", ".join("%s %d" % kv for kv in kinds.items())])
        out.append(_table(["sender", "mails", "kinds"], rows))
        if mail.get("queries"):
            out.append("### Targeted searches (%d)\n" % len(mail["queries"]))
            out.append("Each search is a filter run inside Gmail; new rows are mails the folder sweep had not listed.\n")
            out.append(_table(["search", "purpose", "made by", "rows", "new", "positive", "status"],
                              [[("`%s`" % q["query"][:90]), q.get("purpose", "")[:50], q.get("source", ""), q.get("rows", 0),
                                q.get("new_rows", 0), q.get("positives", 0), q.get("status", "")] for q in mail["queries"]]))
        verification = mail.get("verification") or {}
        if verification.get("used"):
            out.append("Model verification: %d mails re-judged in %d batches; agreed with the rules on the kind %s of the time and on "
                       "positive-or-not %s; %d verdicts changed (%d promoted to a positive signal, %d demoted); %d batches distrusted.\n" % (
                           verification.get("items", 0), verification.get("batches", 0), verification.get("agreement_kind"),
                           verification.get("agreement_positive"), verification.get("changed", 0), verification.get("promoted", 0),
                           verification.get("demoted", 0), verification.get("distrusted_batches", 0)))
        elif verification:
            out.append("Model verification did not run (%s); the kinds below are the rules' verdicts.\n" % (
                "the model did not answer" if verification.get("batches") else "no model available"))
        out.append("### Positive signals (%d mails, %d distinct)\n" % (mail["positive_total"], len(grouped_positives(mail["positives"]))))
        out.append(_table(["latest", "platform", "kind", "from", "subject", "mails"],
                          [[g["date"][:16], g["platform"], g["kind"], g["from"][:36], g["subject"][:70], g["count"]]
                           for g in grouped_positives(mail["positives"])[:60]]))
        if mail["spam_hiring"]:
            out.append("### Hiring mail in Spam (%d)\n" % len(mail["spam_hiring"]))
            out.append(_table(["date", "from", "subject"], [[p["date"][:10], p["from"][:40], p["subject"][:70]] for p in mail["spam_hiring"][:30]]))
    out.append("## Platform account pages\n")
    if sites is None:
        out.append("Skipped (--skip-browser).\n")
    else:
        rows = []
        for site, data in sites.items():
            rows.append([site, data.get("state"), (data.get("message") or "")[:80], len(data.get("pages", [])),
                         ", ".join("%s %s" % kv for kv in data.get("signals", {}).items()) or "-"])
        out.append(_table(["site", "state", "note", "pages", "numbers found"], rows))
        for site, data in sites.items():
            summary = data.get("summary") or {}
            if not summary:
                continue
            out.append("### %s\n" % site)
            if summary.get("facts"):
                out.append(", ".join("%s: %s" % kv for kv in summary["facts"].items()) + "\n")
            if summary.get("status_counts"):
                out.append(_table(["status on the site", "count"], [[k, v] for k, v in summary["status_counts"].items()]))
            if summary.get("messages"):
                out.append(_table(["date", "from", "about", "asks for", "message"],
                                  [[m.get("date", ""), m.get("who", "")[:30], m.get("about", "")[:40], m.get("action") or "-",
                                    m.get("text", "")[:110]] for m in summary["messages"][:12]]))
            if site == "hirist" and summary.get("applications"):
                out.append(_table(["title", "date", "views", "applicants", "recruiter actions", "status"],
                                  [[a["title"][:55], a["date"], a["views"], a["applicants"], a["recruiter_actions"], a["status"]]
                                   for a in summary["applications"][:45]]))
            elif summary.get("applications") and site != "instahyre":
                out.append(_table(["title", "status", "date"],
                                  [[a.get("title", "")[:55], a.get("status", ""), a.get("date", "")] for a in summary["applications"][:40]]))
        out.append("\nEvidence text saved under the day's `diagnostics/` folder.\n")
    out.append("## Resume vs the postings applied to\n")
    if resume.get("error"):
        out.append(resume["error"] + "\n")
    else:
        out.append("Headline: %s\n\nCoverage of in-demand terms: %s; %d of %d bullets carry a number; weak words: %s\n" % (
            resume["headline"], resume["coverage"], resume["bullets_with_metric"], resume["bullets"], ", ".join(resume["weak_words"]) or "none"))
        out.append(_table(["term asked for", "postings", "share", "in resume?"],
                          [[n, c, "%d%%" % int(100 * c / resume["postings_analysed"]) if resume["postings_analysed"] else "-",
                            "yes" if n in resume["terms_in_resume"] else "**no**"] for n, c in resume["demand_top"]]))
        if resume["weak_lines"]:
            out.append("Lines with weak wording:")
            for line in resume["weak_lines"]:
                out.append("- %s" % line)
            out.append("")
    out.extend(trail_lines(trail))
    out.append("## Reference points\n")
    out.append(SOURCES + "\n")
    out.append("\n_Read-only audit by `python3 -m diagnose`. Nothing was applied, sent or changed._\n")
    return "\n".join(out)


def write(settings: Settings, local: Dict[str, Any], mail: Optional[Dict[str, Any]], sites: Optional[Dict[str, Any]],
          resume: Dict[str, Any], causes: List[Dict[str, Any]], day: Optional[date] = None,
          review: Optional[Dict[str, Any]] = None, trail: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Path]:
    folder = report_dir(settings, day)
    markdown = build_markdown(local, mail, sites, resume, causes, review, trail)
    payload = {
        "generated_at": local["generated_at"],
        "causes": causes,
        "plan": action_plan(causes),
        "review": review or {},
        "trail": trail or [],
        "local": {key: value for key, value in local.items() if key != "applications"},
        "leads": local.get("leads") or {},
        "mail": mail,
        "sites": sites,
        "resume": resume,
    }
    md_path = folder / MD_NAME
    json_path = folder / JSON_NAME
    with locked_file(md_path) as target:
        atomic_write_text(target, markdown)
    with locked_file(json_path) as target:
        atomic_write_text(target, json.dumps(payload, indent=1, default=str))
    return {"markdown": md_path, "json": json_path}
