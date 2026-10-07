"""Long and multi-line answers must reach the chatbot intact.

From the run of 7 October: three applications failed with "Real key events did
not produce the requested chatbot text", one of them throwing a stale element
mid-retry, and a long-form answer was cut to exactly 600 characters ending
"...engineering dynamic prompt templates with gr" and submitted to an employer.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import chatbot
from naukri_bot.llm import _trim_to_boundary


# ---------- trimming ----------

def test_a_short_answer_is_untouched():
    text = "Yes, I can join within 30 days."
    assert _trim_to_boundary(text, 1200) == text


def test_trimming_ends_on_a_sentence():
    text = ("I shipped a retrieval feature. The ugliest edge case was duplicate "
            "chunks ranking above the answer. I fixed it with reciprocal rank "
            "fusion and dynamic prompt templates with guardrails.")
    trimmed = _trim_to_boundary(text, 100)
    assert len(trimmed) <= 100
    assert trimmed.endswith("."), "did not end on a sentence: %r" % trimmed[-40:]


def test_trimming_never_ends_mid_word():
    """The 7 October symptom, which a person then read."""
    text = "word " * 400
    trimmed = _trim_to_boundary(text, 600)
    assert len(trimmed) <= 600
    assert not trimmed.endswith("wor"), "cut mid-word"
    assert trimmed == trimmed.rstrip()


def test_trimming_falls_back_to_a_word_break_without_punctuation():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    trimmed = _trim_to_boundary(text, 30)
    assert len(trimmed) <= 30
    assert " " not in trimmed[-1:], "ends on a space"
    assert text.startswith(trimmed)


def test_an_unbreakable_string_is_still_capped():
    text = "x" * 900
    trimmed = _trim_to_boundary(text, 600)
    assert len(trimmed) == 600


# ---------- typing ----------

class _FakeElement:
    def __init__(self):
        self.typed = []
        self.clicked = False
        self.content = ""

    def click(self):
        self.clicked = True

    def send_keys(self, *args):
        self.typed.append(args)

    @property
    def text(self):
        return self.content

    def get_attribute(self, name):
        return self.content if name in ("innerText", "textContent") else ""


class _FakeDriver:
    capabilities = {"platformName": "mac"}

    def __init__(self):
        self.scripts = []

    def execute_script(self, script, element, text=None):
        self.scripts.append((script, text))
        element.content = text or ""


def test_a_long_answer_is_inserted_not_typed(monkeypatch):
    """Key-by-key at ~90ms a character took almost a minute on 600 chars."""
    typed = []
    monkeypatch.setattr(chatbot, "human_type", lambda el, t: typed.append(t))
    driver, element = _FakeDriver(), _FakeElement()
    long_answer = "a long sentence about retrieval. " * 10   # >120 chars

    assert chatbot.write_contenteditable(driver, element, long_answer) is True
    assert typed == [], "a long answer was still typed key by key"
    assert driver.scripts, "it was not inserted either"


def test_a_short_answer_is_still_typed_like_a_person(monkeypatch):
    typed = []

    def _type(el, t):
        typed.append(t)
        el.content = t

    monkeypatch.setattr(chatbot, "human_type", _type)
    driver, element = _FakeDriver(), _FakeElement()

    assert chatbot.write_contenteditable(driver, element, "Yes") is True
    assert typed == ["Yes"]
    assert driver.scripts == [], "a short answer should not need the JS path"


def test_newlines_never_reach_the_keyboard(monkeypatch):
    """Enter in a chat box submits the message, so a multi-line answer would
    be sent a line at a time."""
    typed = []

    def _type(el, t):
        typed.append(t)
        el.content = t

    monkeypatch.setattr(chatbot, "human_type", _type)
    driver, element = _FakeDriver(), _FakeElement()

    chatbot.write_contenteditable(driver, element, "line one\nline two\n\nline three")
    sent = typed[0] if typed else driver.scripts[0][1]
    assert "\n" not in sent, "a newline would have submitted the message early"
    assert sent == "line one line two line three"
