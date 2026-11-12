"""The reels planner turns one topic into a day list and a prompt per day, through a fake claude bridge."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLANNER = ROOT / "admin" / "reels" / "planner.py"

pytestmark = pytest.mark.skipif(not PLANNER.exists(), reason="the private admin folder is not checked out")


@pytest.fixture
def planner(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("admin_reels_planner_test", PLANNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PLANS", tmp_path / "plans")
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "skill_menu", lambda: [
        {"name": "bang-motion", "repo": "bang-motion", "summary": "motion graphics", "installed": True},
        {"name": "hyperframes", "repo": "hyperframes", "summary": "html to mp4", "installed": True},
        {"name": "vox-explainer", "repo": "vox-explainer", "summary": "needs a key", "installed": False},
    ])
    return module


def calendar_reply(days, skill="bang-motion"):
    return {"pillars": ["Tips", "Myths"], "series_note": "Builds up weekly.", "items": [
        {"day": d, "title": f"Title {d}", "hook": f"Hook {d}", "angle": f"Angle {d}", "skill": skill,
         "why_skill": "fits", "duration_s": 25 + d, "beats": ["Open on text", "Show the thing", "End card"],
         "on_screen_text": ["one", "two"], "cta": "Follow for more", "caption": f"Caption {d}",
         "hashtags": ["#python", "coding"], "pillar": "Tips"} for d in range(1, days + 1)]}


SCRIPT = ["Stop writing the same loop by hand every single day at work",
          "Python already has a helper that does this in one short line",
          "Here is the before, and here is the after, side by side now",
          "Follow for one more Python tip like this one tomorrow morning"]


def prompt_reply(days):
    return {"prompts": [{"day": d, "prompt": " ".join(["word"] * 130) + f" day {d}", "script": SCRIPT} for d in days]}


def test_new_plan_is_saved_with_a_slug_id(planner):
    plan = planner.new_plan("  Python   tips for devs ", days=3, language="Hinglish", handle="@dev")
    assert plan["id"].startswith("python-tips-for-devs-")
    assert plan["status"] == "new" and plan["handle"] == "@dev"
    assert planner.load_plan(plan["id"])["topic"] == "Python tips for devs"
    assert [p["id"] for p in planner.list_plans()] == [plan["id"]]


@pytest.mark.parametrize("bad", [("", 30, "English"), ("x", 0, "English"), ("x", 61, "English"), ("x", 3, "French")])
def test_new_plan_refuses_bad_input(planner, bad):
    with pytest.raises(ValueError):
        planner.new_plan(*bad)


def test_run_plan_fills_calendar_then_prompts_in_batches(planner):
    plan = planner.new_plan("Python tips", days=7)
    calls = []

    def fake_ask(prompt, schema, timeout):
        calls.append(prompt)
        if '"items"' in schema:
            return calendar_reply(7)
        asked = json.loads(prompt[prompt.index("Reels:\n") + 7:])
        return prompt_reply([item["day"] for item in asked])

    result = planner.run_plan(plan["id"], ask=fake_ask)
    assert result["status"] == "done"
    assert [i["day"] for i in result["items"]] == list(range(1, 8))
    assert all(i["prompt"] for i in result["items"])
    assert len(calls) == 1 + 2  # one calendar call, prompts in batches of five
    assert result["items"][0]["hashtags"] == ["python", "coding"]
    saved = planner.load_plan(plan["id"])
    assert saved["pillars"] == ["Tips", "Myths"]
    prompt_file = planner.OUT / plan["id"] / "day-03" / "PROMPT.md"
    assert prompt_file.read_text().startswith("word word")
    assert (prompt_file.parent / "caption.draft.txt").read_text() == "Caption 3\n\n#python #coding\n"
    assert "python-tips" in planner.claude_command(saved, saved["items"][2]) and "env -u ANTHROPIC_BASE_URL" in planner.claude_command(saved, saved["items"][2])


def test_calendar_is_asked_again_when_days_are_missing(planner):
    plan = planner.new_plan("Python tips", days=3)
    replies = [calendar_reply(2), calendar_reply(3)]
    prompts = []

    def fake_ask(prompt, schema, timeout):
        prompts.append(prompt)
        return replies.pop(0)

    planner.make_calendar(plan, ask=fake_ask)
    assert len(prompts) == 2 and "missing days: 3" in prompts[1]
    assert len(plan["items"]) == 3 and plan["status"] == "prompting"


def test_unknown_skill_falls_back_to_an_installed_one(planner):
    plan = planner.new_plan("Python tips", days=1)
    items = planner.normalise_items(calendar_reply(1, skill="vox-explainer"), 1, ["bang-motion", "hyperframes"])
    assert items[0]["skill"] == "bang-motion"
    assert planner.calendar_prompt(plan, planner.skill_menu()).count("vox-explainer") == 0


def test_failed_bridge_marks_the_plan_failed(planner):
    plan = planner.new_plan("Python tips", days=2)

    def broken(prompt, schema, timeout):
        raise planner.PlannerError("claude is out of quota for now")

    with pytest.raises(planner.PlannerError):
        planner.run_plan(plan["id"], ask=broken)
    saved = planner.load_plan(plan["id"])
    assert saved["status"] == "failed" and "quota" in saved["error"]


def test_markdown_lists_every_day_and_prompt(planner):
    plan = planner.new_plan("Python tips", days=2)
    planner.make_calendar(plan, ask=lambda p, s, t: calendar_reply(2))
    planner.write_prompts(plan, ask=lambda p, s, t: prompt_reply([1, 2]))
    text = planner.markdown(plan)
    assert "| 2 | Title 2 | bang-motion | 27s | Hook 2 |" in text
    assert text.count("## Day ") == 2 and text.count("Claude Code prompt:") == 2
    assert "#python #coding" in text


def test_plan_id_must_be_a_slug(planner):
    with pytest.raises(ValueError):
        planner.plan_path("../etc/passwd")
    with pytest.raises(FileNotFoundError):
        planner.load_plan("nothing-here")
