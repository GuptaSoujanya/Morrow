"""The studio memory learns only what several published reels agree on, and turns it into the bar."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MEMORY = ROOT / "studio" / "reels" / "memory.py"
AGENT = ROOT / "studio" / "reels" / "social_agent.py"

pytestmark = pytest.mark.skipif(not MEMORY.exists(), reason="the private studio folder is not checked out")


@pytest.fixture()
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("MORROW_STUDIO_MEMORY", str(tmp_path / "memory"))
    spec = importlib.util.spec_from_file_location("studio_memory_under_test", MEMORY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REELS = [{"reel": "p:1", "title": "Incognito", "hook": "Your browser is not hiding you at all, here is why",
          "platforms": {"instagram": {"views": 900}}},
         {"reel": "p:2", "title": "5G", "hook": "5G is not cooking you", "platforms": {"instagram": {"views": 4100}}}]


def _reply(lesson_id="", reels=("p:2",), supports=True, check=None):
    return {"summary": "Short hooks beat long ones on this channel.", "worked": ["p:2 short hook, 4100 views"],
            "failed": ["p:1 eleven-word hook, 900 views"], "fixes": ["Keep the hook to seven words"],
            "findings": [{"lesson_id": lesson_id, "text": "A hook of seven words or fewer holds viewers", "kind": "keep",
                          "supports": supports, "reels": list(reels),
                          "check": check or {"type": "auto", "rule": "max_hook_words", "value": 7}}]}


def _checked(prompt, schema, problems, timeout, ask):
    reply = ask(prompt, schema, timeout)
    found = problems(reply)
    if found:
        raise ValueError("; ".join(found))
    return reply


def test_the_bar_starts_at_level_one_and_nothing_reaches_the_prompts(memory):
    bar = memory.checklist()
    assert bar["level"] == 1 and [item["rule"] for item in bar["items"]] == list(memory.BASE_CHECKS)
    assert memory.rules_text() == ""
    assert memory.summary()["stable"] == []


def test_a_lesson_needs_two_reels_before_it_raises_the_bar(memory):
    first = memory.analyse(REELS, ask=lambda *a: _reply(reels=("p:2",)), checked=_checked)
    lesson = memory.lessons()[0]
    assert lesson["status"] == "candidate" and first["changes"]["level"] == 1
    assert "Keep the hook to seven words" in memory.rules_text(), "the latest fixes reach the next brief at once"
    assert "Keep: A hook" not in memory.rules_text(), "a candidate is not yet a rule"

    second = memory.analyse(REELS, ask=lambda *a: _reply(lesson_id=lesson["id"], reels=("p:1", "p:2")), checked=_checked)
    assert second["changes"]["promoted"] == [lesson["id"]] and second["changes"]["level"] == 2
    bar = memory.checklist()
    assert bar["level"] == 2 and bar["items"][-1]["text"] == "The hook is 7.0 words or fewer"
    rules = memory.rules_text("make")
    assert "memory level 2" in rules and "Keep: A hook of seven words" in rules and "The hook is 7.0 words or fewer" in rules
    home = Path(memory._home())
    assert (home / "LESSONS.md").is_file() and len(list((home / "briefs").glob("*.md"))) == 2
    assert "How the next reels fix it" in (home / second["brief"]).read_text()
    assert len((home / "history.jsonl").read_text().splitlines()) == 2


def test_lessons_the_results_contradict_are_retired(memory):
    memory.analyse(REELS, ask=lambda *a: _reply(reels=("p:2",)), checked=_checked)
    lesson = memory.lessons()[0]
    memory.analyse(REELS, ask=lambda *a: _reply(lesson_id=lesson["id"], reels=("p:1", "p:2"), supports=False), checked=_checked)
    assert memory.lessons()[0]["status"] == "retired"
    assert memory.checklist()["level"] == 1


def test_an_unusable_analysis_is_refused(memory):
    with pytest.raises(ValueError, match="must name reels"):
        memory.analyse(REELS, ask=lambda *a: _reply(reels=("p:9",)), checked=_checked)
    with pytest.raises(ValueError, match="not one of the auto rules"):
        memory.analyse(REELS, ask=lambda *a: _reply(check={"type": "auto", "rule": "views_up", "value": 1}), checked=_checked)
    with pytest.raises(memory.MemoryStoreError):
        memory.analyse([], ask=lambda *a: {})
    assert memory.lessons() == []


def _facts(**extra):
    base = {"plan_id": "p", "day": 1, "sha256": "cut-1", "item": {"hook": "Incognito is not invisible", "title": "X"},
            "record": {"status": "ok"}, "critic": {"hook_ok": True, "mascot_ok": True},
            "voice": {"pace_ok": True, "wpm": 140}, "audio": {"lufs": -14.6, "target_lufs": -14}, "caption": "Hi #a #b",
            "duration_s": 27.0}
    return base | extra


def test_a_reel_is_checked_against_every_item_of_the_bar(memory):
    result = memory.check(_facts())
    assert result["passed"] and len(result["items"]) == 5
    failing = memory.check(_facts(audio={"lufs": -19, "target_lufs": -14}, critic={"hook_ok": False}))
    assert not failing["passed"] and any("loudness" in text or "LUFS" in text for text in failing["failing"])
    unknown = memory.check(_facts(critic={}))
    assert unknown["passed"], "a check with nothing to read is not applicable, not failed"
    assert [item["ok"] for item in unknown["items"] if item["id"] == "hook_clear"] == [None]


def test_learned_checks_are_measured_and_judged(memory):
    memory.analyse(REELS, ask=lambda *a: _reply(reels=("p:2",)), checked=_checked)
    lesson = memory.lessons()[0]
    memory.analyse(REELS, ask=lambda *a: _reply(lesson_id=lesson["id"], reels=("p:1", "p:2")), checked=_checked)
    long_hook = memory.check(_facts(item={"hook": "one two three four five six seven eight nine"}))
    assert not long_hook["passed"] and "measured 9" in long_hook["failing"][0]

    judge = {"type": "judge", "question": "Does the first line name a moment the viewer knows?"}
    memory.analyse(REELS, ask=lambda *a: {**_reply(reels=("p:1", "p:2"), check=judge),
                                          "findings": [{"lesson_id": "", "text": "Open on a moment people recognise",
                                                        "kind": "keep", "supports": True, "reels": ["p:1", "p:2"], "check": judge}]},
                   checked=_checked)
    asked = []
    def ask(prompt, schema, timeout):
        asked.append(prompt)
        item = next(i for i in memory.checklist()["items"] if i["type"] == "judge")
        return {"answers": [{"id": item["id"], "ok": False, "why": "It opens with a definition."}]}
    judged = memory.check(_facts(item={"hook": "short"}), ask=ask)
    assert asked and "first line" in asked[0] and not judged["passed"]
    assert any("opens with a definition" in text for text in judged["failing"])
    assert memory.check_state("p", 1, "cut-1")["current"] is True
    assert memory.check_state("p", 1, "cut-2")["current"] is False, "a new cut needs a new check"


def test_the_planner_and_studio_brief_carry_what_was_proven(memory, monkeypatch):
    memory.analyse(REELS, ask=lambda *a: _reply(reels=("p:1", "p:2")), checked=_checked)
    spec = importlib.util.spec_from_file_location("studio_planner_memory_test", ROOT / "studio" / "reels" / "planner.py")
    planner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(planner)
    plan = {"days": 3, "handle": "@me", "topic": "Tech myths", "audience": "", "language": "English", "notes": "", "brand": None}
    prompt = planner.calendar_prompt(plan, [{"name": "hyperframes", "summary": "x", "installed": True}])
    assert "LESSONS FROM THIS CHANNEL'S OWN RESULTS" in prompt and "seven-word hook" not in prompt
    assert "Keep: A hook of seven words or fewer holds viewers" in prompt


@pytest.fixture()
def agent(memory):
    spec = importlib.util.spec_from_file_location("studio_social_agent_memory", AGENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measured_posts_are_folded_into_one_record_per_reel(agent, monkeypatch):
    posts = [{"plan_id": "p", "day": 1, "platform": platform, "status": "posted", "title": "X", "caption": "c",
              "posted_at": "2026-11-14T10:00:00", "metrics": {"measured_at": "2026-11-15T10:00:00", "views": views}}
             for platform, views in (("instagram", 900), ("youtube", 300))]
    posts.append({"plan_id": "p", "day": 2, "platform": "instagram", "status": "posted", "metrics": None})
    monkeypatch.setattr(agent.social, "posts_with_metrics", lambda limit=60: posts)
    monkeypatch.setattr(agent.planner, "load_plan", lambda plan_id: {"items": [{"day": 1, "hook": "H", "duration_s": 27}]})
    reels = agent._measured_reels()
    assert len(reels) == 1 and reels[0]["reel"] == "p:1" and reels[0]["hook"] == "H"
    assert reels[0]["platforms"]["instagram"]["views"] == 900 and reels[0]["platforms"]["youtube"]["views"] == 300


def test_the_release_refuses_a_reel_that_was_not_checked_or_failed(agent, monkeypatch):
    draft = {"content_metadata": {"plan_id": "p", "day": 1}}
    monkeypatch.setattr(agent, "_approved", lambda *a: draft)
    sent = []
    monkeypatch.setattr(agent, "_publish", lambda *a: sent.append(a) or {"status": "complete", "results": []})
    monkeypatch.setattr(agent, "_advance", lambda plan_id, day: 2)
    monkeypatch.setattr(agent, "bar_state", lambda plan_id, day: {"current": False, "check": {}})
    with pytest.raises(agent.AgentError, match="Check this cut"):
        agent._release("d", "r", True)
    monkeypatch.setattr(agent, "bar_state", lambda plan_id, day: {"current": True, "check": {"passed": False, "failing": ["loud"]}})
    with pytest.raises(agent.AgentError, match="does not pass the bar"):
        agent._release("d", "r", True)
    assert not sent
    monkeypatch.setattr(agent, "bar_state", lambda plan_id, day: {"current": True, "check": {"passed": True}})
    assert agent._release("d", "r", True)["next_day"] == 2 and len(sent) == 1
