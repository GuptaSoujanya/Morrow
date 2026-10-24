"""Conservative local matching of a person's saved screening questions.

This is an intent/word matcher, not a language model. Recognized paraphrases are
normalized, important entities and qualifiers must agree, and compatible texts
are ranked with TF-IDF cosine similarity. Scores measure lexical similarity;
they are not probabilities that an answer is true. Unknown or ambiguous intents
abstain so the caller can ask the person instead of guessing.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class SimilarityMatch:
    answer: str
    matched_question: str
    score: float
    method: str = "intent_tfidf"


@dataclass(frozen=True)
class _Question:
    intent: str
    shape: str
    qualifiers: Tuple[str, ...]
    terms: Tuple[str, ...]

    @property
    def signature(self):
        return self.intent, self.shape, self.qualifiers


_PER_JOB = "[ai writes this for each job]"
_MIN_SCORE = 0.85
_NEGATIONS = frozenset(("not", "never", "cannot", "cant", "unable", "unwilling", "without", "no"))
_JOB_DEPENDENT = re.compile(
    r"\b(?:why|motivation|motivated|relevant|suitable|suited|fit|cover letter|job description|"
    r"job posting|job requirements?|this role|this position|this job|this company|our company|"
    r"our organization|our organisation|our team|joining us|work for us|this location|"
    r"our location|job location|this opportunity|this employer|walk in|walkin|tomorrow|"
    r"today|next week|this week|this month|scheduled interview|attend an interview)\b"
)
_FILLER = frozenset((
    "a", "an", "the", "i", "my", "you", "your", "yourself", "we", "it", "is", "are",
    "was", "were", "be", "been", "being", "am", "do", "does", "did", "have", "has", "had",
    "can", "could", "would", "will", "should", "of", "in", "on", "at", "to", "for", "with",
    "by", "from", "as", "and", "about", "what", "which", "how", "many", "much", "long",
    "please", "kindly", "tell", "state", "specify", "provide", "mention", "enter", "indicate",
    "share", "answer", "number", "amount", "length", "duration", "period", "time",
))
_EXPERIENCE_WORDS = frozenset(("experience", "experienced", "work", "worked", "working", "used", "using", "use", "programming", "coding"))
_TOTAL_WORDS = frozenset(("total", "overall", "professional", "employment", "career", "work", "working", "worked"))
_QUANTITY_WORDS = frozenset(("year", "month", "week", "day"))
_WILLING_WORDS = frozenset(("willing", "comfortable", "open", "ready", "willingness"))
_COMPENSATION_WORDS = frozenset(("compensation", "salary", "ctc", "pay", "remuneration", "package"))
_EXPECTED_WORDS = frozenset(("expected", "expectation", "desired", "target", "expect", "seeking"))
_CURRENT_WORDS = frozenset(("current", "currently", "present", "existing", "now"))
_BINARY_START = re.compile(r"^(?:(?:please|kindly)\s+)?(?:are|is|do|does|have|has|can|could|would|will)\b")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    text = re.sub(r"\bcan['’]?t\b", "cannot", text)
    text = re.sub(r"\b(?:don|doesn|didn|isn|aren|wasn|weren|won|wouldn|couldn|shouldn|haven|hasn)['’]?t\b", "not", text)
    replacements = (
        (r"\bc\+\+", "cplusplus"), (r"\bc#", "csharp"), (r"(?<!\w)\.net\b", "dotnet"),
        (r"\bnode\.?js\b", "nodejs"), (r"\breact\.?js\b", "reactjs"),
        (r"\bcost[ -]+to[ -]+company\b", "compensation"),
        (r"\bat present\b", "current"), (r"\bper annum\b", "annual"),
        (r"\bper year\b", "annual"), (r"\byearly\b", "annual"),
        (r"\bper month\b", "monthly"), (r"\bin hand\b", "inhand"),
        (r"\btake[ -]+home\b", "takehome"), (r"\bhands[ -]+on\b", "handson"),
        (r"\bfull[ -]+time\b", "fulltime"), (r"\bpart[ -]+time\b", "parttime"),
        (r"\bat least\b", "minimum"), (r"\bat most\b", "maximum"),
        (r"\bmore than\b", "greaterthan"), (r"\bless than\b", "lessthan"),
        (r"\b(?:yrs?|years)\b", "year"), (r"\bmonths\b", "month"),
        (r"\bweeks\b", "week"), (r"\bdays\b", "day"),
        (r"\bperiods\b", "period"), (r"\bexperiences\b", "experience"),
        (r"\bexpectations\b", "expectation"), (r"\bshifts\b", "shift"),
        (r"\brelocating\b|\brelocation\b", "relocate"),
        (r"(?<=\d)\s*[-–—]\s*(?=\d)", " numericrange "),
        (r"(?<![a-z0-9])-(?=\d)", "negative "),
        (r"\bpercentage\b", "percent"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    currencies = {"₹": "inr", "$": "usd", "€": "eur", "£": "gbp", "¥": "yen"}
    text = "".join(" %s " % currencies.get(char, "currency%d" % ord(char))
                   if unicodedata.category(char) == "Sc" else char for char in text)
    text = text.replace("%", " percent ")
    return " ".join(re.findall(r"[a-z][a-z0-9]*|\d+(?:\.\d+)?|\.\d+|[<>]=?|\+", text))


def is_job_dependent(question: str) -> bool:
    """Whether wording explicitly depends on a posting, event, or relative date.

    This is an extra guard for saving global facts, not proof that every other
    prompt is safe to save. The caller must still inspect answer provenance.
    """
    return isinstance(question, str) and bool(_JOB_DEPENDENT.search(_clean(question)))


def _question(text: str) -> Optional[_Question]:
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        return None
    clean = _clean(text)
    tokens = clean.split()
    words = set(tokens)
    if not words or words & _NEGATIONS or is_job_dependent(text):
        return None
    binary = bool(_BINARY_START.search(clean))
    families = []
    if "notice" in words or re.search(r"\bhow soon\b.*\b(?:join|start)\b", clean):
        families.append("notice")
    if words & _COMPENSATION_WORDS:
        families.append("compensation")
    if "relocate" in words:
        families.append("relocation")
    if words & _WILLING_WORDS and not families:
        families.append("willingness")
    if words & _EXPERIENCE_WORDS and not families:
        families.append("experience")
    if not families:
        if (words & {"location", "city", "country", "based", "live", "located"}
                and (words & _CURRENT_WORDS or re.search(r"\b(?:where|do you live|are you based)\b", clean))):
            families.append("location")
    if len(families) != 1:
        return None

    family = families[0]
    consumed = set(_FILLER)
    shape = "binary" if binary else "value"
    if family == "notice":
        # Serving notice, immediate availability, and fixed dates are different facts.
        if binary or words & {"serving", "served", "immediate", "immediately", "date", "last", "remaining", "left"}:
            return None
        if "notice" not in words and not re.search(r"\bhow soon\b.*\b(?:join|start)\b", clean):
            return None
        consumed.update({"notice", "soon", "join", "start", "joining"})
        intent = "notice_duration"
    elif family == "compensation":
        current = bool(words & _CURRENT_WORDS)
        expected = bool(words & _EXPECTED_WORDS)
        if current == expected:
            return None
        intent = "expected_compensation" if expected else "current_compensation"
        consumed.update(_COMPENSATION_WORDS | _CURRENT_WORDS | _EXPECTED_WORDS)
        # No conversion between CTC, take-home, annual/monthly or currencies.
    elif family == "relocation":
        if not binary and not words & _WILLING_WORDS:
            return None
        if (words & {"experience", "previous", "previously", "past", "worked", "relocated", "history"}
                or re.match(r"^(?:have|has|had|did|was|were)\b", clean)):
            return None
        intent = "relocation_willingness"
        shape = "binary"
        consumed.update(_WILLING_WORDS | {"relocate"})
    elif family == "experience":
        if words & {"will", "would", "future", "planned", "planning", "plan"}:
            return None
        duration = not binary and (bool(words & _QUANTITY_WORDS) or "how long" in clean or bool(words & _TOTAL_WORDS))
        if not binary and not duration:
            return None
        if binary and (not words & {"experience", "experienced", "used", "worked"}
                       or re.match(r"^(?:can|could|would|will)\b", clean)):
            return None
        consumed.update(_EXPERIENCE_WORDS)
        # An unqualified total and a named skill, employer or industry never merge.
        remainder = words - consumed - _QUANTITY_WORDS - _TOTAL_WORDS
        total = not remainder
        if total:
            consumed.update(_TOTAL_WORDS)
        else:
            # Professional-only, hands-on and production experience stay distinct.
            consumed.update({"total", "overall"})
        intent = ("total" if total else "specific") + "_experience"
        shape = "duration" if duration else "binary"
        if duration:
            units = words & _QUANTITY_WORDS
            if len(units) > 1:
                return None
            consumed.update(_QUANTITY_WORDS)
            intent += "_" + (next(iter(units)) if units else "year")
    elif family == "willingness":
        if (words & {"experience", "past", "previous", "previously", "worked"}
                or re.match(r"^(?:have|has|had|did|was|were)\b", clean)):
            return None
        intent = "work_willingness"
        shape = "binary"
        consumed.update(_WILLING_WORDS | {"work", "working"})
    else:
        if (words & {"preferred", "desired", "expected", "future", "previous", "past", "was", "were", "had", "will", "would", "could"}
                or re.search(r"\bwhere (?:have|had)\b", clean)):
            return None
        intent = "current_location"
        consumed.update(_CURRENT_WORDS | {"where", "location", "located", "based", "live"})

    qualifiers = tuple(sorted(words - consumed))
    # An empty generic willingness question has no stable subject to match.
    if family == "willingness" and not qualifiers:
        return None
    # Repeated intent features make canonical paraphrases comparable without
    # allowing common screening words to overrule a different protected entity.
    terms = (intent, shape, intent, shape) + tuple(token for token in tokens if token not in consumed)
    return _Question(intent, shape, qualifiers, terms)


def _cosines(documents: List[Tuple[str, ...]]) -> List[float]:
    """Smoothed TF-IDF and cosine, using only the local compatible corpus."""
    frequencies = Counter(token for document in documents for token in set(document))
    count = len(documents)
    vectors = []
    for document in documents:
        vector = {token: (1.0 + math.log(frequency)) * (1.0 + math.log((1.0 + count) / (1.0 + frequencies[token])))
                  for token, frequency in Counter(document).items()}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        vectors.append({token: value / norm for token, value in vector.items()} if norm else {})
    query = vectors[0]
    return [min(1.0, sum(value * query.get(token, 0.0) for token, value in vector.items())) for vector in vectors[1:]]


def match(question: str, entries: Iterable[Tuple[List[str], str]]) -> Optional[SimilarityMatch]:
    """Return one compatible saved answer, or abstain on uncertainty/conflict.

    Exact lookup belongs to the caller. Blank/per-job answers, negative prompts,
    job-specific prose, unknown intents, changed skills/countries/qualifiers,
    and conflicting plausible answers cannot produce a similarity match.
    """
    query = _question(question)
    if query is None:
        return None
    candidates = []
    for questions, answer in entries:
        if not isinstance(answer, str) or not answer.strip() or " ".join(answer.split()).casefold() == _PER_JOB:
            continue
        for saved in questions:
            candidate = _question(saved)
            if candidate is not None and candidate.signature == query.signature:
                candidates.append((saved, answer, candidate))
    if not candidates:
        return None
    scores = _cosines([query.terms] + [candidate[2].terms for candidate in candidates])
    ranked = [(score, saved, answer) for score, (saved, answer, _) in zip(scores, candidates) if score >= _MIN_SCORE]
    if not ranked or len({" ".join(answer.split()).casefold() for _, _, answer in ranked}) != 1:
        return None
    score, saved, answer = max(ranked, key=lambda item: item[0])
    return SimilarityMatch(answer=answer, matched_question=saved, score=score)
