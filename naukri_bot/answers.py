"""Fail-closed screening answer resolution."""

import hashlib
import json
import logging
import re
import os
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


_UNANSWERED_FILE = "unanswered_questions.md"
_seen_unanswered = set()
_unanswered_loaded = False


def _record_unanswered(question: str, reason: str, options=None) -> None:
    global _unanswered_loaded

    key = " ".join(question.split()).casefold()
    if not key or key == "unidentified chatbot question":
        return

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


def _profile_fingerprint(profile: Profile) -> str:
    payload = json.dumps(profile.known_facts(), sort_keys=True, default=str)
    payload += profile.resume_text or ""
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


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

    def resolve(
        self,
        question: str,
        options: Optional[List[str]] = None,
        field_type: str = "text",
    ) -> AnswerResolution:
        self._current_options = options
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
            self.client, self.profile, question, options=options
        )
        if llm_resolution.abstained:
            return self._finish(question, llm_resolution, False)
        if self.settings.answer_mode == AnswerMode.ASK:
            return self._finish(
                question, AnswerResolution.abstain("ask_mode_llm_answer"), False
            )
        return self._accept(question, llm_resolution, field_type, persist=True)

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
                question, resolution.reason, getattr(self, "_current_options", None)
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
