"""The topic scout reads live search and community signals, and the planner builds each day on one of them."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
REELS = ROOT / "studio" / "reels"

pytestmark = pytest.mark.skipif(not (REELS / "topics.py").exists(), reason="the private studio folder is not checked out")


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, REELS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def topics(tmp_path, monkeypatch):
    module = _load("studio_reels_topics_test", "topics.py")
    monkeypatch.setattr(module, "HOME", tmp_path / "topics")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)  # no yt-dlp in tests
    return module


ATOM = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>Is incognito useless at work?</title><link href="https://www.reddit.com/r/privacy/1"/></entry>'
        '<entry><title>My phone heard me talk about shoes</title><link href="https://www.reddit.com/r/privacy/2"/></entry>'
        '</feed>')
TRENDS = ('<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item><title>cricket final</title>'
          '<ht:approx_traffic>500K+</ht:approx_traffic></item></channel></rss>')


def fake_get(url):
    if "suggestqueries" in url:
        query = url.split("q=")[-1]
        where = "youtube" if "ds=yt" in url else "google"
        return json.dumps([query, [f"{query} {where} suggestion {n}" for n in range(1, 6)]])
    if "reddit.com" in url:
        return ATOM
    if "hn.algolia" in url:
        return json.dumps({"hits": [{"title": "Incognito tracking lawsuit", "points": 300, "num_comments": 80, "objectID": "9"}]})
    if "trends.google" in url:
        return TRENDS
    raise OSError("unexpected url " + url)


def test_gather_reads_every_source_numbers_signals_and_drops_duplicates(topics):
    signals, counts = topics.gather(["incognito mode", "incognito mode"], ["privacy"], "IN", fake_get)
    assert {"youtube_suggest", "google_suggest", "reddit", "hn", "trends_now"} <= set(counts)
    assert [s["id"] for s in signals] == [f"s{n}" for n in range(1, len(signals) + 1)]
    texts = [s["text"] for s in signals]
    assert len(texts) == len(set(t.casefold() for t in texts))
    hn = next(s for s in signals if s["source"] == "hn")
    assert hn["url"] == "https://news.ycombinator.com/item?id=9" and "300 points" in hn["metric_label"]


def test_a_question_seed_is_not_prefixed_again(topics):
    asked = []
    topics.suggestions("why is my phone slow", True, lambda url: asked.append(url) or json.dumps(["", []]))
    assert len(asked) == 1 and "why%20why" not in asked[0]


def test_a_dead_source_does_not_stop_the_others(topics):
    def flaky(url):
        if "reddit.com" in url:
            raise OSError("blocked")
        return fake_get(url)
    _, counts = topics.gather(["incognito"], ["privacy"], "IN", flaky)
    assert "reddit" not in counts and counts["youtube_suggest"]


def _topic(n, evidence, rel=4, relat=4, title=None):
    return {"id": f"t{n}", "title": title or f"Topic {n}", "search_phrase": "is incognito private",
            "relatable_moment": "You open an incognito tab at work.", "why_now": "searched a lot",
            "evidence": evidence, "scores": {"trend": 4, "relevance": rel, "relatability": relat, "novelty": 3},
            "format": "myth-bust", "hook_idea": "Incognito hides it from you, not your boss."}


def test_rank_problems_refuse_invented_evidence_and_bad_scores(topics):
    ids = {"s1", "s2", "s3"}
    reply = {"topics": [_topic(1, ["s1", "s99"]), {**_topic(2, ["s1", "s2"]), "scores": {"trend": 9}},
                        _topic(3, ["s1", "s2"], title="Topic 1")]}
    problems = " | ".join(topics.rank_problems(reply, ids, 3))
    assert "s99 is not in the signal list" in problems
    assert "t2: scores need" in problems
    assert "duplicate title" in problems


def test_shortlist_keeps_only_relevant_relatable_topics_with_proof_best_first(topics):
    signals = [{"id": f"s{n}", "source": src, "text": f"signal {n}", "metric_label": "x", "url": "https://e.x"}
               for n, src in enumerate(["reddit", "hn", "youtube_suggest"], 1)]
    reply = {"topics": [_topic(1, ["s1", "s3"]), _topic(2, ["s1", "s2", "s3"]),
                        _topic(3, ["s1", "s2"], rel=2), _topic(4, ["s1", "s2"], relat=1), _topic(5, ["s1"])]}
    kept = topics.shortlist(reply, signals)
    assert [t["title"] for t in kept] == ["Topic 2", "Topic 1"]  # three sources beat two; weak ones dropped
    assert [t["id"] for t in kept] == ["t1", "t2"]
    assert kept[0]["evidence"][0]["text"] == "signal 1" and kept[0]["sources"] == ["hn", "reddit", "youtube_suggest"]


def test_scout_runs_seeds_then_ranking_and_saves_the_signals(topics):
    asked = []

    def checked(prompt, schema, check, timeout, ask=None):
        asked.append(schema)
        if '"seeds"' in schema:
            reply = {"seeds": ["incognito mode", "phone listening", "do i need antivirus", "5g health"],
                     "subreddits": ["privacy"], "geo": "IN"}
        else:
            ids = [line.split(" ", 1)[0] for line in prompt.split("Signals:\n", 1)[1].splitlines()]
            reply = {"summary": "People doubt privacy tools.",
                     "topics": [_topic(n, ids[n:n + 2], title=f"Topic {n}") for n in range(1, 11)]}
        assert check(reply) == []
        return reply

    found = topics.scout("Tech myths", "curious people", days=7, checked=checked, get=fake_get)
    assert len(asked) == 2 and len(found["topics"]) == 10
    saved = json.loads(Path(found["path"]).read_text())
    assert saved["signals"] and saved["summary"] == "People doubt privacy tools."
    again = topics.scout("Tech myths", checked=lambda *a, **k: pytest.fail("cache should answer"), get=fake_get)
    assert again["at"] == found["at"]


def test_scout_refuses_when_the_internet_gave_nothing(topics):
    def offline(url):
        raise OSError("offline")
    checked = lambda prompt, schema, check, timeout, ask=None: {"seeds": ["a b", "c d", "e f", "g h"]}
    with pytest.raises(topics.ScoutError, match="signals came back"):
        topics.scout("Tech myths", checked=checked, get=offline, use_cache=False)


@pytest.fixture
def planner(tmp_path, monkeypatch):
    module = _load("studio_reels_planner_topics_test", "planner.py")
    monkeypatch.setattr(module, "PLANS", tmp_path / "plans")
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    monkeypatch.setattr(module, "skill_menu", lambda: [{"name": "bang-motion", "repo": "x", "summary": "m", "installed": True}])
    return module


RESEARCH = {"at": "2026-11-14T09:00:00", "summary": "s", "topics": [
    {"id": "t1", "title": "Overnight charging", "search_phrase": "does charging overnight ruin battery",
     "relatable_moment": "You plug in at bedtime.", "why_now": "1.1M views", "format": "myth-bust",
     "hook_idea": "h", "scores": {"trend": 5, "relevance": 5, "relatability": 5, "novelty": 4}, "score": 5.2,
     "sources": ["youtube_shorts"], "evidence": [{"id": "s1", "source": "youtube_shorts", "text": "Does overcharging hurt?",
                                                  "metric_label": "1,109,298 views", "url": "https://youtube.com/x"}]}]}


def _calendar(topic_id):
    return {"pillars": ["Myths"], "items": [{"day": 1, "topic_id": topic_id, "title": "Charge overnight?", "hook": "You charge at night.",
            "angle": "a", "skill": "bang-motion", "beats": ["b"], "caption": "c", "relatable_moment": ""}]}


def test_calendar_must_use_a_researched_topic_and_carries_its_proof(planner):
    plan = planner.new_plan("Tech myths", days=1, research=True)
    plan["research"] = RESEARCH
    replies = [_calendar("t9"), _calendar("t1")]
    prompts = []

    def ask(prompt, schema, timeout):
        prompts.append(prompt)
        return replies.pop(0)

    planner.make_calendar(plan, ask=ask)
    assert "Researched shortlist" in prompts[0] and "does charging overnight ruin battery" in prompts[0]
    assert "topic_id must be one of t1" in prompts[1]
    item = plan["items"][0]
    assert item["topic_id"] == "t1" and item["search_phrase"] == "does charging overnight ruin battery"
    assert item["relatable_moment"] == "You plug in at bedtime." and item["evidence"][0]["metric_label"] == "1,109,298 views"


def test_failed_research_still_plans_and_says_so(planner, monkeypatch):
    plan = planner.new_plan("Tech myths", days=1, research=True)

    def broken(*args, **kwargs):
        raise planner.topics.ScoutError("only 0 signals came back")

    monkeypatch.setattr(planner.topics, "scout", broken)
    planner.research_topics(plan)
    assert plan["research"]["error"] == "only 0 signals came back" and plan["research"]["topics"] == []
    assert "Researched shortlist" not in planner.calendar_prompt(plan, planner.skill_menu())


def test_plans_without_research_never_touch_the_network(planner, monkeypatch):
    monkeypatch.setattr(planner.topics, "scout", lambda *a, **k: pytest.fail("no research was asked for"))
    plan = planner.new_plan("Tech myths", days=1)
    planner.run_plan(plan["id"], with_prompts=False, ask=lambda *a: _calendar(""))
    assert planner.load_plan(plan["id"])["items"][0]["title"] == "Charge overnight?"


def test_idea_skills_are_not_offered_as_a_way_to_draw_the_reel(tmp_path, monkeypatch):
    module = _load("studio_reels_planner_menu_test", "planner.py")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"skills": [
        {"name": "last30days", "group": "ideas", "skills": ["last30days"], "summary": "research"},
        {"name": "bang", "group": "requested", "skills": ["bang-motion"], "summary": "motion"}]}))
    monkeypatch.setattr(module, "MANIFEST", manifest)
    monkeypatch.setattr(module, "discover_skills", lambda known: [])
    names = [m["name"] for m in module.skill_menu()]
    assert "bang-motion" in names and "last30days" not in names
    assert module.idea_skill_names() == ["last30days"]
