"""Optional LLM integrations for ranking jobs and grounding answers."""

import json
import logging
import math
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    Answer,
    AnswerResolution,
    AnswerSource,
    JobPosting,
    LLMBackend,
    Profile,
    Settings,
)


logger = logging.getLogger(__name__)


def _snippet(text: str, limit: int = 300) -> str:
    return " ".join(text.split())[:limit]


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first balanced JSON object from mixed model output."""
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


class LLMClient:
    """Small interface shared by optional LLM backends."""

    def available(self) -> bool:
        return False

    def complete_json(
        self, prompt: str, schema_hint: str
    ) -> Optional[Dict[str, Any]]:
        return None


class ClaudeCLIClient(LLMClient):
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()

    def available(self) -> bool:
        """Report whether the claude executable can be found.

        A run once reported the CLI present at startup and missing six minutes
        later in the same process, which silently downgraded ranking to lexical
        scoring. The cause was never identified, so this records what the lookup
        actually saw rather than leaving the next occurrence equally opaque.
        """
        found = shutil.which("claude")
        if found is None:
            logger.warning(
                "claude executable not found; PATH=%s",
                os.environ.get("PATH", "<unset>"),
            )
            return False
        return True

    def complete_json(
        self, prompt: str, schema_hint: str
    ) -> Optional[Dict[str, Any]]:
        full_prompt = (
            "%s\n\nRequired JSON shape:\n%s\n\n"
            "Reply with ONE valid JSON object and nothing else."
        ) % (prompt, schema_hint)
        for attempt in range(2):
            request = full_prompt
            if attempt:
                request += "\nYour prior reply could not be parsed. Reply with JSON only."
            try:
                completed = subprocess.run(
                    ["claude", "-p", request],
                    capture_output=True,
                    text=True,
                    timeout=self.settings.llm_timeout_s,
                )
            except subprocess.TimeoutExpired as error:
                output = error.stdout or error.stderr or ""
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                logger.warning(
                    "Claude CLI timed out; output=%r", _snippet(output)
                )
                return None
            except OSError as error:
                logger.warning("Claude CLI could not be run: %s", error)
                return None

            combined = completed.stdout or completed.stderr or ""
            if completed.returncode != 0:
                logger.warning(
                    "Claude CLI exited with code %s; output=%r",
                    completed.returncode,
                    _snippet(combined),
                )
                return None

            parsed = _extract_json(completed.stdout)
            if parsed is not None:
                return parsed
            logger.warning(
                "Claude CLI returned unparseable JSON (attempt %d); output=%r",
                attempt + 1,
                _snippet(completed.stdout),
            )
        return None


class AnthropicClient(LLMClient):
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()

    def available(self) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def complete_json(
        self, prompt: str, schema_hint: str
    ) -> Optional[Dict[str, Any]]:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            import anthropic
        except ImportError:
            logger.warning("Anthropic package is not installed")
            return None

        model = self.settings.llm_model or "claude-haiku-4-5-20251001"
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        base_prompt = (
            "%s\n\nRequired JSON shape:\n%s\n\n"
            "Reply with ONE valid JSON object and nothing else."
        ) % (prompt, schema_hint)
        for attempt in range(2):
            request = base_prompt
            if attempt:
                request += "\nYour prior reply could not be parsed. Reply with JSON only."
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": request}],
                    timeout=self.settings.llm_timeout_s,
                )
            except (anthropic.APIError, OSError) as error:
                logger.warning("Anthropic request failed: %s", error)
                return None

            text_parts = [
                block.text
                for block in response.content
                if getattr(block, "type", "") == "text"
            ]
            output = "\n".join(text_parts)
            parsed = _extract_json(output)
            if parsed is not None:
                return parsed
            logger.warning(
                "Anthropic returned unparseable JSON (attempt %d); output=%r",
                attempt + 1,
                _snippet(output),
            )
        return None


class NullClient(LLMClient):
    def available(self) -> bool:
        return False

    def complete_json(
        self, prompt: str, schema_hint: str
    ) -> Optional[Dict[str, Any]]:
        return None


def build_client(settings: Settings) -> LLMClient:
    if settings.llm_backend == LLMBackend.NONE:
        return NullClient()

    if settings.llm_backend == LLMBackend.ANTHROPIC:
        anthropic_client = AnthropicClient(settings)
        if anthropic_client.available():
            return anthropic_client
        logger.warning(
            "Requested Anthropic backend is unavailable; falling back to NullClient"
        )
        return NullClient()

    if settings.llm_backend == LLMBackend.CLAUDE_CLI:
        cli_client = ClaudeCLIClient(settings)
        if cli_client.available():
            return cli_client
        logger.warning(
            "Requested Claude CLI backend is unavailable; falling back to NullClient"
        )
        return NullClient()

    logger.warning(
        "Unknown LLM backend %r; falling back to NullClient", settings.llm_backend
    )
    return NullClient()


def score_jobs(
    client: LLMClient, profile: Profile, jobs: List[JobPosting]
) -> Dict[str, Dict[str, Any]]:
    if not client.available():
        return {}

    candidate = {
        "titles": profile.titles,
        "skills": profile.skills,
        "total_experience_years": profile.total_experience_years,
        "preferred_locations": profile.preferred_locations,
        "resume_excerpt": profile.resume_text[:2500],
    }
    results: Dict[str, Dict[str, Any]] = {}
    schema = (
        '{"jobs": [{"job_id": "...", "score": 0, '
        '"verdict": "strong|possible|weak", "reasons": ["..."]}]}'
    )
    # score_jobs takes no settings; the client carries them.
    batch_size = max(
        1, getattr(getattr(client, "settings", None), "llm_rank_batch_size", 20)
    )
    for start in range(0, len(jobs), batch_size):
        batch = jobs[start : start + batch_size]
        allowed_ids = {job.job_id for job in batch}
        payload = [
            {
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "experience": job.experience,
                "salary": job.salary,
                "description": job.description[:400],
                "tags": job.tags,
            }
            for job in batch
        ]
        prompt = (
            "Score each job from 0 to 100 for this candidate. Penalise experience "
            "mismatch (especially jobs wanting 8+ years for a roughly 2.5-year "
            "candidate), wrong domain, and non-preferred locations. Reward LLM, "
            "AI, ML, agent, evaluation, and RAG roles. Return one entry per job.\n"
            "Candidate: %s\nJobs: %s"
        ) % (json.dumps(candidate, ensure_ascii=True), json.dumps(payload, ensure_ascii=True))
        response = client.complete_json(prompt, schema)
        if response is None:
            continue
        entries = response.get("jobs")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            job_id = entry.get("job_id")
            if not isinstance(job_id, str) or job_id not in allowed_ids:
                continue
            try:
                score = float(entry.get("score"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(score):
                continue
            verdict = entry.get("verdict")
            if verdict not in ("strong", "possible", "weak"):
                verdict = "weak"
            reasons_value = entry.get("reasons")
            reasons = (
                [reason for reason in reasons_value if isinstance(reason, str)]
                if isinstance(reasons_value, list)
                else []
            )
            results[job_id] = {
                "score": max(0.0, min(100.0, score)),
                "verdict": verdict,
                "reasons": reasons,
            }
    return results


def _normalise_space(value: str) -> str:
    return " ".join(value.split()).casefold()


def _grounding_matches(grounded_in: str, fact_keys: List[str]) -> bool:
    normalised_grounding = "".join(
        character for character in grounded_in.casefold() if character.isalnum()
    )
    return any(
        "".join(character for character in key.casefold() if character.isalnum())
        in normalised_grounding
        for key in fact_keys
    )


def _abstain(question: str, reason: str) -> AnswerResolution:
    logger.info("Abstaining from question %r: %s", question, reason)
    return AnswerResolution.abstain(reason)


def resolve_selection(
    client: LLMClient,
    profile: Profile,
    question: str,
    options: List[str],
) -> Tuple[Optional[List[str]], str]:
    """Choose every option that applies, for a select-all-that-apply question.

    Returns (selected options, reason). The selections are returned exactly as
    rendered, so the caller can match them back to controls. A single-answer
    resolution cannot serve here: the checkbox handler used to resolve one
    answer and tick one box, which makes a genuine multi-select unanswerable.
    """
    if not client.available():
        return None, "llm_unavailable"
    if not options:
        return None, "no_options_rendered"

    facts = profile.known_facts()
    if profile.resume_text:
        facts["resume"] = profile.resume_text[:6000]
    prompt = (
        "This question allows more than one answer. Choose EVERY supplied option "
        "that is true for this candidate, using ONLY the supplied facts. Copy "
        "each chosen option exactly as given. Choose none if the facts do not "
        "support any. Never infer and never estimate.\nInput: %s"
    ) % json.dumps(
        {"facts": facts, "question": question, "options": options},
        ensure_ascii=True,
    )
    schema = '{"selected": ["..."], "grounded_in": "", "confidence": 0.0}'
    response = client.complete_json(prompt, schema)
    if response is None:
        return None, "llm_no_response"

    raw = response.get("selected")
    if not isinstance(raw, list):
        return None, "llm_no_selection"

    lookup = {_normalise_space(option).casefold(): option for option in options}
    chosen: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        matched = lookup.get(_normalise_space(item).casefold())
        if matched is not None and matched not in chosen:
            chosen.append(matched)
    if not chosen:
        return None, "llm_selected_nothing" if raw == [] else "llm_selection_not_in_options"

    grounded = response.get("grounded_in")
    if not isinstance(grounded, str) or not grounded.strip():
        return None, "ungrounded"
    if not _grounding_matches(grounded, list(facts.keys())):
        return None, "grounding_not_verifiable"
    return chosen, ""


def resolve_answer(
    client: LLMClient,
    profile: Profile,
    question: str,
    options: Optional[List[str]] = None,
    prior: Optional[Dict[str, str]] = None,
) -> AnswerResolution:
    if not client.available():
        return _abstain(question, "llm_unavailable")

    facts = profile.known_facts()
    if profile.resume_text:
        facts["resume"] = profile.resume_text[:6000]
    request: Dict[str, Any] = {"facts": facts, "question": question}
    if options:
        request["options"] = options
    if prior:
        request["prior_answers"] = prior
    prompt = (
        "Answer ONLY from the supplied facts. If the facts do not contain what "
        "is needed, you MUST abstain. Never estimate, never infer, never use a "
        "typical or common value. grounded_in must name the exact supplied fact "
        "key supporting the answer. For options, copy one option exactly.\nInput: %s"
    ) % json.dumps(request, ensure_ascii=True)
    schema = (
        '{"can_answer": false, "answer": "", "grounded_in": "", '
        '"confidence": 0.0}'
    )
    response = client.complete_json(prompt, schema)
    if response is None:
        return _abstain(question, "llm_no_response")

    if response.get("can_answer") is not True:
        stated_reason = response.get("answer") or response.get("grounded_in")
        reason = stated_reason.strip() if isinstance(stated_reason, str) else "llm_abstained"
        return _abstain(question, reason or "llm_abstained")

    answer_value = response.get("answer")
    grounded_value = response.get("grounded_in")
    if not isinstance(answer_value, str) or not answer_value.strip():
        return _abstain(question, "empty_answer")
    if not isinstance(grounded_value, str) or not grounded_value.strip():
        return _abstain(question, "ungrounded")
    if not _grounding_matches(grounded_value, list(facts.keys())):
        return _abstain(question, "grounding_not_verifiable")

    try:
        confidence = float(response.get("confidence"))
    except (TypeError, ValueError):
        return _abstain(question, "invalid_confidence")
    if not math.isfinite(confidence) or confidence < 0.6:
        return _abstain(question, "low_confidence")
    confidence = min(confidence, 1.0)

    answer_text = answer_value.strip()
    # `options` empty rather than None means the page offered choices and none
    # could be scraped. Matching against nothing rejected every answer, so the
    # walk-in and salutation questions abstained with a fact sitting right there.
    if options:
        option_lookup = {
            _normalise_space(option).casefold(): option for option in options
        }
        matched_option = option_lookup.get(_normalise_space(answer_text).casefold())
        if matched_option is None:
            return _abstain(question, "llm_answer_not_in_options")
        answer_text = matched_option

    if len(answer_text) > 600:
        logger.warning("Truncating overlong LLM answer for question %r", question)
        answer_text = answer_text[:600]

    return AnswerResolution.resolved(
        Answer(
            text=answer_text,
            grounded_in=grounded_value.strip(),
            source=AnswerSource.LLM,
            confidence=confidence,
        )
    )


__all__ = [
    "AnthropicClient",
    "ClaudeCLIClient",
    "LLMClient",
    "NullClient",
    "build_client",
    "resolve_answer",
    "score_jobs",
]
