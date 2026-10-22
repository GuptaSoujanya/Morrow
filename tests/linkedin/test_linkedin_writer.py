"""The post must read like the author, so the checks are deterministic and strict."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from linkedin_bot import writer
from linkedin_bot.news import Article

ARTICLE = Article(
    title="Judges disagree more as agent tasks get longer",
    url="https://example.com/judges",
    source="Example Wire",
    text="A study of grading agents found agreement between judges dropped by forty percent " * 20,
)

CLEAN = (
    "Forty percent is a lot of disagreement for a grading system.\n\n"
    "I spent the morning with this study on grading agent runs, mostly because the "
    "numbers in it line up with a problem I have been chasing for months.\n\n"
    "The part that stuck: agreement between the judges dropped by about forty percent "
    "once the tasks ran long. That matches what we see on WildClawBench when a run "
    "crosses twenty tool calls, which is why the grading there goes through a council "
    "of three judges rather than one.\n\n"
    "One judge is an opinion. Three is closer to a measurement.\n\n"
    "https://example.com/judges"
)


def _with(extra):
    return CLEAN.replace("One judge is an opinion.", extra + " One judge is an opinion.")


def test_a_clean_post_passes():
    assert writer.lint(CLEAN) == []
    assert writer.check_draft(writer.Draft(CLEAN, "Three judges beat one.", ["evals"]), ARTICLE) == []


@pytest.mark.parametrize(
    "text, fragment",
    [
        (_with("I'm excited to share this."), "banned phrase"),
        (_with("A real game-changer for evals."), "banned phrase"),
        (_with("Let that sink in."), "banned phrase"),
        (_with("It's not about speed, it's about trust."), "construction"),
        (_with("Evals matter \u2014 a lot."), "em dash"),
        (_with("Evals matter \u2013 a lot."), "em dash"),
        (_with("Big day \U0001F680 for evals."), "emoji"),
        (_with("Wow! Really! Truly."), "exclamation"),
        (_with("#one #two #three #four"), "hashtags"),
        (CLEAN.replace("One judge is an opinion.", "- one judge\n- three judges"), "list"),
        (CLEAN.replace("One judge is an opinion.", "1. count the judges"), "list"),
        (CLEAN.replace("One judge is an opinion.", "Why Judges Always Disagree\n"), "Title Case"),
        (_with("As an AI language model I think so."), "banned phrase"),
        ("Too short.\n\nhttps://example.com/judges", "too short"),
        (CLEAN.replace("https://example.com/judges", "Read more: https://example.com/judges"), "URL must be the last line"),
        (CLEAN.replace("One judge", "One judge " * 120), "too long"),
    ],
)
def test_lint_flags_each_kind_of_slop(text, fragment):
    problems = writer.lint(text)
    assert any(fragment in p for p in problems), problems


def test_headline_parrot_is_detected():
    parrot = "Judges disagree more as agent tasks get longer, and " + CLEAN
    assert writer.parrots_headline(parrot, ARTICLE.title)
    assert not writer.parrots_headline(CLEAN, ARTICLE.title)


def test_render_text_puts_hashtags_above_the_url():
    draft = writer.Draft(text="body\n\nhttps://x.y", card_line="c", hashtags=[])
    assert writer.render_text(draft) == "body\n\nhttps://x.y"
    draft.hashtags = ["evals", "#agents"]
    assert writer.render_text(draft) == "body\n\n#evals #agents\n\nhttps://x.y"


class _Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete_json(self, prompt, schema_hint):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else None


def test_lint_findings_go_back_to_the_model_until_a_clean_post():
    client = _Client(
        [
            {"post": _with("I'm thrilled."), "card_line": "Three judges beat one.", "hashtags": []},
            {"post": CLEAN, "card_line": "Three judges beat one.", "hashtags": ["evals"]},
        ]
    )
    draft = writer.write_post(client, ARTICLE)
    assert draft is not None
    assert draft.text == CLEAN
    assert draft.hashtags == ["evals"]
    assert "Rewrite; fix these problems" in client.prompts[1]
    assert "thrilled" in client.prompts[1]
    assert "Rewrite" not in client.prompts[0]


def test_the_writer_gives_up_after_three_bad_attempts():
    bad = {"post": _with("I'm thrilled."), "card_line": "x", "hashtags": []}
    client = _Client([bad, bad, bad, bad])
    assert writer.write_post(client, ARTICLE) is None
    assert len(client.prompts) == 3


def test_a_post_that_parrots_the_headline_is_rejected():
    parrot = "Judges disagree more as agent tasks get longer, and " + CLEAN
    client = _Client([{"post": parrot, "card_line": "c", "hashtags": []}])
    assert writer.write_post(client, ARTICLE) is None
    assert "restates the article headline" in client.prompts[1]


def test_a_missing_url_line_is_added_and_hashtags_are_normalised():
    body = CLEAN.replace("\n\nhttps://example.com/judges", "")
    client = _Client([{"post": body, "card_line": "c", "hashtags": ["#Agent Evals", "LLM"]}])
    draft = writer.write_post(client, ARTICLE)
    assert draft is not None
    assert draft.text.endswith("\n\nhttps://example.com/judges")
    assert draft.hashtags == ["agentevals", "llm"]


def test_the_prompt_lists_the_rules_and_the_article():
    prompt = writer.build_prompt(ARTICLE, writer.VOICE)
    for needle in ("Never use", "em dashes", "game-changer", "card_line", ARTICLE.url, "WildClawBench"):
        assert needle in prompt


GOOD_SLIDES = [{"title": "Point %d in a sentence" % i, "body": "One plain sentence about point %d." % i} for i in range(1, 6)]


def _visual(**over):
    fields = dict(text=CLEAN, card_line="c", slides=GOOD_SLIDES, question="How do you grade long runs?", subtitle="")
    fields.update(over)
    return writer.Draft(**fields)


def test_good_slides_pass_the_visual_checks():
    assert writer.check_visuals(_visual()) == []


@pytest.mark.parametrize("over", [
    {"slides": GOOD_SLIDES[:2]},
    {"slides": [{"title": "A \u2014 dash", "body": "b"}] + GOOD_SLIDES[1:]},
    {"question": "No question mark"},
])
def test_bad_slides_or_question_are_reported(over):
    assert writer.check_visuals(_visual(**over))


def test_a_post_with_bad_slides_falls_back_to_text_only():
    client = _Client([{"post": CLEAN, "card_line": "Three judges beat one.", "slides": [], "question": ""}])
    draft = writer.write_post(client, ARTICLE)
    assert draft is not None and draft.slides == []
