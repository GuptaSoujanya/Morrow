"""Fail-closed screening answer resolution."""

import hashlib
import json
import logging
import difflib
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from . import llm
from .llm import LLMClient
from .models import (
    Answer,
    AnswerMode,
    AnswerResolution,
    AnswerSource,
    Profile,
    Settings,
)

if TYPE_CHECKING:
    from .ledger import Ledger


logger = logging.getLogger(__name__)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _number_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_UNANSWERED_FILE = "data/worklists/unanswered_questions.md"
_seen_unanswered = set()
_unanswered_loaded = False

_ANSWERS_FILE_NAME = "answers.txt"
_FUZZY_MATCH_RATIO = 0.9
# An answer written like this in answers.txt is never sent as it stands: the AI
# writes a fresh one for every posting from the resume and that posting.
PER_JOB = "[AI writes this for each job]"
_LISTED_OPTIONS = 12
_book = None  # type: Optional[AnswerBook]


def answers_file_path(settings: Any) -> str:
    return os.path.join(getattr(settings, "data_dir", "") or "data/inputs", _ANSWERS_FILE_NAME)


def _question_key(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def parse_answers(text: str) -> List[Tuple[List[str], str]]:
    """(questions, answer) blocks of a Q:/A: file; an answer left blank stays ""."""
    entries = []  # type: List[Tuple[List[str], str]]
    questions = []  # type: List[str]
    answer_parts = None  # type: Optional[List[str]]

    def flush() -> None:
        if questions:
            answer = " ".join(part for part in (answer_parts or []) if part)
            entries.append((list(questions), answer.strip()))
        del questions[:]

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not line:
            flush()
            answer_parts = None
            continue
        tag = line[:2].upper()
        if tag == "Q:":
            if answer_parts is not None:
                flush()
                answer_parts = None
            questions.append(line[2:].strip())
        elif tag == "A:":
            if answer_parts is None:
                answer_parts = []
            answer_parts.append(line[2:].strip())
        elif answer_parts is not None:
            answer_parts.append(line)
    flush()
    return entries


def _word_contains(text: str, part: str) -> bool:
    return (" %s " % part) in (" %s " % text)


def match_option(answer: str, options: List[str]) -> Optional[str]:
    """The rendered option the user's answer names, or None when none or several do."""
    wanted = _question_key(answer)
    if not wanted:
        return None
    keyed = [(option, _question_key(option)) for option in options]
    for option, key in keyed:
        if key and key == wanted:
            return option
    first = wanted.split()[0]
    if first in ("yes", "no"):
        for option, key in keyed:
            if key == first:
                return option
    containing = [
        option
        for option, key in keyed
        if key and (_word_contains(wanted, key) or _word_contains(key, wanted))
    ]
    return containing[0] if len(containing) == 1 else None


def match_options(answer: str, options: List[str]) -> Optional[List[str]]:
    """Every option named in a comma-separated answer, in rendered order, or None."""
    parts = [part for part in re.split(r"[,;/]| and ", answer) if part.strip()]
    chosen = []  # type: List[str]
    for part in parts:
        option = match_option(part, options)
        if option is None:
            return None
        if option not in chosen:
            chosen.append(option)
    return [option for option in options if option in chosen] or None


class AnswerBook:
    """The user's own answers in data/inputs/answers.txt, and the questions left for them."""

    def __init__(self, path: str):
        self.path = path
        self.entries = []  # type: List[Tuple[List[str], str]]
        self._by_key = {}  # type: Dict[str, str]
        self._loaded_mtime = None  # type: Optional[float]
        self.reload()

    def reload(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                text = handle.read()
            mtime = os.path.getmtime(self.path)  # type: Optional[float]
        except OSError:
            text, mtime = "", None
        self.entries = parse_answers(text)
        self._loaded_mtime = mtime
        self._by_key = {}
        for questions, answer in self.entries:
            for question in questions:
                self._by_key.setdefault(_question_key(question), answer)

    def _refresh_if_changed(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)  # type: Optional[float]
        except OSError:
            mtime = None
        if mtime != self._loaded_mtime:
            self.reload()

    def answer_for(self, question: str) -> Optional[str]:
        """The user's answer, or None when the question is unknown, blank or written per job."""
        answer = self._lookup(question)
        return None if answer is None or _is_per_job(answer) else answer

    def per_job(self, question: str) -> bool:
        """Whether the user asked for this one to be written fresh for every posting."""
        answer = self._lookup(question)
        return answer is not None and _is_per_job(answer)

    def _lookup(self, question: str) -> Optional[str]:
        self._refresh_if_changed()
        key = _question_key(question)
        if not key:
            return None
        answer = self._by_key.get(key)
        if answer is None:
            best, best_ratio = "", 0.0
            for candidate, candidate_answer in self._by_key.items():
                ratio = difflib.SequenceMatcher(None, key, candidate).ratio()
                if ratio > best_ratio:
                    best, best_ratio = candidate_answer, ratio
            if best_ratio >= _FUZZY_MATCH_RATIO:
                answer = best
        return answer or None

    def blank_questions(self) -> List[str]:
        return [questions[0] for questions, answer in self.entries if not answer]

    def add_blank(
        self,
        question: str,
        reason: str,
        options: Optional[List[str]] = None,
        context: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Append the question with an empty A: unless the file already lists it."""
        self._refresh_if_changed()
        key = _question_key(question)
        if not key or key in self._by_key:
            return False
        where = ""
        if context and (context.get("title") or context.get("company")):
            where = " | while applying to %s at %s" % (
                context.get("title") or "a role",
                context.get("company") or "an employer",
            )
        shown = ""
        if options:
            # A university or country list runs to thousands; a sample says what kind of answer fits.
            shown = " | options: %s" % (list(options[:_LISTED_OPTIONS]),)
            if len(options) > _LISTED_OPTIONS:
                shown += " and %d more" % (len(options) - _LISTED_OPTIONS)
        block = "\n# %s%s | %s%s\nQ: %s\nA:\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            where,
            reason,
            shown,
            " ".join(question.split()),
        )
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(block)
            self._loaded_mtime = os.path.getmtime(self.path)
        except OSError as exc:
            logger.warning("Could not add the question to %s: %s", self.path, exc)
            return False
        self.entries.append(([question], ""))
        self._by_key[key] = ""
        return True


def _is_per_job(answer: str) -> bool:
    return " ".join(answer.split()).casefold() == PER_JOB.casefold()


def install_answer_book(settings: Any) -> AnswerBook:
    global _book
    _book = AnswerBook(answers_file_path(settings))
    return _book


def _record_unanswered(
    question: str, reason: str, options=None, context: Optional[Dict[str, str]] = None
) -> None:
    global _unanswered_loaded

    key = " ".join(question.split()).casefold()
    if not key or key == "unidentified chatbot question":
        return

    if _book is not None:
        _book.add_blank(question, reason, options, context)

    if not _unanswered_loaded:
        _unanswered_loaded = True
        try:
            with open(_UNANSWERED_FILE, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("- ["):
                        text = line.split("] ", 1)[-1].rsplit(" -- ", 1)[0]
                        _seen_unanswered.add(" ".join(text.split()).casefold())
        except OSError:
            pass

    if key in _seen_unanswered:
        return
    _seen_unanswered.add(key)

    try:
        os.makedirs(os.path.dirname(_UNANSWERED_FILE), exist_ok=True)
        with open(_UNANSWERED_FILE, "a", encoding="utf-8") as handle:
            handle.write(
                "- [%s] %s -- %s%s\n"
                % (
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    " ".join(question.split()),
                    reason,
                    " | options: %s" % (options,) if options else "",
                )
            )
    except OSError as exc:
        logger.warning("Could not write %s: %s", _UNANSWERED_FILE, exc)


def _used_job_context(resolution: AnswerResolution) -> bool:
    """Did the answer rest on a job_* fact rather than the profile alone?"""
    answer = resolution.answer
    if answer is None:
        return False
    return any(
        part.strip().startswith("job_")
        for part in _normalise(answer.grounded_in or "").replace(",", " ").split()
    )


def _profile_fingerprint(profile: Profile) -> str:
    payload = json.dumps(profile.known_facts(), sort_keys=True, default=str)
    payload += profile.resume_text or ""
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def facts_fingerprint(profile: Profile, settings: Any) -> str:
    """Changes when you fill a fact or an answer, not when the bot adds a blank question."""
    book = AnswerBook(answers_file_path(settings))
    answered = sorted([sorted(questions), answer] for questions, answer in book.entries if answer)
    payload = _profile_fingerprint(profile) + json.dumps(answered)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# Questions where a guess is a false declaration or private: always left to you.
_NOT_FOR_JUDGEMENT = re.compile(
    r"\b(gender|sex|marital|religio\w*|caste|race|ethnic\w*|veteran|disabilit\w*"
    r"|criminal|convict\w*|visa|sponsor\w*|citizen\w*|permanent resident"
    r"|authori[sz]ed to work|work authori[sz]ation|right to work|pan|aadhaa?r"
    r"|passport number|ssn|social security|bank|account number)\b",
    re.I,
)

_SKILL_YEARS_RE = re.compile(
    r"(how many years|years of (experience|exp)\b|relevant experience"
    r"|experience in years|yrs of (experience|exp)\b)"
)


class AnswerEngine:
    def __init__(
        self,
        ledger: Any,
        client: LLMClient,
        profile: Profile,
        settings: Settings,
    ):
        self.ledger = ledger
        self.client = client
        self.profile = profile
        self.settings = settings
        self.answered = 0
        self.abstained = 0
        self.profile_fingerprint = _profile_fingerprint(profile)
        self.job_context: Dict[str, str] = {}
        self.job = None  # type: Any
        self.book = install_answer_book(settings)

    def set_job_context(self, job: Any) -> None:
        """Note which posting the next questions belong to.

        A question can name no place and still have one: "Will you attend the
        walk-in?" means the employer's own location. Without this the model has
        nothing to resolve it against and abstains, which skips the job.
        """
        self.job = job
        self.job_context = {
            key: value
            for key, value in (
                ("location", getattr(job, "location", "") or ""),
                ("title", getattr(job, "title", "") or ""),
                ("company", getattr(job, "company", "") or ""),
            )
            if value
        }

    def resolve(
        self,
        question: str,
        options: Optional[List[str]] = None,
        field_type: str = "text",
    ) -> AnswerResolution:
        self._current_options = options
        if not options and self.book.per_job(question):
            return self._write_for_job(question, field_type)
        own = self._own_answer(question, options)
        if own is not None:
            return self._accept(question, own, field_type, persist=False)
        cached = self.ledger.get_answer(question, self.profile_fingerprint)
        cached_answer = self._cached_answer(cached)
        if cached_answer is not None:
            if options is None or self._exact_option(cached_answer.text, options) is not None:
                if options is not None:
                    cached_answer.text = self._exact_option(cached_answer.text, options) or ""
                return self._accept(
                    question,
                    AnswerResolution.resolved(cached_answer),
                    field_type,
                    persist=False,
                )

        direct = self._profile_answer(question, options)
        if direct is not None:
            if direct.abstained:
                return self._finish(question, direct, False)
            return self._accept(question, direct, field_type, persist=True)

        llm_resolution = llm.resolve_answer(
            self.client,
            self.profile,
            question,
            options=options,
            job_context=self.job_context,
        )
        if llm_resolution.abstained:
            judged = self._judge(question, options)
            if judged is None:
                return self._finish(question, llm_resolution, False)
            return self._accept(question, judged, field_type, persist=False)
        if self.settings.answer_mode == AnswerMode.ASK:
            return self._finish(
                question, AnswerResolution.abstain("ask_mode_llm_answer"), False
            )
        # An answer that leaned on the posting is true of that posting only.
        # Cached, "Yes" to a walk-in at a Noida employer would be replayed to a
        # Chennai one, since the cache is keyed on the question text and the
        # profile fingerprint -- neither of which changes between jobs.
        persist = not _used_job_context(llm_resolution)
        if not persist:
            logger.info(
                "Not caching the answer to %r: it depends on this posting (%s)",
                question,
                llm_resolution.answer.grounded_in if llm_resolution.answer else "",
            )
        return self._accept(question, llm_resolution, field_type, persist=persist)

    def _judge(
        self, question: str, options: Optional[List[str]]
    ) -> Optional[AnswerResolution]:
        """The model's honest inference for a question no fact answers, or None."""
        if not self.settings.judge_answers or self.settings.answer_mode != AnswerMode.AUTO:
            return None
        from . import assist  # assist imports this module, so not at the top

        if _NOT_FOR_JUDGEMENT.search(question) or assist._OWN_WORDS.search(question):
            return None
        texts = assist.sources(self.settings, self.profile, self.book)
        candidate_text = "\n\n".join(
            "%s:\n%s" % (name.upper(), text) for name, text in texts.items() if text
        )
        judged = llm.judge_answer(
            self.client, question, candidate_text, options=options, job_context=self.job_context
        )
        if judged is None:
            return None
        answer = judged["answer"]
        skill = assist._SKILL_YEARS.search(question)
        if skill and not llm.claims_nothing(answer):
            total = self.profile.total_experience_years
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", answer)]
            if not assist._named_anywhere(skill.group(1), candidate_text.casefold()):
                logger.info("Refused %r for %r: the skill is named nowhere in your files", answer, question)
                return None
            if total is not None and any(n > float(total) for n in numbers):
                logger.info("Refused %r for %r: more than your %s years in total", answer, question, total)
                return None
        logger.info("[judged] %s -> %s (%s)", question, answer, judged["reason"])
        self._keep_judged(question, answer, judged, saved=not options and not judged["depends_on_posting"])
        return AnswerResolution.resolved(
            Answer(
                text=answer,
                grounded_in="judged: %s" % judged["reason"],
                source=AnswerSource.LLM,
                confidence=0.6,
            )
        )

    def _keep_judged(self, question: str, answer: str, judged: Dict[str, Any], saved: bool) -> None:
        """Write a typed judged answer into answers.txt; note every judgement for the report.

        A pick from one form's list ("Other", "10 - 20 LPA") is not saved: replayed
        as typed text on another form it would be wrong.
        """
        from . import assist

        where = ""
        if self.job_context.get("company"):
            where = " while applying to %s at %s" % (
                self.job_context.get("title") or "a role",
                self.job_context["company"],
            )
        note = "AI judged this on %s%s: %s. Change it if it is wrong." % (
            datetime.now().strftime("%Y-%m-%d"),
            where,
            judged["reason"].rstrip("."),
        )
        self.book._refresh_if_changed()
        key = _question_key(question)
        if saved and self.book._by_key.get(key):
            saved = False
        if saved:
            try:
                with open(self.book.path, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                text = ""
            updated = assist.fill_answer(text, question, answer, note) if key in self.book._by_key else None
            if updated is None:
                updated = text + "\n# %s\nQ: %s\nA: %s\n" % (note, " ".join(question.split()), answer)
            try:
                os.makedirs(os.path.dirname(self.book.path) or ".", exist_ok=True)
                with open(self.book.path, "w", encoding="utf-8") as handle:
                    handle.write(updated)
                self.book.reload()
            except OSError as exc:
                logger.warning("Could not write the judged answer to %s: %s", self.book.path, exc)
                saved = False
        try:
            assist.record_change(
                self.settings,
                assist.Change(
                    file=self.book.path if saved else "this application only",
                    item=" ".join(question.split()),
                    value=answer,
                    source="judgement",
                    evidence=judged["evidence"] or judged["reason"],
                    kind="judged",
                ),
            )
        except OSError as exc:
            logger.warning("Could not record the judged answer: %s", exc)

    def _write_for_job(self, question: str, field_type: str) -> AnswerResolution:
        """A fresh answer for this posting, from the resume and the posting only."""
        from . import assist
        from . import resume

        text = None  # type: Optional[str]
        if self.job is not None and self.client.available():
            try:
                base = resume.load_base(self.settings.resume_path)
            except resume.ResumeError as exc:
                logger.info("Cannot write %r for this job: %s", question, exc)
            else:
                text = resume.write_long_answer(
                    self.client, base, self.job, question, max_chars=llm.JUDGED_MAX_CHARS
                )
        if text is None:
            return self._finish(
                question, AnswerResolution.abstain("the AI could not write it for this job"), False
            )
        company = getattr(self.job, "company", "") or "this company"
        logger.info("[written for %s] %s -> %s", company, question, text)
        assist.record_change(self.settings, assist.Change(
            file="this application only", item=" ".join(question.split()), value=text,
            source="resume and the %s posting" % company, evidence="", kind="written"))
        return self._accept(
            question,
            AnswerResolution.resolved(Answer(
                text=text,
                grounded_in="written for %s from your resume and the posting" % company,
                source=AnswerSource.LLM,
                confidence=0.8,
            )),
            field_type,
            persist=False,
        )

    def own_answer(self, question: str, options: Optional[List[str]] = None) -> Optional[str]:
        """The answer from data/inputs/answers.txt alone: no cache, no model, nothing recorded."""
        resolution = self._own_answer(question, options)
        if resolution is None or resolution.answer is None:
            return None
        return resolution.answer.text

    def _own_answer(
        self, question: str, options: Optional[List[str]]
    ) -> Optional[AnswerResolution]:
        """What the user wrote in data/inputs/answers.txt, when it fits the rendered options."""
        text = self.book.answer_for(question)
        if text is None:
            return None
        if options is not None:
            matched = match_option(text, options)
            if matched is None:
                logger.info(
                    "Your answer %r to %r names none of the options %s; trying the "
                    "other sources",
                    text,
                    question,
                    options,
                )
                return None
            text = matched
        return AnswerResolution.resolved(
            Answer(
                text=text,
                grounded_in="data/inputs/answers.txt",
                source=AnswerSource.DATA,
                confidence=1.0,
            )
        )

    def _accept(
        self,
        question: str,
        resolution: AnswerResolution,
        field_type: str,
        persist: bool,
    ) -> AnswerResolution:
        answer = resolution.answer
        if answer is None:
            return self._finish(
                question, AnswerResolution.abstain("missing_resolved_answer"), False
            )
        if self.settings.answer_mode == AnswerMode.PROPOSE:
            logger.info("[PROPOSE] %s -> %s", question, answer.text)
            return self._finish(
                question, AnswerResolution.abstain("propose_mode"), False
            )
        if persist:
            self.ledger.save_answer(
                question, answer, field_type, self.profile_fingerprint
            )
        return self._finish(question, resolution, False)

    def resolve_many(
        self, question: str, options: List[str]
    ) -> Tuple[Optional[List[str]], str]:
        """Resolve a select-all-that-apply question.

        Returns (selections, reason). Nothing is cached: the cache is keyed on a
        single answer string, and a partial hit would silently drop selections.
        Abstains are recorded like any other so the question reaches
        data/worklists/unanswered_questions.md.
        """
        self._current_options = options
        if not options:
            self._record_abstain(question, "no_options_rendered", options)
            return None, "no_options_rendered"

        own = self.book.answer_for(question)
        if own is not None:
            chosen = match_options(own, options)
            if chosen:
                self.answered += 1
                logger.info("[multi] %s -> %s (data/inputs/answers.txt)", question, chosen)
                return chosen, ""
            logger.info(
                "Your answer %r to %r names none of the options %s; asking the model",
                own,
                question,
                options,
            )

        selections, reason = llm.resolve_selection(
            self.client, self.profile, question, options
        )
        if selections is None:
            self.abstained += 1
            logger.info("Abstaining from question %r: %s", question, reason)
            _record_unanswered(question, reason, options, self.job_context)
            return None, reason
        self.answered += 1
        logger.info("[multi] %s -> %s", question, selections)
        return selections, ""

    def record_option_mismatch(
        self, question: str, answer_text: str, options: Optional[List[str]]
    ) -> None:
        """Note an answer that was resolved but matched none of the controls.

        This is not the same as being unable to answer, and reporting it as an
        abstain hid the difference: the fact was present and the rendering was
        the problem.
        """
        logger.warning(
            "Resolved answer %r matched none of the rendered options %s",
            answer_text,
            options,
        )
        _record_unanswered(
            question,
            "answer_%r_not_among_rendered_options" % answer_text,
            options,
            self.job_context,
        )

    def _record_abstain(
        self, question: str, reason: str, options: Optional[List[str]]
    ) -> None:
        self.abstained += 1
        logger.info("Abstaining from question %r: %s", question, reason)
        _record_unanswered(question, reason, options, self.job_context)

    def _finish(
        self, question: str, resolution: AnswerResolution, already_logged: bool
    ) -> AnswerResolution:
        if resolution.abstained:
            self.abstained += 1
            if not already_logged:
                logger.info(
                    "Abstaining from question %r: %s", question, resolution.reason
                )
            _record_unanswered(
                question,
                resolution.reason,
                getattr(self, "_current_options", None),
                self.job_context,
            )
        else:
            self.answered += 1
        return resolution

    @staticmethod
    def _cached_answer(cached: Any) -> Optional[Answer]:
        if isinstance(cached, Answer):
            return Answer(
                text=cached.text,
                grounded_in=cached.grounded_in,
                source=AnswerSource.CACHE,
                confidence=cached.confidence,
            )
        if isinstance(cached, str) and cached:
            return Answer(
                text=cached,
                grounded_in="exact_cache",
                source=AnswerSource.CACHE,
                confidence=1.0,
            )
        if isinstance(cached, dict):
            text = cached.get("text") or cached.get("answer")
            if isinstance(text, str) and text:
                return Answer(
                    text=text,
                    grounded_in="exact_cache",
                    source=AnswerSource.CACHE,
                    confidence=1.0,
                )
        return None

    @staticmethod
    def _exact_option(answer: str, options: List[str]) -> Optional[str]:
        wanted = _normalise(answer)
        for option in options:
            if _normalise(option) == wanted:
                return option
        return None

    def _profile_answer(
        self, question: str, options: Optional[List[str]]
    ) -> Optional[AnswerResolution]:
        normalised_question = _normalise(question)
        mappings: List[Tuple[Tuple[str, ...], str, str]] = [
            (("notice period",), "notice_period_days", "notice_period_days"),
            (("expected ctc", "expected salary"), "expected_ctc_lpa", "expected_ctc_lpa"),
            (("current ctc", "current salary"), "current_ctc_lpa", "current_ctc_lpa"),
            (("total experience", "overall experience"), "total_experience_years", "total_experience_years"),
            (("current location", "currently located"), "current_location", "current_location"),
            (("willing to relocate",), "willing_to_relocate", "willing_to_relocate"),
            (("passport",), "has_passport", "has_passport"),
            (("work authorization", "authorised to work", "authorized to work", "legally authorized", "legally authorised"), "work_authorization", "work_authorization"),
        ]
        for phrases, field_name, grounding in mappings:
            if not any(phrase in normalised_question for phrase in phrases):
                continue
            value = getattr(self.profile, field_name)
            if value is None or value == "":
                return AnswerResolution.abstain("profile_fact_missing:%s" % field_name)
            candidates = self._profile_candidates(field_name, value)
            text = candidates[0]
            if options is not None:
                text = ""
                for candidate in candidates:
                    matched = self._exact_option(candidate, options)
                    if matched is not None:
                        text = matched
                        break
                if not text:
                    return None
            return AnswerResolution.resolved(
                Answer(
                    text=text,
                    grounded_in=grounding,
                    source=AnswerSource.PROFILE,
                    confidence=1.0,
                )
            )
        return self._skill_years_answer(normalised_question, options)

    def _skill_years_answer(
        self, normalised_question: str, options: Optional[List[str]]
    ) -> Optional[AnswerResolution]:
        """Answer "how many years of experience in X" for any X, if configured.

        Reached only after the specific mappings above, so total and overall
        experience still answer from total_experience_years. This exists because
        the instruction cannot live in profile.yaml: resolve_answer tells the
        model to answer only from the supplied facts and never infer, and it
        rightly declines to claim years in a technology the resume never
        mentions. Stating the policy as a rule makes it the user's explicit
        choice rather than something coaxed out of the model.
        """
        years = self.settings.default_skill_experience_years
        if years <= 0:
            return None
        if not _SKILL_YEARS_RE.search(normalised_question):
            return None

        text = ("%g" % years)
        if options is not None:
            matched = None
            for candidate in (text, "%s years" % text, "%s year" % text):
                matched = self._exact_option(candidate, options)
                if matched is not None:
                    break
            if matched is None:
                return None  # let the LLM try to pick from the offered choices
            text = matched
        return AnswerResolution.resolved(
            Answer(
                text=text,
                grounded_in="default_skill_experience_years",
                source=AnswerSource.PROFILE,
                confidence=1.0,
            )
        )

    @staticmethod
    def _profile_candidates(field_name: str, value: Any) -> List[str]:
        if isinstance(value, bool):
            return ["Yes" if value else "No", "true" if value else "false"]
        text = _number_text(value)
        if field_name == "notice_period_days":
            return [text, "%s days" % text]
        if field_name in ("current_ctc_lpa", "expected_ctc_lpa"):
            return [text, "%s LPA" % text]
        if field_name == "total_experience_years":
            return [text, "%s years" % text]
        return [text]


__all__ = ["AnswerEngine"]
