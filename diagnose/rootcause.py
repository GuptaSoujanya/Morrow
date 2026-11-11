"""Turn the collected numbers into ranked causes, each with its evidence and its fix.

A cause only appears when the data supports it; the evidence lines quote the
numbers so the reader can disagree with the conclusion but not with the facts.
Fix kinds: env (a .env value), code (a module to change), answers (the saved
chatbot answers), profile (profile.yaml), resume, skill (something to learn or
add), manual (a thing only the person can do).
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

#: Industry reference points (sources in the report appendix).
COLD_APPLY_INTERVIEW_RATE = (0.02, 0.03)   # meta-analysis of 27 studies; Ashby Q1-2026 technical 3.6%
NAUKRI_SHORTLIST_RATE = 0.0278             # 76/2734, lowest of four platforms in the same study


@dataclass
class Cause:
    id: str
    severity: str
    title: str
    evidence: List[str]
    fix_kind: str
    fix: List[str]
    confidence: float = 0.7
    where: List[str] = field(default_factory=list)
    plain: str = ""        # the cause in plain words, when the generic PLAIN_WORDS text does not fit
    model_note: str = ""   # what the model said about this cause on review, if it was asked

    def sort_key(self):
        return (SEVERITY_ORDER.get(self.severity, 9), -self.confidence)


def _share(part: Optional[int], whole: Optional[int]) -> float:
    return (part or 0) / whole if whole else 0.0


def expected_interviews(submitted: int) -> Dict[str, float]:
    low, high = COLD_APPLY_INTERVIEW_RATE
    return {"low": round(submitted * low, 1), "high": round(submitted * high, 1),
            "naukri_only": round(submitted * NAUKRI_SHORTLIST_RATE, 1)}


#: Invitations for roles nobody with this profile should chase; they are evidence, not leads.
JUNK_ROLE = re.compile(r"data entry|mis executive|operator|tester|telecaller|bpo|sales|back office|typist|"
                       r"\b[0-4](\.\d)? ?- ?[0-5](\.\d)? lpa\b", re.I)


def _site_causes(sites: Dict[str, Any], local: Dict[str, Any]) -> List[Cause]:
    causes: List[Cause] = []
    waiting: List[str] = []
    rejections: List[str] = []
    for site, data in sites.items():
        if data.get("state") != "read":
            continue
        summary = data.get("summary") or {}
        for message in summary.get("messages", []):
            header = " ".join(part for part in (site, message.get("who", "?"), message.get("date", ""), message.get("about", "")) if part)
            line = "%s: %s" % (header, message.get("text", "")[:160])
            if message.get("action") == "apply-invitation" and JUNK_ROLE.search(message.get("text", "")):
                continue
            if message.get("action"):
                waiting.append("[%s] %s" % (message["action"], line))
            if message.get("rejection"):
                rejections.append(line)
        facts = summary.get("facts", {})
        statuses = summary.get("status_counts", {})
        listed = facts.get("applications_listed") or facts.get("applications") or sum(statuses.values())
        if listed:
            moved = sum(count for status, count in statuses.items()
                        if status.lower() not in ("applied/sent", "pending", "applications pending", "viewed", "not shortlisted",
                                                  "not accepted", "applications rejected", "archived", "status updates offsite"))
            detail = ["%s lists %d applications; statuses %s" % (site, listed, statuses or facts)]
            if site == "hirist" and facts.get("jobs_with_zero_recruiter_actions") is not None:
                detail.append("%d of %d Hirist jobs show zero recruiter actions for anyone; median %d applicants per job; %d moved past Applied/Sent" % (
                    facts["jobs_with_zero_recruiter_actions"], facts.get("applied_listed", listed),
                    facts.get("median_applicants_per_job", 0), facts.get("viewed_or_better", 0)))
            causes.append(Cause(
                "site-funnel-%s" % site, "high" if not moved else "medium",
                "%s: %d applications, %d shortlisted or in conversation" % (site, listed, moved),
                detail, "manual",
                ["Pause %s applies until MIN_SCORE and EXCLUDE_TITLES are fixed, then at most 5 close-fit applies a day there." % site],
                0.85, data.get("evidence", [])[:2]))
    if waiting:
        causes.append(Cause(
            "unanswered-messages", "critical", "Recruiters did reply on the boards and nobody answered them",
            waiting[:12] + ["The bots never read board inboxes (nothing in sites_bot reads Naukri NVites, Hirist chats, Instahyre inbox or Wellfound messages), "
                           "so a questionnaire or assessment request waits until someone logs in by hand."],
            "code", ["Today: open each board inbox above and complete the questionnaire/assessment; these are the only live leads.",
                     "Code: add an 'inbox' stage per board that lists new threads into user/worklists/ and marks the job needs_you "
                     "(read-only, like diagnose/platforms.py); extend cutshort_bot/questionnaires.py's pattern to Instahyre.",
                     "Wellfound: record the 15-minute AI interview once — Wellfound lists candidates with one first."],
            0.95, ["sites_bot/", "cutshort_bot/questionnaires.py", "pipeline/run.py"]))
    if rejections:
        causes.append(Cause(
            "recruiter-said-why", "high", "A recruiter wrote down the reason", rejections[:4], "profile",
            ["Take the stated reason literally: experience and stack filters, not luck. Tighten EXCLUDE_TITLES and MAX_YEARS_OVER."],
            0.9))
    naukri_facts = (sites.get("naukri") or {}).get("summary", {}).get("facts", {})
    if naukri_facts.get("search_appearances") is not None or naukri_facts.get("recruiter_actions") is not None:
        naukri_applies = naukri_facts.get("applies_on_naukri") or local["funnel_all"]["submitted_by_status"].get("applied", 0)
        appearances = naukri_facts.get("search_appearances", 0)
        actions = naukri_facts.get("recruiter_actions", 0)
        statuses = (sites.get("naukri") or {}).get("summary", {}).get("status_counts", {})
        nvites = [m for m in (sites.get("naukri") or {}).get("summary", {}).get("messages", []) if m.get("action") == "apply-invitation"]
        junk_nvites = [m["about"] for m in nvites if JUNK_ROLE.search(m.get("text", ""))]
        evidence = [
            "Naukri's own profile-performance page: %d search appearances and %d recruiter actions in 90 days; the actions by type: %s." % (
                appearances, actions, ", ".join("%s %d" % (k.replace("Recruiter action: ", ""), v) for k, v in statuses.items() if k.startswith("Recruiter action")) or "not shown"),
            "Application history on Naukri: %s total applies (%s on Naukri, %s on external sites), %s application updates, %s recruiter actions on applications." % (
                naukri_facts.get("total_applies", "?"), naukri_facts.get("applies_on_naukri", "?"), naukri_facts.get("applies_on_external_site", "?"),
                naukri_facts.get("application_updates", "?"), naukri_facts.get("recruiter_actions_on_applies", "?")),
            "Headline on Naukri: %s" % naukri_facts.get("headline", "(not read)")]
        if nvites:
            evidence.append("%d NVites (recruiters inviting this profile to apply); %d of them are for unrelated or low-paid roles: %s. "
                            "Naukri's matching reads this profile as a generalist, which is what the headline and key skills tell it." % (
                                len(nvites), len(junk_nvites), "; ".join(junk_nvites[:4]) or "none"))
        causes.append(Cause(
            "naukri-performance", "high" if actions < max(5, naukri_applies * 0.05) else "medium",
            "Naukri: %d recruiter actions against %d applies and %d search appearances" % (actions, naukri_applies, appearances),
            evidence + [
             "Experience shown %s; notice %s; resume uploaded %s; profile updated %s." % (
                 naukri_facts.get("experience", "?"), naukri_facts.get("notice_period", "?"),
                 naukri_facts.get("resume_uploaded", "?"), naukri_facts.get("profile_updated", "?"))],
            "profile",
            ["Recruiters find this profile in search %d times but act on it %d times: the headline and key skills decide that click. "
             "Put the job title, the stack recruiters search (Python, FastAPI, React, LangChain, AWS) and the city in the first 60 characters; "
             "drop private project names (WildClawBench) from the headline." % (appearances, actions),
             "Open naukri.com > Recruiter actions and read which companies viewed/downloaded; those are the warm leads to mail directly."],
            0.85, (sites.get("naukri") or {}).get("evidence", [])[:2]))
    hirist_view = (sites.get("hirist") or {}).get("summary", {}).get("facts", {})
    cutshort_view = (sites.get("cutshort") or {}).get("summary", {}).get("facts", {})
    inconsistencies = []
    notice = str(local["profile"].get("notice_days") or "")
    if hirist_view.get("notice_period") and notice and "month" in hirist_view["notice_period"].lower() and notice.strip() in ("15", "15 days", "0", "7"):
        inconsistencies.append("Hirist shows notice period '%s' while profile.yaml and the Naukri answers say %s days" % (hirist_view["notice_period"], notice))
    years = local["profile"].get("years")
    for label, shown in (("Hirist", hirist_view.get("experience")), ("Cutshort", cutshort_view.get("experience_shown"))):
        if shown and years and not str(years).split(".")[0] in shown:
            inconsistencies.append("%s shows experience '%s' while profile.yaml says %s years" % (label, shown, years))
    if inconsistencies:
        causes.append(Cause(
            "profile-inconsistent", "medium", "The boards show different facts than the profile the bots answer with",
            inconsistencies, "profile",
            ["Make notice period, total experience and location identical on Naukri, Hirist, Instahyre, Cutshort, Wellfound and profile.yaml; "
             "recruiters filter on these fields and the bots' answers must match what the page shows."],
            0.8, ["user/inputs/profile.yaml"]))
    return causes


#: The journal states leads.store counts as waiting for the bots, and as waiting for the person.
LEAD_OPEN_STATES = ("new", "deferred", "failed")
LEAD_PERSON_STATES = ("needs_you",)


def _lead_line(item: Dict[str, Any]) -> str:
    sender = item.get("who") or item.get("company") or "unknown"
    about = item.get("title") or item.get("subject") or str(item.get("text") or "")[:80] or "(no subject)"
    return "%s %s from %s: %s" % (item.get("platform") or "unknown", str(item.get("kind") or "REPLY").lower(),
                                  str(sender)[:40], str(about)[:90])


def _received(item: Dict[str, Any]) -> str:
    return str(item.get("received_at") or str(item.get("first_seen") or "")[:10] or "?")


def _thread(platform: Any, subject: Any) -> tuple:
    subject = " ".join(str(subject or "").casefold().split())
    return str(platform or "").casefold(), re.sub(r"^(?:(?:re|fwd?|fw)\s*:\s*)+", "", subject)


def _answered_mail_threads(leads: Dict[str, Any]) -> set:
    return {_thread(item.get("platform"), item.get("subject")) for item in leads.get("items") or []
            if item.get("source") == "mail" and item.get("state") == "answered" and item.get("subject")}


def _lead_causes(leads: Dict[str, Any]) -> List[Cause]:
    causes: List[Cause] = []
    day = str(leads.get("day") or date.today().isoformat())[:10]
    items = [item for item in leads.get("items") or [] if isinstance(item, dict)]
    today = leads.get("today") or {}
    waiting, needs_you = int(leads.get("waiting") or 0), int(leads.get("needs_you") or 0)
    answered, answered_today = int(leads.get("answered") or 0), int(today.get("answered") or 0)
    if waiting:
        open_items = [item for item in items if item.get("state") in LEAD_OPEN_STATES]
        # summary() lists the newest updates first, so a waiting lead past its list was last updated before all of them.
        stale = any(str(item.get("first_seen") or day)[:10] < day for item in open_items) or (
            waiting > len(open_items) and bool(items) and min(str(item.get("updated_at") or "")[:10] for item in items) < day)
        evidence = ["%d leads in the journal still unanswered: %d waiting for the bots, %d waiting for you; answered so far %d (%d today)" % (
            waiting + needs_you, waiting, needs_you, answered, answered_today)]
        evidence += ["%s (received %s, state %s)" % (_lead_line(item), _received(item), item.get("state")) for item in open_items[:10]]
        if waiting > len(open_items[:10]):
            evidence.append("%d more waiting; the Leads section lists the newest." % (waiting - len(open_items[:10])))
        causes.append(Cause(
            "leads-waiting", "critical" if stale else "high", "Recruiter threads are waiting for an answer", evidence, "manual",
            ["Today: run `python3 -m leads` (stages inbox:<board> and leads:mail) or open each thread above and answer it; "
             "a questionnaire or assessment dies in about 48 hours.",
             "Keep LEADS_AUTO_REPLY=true so tomorrow's run answers them itself."],
            0.95, ["user/inputs/leads.json", "leads/"]))
    if needs_you:
        person = [item for item in items if item.get("state") in LEAD_PERSON_STATES][:10]
        evidence = ["%d leads wait for you, %d of them since today." % (needs_you, int(today.get("needs_you") or 0))]
        evidence += ["%s (received %s); why: %s" % (_lead_line(item), _received(item), item.get("why") or "not recorded")
                     for item in person]
        if needs_you > len(person):
            evidence.append("%d more wait for you; the Leads section lists the newest." % (needs_you - len(person)))
        causes.append(Cause(
            "leads-need-you", "high", "Leads the bots could not finish need you", evidence, "manual",
            ["Open each one; the 'why' says what was missing (an assessment to take, a fact not in profile.yaml, a draft in Gmail to finish)."],
            0.9, ["user/inputs/leads.json"]))
    if answered_today:
        done = [item for item in items if str(item.get("answered_at") or "")[:10] == day][:10]
        evidence = ["%s (answered at %s)" % (_lead_line(item), str(item.get("answered_at"))[11:16]) for item in done]
        if answered_today > len(done):
            evidence.append("%d more answered today." % (answered_today - len(done)))
        causes.append(Cause(
            "leads-answered", "info", "%d recruiter threads were answered today by the leads bot" % answered_today,
            evidence, "manual", ["Nothing to do; check the dashboard's Leads tab for what was written."], 0.9))
    return causes


def rank(local: Dict[str, Any], mail: Optional[Dict[str, Any]], sites: Optional[Dict[str, Any]],
         resume: Dict[str, Any], settings_email: str = "") -> List[Dict[str, Any]]:
    causes: List[Cause] = []
    funnel = local["funnel_all"]
    fit = local["fit"]
    submitted = funnel["submitted_total"]
    expected = expected_interviews(submitted)

    # --- Leads: the threads recruiters started, and what the bots did with them ---
    leads = local.get("leads") or {}
    causes.extend(_lead_causes(leads))

    # --- Is the silence real, or were the calls missed? ---------------------
    mail_positive = (mail or {}).get("positive_total") if mail else None
    local_positive = local["replies"]["positive"]
    if mail and not mail.get("error"):
        if mail_positive:
            from diagnose.report import LEADS_ANSWERED, grouped_positives

            groups = grouped_positives(mail["positives"])
            answered_threads = _answered_mail_threads(leads)
            done = [_thread(g.get("platform"), g.get("subject")) in answered_threads for g in groups]
            listed = ["%s %s from %s: \"%s\"%s%s" % (g["platform"], g["kind"].lower(), g["from"][:30], g["subject"][:80],
                                                    " (x%d)" % g["count"] if g["count"] > 1 else "",
                                                    " (%s)" % LEADS_ANSWERED if answered else "")
                      for g, answered in zip(groups[:10], done)]
            # Kept ahead of the reply-reader note: action_plan() reads evidence[1:-1] as the mails to answer.
            since = (["%d of these threads have since been %s (see Leads)" % (sum(done), LEADS_ANSWERED)]
                     if leads.get("answered") else [])
            causes.append(Cause(
                "calls-exist", "critical", "Positive mail exists that nobody answered",
                ["%d hiring-positive mails (%d distinct) in the last %d days: %s" % (
                    mail_positive, len(groups), mail["days"], ", ".join("%s %d" % kv for kv in mail["positive_by_kind"].items()))]
                + listed
                + since
                + ["The reply reader (sites_bot/replies.py) only matches mail to one applied job and drops anything "
                   "from a job-board domain, so employer_replies.jsonl shows %d positives." % local_positive],
                "code", ["Today: answer every item above; a shortlist, an assessment invite or a reply to a cold mail dies in 48 hours.",
                         "sites_bot/replies.py: stop dropping mail from board domains in link(); classify unmatched "
                         "hiring mail as a lead instead of discarding it.",
                         "Read Spam and All Mail too; the reader only scans INBOX."],
                0.9, ["sites_bot/replies.py", "user/inputs/employer_replies.jsonl"]))
        else:
            causes.append(Cause(
                "silence-confirmed", "info", "The silence is real: no interview, shortlist or recruiter mail anywhere",
                ["%d mails scanned across %s; positives 0." % (mail["scanned"], ", ".join(mail["folders"])),
                 "Cold applications usually turn into interviews %d-%d%% of the time, so %d submissions should have "
                 "produced about %s-%s interviews. Zero is a broken funnel, not bad luck." % (
                     int(COLD_APPLY_INTERVIEW_RATE[0] * 100), int(COLD_APPLY_INTERVIEW_RATE[1] * 100), submitted,
                     expected["low"], expected["high"])],
                "manual", ["Fix the causes below in order; re-run this audit after two weeks of changed applying."],
                0.95))
        if mail.get("spam_hiring"):
            causes.append(Cause(
                "spam", "high", "Hiring mail is landing in Spam",
                ["%d hiring-related messages in [Gmail]/Spam, e.g. %s" % (
                    len(mail["spam_hiring"]), "; ".join(m["subject"][:60] for m in mail["spam_hiring"][:3]))],
                "manual", ["Mark each as 'Not spam' and create a Gmail filter 'Never send to Spam' for the sender domains."],
                0.9))
        naukri_counts = mail["by_platform"].get("naukri", {})
        naukri_submitted = funnel["submitted_by_status"].get("applied", 0)
        if naukri_submitted and not naukri_counts:
            causes.append(Cause(
                "naukri-mail-missing", "high", "Naukri sent nothing to this mailbox although %d Naukri applies were made" % naukri_submitted,
                ["0 mails from naukri.com in %d days in %s." % (mail["days"], mail["account"]),
                 "Either Naukri's account uses another address, or its email notifications are off, or applies did not register."],
                "manual", ["Open naukri.com > Settings > Communication and confirm the address and that 'Recruiter actions' "
                           "and 'Application status' mails are on.",
                           "Compare the address with %s and NAUKRI_EMAIL in .env." % (mail["account"] or "the mailbox read")],
                0.75, ["user/inputs/profile.yaml", ".env"]))
        for platform, count in funnel["submitted_by_channel"].items():
            if platform in ("naukri", "unknown", "other", "instahyre") or count < 10:
                continue
            kinds = mail["by_platform"].get(platform, {})
            acks = kinds.get("ACKNOWLEDGEMENT", 0) + kinds.get("SHORTLIST", 0) + kinds.get("REJECTION", 0)
            if acks == 0:
                causes.append(Cause(
                    "no-ack-%s" % platform, "high", "%s: %d applications recorded, no application mail at all" % (platform, count),
                    ["Mail from %s in %d days: %s" % (platform, mail["days"], kinds or "none"),
                     "Every board confirms a real application by mail; none means the submissions may not have landed."],
                    "manual", ["Compare %s's own applied list (platform pages section) with the ledger's %d; fewer on the site means "
                               "%s_bot marks a job applied before the site confirms it." % (platform, count, platform)],
                    0.7, ["%s_bot/" % platform]))
    elif mail and mail.get("error"):
        causes.append(Cause("mail-unread", "medium", "The mailbox could not be read", [mail["error"]], "env",
                            ["Set GMAIL_APP_PASSWORD (Google account > Security > App passwords) and GOOGLE_EMAIL in .env."],
                            0.9, [".env"]))

    if settings_email and local["profile"].get("naukri_email") and \
            settings_email.casefold() != str(local["profile"]["naukri_email"]).casefold():
        causes.append(Cause(
            "email-mismatch", "medium", "The Naukri login address and the profile address differ",
            ["NAUKRI_EMAIL=%s, profile.yaml email=%s" % (settings_email, local["profile"]["naukri_email"])],
            "profile", ["Use one address everywhere, and read that one's inbox."], 0.6, [".env", "user/inputs/profile.yaml"]))

    # --- Fit -------------------------------------------------------------------
    scored_total = sum(c for band, c in fit["score_bands"].items() if band != "unscored")
    low_fit = fit["score_bands"].get("<40", 0) + fit["score_bands"].get("40-49", 0)
    if scored_total and _share(low_fit, scored_total) > 0.3:
        causes.append(Cause(
            "low-fit", "critical", "Most applications went to postings the ranker itself scored as a poor match",
            ["%d of %d scored submissions (%.0f%%) scored under 50; median score %s; MIN_SCORE is %s." % (
                low_fit, scored_total, 100 * _share(low_fit, scored_total), fit["median_score"], fit["min_score"]),
             "%d submissions were below the configured MIN_SCORE, so a lane applies without the Naukri threshold." % fit["below_min_score"],
             "Keyword-match studies put callbacks near 1% under 50% match and ~11% above 85%."],
            "env", ["MIN_SCORE=65 in .env (local_setup VOLUME_DEFAULTS still says 40; tenant_api says 70).",
                    "Code: make hirist_bot, instahyre_bot, wellfound_bot and cutshort_bot drop candidates under settings.min_score "
                    "the way naukri_bot/cli.py does (see naukri_bot/ranking.py select_for_application).",
                    "Skill: for the top missing keywords below, either learn and add them or stop applying to roles that require them."],
            0.9, ["naukri_bot/ranking.py", "common/local_setup.py", "hirist_bot/", "instahyre_bot/", "wellfound_bot/"]))
    if fit["mismatched_titles"]:
        causes.append(Cause(
            "title-mismatch", "high", "Applications went to levels and roles the profile cannot pass the first filter for",
            ["%d submitted titles contain senior/lead/manager/SDET/data-scientist/mobile words, e.g. %s" % (
                fit["mismatched_titles"], "; ".join(fit["mismatched_examples"][:6])),
             "EXCLUDE_TITLES currently: %s" % ", ".join(local["settings"]["exclude_titles"])],
            "env", ["EXCLUDE_TITLES=Senior,Sr,Lead,Staff,Principal,Head,Architect,Manager,Director,Intern,Trainee,QA,SDET,"
                    "Test,Data Analyst,Data Scientist,React Native,Android,iOS,Flutter,DevOps,SRE,Embedded,III",
                    "Code: apply ranking.excluded_title() in every board lane, not only Naukri."],
            0.85, ["naukri_bot/ranking.py:401", ".env"]))
    if fit["experience_gap_count"] or local["profile"].get("under_three_years"):
        causes.append(Cause(
            "experience-filter", "high", "Under the 3-year line while applying to 3+ and 4+ year roles",
            ["profile total_experience_years=%s; %d submissions list an experience-years gap; top gaps: %s" % (
                local["profile"].get("years"), fit["experience_gap_count"],
                ", ".join("%s (%d)" % g for g in fit["top_gaps"][:5])),
             "Naukri's recruiter search filters on whole years: 2.9 is shown as 2 years, so '3-5 yrs' searches never list this profile."],
            "profile", ["Apply only where the minimum is 2 years or less until the three-year mark (MAX_YEARS_OVER=0).",
                        "State experience as years and months everywhere (Naukri profile, resume headline) and keep them identical."],
            0.8, ["user/inputs/profile.yaml", ".env"]))

    # --- Answers -----------------------------------------------------------------
    if local["answers"]["suspicious"]:
        causes.append(Cause(
            "bad-answers", "critical", "Saved chatbot answers tell recruiters the candidate is somewhere else",
            ["%s" % "; ".join("'%s' -> '%s' (%s)" % (a["question"][:50], a["answer"], a["why"]) for a in local["answers"]["suspicious"][:5]),
             "These are sent with every Naukri apply; a location answer of 'Others' or 'Remote' fails the recruiter's city filter."],
            "answers", ["Set current location to the real city (Gurugram) and preferred location to real cities (Gurugram, Delhi NCR, Noida, Pune) in user/inputs/answers.txt, then let the bot re-save.",
                        "Code: common/answers.py should refuse 'Others'/'Remote'/'Any' for a location question and ask the person instead."],
            0.9, ["user/inputs/answers.txt", "common/answers.py", "user/db/naukri_bot.db (answers table)"]))

    # --- Volume and quality of submission --------------------------------------------
    per_day = funnel["submitted_by_day"]
    if per_day:
        daily = [sum(c.values()) for c in per_day.values()]
        peak = funnel["peak_day"]
        if max(daily) > 100 or sum(daily) / len(daily) > 60:
            causes.append(Cause(
                "volume", "high", "Volume applying: hundreds a day, each with the same untailored resume",
                ["%d submissions over %d days; peak %d on %s; %s" % (
                    submitted, funnel["days_running"], peak["count"], peak["day"],
                    ", ".join("%s %d" % kv for kv in funnel["submitted_by_channel"].items())),
                 "Boards rank a candidate who applies to everything lower and recruiters see the same resume for unrelated roles."],
                "env", ["TARGET_APPLICATIONS=20, DAILY_QUOTA=25, MAX_CANDIDATES=300.",
                        "Code: turn on resume tailoring per application (common/resume.py) so each apply carries the posting's words."],
                0.75, [".env", "common/resume.py"]))
    unfinished = local["errors"]["unfinished_total"]
    if submitted and _share(unfinished, submitted + unfinished) > 0.15:
        causes.append(Cause(
            "unfinished", "medium", "A large share of attempts never completed, some after the quota was spent",
            ["%d unfinished (error/chatbot_timeout/abstained/no_apply_button) against %d submitted; wasted quota slots %d" % (
                unfinished, submitted, funnel["wasted_quota"]),
             "Top reasons: %s" % "; ".join("%s x%d" % (d["detail"][:70], d["count"]) for d in local["errors"]["detail_counts"][:4])],
            "code", ["Browser agent stopped by the Claude session limit: the pipeline should pause the lane when ai_cli reports a quota error "
                     "instead of recording an error per job (common/ai_cli.py, sites_bot/browser_agent.py).",
                     "Cutshort 'Submit clicked but not Applied after reload': verify by re-reading the conversation thread, not the job card.",
                     "Browser-agent runs past 900 s: lower BROWSER_AGENT_TIMEOUT and mark the job needs_you instead of error.",
                     "Abstained questions: answer the %d open items in user/worklists/unanswered_questions.md." % local["funnel_all"]["status_counts"].get("abstained", 0)],
            0.7, ["cutshort_bot/", "sites_bot/browser_agent.py", "user/worklists/unanswered_questions.md"]))
    sites_local = local["company_sites"]
    if sites_local.get("unresolved"):
        causes.append(Cause(
            "company-sites-unresolved", "medium", "Company-site applications sit in 'uncertain' or 'needs you'",
            ["%d of %d company-site attempts are unresolved: %s" % (sites_local["unresolved"], sites_local["rows"], sites_local["states"])],
            "manual", ["Walk the needs_you list in user/worklists/external_jobs.md; each is a form one click from done."],
            0.8, ["user/worklists/external_jobs.md"]))
    if local["cutshort"].get("unfinished"):
        causes.append(Cause(
            "cutshort-questionnaires", "medium", "Cutshort questionnaires are waiting on the candidate",
            ["%d threads not done: %s" % (local["cutshort"]["unfinished"], local["cutshort"]["states"])],
            "manual", ["Open cutshort.io > conversations > awaiting and finish them; a Cutshort apply is not sent until the questionnaire is."],
            0.85, ["user/inputs/cutshort_questionnaires.json"]))

    # --- Resume -------------------------------------------------------------------
    if not resume.get("error"):
        problems = []
        if resume.get("coverage") is not None and resume["coverage"] < 0.6:
            problems.append("keyword coverage of the applied postings is %.0f%%; missing from the resume although asked for: %s" % (
                100 * resume["coverage"], ", ".join("%s (asked in %d postings)" % (n, c) for n, c, _ in resume["missing_in_demand"][:10])))
        if resume.get("weak_words"):
            problems.append("toy-project wording present: %s" % ", ".join(resume["weak_words"]))
        if resume.get("metric_share") is not None and resume["metric_share"] < 0.3:
            problems.append("only %d of %d bullets carry a number" % (resume["bullets_with_metric"], resume["bullets"]))
        if resume.get("headline_flags"):
            problems.append("headline '%s': %s" % (resume["headline"], "; ".join(resume["headline_flags"])))
        if problems:
            causes.append(Cause(
                "resume", "high", "The resume does not say what the postings ask for, in their words",
                problems,
                "resume", ["Headline: 'Software Engineer (Python, LLM/RAG, FastAPI, React) · 2.9 yrs' — the job title first, then the stack.",
                           "Remove every 'mock', 'simulated', 'prototype', 'beta'; describe shipped behaviour and who used it.",
                           "Add the missing terms you genuinely have (%s) to the skills block and to one bullet each." % ", ".join(n for n, _, _ in resume["missing_in_demand"][:6]),
                           "One number per bullet: latency, throughput, users, cost, time saved."],
                0.8, ["user/resume/base.tex"]))
            if resume["missing_in_demand"]:
                causes.append(Cause(
                    "skills-to-add", "medium", "Skills the market asks for that neither resume nor profile shows",
                    ["Asked in >=15%% of applied postings, absent from the resume: %s" % ", ".join(
                        "%s %d" % (n, c) for n, c, _ in resume["missing_in_demand"][:12])],
                    "skill", ["Pick two (the cloud one and the data-store one first) and ship one small public project each; add them to profile.yaml skills and the resume."],
                    0.7, ["user/inputs/profile.yaml", "user/resume/base.tex"]))
    else:
        causes.append(Cause("resume-unreadable", "medium", "Resume could not be read", [resume["error"]], "env",
                            ["Set RESUME_PATH in .env to the .tex or PDF."], 0.9, [".env"]))

    # --- Channels -----------------------------------------------------------------
    replies_local = local["replies"]
    if replies_local["contacts_known"] >= 20 and replies_local["cold_emails_sent"] < replies_local["contacts_known"] // 10:
        causes.append(Cause(
            "contacts-unused", "medium", "Named recruiter contacts exist but almost none were written to",
            ["%d contacts in job_contacts.jsonl, %d cold emails sent." % (replies_local["contacts_known"], replies_local["cold_emails_sent"])],
            "manual", ["Send 5 short, specific mails a day from the contacts list; direct mail converts several times better than portal applies."],
            0.7, ["user/inputs/job_contacts.jsonl"]))
    if sites:
        causes.extend(_site_causes(sites, local))
    if funnel["days_running"] and funnel["days_running"] < 21:
        causes.append(Cause(
            "too-early", "low", "The pipeline is %d days old; most recruiter replies take 2-4 weeks" % funnel["days_running"],
            ["first application %s, last %s" % (funnel["first_at"][:10], funnel["last_at"][:10])],
            "manual", ["Keep going with the fixes above; judge the funnel again on day 30."], 0.6))

    causes.sort(key=Cause.sort_key)
    return [asdict(cause) for cause in causes]
