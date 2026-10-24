"""Provenance for learned answers, kept beside editable Q:/A: entries.

Annotations bind to both the question and value. Editing an answer makes it a
user-authored answer; unchanged AI answers retain their profile and form scope.
No model or embedding service is needed to read this metadata.
"""
import hashlib
import json
import re
import unicodedata

PREFIX = "# Morrow learned: "


def key(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(" currency_%x " % ord(character)
                   if unicodedata.category(character) == "Sc" and character not in "₹$€£" else character
                   for character in text)
    for pattern, replacement in ((r"\bc\+\+", "cplusplus"), (r"\bc#", "csharp"),
                                 (r"(?<!\w)\.net\b", "dotnet")):
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"(?<!\w)\.(?=\d)", "0.", text)
    text = re.sub(r"(?<=\d)\.(?=\d)", " decimal ", text)
    text = re.sub(r"(?<=\d)\s*[-–—]\s*(?=\d)", " range ", text)
    text = re.sub(r"(?<!\w)[-−](?=\d)", "negative ", text)
    for symbol, word in ((">=", "greater equal"), ("<=", "less equal"),
                         (">", "greater"), ("<", "less"), ("+", "plus"), ("%", "percent"),
                         ("₹", "inr"), ("$", "usd"), ("€", "eur"), ("£", "gbp")):
        text = text.replace(symbol, " " + word + " ")
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def identity(question, answer):
    return (hashlib.sha256(key(question).encode()).hexdigest(),
            hashlib.sha256(" ".join(answer.split()).encode()).hexdigest())


def choices(options):
    return None if options is None else sorted({" ".join(value.casefold().split()) for value in options})


def annotation(question, answer, fingerprint, options=None, multi=False, source="llm"):
    question_hash, answer_hash = identity(question, answer)
    data = dict(version=1, profile=fingerprint, options=choices(options), multi=multi, source=source)
    return PREFIX + question_hash + " " + answer_hash + " " + json.dumps(data, ensure_ascii=True, sort_keys=True)


def read_metadata(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(PREFIX):
            continue
        parts = line[len(PREFIX):].split(maxsplit=2)
        if len(parts) < 2:
            continue
        try:
            value = json.loads(parts[2])
        except (IndexError, ValueError):
            value = None
        if (not isinstance(value, dict) or set(value) != {"version", "profile", "options", "multi", "source"}
                or type(value.get("version")) is not int or value["version"] != 1
                or not isinstance(value["profile"], str) or not value["profile"]
                or type(value["multi"]) is not bool or value["source"] not in ("llm", "judgement")
                or (value["options"] is not None and (not isinstance(value["options"], list)
                    or not value["options"] or any(not isinstance(option, str) or not option for option in value["options"])))
                or (value["multi"] and value["options"] is None)):
            value = None
        result[tuple(parts[:2])] = value
    return result


def eligible(question, answer, metadata, fingerprint, options=None, multi=False, semantic=False):
    reference = identity(question, answer)
    if reference not in metadata:
        return True
    data = metadata[reference]
    if not data or not fingerprint or data.get("profile") != fingerprint:
        return False
    if data.get("multi") is not multi:
        return False
    if semantic and data.get("source") == "judgement":
        return False
    # A choice such as "Other" or "10–20 LPA" belongs to that exact choice set.
    # A typed value can still be matched against a later form's choices.
    stored_options = data.get("options")
    return stored_options is None or stored_options == choices(options)


def model_fingerprint(profile_fingerprint, options=None, multi=False):
    """Keep legacy unscoped cache values from leaking between form types."""
    payload = json.dumps(["answer-scope-v1", profile_fingerprint, choices(options), multi], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]
