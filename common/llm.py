"""Optional LLM integrations for ranking jobs and grounding answers."""

import json
import logging
import math
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
    executable = "claude"
    label = "Claude CLI"

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()

    def _command(self, request: str, image: Optional[Path]) -> List[str]:
        # Read is the only tool it may use, and only inside the screenshot's folder.
        tool_args: List[str] = []
        if image is not None:
            tool_args = ["--allowedTools=Read", "--add-dir=%s" % image.parent]
        return ["claude", "-p", request] + tool_args

    def available(self) -> bool:
        """Report whether the claude executable can be found.

        A run once reported the CLI present at startup and missing six minutes
        later in the same process, which silently downgraded ranking to lexical
        scoring. The cause was never identified, so this records what the lookup
        actually saw rather than leaving the next occurrence equally opaque.
        """
        found = shutil.which(self.executable)
        if found is None:
            logger.warning(
                "%s executable not found; PATH=%s",
                self.executable,
                os.environ.get("PATH", "<unset>"),
            )
            return False
        return True

    def complete_json(
        self, prompt: str, schema_hint: str
    ) -> Optional[Dict[str, Any]]:
        return self._complete(prompt, schema_hint, None)

    def complete_json_with_image(
        self, prompt: str, schema_hint: str, image: Path
    ) -> Optional[Dict[str, Any]]:
        """complete_json, with a screenshot the CLI opens through its Read tool."""
        image = Path(image).resolve()
        prompt = (
            "First use the Read tool to look at the image %s: it is a screenshot "
            "of the page described below.\n\n%s"
        ) % (image, prompt)
        return self._complete(prompt, schema_hint, image)

    def _complete(
        self, prompt: str, schema_hint: str, image: Optional[Path]
    ) -> Optional[Dict[str, Any]]:
        full_prompt = (
            "%s\n\nRequired JSON shape:\n%s\n\n"
            "Reply with ONE valid JSON object and nothing else."
        ) % (prompt, schema_hint)
        # Without a closed stdin the CLI waits 3 seconds for piped input on every call.
        extra: Dict[str, Any] = {"stdin": subprocess.DEVNULL}
        if image is not None:
            extra["cwd"] = str(image.parent)
        for attempt in range(2):
            request = full_prompt
            if attempt:
                request += "\nYour prior reply could not be parsed. Reply with JSON only."
            try:
                completed = subprocess.run(
                    self._command(request, image),
                    capture_output=True,
                    text=True,
                    timeout=self.settings.llm_timeout_s,
                    **extra,
                )
            except subprocess.TimeoutExpired as error:
                output = error.stdout or error.stderr or ""
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                logger.warning(
                    "%s timed out; output=%r", self.label, _snippet(output)
                )
                return None
            except OSError as error:
                logger.warning("%s could not be run: %s", self.label, error)
                return None

            combined = completed.stdout or completed.stderr or ""
            if completed.returncode != 0:
                parsed = _extract_json(completed.stdout or "")
                if parsed is not None:
                    # Kiro has answered in full and then exited 1 on a chore of its own; the reply stands.
                    logger.warning(
                        "%s exited with code %s after a complete JSON reply; using the reply.",
                        self.label,
                        completed.returncode,
                    )
                    return parsed
                logger.warning(
                    "%s exited with code %s; output=%r",
                    self.label,
                    completed.returncode,
                    _snippet(combined),
                )
                return None

            parsed = _extract_json(completed.stdout)
            if parsed is not None:
                return parsed
            logger.warning(
                "%s returned unparseable JSON (attempt %d); output=%r",
                self.label,
                attempt + 1,
                _snippet(completed.stdout),
            )
        return None


class KiroCLIClient(ClaudeCLIClient):
    executable = "kiro-cli"
    label = "Kiro CLI"

    def _command(self, request: str, image: Optional[Path]) -> List[str]:
        # No tools for text-only calls; only file reading when a screenshot is attached.
        trust = "--trust-tools=fs_read" if image is not None else "--trust-tools="
        command = ["kiro-cli", "chat", "--no-interactive", trust]
        if self.settings.llm_model:
            command += ["--model", self.settings.llm_model]
        return command + [request]


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

    if settings.llm_backend == LLMBackend.KIRO_CLI:
        kiro_client = KiroCLIClient(settings)
        if kiro_client.available():
            return kiro_client
        logger.warning(
            "Requested Kiro CLI backend is unavailable; falling back to NullClient"
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
    client_settings = getattr(client, "settings", None)
    batch_size = max(1, getattr(client_settings, "llm_rank_batch_size", 20))
    workers = max(1, getattr(client_settings, "llm_rank_workers", 1))
    batches = [jobs[start : start + batch_size] for start in range(0, len(jobs), batch_size)]
    candidate_json = json.dumps(candidate, ensure_ascii=True)
    if workers == 1 or len(batches) < 2:
        scored = [_score_batch(client, candidate_json, batch, schema) for batch in batches]
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(batches))) as pool:
            scored = list(
                pool.map(lambda batch: _score_batch(client, candidate_json, batch, schema), batches)
            )
    for batch_results in scored:
        results.update(batch_results)
    return results


def _score_batch(
    client: LLMClient, candidate_json: str, batch: List[JobPosting], schema: str
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
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
    ) % (candidate_json, json.dumps(payload, ensure_ascii=True))
    response = client.complete_json(prompt, schema)
    if response is None:
        return results
    entries = response.get("jobs")
    if not isinstance(entries, list):
        return results
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


def _trim_to_boundary(text: str, limit: int) -> str:
    """Cut to at most `limit` characters without ending mid-word.

    A hard slice produced "...engineering dynamic prompt templates with gr",
    which a person then read. Prefer the last sentence end, then the last word
    break, so what is submitted at least finishes a thought.
    """
    if len(text) <= limit:
        return text
    window = text[:limit]
    for terminator in (". ", "! ", "? ", ".\n", ".", "!", "?"):
        cut = window.rfind(terminator)
        if cut >= limit // 2:
            return window[: cut + len(terminator.rstrip())].rstrip()
    cut = window.rfind(" ")
    if cut >= limit // 2:
        return window[:cut].rstrip()
    return window.rstrip()


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


_LOCATION_NOT_STATED = "not stated in this posting"


def resolve_answer(
    client: LLMClient,
    profile: Profile,
    question: str,
    options: Optional[List[str]] = None,
    prior: Optional[Dict[str, str]] = None,
    job_context: Optional[Dict[str, str]] = None,
) -> AnswerResolution:
    if not client.available():
        return _abstain(question, "llm_unavailable")

    facts = profile.known_facts()
    if profile.resume_text:
        facts["resume"] = profile.resume_text[:6000]
    # The posting's own details, under job_* keys so grounding still verifies
    # against a named fact. "Will you attend the walk-in?" names no city, so a
    # candidate who attends walk-ins only in Delhi-NCR cannot answer it from the
    # profile alone and abstained -- three applications lost in one run. The
    # walk-in is at the employer's location, so the posting resolves it.
    if job_context is not None:
        for key, value in job_context.items():
            if value:
                facts["job_%s" % key] = value
        # Say so when the posting has no location, rather than leaving the key
        # out. A question that names no city and a profile that answers by city
        # leaves the model with nothing to ground on, and it abstains -- which
        # skips the job. Stated as a value, "not stated" is something a fact can
        # answer about. Prose in the profile telling the model never to assume a
        # location did not work: it dragged the in-region answers to No too.
        facts.setdefault("job_location", _LOCATION_NOT_STATED)
    # A list of blank strings is not a list of choices. handle_radio builds
    # options from label text, and when the labels have not painted it produces
    # ['', ''] -- truthy, so an earlier guard let it through, the model was
    # handed two blank options and answered in prose, and nothing matched.
    usable_options = [o for o in (options or []) if o and o.strip()]
    request: Dict[str, Any] = {"facts": facts, "question": question}
    if usable_options:
        request["options"] = usable_options
    if prior:
        request["prior_answers"] = prior
    prompt = (
        "Answer ONLY from the supplied facts. If the facts do not contain what "
        "is needed, you MUST abstain. Never estimate, never infer, never use a "
        "typical or common value. grounded_in must name the exact supplied fact "
        "key supporting the answer. For options, copy one option exactly.\n"
        # Without this the model treats the posting's city as the candidate's.
        "Any fact whose key starts with job_ describes the JOB, not the "
        "candidate. Use those only to decide which place or role a question "
        "refers to when the question itself does not say -- for instance an "
        "interview or walk-in with no city named is at job_location. Never "
        "treat job_ facts as statements about the candidate, and never answer "
        "a question about the candidate from them alone.\n"
        # These answers go into a chat box, not a cover letter. A yes/no question
        # answered in 192 characters was rejected outright: the drawer closed
        # without submitting and the application was lost. Four of thirty-eight
        # attempts failed this way in one run, all of them long answers, while
        # every short answer went through.
        "Keep the answer under 90 characters, and make it a complete sentence "
        "or a bare value -- never a fragment. Naukri's chat box rejects longer "
        "answers: the drawer closes without submitting and the application is "
        "lost, which was verified by sending the same answer long and short to "
        "the same job. A yes or no question gets \"Yes\" or \"No\". A question "
        "asking for a value gets just the value. Even a question inviting "
        "several lines must be answered within the limit, so pick the single "
        "most useful sentence rather than starting a longer answer that will "
        "be cut off.\nInput: %s"
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
        # One line: the reason is written into answers.txt, where a line break could start a fake Q:/A:.
        reason = " ".join(stated_reason.split()) if isinstance(stated_reason, str) else "llm_abstained"
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
    if usable_options:
        option_lookup = {
            _normalise_space(option).casefold(): option
            for option in usable_options
        }
        matched_option = option_lookup.get(_normalise_space(answer_text).casefold())
        if matched_option is None:
            return _abstain(question, "llm_answer_not_in_options")
        answer_text = matched_option

    limit = getattr(
        getattr(client, "settings", None), "max_answer_chars", 1200
    )
    if len(answer_text) > limit:
        answer_text = _trim_to_boundary(answer_text, limit)
        logger.warning(
            "Trimmed an overlong answer to %d characters for question %r",
            len(answer_text),
            question,
        )

    return AnswerResolution.resolved(
        Answer(
            text=answer_text,
            grounded_in=grounded_value.strip(),
            source=AnswerSource.LLM,
            confidence=confidence,
        )
    )


JUDGED_MAX_CHARS = 90

_JUDGE_PROMPT = (
    "A job application asks the candidate a screening question that her stated "
    "facts do not answer directly. Decide whether ONE of these honest inferences "
    "answers it. If none does, set can_answer to false: a skipped question costs "
    "one job, a wrong answer is a false statement made in her name.\n"
    "1. A skill, tool, framework, language or domain that appears nowhere in her "
    "facts: she has no recorded experience with it. Answer 0 for years (or the "
    "option meaning none, 0 or less than a year) and No for 'have you worked "
    "with it'.\n"
    "2. A skill her resume shows her using: the years are the time of the role "
    "or project where she used it, never more than her total experience. Quote "
    "that resume line.\n"
    "3. A follow-up whose premise her facts make false, such as 'If yes, share "
    "your employee code' when her facts say she never worked there: answer N/A, "
    "or the option meaning not applicable.\n"
    "4. A choice list without her stated value: pick the range that contains her "
    "number, or Other, None of these or Not applicable when nothing else fits.\n"
    "5. A question her facts already answer in other words (a city she lists, a "
    "work mode or shift she accepts or declined): give that answer and quote "
    "the fact.\n"
    "Never answer about gender, religion, caste, race, disability, criminal "
    "history, visa, sponsorship, citizenship or the legal right to work in a "
    "country. Never write a motivation or essay answer. Never invent a number, "
    "date, name, percentage or year that is not written in her facts.\n"
    "evidence: copy a phrase word for word from her facts (or from the job, when "
    "the answer rests on it) unless the answer is 0, None, No, N/A or Other. "
    "reason: one short sentence a person can check, for example 'CrewAI is not "
    "named in her resume, profile or answers'. depends_on_posting: true when the "
    "answer rests on this job's details (its city, its company) rather than on "
    "her alone.\n"
    "Keep answer under 90 characters: a bare value, Yes or No, or one short "
    "sentence. With options, copy one option exactly.\n\n"
    "HER FACTS\n%s\n\nTHE JOB\n%s\n\nINPUT\n%s"
)
_JUDGE_SCHEMA = (
    '{"can_answer": false, "answer": "", "evidence": "", "reason": "", '
    '"depends_on_posting": false}'
)
_NOTHING_CLAIMED = re.compile(
    r"^\s*(zero|none|no|nil|n/?a|not applicable|others?|none of (the|these)( above)?"
    r"|fresher|no experience|less than (1|one|a) year)\b",
    re.I,
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def claims_nothing(answer: str) -> bool:
    """0 years, No, N/A, Other: an answer that asserts no experience or fact of hers."""
    if _NOTHING_CLAIMED.match(answer):
        return True
    numbers = [float(n) for n in _NUMBER.findall(answer)]
    return bool(numbers) and min(numbers) == 0


def _quoted(evidence: str, text: str) -> bool:
    def norm(value: str) -> str:
        for curly, plain in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"')):
            value = value.replace(curly, plain)
        return " ".join(value.casefold().split())

    quote = norm(evidence).strip(" .\"'")
    return len(quote) >= 12 and quote in norm(text)


def judge_answer(
    client: LLMClient,
    question: str,
    candidate_text: str,
    options: Optional[List[str]] = None,
    job_context: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """A second look at a question the strict pass abstained on.

    Returns {"answer", "reason", "evidence", "depends_on_posting"}, or None when
    no listed inference applies, the claim is not quoted from the facts, or a
    number in a typed answer is not written in them.
    """
    if not client.available():
        return None
    usable_options = [o for o in (options or []) if o and o.strip()]
    job_text = "\n".join("%s: %s" % (k, v) for k, v in (job_context or {}).items() if v)
    request: Dict[str, Any] = {"question": question}
    if usable_options:
        request["options"] = usable_options
    prompt = _JUDGE_PROMPT % (
        candidate_text[:12000],
        job_text or "not given",
        json.dumps(request, ensure_ascii=True),
    )
    response = client.complete_json(prompt, _JUDGE_SCHEMA)
    if response is None:
        logger.info("No judgement for %r: the model did not answer", question)
        return None
    if response.get("can_answer") is not True:
        logger.info("No judgement for %r: %s", question, response.get("reason") or "none applies")
        return None

    answer, reason, evidence = (
        response.get(key) if isinstance(response.get(key), str) else ""
        for key in ("answer", "reason", "evidence")
    )
    answer, reason, evidence = answer.strip(), reason.strip(), evidence.strip()
    refusal = ""
    if not answer or not reason:
        refusal = "no answer or no reason given"
    elif usable_options:
        lookup = {_normalise_space(option): option for option in usable_options}
        matched = lookup.get(_normalise_space(answer))
        if matched is None:
            refusal = "%r is not one of the options" % answer
        answer = matched or answer
    elif len(answer) > JUDGED_MAX_CHARS:
        refusal = "the answer runs past %d characters" % JUDGED_MAX_CHARS
    else:
        stated = set(_NUMBER.findall(candidate_text))
        invented = [n for n in _NUMBER.findall(answer) if float(n) != 0 and n not in stated]
        if invented:
            refusal = "%s is not written in her facts" % ", ".join(invented)
    if not refusal and not claims_nothing(answer):
        if not _quoted(evidence, candidate_text + "\n" + job_text):
            refusal = "the evidence %r is not a quote from her facts" % evidence
    if refusal:
        logger.info("Refused the judged answer %r to %r: %s", answer, question, refusal)
        return None
    return {
        "answer": answer,
        "reason": reason,
        "evidence": evidence,
        "depends_on_posting": response.get("depends_on_posting") is True,
    }


__all__ = [
    "AnthropicClient",
    "ClaudeCLIClient",
    "KiroCLIClient",
    "LLMClient",
    "NullClient",
    "build_client",
    "claims_nothing",
    "judge_answer",
    "resolve_answer",
    "score_jobs",
]
