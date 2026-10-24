"""The AI keeps your data files filled in, from what you have already written down.

Questions the bot could not answer land in data/inputs/answers.txt with an empty A:,
and some facts in data/inputs/profile.yaml are still null. Before and after each run
this asks the model to answer them from three sources only: the resume, the
profile and the answers already in answers.txt. An answer is written only when
the model quotes, word for word, the line of a source that supports it; the
quote is checked here, not trusted. Every edit is backed up, marked in the file
as written by the AI, and listed in the day's report.

It never answers "why do you want to join us" questions, never claims years in
a skill none of the sources name, never copies identity numbers, and never
resolves a disagreement between answers.txt and profile.yaml: that is reported
for a person to settle.
"""

import argparse
import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .answers import AnswerBook, _question_key, answers_file_path
from .models import Profile, Settings
from .shared_files import atomic_write_text, locked_file


logger = logging.getLogger(__name__)

CHANGES_FILE = "ai_changes.jsonl"
NOT_A_DATE = "not a real date"
MIN_EVIDENCE_CHARS = 12
MAX_BACKUPS = 10

_OWN_WORDS = re.compile(r"^\s*(why\b|tell us|describe|what (makes|motivates)|cover letter)", re.I)
_SKILL_YEARS = re.compile(r"years? of (?:\w+ )?experience (?:do you have )?(?:in|with|on) (.+?)\s*\??$", re.I)
_NEVER_COPY = re.compile(r"\bpan\b|aadhaar|aadhar|passport number|ssn|social security|bank|account number", re.I)
_DOB = re.compile(r"date of birth|\bdob\b|birth ?date", re.I)
_LAST_DAY = re.compile(r"last working (day|date)", re.I)
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y")

_TOPICS = (
    ("serving notice", re.compile(r"serving (your )?notice", re.I), "serving_notice", "bool"),
    ("notice period", re.compile(r"^(?!.*\b(buy|bought)).*notice period", re.I), "notice_period_days", "number"),
    ("expected CTC", re.compile(r"expected (annual )?(ctc|salary|compensation)", re.I), "expected_ctc_lpa", "number"),
    ("current CTC", re.compile(r"current (annual )?(ctc|salary|compensation)", re.I), "current_ctc_lpa", "number"),
    ("passport", re.compile(r"\bpassport\b(?!.*number)", re.I), "has_passport", "bool"),
    ("relocation", re.compile(r"relocat", re.I), "willing_to_relocate", "bool"),
    ("total experience", re.compile(r"(total|overall) (years of )?experience", re.I), "total_experience_years", "number"),
    ("night shifts", re.compile(r"night shift|\bus shift", re.I), "extra_facts.willing_night_shifts", "bool"),
    ("rotational shifts", re.compile(r"rotational shift", re.I), "extra_facts.willing_rotational_shifts", "bool"),
)


@dataclass
class Change:
    file: str
    item: str
    value: str
    source: str
    evidence: str
    at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    kind: str = "filled"


@dataclass
class Disagreement:
    topic: str
    question: str
    in_answers: str
    in_profile: str

    @property
    def message(self) -> str:
        if self.in_profile == NOT_A_DATE:
            return 'answers.txt has "%s" for "%s", which is not a real date' % (self.in_answers, self.question)
        return 'answers.txt says "%s" for "%s", profile.yaml says %s' % (self.in_answers, self.question, self.in_profile)


# ---------------------------------------------------------------------------
# Sources and checking quotes
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(text.casefold().split())


def _profile_source(settings: Settings) -> str:
    """The facts file as key: value lines, comments dropped: their examples are not facts."""
    import yaml

    try:
        data = yaml.safe_load(Path(settings.profile_path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    lines = []  # type: List[str]

    def walk(node: Any, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, "%s.%s" % (prefix, key) if prefix else str(key))
        elif isinstance(node, list):
            lines.append("%s: %s" % (prefix, ", ".join(str(item) for item in node)))
        elif node is not None and str(node).strip():
            lines.append("%s: %s" % (prefix, node))

    walk(data, "")
    return "\n".join(lines)


def _answers_source(book: AnswerBook) -> str:
    return "\n".join(
        "Q: %s\nA: %s" % (" / ".join(questions), answer) for questions, answer in book.source_entries if answer
    )


def sources(settings: Settings, profile: Profile, book: AnswerBook) -> Dict[str, str]:
    return {
        "resume": profile.resume_text,
        "profile": _profile_source(settings),
        "answers": _answers_source(book),
    }


def quote_found(evidence: str, source_text: str) -> bool:
    quote = _norm(evidence).strip(" .\"'")
    return len(quote) >= MIN_EVIDENCE_CHARS and quote in _norm(source_text)


def numbers_backed(answer: str, evidence: str) -> bool:
    """Every number in the answer appears in the quote, so a quote cannot vouch for a different figure."""
    quoted = set(re.findall(r"\d+(?:\.\d+)?", evidence))
    return all(number in quoted for number in re.findall(r"\d+(?:\.\d+)?", answer))


def _named_anywhere(skill_part: str, corpus: str) -> bool:
    for name in re.split(r"\s*(?:,|/|\bor\b|\band\b)\s*", skill_part, flags=re.I):
        name = name.strip(" .?")
        if len(name) >= 2 and re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(name.casefold()), corpus):
            return True
    return False


# ---------------------------------------------------------------------------
# What is left to fill
# ---------------------------------------------------------------------------


def _null_facts(settings: Settings) -> List[Tuple[str, str]]:
    """(dotted key, the comment after it) for every fact still null in profile.yaml."""
    try:
        text = Path(settings.profile_path).read_text(encoding="utf-8")
    except OSError:
        return []
    found = []  # type: List[Tuple[str, str]]
    parents = []  # type: List[Tuple[int, str]]
    for line in text.splitlines():
        match = re.match(r"^(\s*)([A-Za-z_][\w]*):\s*(.*)$", line)
        if not match:
            continue
        indent, key, rest = len(match.group(1)), match.group(2), match.group(3)
        while parents and parents[-1][0] >= indent:
            parents.pop()
        value, _, comment = rest.partition("#")
        if not value.strip():
            parents.append((indent, key))
            continue
        if value.strip() in ("null", "~"):
            dotted = ".".join([name for _, name in parents] + [key])
            found.append((dotted, comment.strip()))
    return found


def _declined(settings: Settings, corpus_hash: str) -> set:
    keys = set()
    for record in read_changes(settings):
        if record.get("kind") == "declined" and record.get("corpus") == corpus_hash:
            keys.add(record.get("item"))
    return keys


# ---------------------------------------------------------------------------
# Asking the model
# ---------------------------------------------------------------------------


_SCHEMA = '{"items": [{"id": "q1", "answer": "", "source": "resume|profile|answers", "evidence": "", "reason": ""}]}'


def build_prompt(items: List[Dict[str, str]], texts: Dict[str, str]) -> str:
    return (
        "You fill in blanks in a job seeker's own data files. Use ONLY the three "
        "sources below. For each item either give an answer or leave answer empty "
        "and say why in reason.\n"
        "Rules:\n"
        "- evidence must be copied word for word from the named source, a full "
        "phrase of at least a few words that by itself supports the answer. It is "
        "checked by exact text search, so do not paraphrase.\n"
        "- Never estimate, never guess, never use a typical value. Never claim "
        "experience in a tool or skill the sources do not name.\n"
        "- Leave out anything asking for motivation or opinion, and any identity "
        "or account number.\n"
        "- Answers are short: a number, Yes or No, a date, or a short phrase, in "
        "the style an application form expects. For a profile fact, follow the "
        "style hint, but the hint is an example, never a source.\n\n"
        "ITEMS:\n%s\n\nRESUME:\n%s\n\nPROFILE:\n%s\n\nANSWERS:\n%s\n"
    ) % (
        json.dumps(items, ensure_ascii=True),
        texts["resume"][:7000],
        texts["profile"][:5000],
        texts["answers"][:6000],
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _backup(path: Path, settings: Settings) -> None:
    folder = Path(settings.data_dir or "data/inputs") / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(path), str(folder / ("%s.%s" % (path.name, datetime.now().strftime("%Y%m%d-%H%M%S-%f")))))
    old = sorted(folder.glob("%s.*" % path.name))
    for stale in old[:-MAX_BACKUPS]:
        stale.unlink()


def fill_answer(text: str, question: str, answer: str, note: str) -> Optional[str]:
    """answers.txt with the blank A: under `question` filled and `note` above its block."""
    lines = text.splitlines()
    wanted = _question_key(question)
    for index, line in enumerate(lines):
        if not (line.strip().upper().startswith("Q:") and _question_key(line.strip()[2:]) == wanted):
            continue
        start = index
        while start > 0 and lines[start - 1].strip().upper().startswith("Q:"):
            start -= 1
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip().upper().startswith("Q:"):
            cursor += 1
        if cursor >= len(lines) or lines[cursor].strip().upper() != "A:":
            return None
        following = cursor + 1
        while following < len(lines) and lines[following].lstrip().startswith("#"):
            following += 1
        if following < len(lines) and lines[following].strip() and not lines[following].lstrip().upper().startswith("Q:"):
            return None
        lines[cursor] = "A: %s" % answer
        lines.insert(start, "# %s" % note)
        return "\n".join(lines) + "\n"
    return None


def fill_fact(text: str, dotted: str, value: str, note: str) -> Optional[str]:
    """profile.yaml with `key: null` for the last part of `dotted` set, when exactly one such line exists."""
    key = dotted.split(".")[-1]
    pattern = re.compile(r"^(\s*)%s:\s*(null|~)\s*(#.*)?$" % re.escape(key))
    lines = text.splitlines()
    hits = [index for index, line in enumerate(lines) if pattern.match(line)]
    if len(hits) != 1:
        return None
    indent = pattern.match(lines[hits[0]]).group(1)
    lines[hits[0]] = "%s%s: %s   # %s" % (indent, key, json.dumps(value, ensure_ascii=False), note)
    return "\n".join(lines) + "\n"


def changes_path(settings: Settings) -> Path:
    return Path(settings.report_dir or "data/reports") / CHANGES_FILE


def record_change(settings: Settings, change: Change) -> None:
    path = changes_path(settings)
    with locked_file(path) as target:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(change), ensure_ascii=False) + "\n")


def read_changes(settings: Settings) -> List[Dict[str, Any]]:
    path = changes_path(settings)
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def changes_on(settings: Settings, day: str, kind: str = "filled") -> List[Dict[str, Any]]:
    return [record for record in read_changes(settings) if str(record.get("at", "")).startswith(day) and record.get("kind") == kind]


# ---------------------------------------------------------------------------
# Disagreements
# ---------------------------------------------------------------------------


def _number(text: str) -> Optional[float]:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _yes_no(text: str) -> Optional[bool]:
    first = (text.strip().split() or [""])[0].strip(".,!").casefold()
    return True if first == "yes" else False if first == "no" else None


def _as_date(text: str) -> Optional[datetime]:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def _fact(profile: Profile, attribute: str) -> Any:
    if not attribute.startswith("extra_facts."):
        return getattr(profile, attribute)
    value = profile.extra_facts.get(attribute.split(".", 1)[1])
    if isinstance(value, str):
        return {"true": True, "yes": True, "false": False, "no": False}.get(value.strip().casefold())
    return value


def disagreements(profile: Profile, book: AnswerBook) -> List[Disagreement]:
    """Where answers.txt and profile.yaml say different things, so employers would hear both."""
    found = []  # type: List[Disagreement]
    for questions, answer in book.entries:
        if not answer:
            continue
        for question in questions:
            if _LAST_DAY.search(question):
                if not re.search(r"\d|\bnot\b|\bno\b", answer, re.I):
                    found.append(Disagreement("last working day", question, answer, NOT_A_DATE))
                break
            if _DOB.search(question):
                if _as_date(answer) is None:
                    found.append(Disagreement("date of birth", question, answer, NOT_A_DATE))
                else:
                    stated = str(profile.extra_facts.get("date_of_birth") or "")
                    if stated and _as_date(stated) and _as_date(stated) != _as_date(answer):
                        found.append(Disagreement("date of birth", question, answer, stated))
                break
            topic = next((t for t in _TOPICS if t[1].search(question)), None)
            if topic is None:
                continue
            name, _, attribute, kind = topic
            value = _fact(profile, attribute)
            if value is None:
                break
            if kind == "number":
                said = _number(answer)
                if said is not None and abs(said - float(value)) > 0.01:
                    found.append(Disagreement(name, question, answer, "%s: %g" % (attribute, float(value))))
            else:
                said_bool = _yes_no(answer)
                if said_bool is not None and said_bool != bool(value):
                    found.append(Disagreement(name, question, answer, "%s: %s" % (attribute, str(bool(value)).lower())))
            break
    return found


# ---------------------------------------------------------------------------
# The whole pass
# ---------------------------------------------------------------------------


def _corpus(settings: Settings, profile: Profile) -> Tuple[Dict[str, str], str, str]:
    texts = sources(settings, profile, AnswerBook(answers_file_path(settings)))
    corpus = _norm("\n".join(texts.values()))
    return texts, corpus, hashlib.sha1(corpus.encode("utf-8")).hexdigest()[:16]


def fill_blanks(settings: Settings, profile: Profile, client: Any, write: bool = True) -> List[Change]:
    """Ask the model for every blank it may answer; write the quoted ones. Returns what was (or would be) filled."""
    book = AnswerBook(answers_file_path(settings))
    texts, corpus, corpus_hash = _corpus(settings, profile)
    declined = _declined(settings, corpus_hash)
    turned_down = []  # type: List[str]

    items = []  # type: List[Dict[str, str]]
    for questions, answer in book.entries:
        if answer:
            continue
        question = questions[0]
        item_id = "q:%s" % _question_key(question)
        if item_id in declined or _OWN_WORDS.search(question) or _NEVER_COPY.search(question):
            continue
        skill = _SKILL_YEARS.search(question)
        if skill and not _named_anywhere(skill.group(1), corpus):
            turned_down.append(item_id)
            continue
        items.append({"id": item_id, "kind": "question", "text": question})
    for dotted, comment in _null_facts(settings):
        item_id = "f:%s" % dotted
        if item_id in declined or _NEVER_COPY.search(dotted.replace("_", " ")):
            continue
        items.append({"id": item_id, "kind": "profile fact", "text": dotted, "style hint": comment})

    if not items:
        if write:
            for item_id in turned_down:
                _mark_declined(settings, item_id, corpus_hash)
        return []
    if not client.available():
        logger.info("AI assist: %d blank(s) to look at, but no LLM backend is available", len(items))
        return []
    logger.info("AI assist: asking the model about %d blank(s) in answers.txt and profile.yaml", len(items))
    response = client.complete_json(build_prompt(items, texts), _SCHEMA)
    proposals = response.get("items") if isinstance(response, dict) else None
    if not isinstance(proposals, list):
        logger.warning("AI assist: the model gave no usable reply; nothing changed")
        return []

    by_id = {item["id"]: item for item in items}
    changes = []  # type: List[Change]
    for proposal in proposals:
        if not isinstance(proposal, dict) or proposal.get("id") not in by_id:
            continue
        item = by_id.pop(proposal["id"])
        answer = str(proposal.get("answer") or "").strip()
        source = str(proposal.get("source") or "").strip().casefold()
        evidence = str(proposal.get("evidence") or "").strip()
        if (
            not answer
            or source not in texts
            or not quote_found(evidence, texts[source])
            or not numbers_backed(answer, evidence)
            or len(answer) > 120
        ):
            turned_down.append(item["id"])
            if answer:
                logger.info("AI assist: dropped %r for %r: its quote is not in your %s", answer, item["text"], source or "files")
            continue
        changes.append(Change(
            file="answers.txt" if item["kind"] == "question" else "profile.yaml",
            item=item["text"],
            value=answer,
            source=source,
            evidence=evidence,
        ))
    turned_down.extend(by_id)

    if write:
        backed_up = set()  # type: set
        changes = [change for change in changes if _apply(settings, change, backed_up)]
        # Remembered against the files as they now are: an edit to any of them asks again.
        _, _, after = _corpus(settings, profile)
        for item_id in turned_down:
            _mark_declined(settings, item_id, after)
    for change in changes:
        logger.info(
            "AI assist: %s %s -> %s (from your %s: \"%s\")",
            "filled" if write else "would fill",
            change.item,
            change.value,
            change.source,
            change.evidence[:80],
        )
    return changes


def _mark_declined(settings: Settings, item_id: str, corpus_hash: str) -> None:
    path = changes_path(settings)
    with locked_file(path) as target:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": "declined", "item": item_id, "corpus": corpus_hash,
                                     "at": datetime.now().isoformat(timespec="seconds")}) + "\n")


def _apply(settings: Settings, change: Change, backed_up: set) -> bool:
    note = 'AI filled this on %s from your %s: "%s". Change it if it is wrong.' % (
        datetime.now().strftime("%Y-%m-%d"),
        change.source,
        " ".join(change.evidence.split())[:100],
    )
    path = Path(answers_file_path(settings) if change.file == "answers.txt" else settings.profile_path)
    with locked_file(path) as path:
        text = path.read_text(encoding="utf-8")
        if change.file == "answers.txt":
            updated = fill_answer(text, change.item, change.value, note)
        else:
            updated = fill_fact(text, change.item, change.value, note)
            if updated is not None and not _still_valid_yaml(updated):
                updated = None
        if updated is None:
            logger.info("AI assist: could not place %r in %s; left it alone", change.item, path.name)
            return False
        if path not in backed_up:
            _backup(path, settings)
            backed_up.add(path)
        atomic_write_text(path, updated)
    if change.file == "answers.txt":
        from .answer_events import answer_saved
        answer_saved(change.item, change.value, "AI assist")
    record_change(settings, change)
    return True


def _still_valid_yaml(text: str) -> bool:
    import yaml

    try:
        return isinstance(yaml.safe_load(text), dict)
    except yaml.YAMLError:
        return False


def run_pass(settings: Settings, write: bool = True) -> Tuple[List[Change], List[Disagreement]]:
    """Fill what the sources support and name the disagreements; never raises."""
    from . import llm
    from .profile import ProfileError, load_profile

    try:
        profile = load_profile(settings)
    except ProfileError as exc:
        logger.warning("AI assist skipped: %s", exc)
        return [], []
    book = AnswerBook(answers_file_path(settings))
    try:
        changes = fill_blanks(settings, profile, llm.build_client(settings), write=write)
    except Exception as exc:  # a helper pass must never stop a job run
        logger.warning("AI assist failed (%s: %s); nothing changed", type(exc).__name__, exc)
        changes = []
    found = disagreements(load_profile(settings) if changes else profile, AnswerBook(book.path))
    for item in found:
        logger.warning("Check your files, %s: %s.", item.topic, item.message)
    return changes, found


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m common.assist",
        description="Let the AI fill blank answers and facts from your resume, profile and answers, with quotes.",
    )
    parser.add_argument("--dry-run", action="store_true", help="show what would be filled; change nothing")
    parser.add_argument("--env", default=None, help="path to the .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from . import config
    from .run import EXIT_CONFIG, EXIT_OK, configure_logging, keep_log

    args = parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = config.load_settings(args.env)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG
    keep_log(settings, "assist")
    changes, found = run_pass(settings, write=not args.dry_run)
    logger.info(
        "AI assist: %d %s, %d disagreement(s) between answers.txt and profile.yaml.",
        len(changes),
        "change(s) made" if not args.dry_run else "change(s) proposed",
        len(found),
    )
    if not args.dry_run:
        from . import report

        report.update_quietly(settings)
    return EXIT_OK


if __name__ == "__main__":
    import sys

    sys.exit(main())
