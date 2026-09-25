"""Shared data contracts for the Naukri auto-apply pipeline.

Every other module in this package imports from here. Nothing in this module
imports from the rest of the package, so it can never participate in a cycle.

Python 3.9 compatible: use typing.Optional / List / Dict, never PEP-604 unions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@dataclass
class JobPosting:
    """A single job card collected from Naukri, before any ranking."""

    job_id: str
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    experience: str = ""
    salary: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    # Raw freshness label as rendered on the card, e.g. "3 days ago", "Just now".
    posted_label: str = ""
    # Parsed from posted_label. None means "unknown", which is NOT the same as 0.
    posted_days_ago: Optional[float] = None
    # Provenance: "search:<keyword>" or "recommended:<tab_id>".
    source: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def text_blob(self) -> str:
        """Everything worth matching against the resume, lowercased."""
        parts = [
            self.title,
            self.company,
            self.location,
            self.experience,
            self.description,
            " ".join(self.tags),
        ]
        return " ".join(p for p in parts if p).lower()


class Verdict:
    STRONG = "strong"
    POSSIBLE = "possible"
    WEAK = "weak"


@dataclass
class ScoredJob:
    """A JobPosting with a relevance score derived from the user's resume."""

    job: JobPosting
    score: float = 0.0           # final blended score, 0-100
    lexical_score: float = 0.0   # cheap skill/title overlap, 0-100
    llm_score: Optional[float] = None  # None when the LLM did not rate this job
    reasons: List[str] = field(default_factory=list)
    verdict: str = Verdict.WEAK


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


class ApplyStatus:
    """Outcome of a single apply attempt.

    Only APPLIED consumes Naukri quota. EXTERNAL_SKIPPED exists because Naukri's
    "Apply on company site" button navigates off-site and applies to nothing on
    Naukri -- the legacy scripts counted that as success, which is why their
    counters drifted from the real 50/day quota.
    """

    APPLIED = "applied"
    ALREADY_APPLIED = "already_applied"
    EXTERNAL_SKIPPED = "external_skipped"
    ABSTAINED = "abstained"
    NO_APPLY_BUTTON = "no_apply_button"
    QUOTA_EXPIRED = "quota_expired"
    SESSION_EXPIRED = "session_expired"
    CHATBOT_TIMEOUT = "chatbot_timeout"
    ERROR = "error"

    #: Statuses that mean a Naukri application was really submitted.
    CONSUMES_QUOTA = (APPLIED,)

    #: Statuses that mean "stop the run immediately".
    TERMINAL = (QUOTA_EXPIRED, SESSION_EXPIRED)


@dataclass
class ApplyResult:
    job_id: str
    url: str
    status: str
    detail: str = ""
    quota_consumed: bool = False
    questions_answered: int = 0
    questions_abstained: int = 0
    at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def ok(self) -> bool:
        return self.status == ApplyStatus.APPLIED


# ---------------------------------------------------------------------------
# Screening answers
# ---------------------------------------------------------------------------


class AnswerSource:
    CACHE = "cache"      # previously resolved and stored in the ledger
    LLM = "llm"          # produced this run by the LLM, grounded in the profile
    PROFILE = "profile"  # read straight off a Profile field, no model involved


@dataclass
class Answer:
    text: str
    grounded_in: str = ""          # which profile fact justifies this answer
    source: str = AnswerSource.LLM
    confidence: float = 0.0        # 0-1, informational only


@dataclass
class AnswerResolution:
    """Either an answer, or an explicit refusal to guess.

    ``abstained`` is the safety valve: when the model cannot ground an answer in
    the user's facts file we do NOT submit anything. The caller skips the job.
    """

    answer: Optional[Answer] = None
    abstained: bool = False
    reason: str = ""

    @classmethod
    def abstain(cls, reason: str) -> "AnswerResolution":
        return cls(answer=None, abstained=True, reason=reason)

    @classmethod
    def resolved(cls, answer: Answer) -> "AnswerResolution":
        return cls(answer=answer, abstained=False, reason="")


@dataclass
class ChatbotOutcome:
    completed: bool = False     # questionnaire reached a submitted state
    answered: int = 0
    abstained: int = 0
    reason: str = ""


# ---------------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------------


@dataclass
class Profile:
    """The user's ground truth.

    Resume-derived fields are populated from the resume; the negotiation fields
    (CTC, notice period, work authorization) do NOT appear in any resume and can
    only come from the YAML facts file. They stay Optional on purpose: an absent
    value must cause an abstain, never an inferred guess.
    """

    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""

    current_location: str = ""
    preferred_locations: List[str] = field(default_factory=list)

    total_experience_years: Optional[float] = None
    current_ctc_lpa: Optional[float] = None
    expected_ctc_lpa: Optional[float] = None
    notice_period_days: Optional[int] = None
    serving_notice: Optional[bool] = None
    willing_to_relocate: Optional[bool] = None
    work_authorization: str = ""
    has_passport: Optional[bool] = None
    highest_qualification: str = ""

    skills: List[str] = field(default_factory=list)
    titles: List[str] = field(default_factory=list)

    resume_text: str = ""
    #: Free-form extra facts from the YAML, surfaced to the LLM verbatim.
    extra_facts: Dict[str, Any] = field(default_factory=dict)

    def known_facts(self) -> Dict[str, Any]:
        """Only the facts that are actually known.

        This is what gets sent to the LLM. Absent fields are omitted rather than
        sent as null, so the model is never tempted to fill in a blank.
        """
        candidate: Dict[str, Any] = {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "current_location": self.current_location,
            "preferred_locations": self.preferred_locations,
            "total_experience_years": self.total_experience_years,
            "current_ctc_lpa": self.current_ctc_lpa,
            "expected_ctc_lpa": self.expected_ctc_lpa,
            "notice_period_days": self.notice_period_days,
            "serving_notice": self.serving_notice,
            "willing_to_relocate": self.willing_to_relocate,
            "work_authorization": self.work_authorization,
            "has_passport": self.has_passport,
            "highest_qualification": self.highest_qualification,
            "skills": self.skills,
            "titles": self.titles,
        }
        known: Dict[str, Any] = {}
        for key, value in candidate.items():
            if value is None:
                continue
            if isinstance(value, (str, list, dict)) and len(value) == 0:
                continue
            known[key] = value
        for key, value in self.extra_facts.items():
            if value is not None:
                known[key] = value
        return known


# ---------------------------------------------------------------------------
# Runtime settings
# ---------------------------------------------------------------------------


class AnswerMode:
    AUTO = "auto"        # submit grounded answers without asking
    PROPOSE = "propose"  # log what would be submitted, then abstain
    ASK = "ask"          # pause for the human on every unknown question


class LLMBackend:
    CLAUDE_CLI = "claude-cli"
    ANTHROPIC = "anthropic"
    NONE = "none"


@dataclass
class Settings:
    email: str = ""
    password: str = ""

    profile_path: str = "profile.yaml"
    resume_path: str = ""
    db_path: str = "naukri_bot.db"

    daily_quota: int = 50
    target_applications: int = 50
    max_candidates: int = 400
    llm_rank_top_n: int = 150
    min_score: float = 55.0
    max_days_old: int = 7
    # Fallback tiers, used only when the preferred tier cannot fill
    # target_applications. A floor of 0 disables the tier entirely.
    min_score_floor: float = 50.0
    max_days_old_fallback: int = 14
    # Stops one prolific poster's near-duplicate listings from taking a
    # large share of the day's applications. 0 disables the cap.
    max_per_company: int = 3
    # Jobs per LLM ranking call. Larger batches mean fewer sequential calls
    # and a much shorter run, at the cost of a bigger prompt per call.
    llm_rank_batch_size: int = 20

    keywords: List[str] = field(default_factory=list)
    location: str = ""
    pages_per_keyword: int = 3

    headless: bool = False
    dry_run: bool = False

    llm_backend: str = LLMBackend.CLAUDE_CLI
    llm_model: str = ""
    llm_timeout_s: int = 90
    answer_mode: str = AnswerMode.AUTO

    def validate(self) -> List[str]:
        """Return a list of human-readable problems; empty means usable."""
        problems: List[str] = []
        if not self.email:
            problems.append("NAUKRI_EMAIL is not set")
        if not self.password:
            problems.append("NAUKRI_PASSWORD is not set")
        if self.target_applications > self.daily_quota:
            problems.append(
                "target_applications (%d) exceeds daily_quota (%d)"
                % (self.target_applications, self.daily_quota)
            )
        if self.answer_mode not in (AnswerMode.AUTO, AnswerMode.PROPOSE, AnswerMode.ASK):
            problems.append("unknown answer_mode: %s" % self.answer_mode)
        return problems


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@dataclass
class LoginResult:
    ok: bool = False
    reason: str = ""
    #: True when a human must intervene (captcha / OTP), as opposed to a
    #: recoverable failure such as a slow page.
    needs_manual: bool = False


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------


@dataclass
class RunSummary:
    collected: int = 0
    ranked: int = 0
    attempted: int = 0
    applied: int = 0
    skipped_already_applied: int = 0
    skipped_external: int = 0
    skipped_abstained: int = 0
    errors: int = 0
    quota_before: int = 0
    quota_after: int = 0
    results: List[ApplyResult] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    finished_at: str = ""


__all__ = [
    "Answer",
    "AnswerMode",
    "AnswerResolution",
    "AnswerSource",
    "ApplyResult",
    "ApplyStatus",
    "ChatbotOutcome",
    "JobPosting",
    "LLMBackend",
    "LoginResult",
    "Profile",
    "RunSummary",
    "ScoredJob",
    "Settings",
    "Verdict",
]
