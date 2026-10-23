"""Update-lane correctness reproductions with inert files and mocked AI/browser calls."""

from pathlib import Path

import pytest

from linkedin_bot import design, writer
from linkedin_bot.news import Article


ARTICLE = Article(
    title="Judges disagree more as agent tasks get longer",
    url="https://example.invalid/judges",
    source="Example Wire",
    text="A study of grading agents found agreement between judges dropped by forty percent " * 20,
)
TEXT = (
    "Forty percent is a lot of disagreement for a grading system.\n\n"
    "I spent the morning with this study on grading agent runs, mostly because the "
    "numbers in it line up with a problem I have been chasing for months.\n\n"
    "The part that stuck: agreement between the judges dropped by about forty percent "
    "once the tasks ran long. That matches what we see on WildClawBench when a run "
    "crosses twenty tool calls, which is why the grading there goes through a council "
    "of three judges rather than one.\n\n"
    "How do you grade long runs? Three is closer to a measurement.\n\n"
    "https://example.invalid/judges"
)
SLIDES = [
    {"title": "Point %d in a sentence" % i, "body": "One plain sentence about point %d." % i}
    for i in range(1, 6)
]
PAYLOAD = {
    "post": TEXT,
    "card_line": "Three judges beat one.",
    "hashtags": [],
    "slides": SLIDES,
    "question": "How do you grade long runs?",
    "subtitle": "",
}


class Client:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.prompts = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return next(self.answers, None)


def test_updatebots_01_invalid_rendered_png_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """design's module contract: Any failure returns None for the Pillow fallback."""
    monkeypatch.setattr(design, "find_chrome", lambda: "mock-chrome")
    monkeypatch.setattr(
        design.ai_cli, "ask", lambda *args, **kwargs: "<html><body>Inert card fixture</body></html>"
    )

    def fake_browser_render(html_path, out_path, chrome):
        assert chrome == "mock-chrome"
        out_path.write_bytes(b"inert invalid PNG fixture")
        return True

    monkeypatch.setattr(design, "render_html", fake_browser_render)
    result = design.design_card(
        writer.Draft(TEXT, "Three judges beat one."), ARTICLE, tmp_path / "card.png", "claude", 10
    )
    assert result is None, "Invalid PNG must trigger the documented Pillow fallback"


def test_updatebots_02_first_valid_third_draft_still_gets_reviewed() -> None:
    """write_post's contract: with a critic, the first passing draft goes to it once."""
    draft = writer._draft_from(PAYLOAD, ARTICLE)
    assert draft is not None
    assert writer.check_draft(draft, ARTICLE) == []
    assert writer.check_visuals(draft) == []
    client = Client([None, None, PAYLOAD])
    critic = Client([{"verdict": "publish", "problems": []}])
    result = writer.write_post(client, ARTICLE, critic=critic)
    assert result is not None
    assert len(client.prompts) == 3
    assert len(critic.prompts) == 1, "The configured critic was bypassed on the last writing attempt"


def test_updatebots_clean_missing_chrome_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Clean control: an unavailable renderer uses the intended fallback channel."""
    monkeypatch.setattr(design, "find_chrome", lambda: None)
    assert design.design_card(writer.Draft(TEXT, "Three judges beat one."), ARTICLE, tmp_path / "card.png", "claude", 10) is None


def test_updatebots_clean_first_valid_draft_is_reviewed() -> None:
    """Clean control: the ordinary first-attempt review path invokes the critic."""
    client = Client([PAYLOAD])
    critic = Client([{"verdict": "publish", "problems": []}])
    assert writer.write_post(client, ARTICLE, critic=critic) is not None
    assert len(critic.prompts) == 1
