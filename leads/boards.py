"""inbox:<board> - read one job board's own inbox and answer the recruiters who wrote there.

    python3 -m leads.boards --board hirist [--limit N] [--dry-run] [--env PATH] [-v]

Runs first in each board's lane, before profile:<board> and apply:<board>, in the board's own
saved browser profile. It

1. opens the board's inbox pages read-only (Naukri NVites, Hirist chats, Instahyre inbox,
   Cutshort conversations, Wellfound messages), parses them with diagnose.pages and records
   every thread that asks something as a lead in user/inputs/leads.json; the page text is kept
   under user/reports/<day>/leads/<board>-<slug>.txt;
2. on Cutshort and Instahyre, first finishes the pending questionnaires with the board's own
   verified finisher (<board>_bot.questionnaires.finish_pending) and mirrors each result onto
   the lead the inbox page produced, so the generic agent never answers the same thread twice;
3. lets the browser agent (sites_bot.browser_agent, `claude -p` on this Chrome) open each waiting
   thread and answer it from the saved facts only. It never applies, never accepts an offer and
   never takes an assessment: those come back needs_you with the reason. The one exception is a
   Naukri NVite, a recruiter's invitation to apply: a fit one is applied to (and recorded in the
   ledger like any Naukri apply); a junk, excluded or over-experienced one is closed as skipped.

Exit codes follow the other bots; EXIT_QUOTA pauses the lane when the model is out of quota.
"""

import argparse
import importlib
import json
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import paths
from common.models import Profile, Settings
from common.shared_files import atomic_write_text
from diagnose import pages
from leads import collect, store

logger = logging.getLogger(__name__)

SITES = ("naukri", "hirist", "instahyre", "cutshort", "wellfound")
#: The inbox pages of each board; read in this order.
INBOX_SEEDS: Dict[str, Tuple[str, ...]] = {
    "naukri": ("https://www.naukri.com/mnjuser/inbox",),
    "hirist": ("https://www.hirist.tech/chats",),
    "instahyre": ("https://www.instahyre.com/candidate/inbox/",),
    "cutshort": ("https://cutshort.io/profile/candidate-conversations?i=all",
                 "https://cutshort.io/profile/candidate-conversations?i=all&stage=awaiting"),
    "wellfound": ("https://wellfound.com/jobs/messages",),
}
#: The page each board's sign-in check needs to see first (connections.verify reads account details there).
SIGN_IN_PAGES: Dict[str, str] = {
    "naukri": "https://www.naukri.com/mnjuser/homepage",
    "hirist": "https://www.hirist.tech/myprofile",
    "instahyre": "https://www.instahyre.com/candidate/profile/",
    "cutshort": "https://cutshort.io/profile/candidate-dashboard",
    "wellfound": "https://wellfound.com/profile/edit",
}
RETRY_COOLDOWN_S = 900
#: What `claude -p` must answer with when it stops (sites_bot.browser_agent.task_prompt's report).
LEAD_REPORT = (
    'When you finish or stop, reply with ONE JSON object and nothing else:\n'
    '{"status": "done|needs_you|failed", "why": "one or two sentences", '
    '"action": "replied|answered_questionnaire|nothing", '
    '"confirmation": "the exact text of the message or answer now visible on the page, copied verbatim", '
    '"missing": ["each fact the thread asked for that is not in the facts"], '
    '"blocker": "none|human_check|sign_in|assessment|offer|transient|other", '
    '"written": "the full text you sent or entered", '
    '"job_url": "the job page address when the task applied to a job, else empty"}'
)
#: Questionnaire journal state (cutshort_bot / instahyre_bot questionnaires) -> lead state.
CUTSHORT_STATES = {"done": "answered", "needs_you": "needs_you", "retry_later": "deferred",
                   "uncertain": "needs_you", "deferred": "deferred", "running": "needs_you"}
#: Boards whose pending questionnaires have their own verified finisher; it runs before the generic agent.
QUESTIONNAIRE_BOTS = {"cutshort": "cutshort_bot.questionnaires", "instahyre": "instahyre_bot.questionnaires"}
#: Roles no recruiter invitation is worth answering (mirrors diagnose.rootcause.JUNK_ROLE).
JUNK_ROLE = re.compile(r"data entry|mis executive|operator|tester|telecaller|bpo|sales|back office|typist", re.I)
_YEARS = re.compile(r"(\d+)\s*-\s*(\d+)\s*Years", re.I)
_LPA = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*LPA", re.I)
MIN_LPA_CEILING = 5.0


# ---------------------------------------------------------------------------
# Reading the inbox
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "page"


def evidence_dir(settings: Settings, day: Optional[date] = None) -> Path:
    return Path(settings.report_dir or paths.user("reports")) / (day or date.today()).isoformat() / "leads"


def read_inbox(driver: Any, site: str, settings: Settings, folder: Path) -> Dict[str, Any]:
    """{state, message, pages, summary, evidence}: the board's inbox pages, read-only."""
    from common.browser import human_pause, safe_get
    from diagnose.platforms import PAGE_TEXT, _signed_in

    result: Dict[str, Any] = {"site": site, "state": "skipped", "message": "", "pages": [], "evidence": [],
                              "summary": pages.summarise(site, [])}
    if not safe_get(driver, SIGN_IN_PAGES[site]):
        result.update(state="browser_error", message="The %s account page did not load." % site)
        return result
    human_pause(1.5, 3.0)
    ok, message = _signed_in(driver, site)
    if not ok:
        result.update(state="needs_sign_in", message=message or "Not signed in.")
        return result
    result["state"] = "read"
    for url in INBOX_SEEDS[site]:
        if not safe_get(driver, url):
            result["pages"].append({"url": url, "error": "navigation failed"})
            continue
        human_pause(1.5, 3.0)
        text = str(driver.execute_script(PAGE_TEXT) or "")
        final = driver.current_url
        page = {"url": url, "final_url": final, "chars": len(text), "parsed": pages.parse(site, final, text)}
        target = folder / ("%s-%s.txt" % (site, _slug(url.split("//", 1)[-1])))
        atomic_write_text(target, "URL: %s\nFINAL: %s\n\n%s" % (url, final, text))
        page["evidence"] = str(target)
        result["pages"].append(page)
        result["evidence"].append(str(target))
    result["summary"] = pages.summarise(site, result["pages"])
    return result


# ---------------------------------------------------------------------------
# Deciding what a browser-agent run proved
# ---------------------------------------------------------------------------


def state_for(report: Optional[Dict[str, Any]], verified: bool, problem: str = "") -> Tuple[str, str]:
    """(lead state, why) from the agent's report. Pure; no I/O.

    `verified` is whether the confirmation it quoted is really on the page now."""
    if not report:
        return "failed", problem or "The agent gave no report."
    status = str(report.get("status") or "").lower()
    why = " ".join(str(report.get("why") or "").split())
    blocker = str(report.get("blocker") or "none").lower()
    if status == "done":
        if report.get("action") == "nothing":
            return "skipped", why or "Nothing in the thread needed an answer."
        if verified:
            return "answered", why or "Answered on the board."
        return "failed", "The agent said done but its confirmation text is not on the page; nothing was recorded as sent."
    if status == "needs_you":
        if blocker in ("human_check", "sign_in", "transient"):
            return "deferred", why or "Stopped by a %s; it will be retried later." % blocker.replace("_", " ")
        missing = [str(m) for m in report.get("missing") or [] if str(m).strip()]
        if missing:
            why = "%s Missing facts: %s." % (why, "; ".join(missing)[:200]) if why else "Missing facts: %s." % "; ".join(missing)[:200]
        return "needs_you", why or "The agent needs something only you can give."
    return "failed", why or problem or "The agent stopped without answering."


# ---------------------------------------------------------------------------
# Answering one lead
# ---------------------------------------------------------------------------


def nvite_misfit(lead: Dict[str, Any], settings: Settings, profile: Optional[Profile] = None) -> str:
    """Why a Naukri NVite is not worth applying to, or '' when it is: a junk role, an excluded title,
    or an experience range the candidate cannot meet. Pure; no I/O."""
    from naukri_bot import ranking

    title = str(lead.get("title") or "").split(",")[0].strip()
    text = str(lead.get("text") or "")
    junk = JUNK_ROLE.search("%s %s" % (title, text))
    if junk:
        return "a role the bots never apply to (%s)" % junk.group(0).strip()
    word = ranking.excluded_title(title, settings)
    if word:
        return "its title carries the EXCLUDE_TITLES word %s" % word
    years = getattr(profile, "total_experience_years", None) if profile is not None else None
    match = _YEARS.search(text)
    if years is not None and match and int(match.group(1)) > float(years) + float(settings.max_years_over):
        return "it asks for %s+ years and the profile has %s" % (match.group(1), years)
    pay = _LPA.search(text)
    current = getattr(profile, "current_ctc_lpa", None) if profile is not None else None
    floor = float(current) if current else MIN_LPA_CEILING
    if pay and float(pay.group(2)) < floor:
        return "it pays at most %s LPA and the profile is at %s LPA" % (pay.group(2), "%g" % floor)
    return ""


def _nvite_instruction(lead: Dict[str, Any]) -> str:
    role = lead.get("title") or "the invited role"
    return "\n\n".join([
        "This is a Naukri NVite: a recruiter invited the candidate to apply for %s. Open the NVites inbox "
        "(https://www.naukri.com/mnjuser/inbox), find this invitation by its title and city, and open the job." % role,
        ("What the page showed of the invitation: %s" % lead["text"]) if lead.get("text") else "",
        "If the job page shows an Apply button and not 'Applied', click Apply once. Answer every question "
        "Naukri's chatbot then asks from the facts below only; if it asks for a fact that is not in the facts, "
        "stop and report status needs_you with that fact in 'missing'. Stop when the page says the application "
        "went through and report status done with action 'applied', confirmation = the exact confirmation text "
        "now on the page, and job_url = the job page address. If the job already shows Applied, report status "
        "done with action 'nothing'.",
        "Never apply to any job other than this one invitation, never click Apply twice, never accept or decline "
        "an offer, and never write to anyone.",
    ]).replace("\n\n\n\n", "\n\n")


def instruction(site: str, lead: Dict[str, Any]) -> str:
    if site == "naukri" and lead.get("kind") == "RECRUITER_OUTREACH":
        return _nvite_instruction(lead)
    who = lead.get("who") or "the recruiter"
    about = " about %s" % " at ".join(filter(None, (lead.get("title"), lead.get("company")))) if (
        lead.get("title") or lead.get("company")) else ""
    opening = ("Open the %s inbox thread from %s%s. The address is already open or linked from this page; "
               "find the thread by the sender's name and the role." % (site, who, about))
    their_text = ("What the page showed of their message: %s" % lead["text"]) if lead.get("text") else ""
    kinds = {
        "QUESTION": ("It is a questionnaire or a list of questions. Answer every question from the facts "
                     "below, in the form the page provides, and submit the answers. If a question asks for "
                     "a fact that is not in the facts, stop and report status needs_you with that fact in "
                     "'missing'. Never make anything up."),
        "INTERVIEW": ("They propose or ask for an interview. Reply politely in the thread, confirm interest, "
                      "give availability only as the facts state it (notice period, location, timings), "
                      "and ask for the details you need. Do not accept a time the facts do not support."),
        "ASSESSMENT": ("It is an assessment or test link. Do not start or take it. Reply in the thread that "
                       "the candidate will take it, then report status needs_you with blocker 'assessment'."),
        "RECRUITER_OUTREACH": ("A recruiter invited the candidate to apply or asked whether they are interested. "
                               "Reply in the thread with interest and the facts they asked for. Do not apply "
                               "to the job yourself and do not click any Apply button."),
    }
    task = kinds.get(str(lead.get("kind") or ""), (
        "They wrote to the candidate. Read the whole thread, then reply in it, politely and briefly, "
        "answering exactly what they asked using only the facts below. If they ask for a fact that "
        "is not in the facts, do not guess: stop and report status needs_you with it in 'missing'."))
    return "\n\n".join(filter(None, [
        opening, their_text, task,
        "Never apply to a job, never accept or decline an offer, never share a phone number or email that "
        "is not in the facts, and never write to anyone other than this thread. If the thread shows your "
        "side already answered them after their last message, do nothing and report status done with "
        "action 'nothing'.",
    ]))


def answer_lead(driver: Any, settings: Settings, profile: Profile, site: str, lead: Dict[str, Any],
                facts: str) -> Tuple[str, str, Dict[str, Any]]:
    """Let the browser agent answer one thread; (state, why, report)."""
    from common.browser import safe_get
    from sites_bot import browser_agent

    url = lead.get("url") or collect.INBOX_URLS.get(site, "")
    if url and not safe_get(driver, url):
        return "deferred", "The inbox page did not load; it will be retried later.", {}
    time.sleep(2)
    prompt = browser_agent.task_prompt(instruction(site, lead), url, facts, profile.email or settings.email,
                                       has_password=False, report=LEAD_REPORT)
    workdir = browser_agent.workdir_for(settings, "%s lead %s" % (site, lead.get("company") or lead.get("who") or ""))
    run = browser_agent.run_agent(driver, settings, prompt, workdir)
    report = run.report or {}
    verified = False
    if report.get("status") == "done" and report.get("action") != "nothing":
        quote = str(report.get("confirmation") or report.get("written") or "")
        verified = bool(quote) and browser_agent.quote_on_page(driver, quote, allowed_handles=list(driver.window_handles))
    state, why = state_for(report or None, verified, run.problem)
    if state == "answered" and site == "naukri" and report.get("action") == "applied":
        record_nvite_apply(settings, lead, report)
    workdir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(workdir / "lead-report.json", json.dumps(
        {"lead": lead.get("id"), "url": url, "state": state, "why": why, "verified": verified, "report": report,
         "problem": run.problem}, indent=2, ensure_ascii=False))
    report.setdefault("workdir", str(workdir))
    return state, why, report


def record_nvite_apply(settings: Settings, lead: Dict[str, Any], report: Dict[str, Any]) -> bool:
    """An NVite the agent applied to goes into the ledger like any Naukri apply, so the quota count and
    the daily report see it. Returns whether a row was written."""
    from common.ledger import Ledger
    from common.models import ApplyResult, ApplyStatus

    url = str(report.get("job_url") or "").strip()
    if not url.startswith("http"):
        logger.warning("Naukri NVite applied but the agent gave no job address; the ledger has no row for it")
        return False
    match = re.search(r"-(\d{6,})(?:[?#]|$)", url)
    job_id = match.group(1) if match else "nvite:%s" % lead["id"].rsplit(":", 1)[-1]
    title = str(lead.get("title") or "").split(",")[0].strip()
    try:
        Ledger(settings.db_path).record_attempt(
            ApplyResult(job_id=job_id, url=url, status=ApplyStatus.APPLIED, quota_consumed=True,
                        detail="Applied from a recruiter's NVite (inbox:naukri)"),
            title=title, company=str(lead.get("company") or ""))
    except Exception:  # noqa: BLE001 - the apply happened; a ledger problem must not undo the lead
        logger.exception("Could not record the NVite apply for %s in the ledger", title)
        return False
    return True


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def _mirror(settings: Settings, site: str, results: List[Dict[str, Any]], facts: str) -> int:
    """Each questionnaire finish_pending handled becomes (or updates) a lead.

    The inbox parser already recorded the same thread as a QUESTION lead named by company and
    role; that lead takes the result, so the generic agent never answers a questionnaire the
    board's own finisher already handled. A result naming no known lead gets one of its own."""
    mirrored = 0
    known = [lead for lead in store.load(settings).values()
             if lead.get("source") == "board" and lead.get("platform") == site]
    for item in results or []:
        thread = str(item.get("thread") or "")
        if not thread:
            continue
        state = CUTSHORT_STATES.get(str(item.get("state") or ""), "failed")
        why = "%s questionnaire: %s (%s)." % (site.capitalize(), item.get("state"), QUESTIONNAIRE_BOTS.get(site, "questionnaires"))
        retry_after = (datetime.now() + timedelta(seconds=RETRY_COOLDOWN_S)).isoformat() if state == "deferred" else None
        company, title = _norm(item.get("company")), _norm(item.get("title"))
        matched = [lead for lead in known if company and _norm(lead.get("company")) == company
                   and (not title or not lead.get("title") or _norm(lead.get("title")) == title)]
        if not matched:
            lead = store.make_lead("board", site, "QUESTION", company=str(item.get("company") or ""),
                                   title=str(item.get("title") or "questionnaire"), who="%s questionnaire" % site.capitalize(),
                                   text="Pending questionnaire thread %s" % thread,
                                   url=("https://cutshort.io/profile/candidate-conversations/%s" % thread
                                        if site == "cutshort" else collect.INBOX_URLS.get(site, "")),
                                   key="%s-questionnaire:%s" % (site, thread))
            store.record(settings, [lead])
            matched = [lead]
        for lead in matched:
            store.update(settings, lead["id"], state, why, facts=facts, retry_after=retry_after,
                         finisher=QUESTIONNAIRE_BOTS.get(site, "questionnaires"))
        mirrored += 1
    return mirrored


def _mirror_cutshort(settings: Settings, results: List[Dict[str, Any]], facts: str) -> int:
    return _mirror(settings, "cutshort", results, facts)


# ---------------------------------------------------------------------------
# One board
# ---------------------------------------------------------------------------


def process_board(driver: Any, site: str, settings: Settings, profile: Profile, limit: int, dry_run: bool,
                  folder: Optional[Path] = None) -> Dict[str, Any]:
    """Read, record and answer one board's inbox; the counts are what the log and the lane see."""
    from common.answers import facts_fingerprint
    from sites_bot import browser_agent

    counts: Dict[str, Any] = {"site": site, "state": "", "found": 0, "new": 0, "answered": 0, "needs_you": 0,
                              "deferred": 0, "failed": 0, "skipped": 0, "quota": False}
    folder = folder or evidence_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    inbox = read_inbox(driver, site, settings, folder)
    counts["state"] = inbox["state"]
    if inbox["state"] != "read":
        logger.warning("%s inbox not read: %s", site, inbox.get("message") or inbox["state"])
        return counts
    leads = collect.from_board_summary(site, inbox["summary"])
    counts["found"] = len(leads)
    for lead in leads:
        logger.info("%s lead: %s %s %s %r", site, lead["kind"], lead.get("who"), lead.get("company"), lead.get("text", "")[:80])
    if dry_run:
        counts["new"] = len(leads)
        return counts
    counts["new"] = store.record(settings, leads)["new"]
    try:
        facts = facts_fingerprint(profile, settings)
    except Exception:  # Only decides whether a needs_you lead is retried.
        facts = ""
    if site == "naukri":
        # An NVite is an invitation to apply, so answering it means applying; the ones the apply bot
        # would never rank are closed here with the reason, not handed to the agent.
        for lead in leads:
            problem = nvite_misfit(lead, settings, profile) if lead.get("kind") == "RECRUITER_OUTREACH" else ""
            if problem and store.claim(settings, lead["id"], facts):
                store.update(settings, lead["id"], "skipped", "Not applied to: %s." % problem)
                counts["skipped"] += 1
    if site in QUESTIONNAIRE_BOTS and settings.browser_agent:
        questionnaires = importlib.import_module(QUESTIONNAIRE_BOTS[site])
        try:
            counts["questionnaires"] = _mirror(settings, site, questionnaires.finish_pending(driver, profile, settings, limit), facts)
        except Exception:
            logger.exception("%s questionnaires stopped; the inbox threads are still answered below", site.capitalize())
    if not settings.browser_agent:
        logger.info("BROWSER_AGENT is off: %s leads are recorded for you, none answered.", site)
        return counts
    done = 0
    for lead in store.open_leads(settings, "board", site, states=store.OPEN_STATES + store.PERSON_STATES):
        if done >= limit:
            break
        if lead.get("finisher"):
            # A questionnaire the board's finisher claimed stays its own (one journal, never a second Submit).
            continue
        if not store.claim(settings, lead["id"], facts):
            continue
        if not browser_agent.reserve_task(settings):
            from common.llm import out_of_quota

            counts["quota"] = bool(out_of_quota())
            store.update(settings, lead["id"], "deferred", "No browser-agent task left this run." if not counts["quota"]
                         else "The model is out of quota; retried once the window resets.",
                         retry_after=(datetime.now() + timedelta(seconds=RETRY_COOLDOWN_S)).isoformat())
            break
        done += 1
        try:
            state, why, report = answer_lead(driver, settings, profile, site, lead, browser_agent.facts_text(profile, settings))
        except Exception as exc:  # One thread must not stop the lane.
            logger.exception("%s lead %s stopped", site, lead["id"])
            state, why, report = "failed", "%s: %s" % (type(exc).__name__, str(exc)[:200]), {}
        store.update(settings, lead["id"], state, why, answer=str(report.get("written") or ""), facts=facts,
                     report=report or None, workdir=report.get("workdir"),
                     retry_after=(datetime.now() + timedelta(seconds=RETRY_COOLDOWN_S)).isoformat() if state == "deferred" else None)
        counts[state] = counts.get(state, 0) + 1
        logger.info("%s lead %s: %s (%s)", site, lead.get("who") or lead["id"], state, why)
    return counts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m leads.boards", description=__doc__.splitlines()[0])
    parser.add_argument("--board", required=True, choices=SITES, help="which board's inbox to read")
    parser.add_argument("--limit", type=int, help="threads to answer this run (default LEADS_LIMIT)")
    parser.add_argument("--dry-run", action="store_true", help="read and list the threads, answer nothing")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common import browser, config, profile as profile_module, report
    from common.run import (EXIT_BROWSER_LOCKED, EXIT_CONFIG, EXIT_FAILED, EXIT_LOGIN, EXIT_OK, EXIT_QUOTA,
                            configure_logging, keep_log)
    from sites_bot import browser_agent

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env, {"dry_run": True} if args.dry_run else {})
        profile = profile_module.load_profile(settings)
    except Exception as exc:
        logger.error("Could not load settings or profile: %s", exc)
        return EXIT_CONFIG
    keep_log(settings, "inbox-%s" % args.board)
    browser_agent.reset()
    limit = args.limit if args.limit is not None else settings.leads_limit
    try:
        driver = browser.create_driver(settings)
    except Exception as exc:
        text = str(exc)
        logger.error("Could not start the browser for %s: %s", args.board, text.splitlines()[0][:200])
        return EXIT_BROWSER_LOCKED if "lock" in text.lower() or "in use" in text.lower() else EXIT_FAILED
    try:
        counts = process_board(driver, args.board, settings, profile, limit, args.dry_run)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    logger.info("%s inbox: %s", args.board, ", ".join("%s %s" % item for item in counts.items() if item[0] != "site"))
    if not args.dry_run:
        report.update_quietly(settings)
    if counts.get("state") == "needs_sign_in":
        return EXIT_LOGIN
    if counts.get("quota"):
        return EXIT_QUOTA
    if counts.get("state") not in ("read",):
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
