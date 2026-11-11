"""Tell what a hiring-related email is from its sender and subject alone.

Rule-based so thousands of headers can be sorted without a model call. The
shape (sender-domain table, then ordered regex lists per kind) follows the MIT
classifier in amimrjo/Job-Application-Tracker (src/classifier.py); the Indian
job-board templates (Naukri, Hirist, Instahyre, Cutshort, Foundit, Shine) and
the SHORTLIST / PROFILE_VIEW kinds are our own additions.
"""

import re
from dataclasses import dataclass
#: Sender host suffix -> platform label.
PLATFORMS = (
    ("naukri.com", "naukri"), ("naukri.in", "naukri"), ("infoedge.com", "naukri"),
    ("hirist.tech", "hirist"), ("hirist.com", "hirist"),
    ("instahyre.com", "instahyre"),
    ("cutshort.io", "cutshort"),
    ("wellfound.com", "wellfound"), ("angel.co", "wellfound"), ("angellist.com", "wellfound"),
    ("linkedin.com", "linkedin"),
    ("accounts.google.com", "google"), ("google.com", "google"), ("youtube.com", "google"),
    ("indeed.com", "indeed"),
    ("foundit.in", "foundit"), ("monsterindia.com", "foundit"),
    ("shine.com", "shine"),
    ("iimjobs.com", "iimjobs"),
    ("greenhouse.io", "ats"), ("greenhouse-mail.io", "ats"), ("lever.co", "ats"), ("hire.lever.co", "ats"),
    ("myworkday.com", "ats"), ("myworkdayjobs.com", "ats"), ("workday.com", "ats"),
    ("ashbyhq.com", "ats"), ("smartrecruiters.com", "ats"), ("jobvite.com", "ats"),
    ("icims.com", "ats"), ("bamboohr.com", "ats"), ("recruitee.com", "ats"), ("workable.com", "ats"),
    ("zohorecruit.com", "ats"), ("keka.com", "ats"), ("darwinbox.com", "ats"), ("freshteam.com", "ats"),
    ("successfactors.com", "ats"), ("taleo.net", "ats"), ("breezy.hr", "ats"), ("rippling.com", "ats"),
    ("calendly.com", "scheduler"), ("goodtime.io", "scheduler"), ("cal.com", "scheduler"),
    ("hackerrank.com", "assessment"), ("hackerearth.com", "assessment"), ("codility.com", "assessment"),
    ("codesignal.com", "assessment"), ("mettl.com", "assessment"), ("testgorilla.com", "assessment"),
    ("hirevue.com", "assessment"), ("imocha.io", "assessment"), ("doselect.com", "assessment"),
)

KINDS = ("OFFER", "INTERVIEW", "ASSESSMENT", "SHORTLIST", "RECRUITER_OUTREACH", "QUESTION", "REPLY",
         "REJECTION", "ACKNOWLEDGEMENT", "PROFILE_VIEW", "JOB_ALERT", "PROMO", "OTHER")

#: Positive movement a candidate would call "a call back".
POSITIVE = ("OFFER", "INTERVIEW", "ASSESSMENT", "SHORTLIST", "RECRUITER_OUTREACH", "QUESTION", "REPLY")

#: Bulk senders' subjects that look like outreach but are job alerts.
_ALERT_FIRST = re.compile(r"\bis hiring for an? \b|\bjobs? (for you|you may like|matching)\b|\bnew jobs?\b|\brecommended jobs?\b", re.IGNORECASE)

_RULES = (
    ("OFFER", (
        r"\boffer letter\b", r"\bletter of intent\b", r"\bpleased to offer\b", r"\boffer of employment\b",
    )),
    ("INTERVIEW", (
        r"\binterview\b(?!-ready)(?!.*\b(tips|prep|guide|questions you|skills|course|webinar|masterclass|ready|learn(ing)?|"
        r"previous applicants|experiences?|cracking|how to|account data|firebaseapp|ace|help|we're here)\b)",
        r"\bschedule (a|your) (call|conversation|discussion|meeting)\b", r"\bbook a (slot|time)\b",
        r"\binvitation:.*(call|interview|discussion)", r"\bcalendar invite\b", r"\bhiring manager (call|round)\b",
        r"\btechnical (round|discussion)\b", r"\bscreening (call|round)\b", r"\bvideo (call|interview)\b",
        r"\bzoom|google meet|teams meeting\b.*\b(call|round|discussion)\b",
    )),
    ("ASSESSMENT", (
        r"\b(coding|online|technical|skill|take[- ]home|aptitude) (test|assessment|challenge|assignment)\b",
        r"\bassessment (link|invite|invitation)\b", r"\bhackerrank|hackerearth|codility|codesignal|mettl\b",
        r"\bcomplete (the|your) (test|assessment|assignment)\b",
    )),
    ("SHORTLIST", (
        r"\bshortlist(ed)?\b", r"\byou(’|')?ve been (selected|shortlisted|picked)\b", r"\bmoving forward with your\b",
        r"\bnext (round|step|stage) of (the|our) (hiring|selection|interview) process\b",
        r"\brecruiter (is )?interested\b", r"\bshowed interest in your profile\b", r"\bwants to connect with you\b",
        r"\binvited you to apply\b", r"\bprofile (has been |was )?(downloaded|shortlisted)\b",
        r"\byour application (is|has been) (under review|being reviewed|in review)\b",
    )),
    ("RECRUITER_OUTREACH", (
        r"\b(exciting |new )?(opportunity|opening|position|role) (for|with|at) you\b", r"\bare you (open|looking)\b",
        r"\bwe (came across|found) your (profile|resume)\b", r"\byour profile (matches|suits)\b",
        r"\bhiring for\b.*\b(role|position)\b", r"\breaching out\b", r"\bjob (opportunity|offer) [-–:]\b",
    )),
    ("QUESTION", (
        r"\b(please|kindly) (share|send|confirm|provide|update)\b", r"\bcould you (share|send|confirm)\b",
        r"\b(few|some|additional|more) (details|information|questions)\b", r"\bquestionnaire\b",
        r"\bfill (in|out) (the|this) form\b", r"\bcurrent (ctc|salary) and notice\b",
    )),
    ("REPLY", (
        r"^\s*(re|aw|sv|antw):\s", r"^\s*re\[\d+\]:\s",
    )),
    ("REJECTION", (
        r"\bnot (been )?(selected|shortlisted|successful|moving forward|proceed)\b", r"\bunfortunately\b",
        r"\bregret to inform\b", r"\bdecided (not to|to not)\b", r"\bother candidates\b",
        r"\bposition (has been|is now) (filled|closed)\b", r"\bno longer (being )?considered\b",
        r"\bapplication (status|update)[: ].*\b(closed|rejected|declined|unsuccessful)\b", r"\bwill not be\b",
    )),
    ("ACKNOWLEDGEMENT", (
        r"\bthank(s| you) for (applying|your (application|interest))\b", r"\bapplication (received|submitted|confirmation)\b",
        r"\bwe(’|')?ve received your (application|resume|cv)\b", r"\byou(’|')?ve (successfully )?applied\b",
        r"\byour application (to|for|at) .* (has been|was) (received|sent|submitted)\b", r"\bapplied successfully\b",
        r"\bapplication (sent|successful)\b", r"\bsuccessfully (applied|submitted)\b",
    )),
    ("PROFILE_VIEW", (
        r"\b(recruiter|employer|company|hr).{0,40}(viewed|visited|checked|saw) your (profile|resume)\b",
        r"\byour profile (was|has been|got) (viewed|visited|seen)\b", r"\bprofile view(s)?\b",
        r"\brecruiters? (looked at|searched for|are viewing)\b", r"\bwho(’|')?s viewed\b",
    )),
    ("JOB_ALERT", (
        r"\bjob alert\b", r"\bjobs? (for you|matching|recommended|you may like|that match)\b", r"\bnew jobs?\b",
        r"\b\d+\+? (new )?(jobs|openings|roles)\b", r"\brecommended (jobs|for you)\b", r"\bjobs? (in|near) \w+\b",
        r"\btop (jobs|picks|matches)\b", r"\bsimilar jobs\b", r"\bjob (recommendations|digest|matches)\b",
        r"\bare hiring\b", r"\bopenings at\b",
    )),
    ("PROMO", (
        r"\bupgrade\b", r"\bpremium\b", r"\bsubscription\b", r"\bresume (writing|service|score|booster)\b",
        r"\bwebinar\b", r"\bmasterclass\b", r"\bcourse\b", r"\bcertification\b", r"\bnewsletter\b", r"\bdiscount\b",
        r"\boff(er)? on\b", r"\bunsubscribe\b", r"\bcomplete your profile\b", r"\bprofile (is|looks) incomplete\b",
        r"\bboost your\b", r"\bfeatured profile\b", r"\btips\b", r"\bweekly (summary|digest)\b",
    )),
)
_COMPILED = tuple((kind, tuple(re.compile(p, re.IGNORECASE) for p in patterns)) for kind, patterns in _RULES)

_NOREPLY = re.compile(r"no-?reply|do-?not-?reply|notifications?|alerts?|mailer|newsletter|info@|updates?@|digest", re.IGNORECASE)
_HIRING_WORDS = re.compile(
    r"\b(job|jobs|hiring|recruit|career|careers|application|applied|interview|candidate|position|opening|"
    r"opportunity|vacancy|resume|cv|talent|hr|shortlist|offer|assessment|round|profile)\b", re.IGNORECASE)


@dataclass
class Verdict:
    platform: str
    kind: str
    rule: str = ""
    automated: bool = False
    hiring_related: bool = False

    @property
    def positive(self) -> bool:
        return self.kind in POSITIVE


def sender_domain(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender or "")
    return match.group(1).lower() if match else ""


def platform_of(sender: str) -> str:
    domain = sender_domain(sender)
    for suffix, label in PLATFORMS:
        if domain == suffix or domain.endswith("." + suffix):
            return label
    if domain.endswith((".edu", ".ac.in")):
        return "education"
    if any(part in domain for part in ("gmail.", "yahoo.", "outlook.", "hotmail.", "proton")):
        return "personal"
    return "employer" if domain else "unknown"


def classify(sender: str, subject: str, snippet: str = "") -> Verdict:
    """Platform from the sender, kind from the first rule list that matches subject then snippet."""
    platform = platform_of(sender)
    text_subject = " ".join((subject or "").split())
    text_all = text_subject + " \n " + " ".join((snippet or "").split())[:1500]
    automated = bool(_NOREPLY.search(sender or ""))
    hiring = bool(_HIRING_WORDS.search(text_all)) or platform in (
        "naukri", "hirist", "instahyre", "cutshort", "wellfound", "indeed", "foundit", "shine", "iimjobs", "ats",
        "scheduler", "assessment")
    # Platform bulk mail: a job board writing about "interview tips" is promo, so
    # subject-only rules decide for automated senders before the body is read.
    if platform == "google":
        return Verdict(platform, "OTHER", "google-account-notice", automated, False)
    if automated and platform not in ("employer", "personal", "unknown", "ats") and _ALERT_FIRST.search(text_subject):
        return Verdict(platform, "JOB_ALERT", "subject:alert-first", automated, hiring)
    if platform in ("scheduler",):
        return Verdict(platform, "INTERVIEW", "scheduler-domain", automated, True)
    if platform in ("assessment",):
        return Verdict(platform, "ASSESSMENT", "assessment-domain", automated, True)
    for scope, text in (("subject", text_subject), ("body", text_all)):
        for kind, patterns in _COMPILED:
            if scope == "body" and kind in ("JOB_ALERT", "PROMO"):
                continue  # Marketing words in a body must not override a real subject.
            for pattern in patterns:
                if pattern.search(text):
                    return Verdict(platform, kind, "%s:%s" % (scope, pattern.pattern[:40]), automated, hiring)
    if automated and platform not in ("employer", "personal", "unknown"):
        return Verdict(platform, "PROMO", "automated-platform-sender", automated, hiring)
    return Verdict(platform, "OTHER", "", automated, hiring)


def is_noise(verdict: Verdict) -> bool:
    return verdict.kind in ("JOB_ALERT", "PROMO") or not verdict.hiring_related
