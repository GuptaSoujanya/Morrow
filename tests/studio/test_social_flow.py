"""The social pipeline reports where it stands from evidence, and says what is in the way."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "studio" / "reels" / "social_agent.py"

pytestmark = pytest.mark.skipif(not AGENT.exists(), reason="the private studio folder is not checked out")


@pytest.fixture(scope="module")
def flow_of():
    spec = importlib.util.spec_from_file_location("studio_social_agent_flow", AGENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _agent(**extra):
    base = {"config": {"brand_name": "Cyber Mythic", "niche": "Tech myths", "audience": "Curious people",
                       "brand_facts": ["Two years of writing about security"], "platforms": ["instagram", "youtube"],
                       "plan_id": ""},
            "runs": [], "operations": [], "draft": None, "review_stale": False, "review_stale_reason": "",
            "audit": {"accounts": {}}, "running": None}
    return base | extra


def _facts(**extra):
    base = {"accounts": {}, "current_plan": {}, "next": {}, "posts": [], "research": None, "learnings": None,
            "running": None}
    return base | extra


def _step(flow, key):
    return next(step for step in flow["steps"] if step["key"] == key)


def _signed_in(platform, handle):
    return {platform: {"logged_in": True, "handle": handle, "checked_at": "2026-11-13T04:00:00+00:00"}}


def _plan(briefed=7, total=7):
    return {"id": "a-plan", "topic": "Myth Lab", "days": total, "items_total": total, "prompts_done": briefed,
            "status": "done", "updated": "2026-11-12T23:00:00"}


def test_every_step_of_the_flow_is_reported_in_order(flow_of):
    flow = flow_of.flow(_agent(), _facts())
    assert [step["key"] for step in flow["steps"]] == ["identity", "audit", "research", "plan", "render",
                                                       "prepare", "review", "apply-profile", "publish",
                                                       "measure", "learn"]
    assert flow["total"] == 11 and flow["done"] <= flow["total"]
    assert all(step["label"] and step["blurb"] and step["state"] for step in flow["steps"])


def test_an_incomplete_brief_names_exactly_what_is_missing(flow_of):
    thin = _agent(config={"brand_name": "", "niche": "Tech myths", "audience": "", "brand_facts": [],
                          "platforms": ["instagram"]})
    step = _step(flow_of.flow(thin, _facts()), "identity")
    assert step["state"] == "blocked"
    for wanted in ("a name", "who it is for", "at least one fact"):
        assert wanted in step["blocked_on"]
    assert "what you create" not in step["blocked_on"], "a field that is filled must not be asked for"


def test_a_complete_brief_is_done_and_counts_its_facts(flow_of):
    step = _step(flow_of.flow(_agent(), _facts()), "identity")
    assert step["state"] == "done" and step["evidence"]["facts"] == 1
    assert "Cyber Mythic" in step["detail"]


def test_a_profile_that_was_read_but_not_confirmed_says_so(flow_of):
    audited = {"accounts": {"instagram": {"logged_in": False, "handle": "im_cybermythic",
                                          "profile_url": "https://instagram.com/im_cybermythic",
                                          "problem": "The profile is new and blank."},
                            "youtube": {"logged_in": False, "handle": "@Iam_CyberMythic"}}}
    step = _step(flow_of.flow(_agent(audit=audited), _facts()), "audit")
    assert step["state"] == "blocked"
    assert "im_cybermythic" in step["detail"] and "could not be confirmed" in step["detail"]
    assert "sign in" in step["blocked_on"] and "The profile is new and blank." in step["blocked_on"]
    assert step["evidence"]["read"] == ["im_cybermythic", "@Iam_CyberMythic"]


def test_an_unchecked_account_is_not_called_signed_out(flow_of):
    step = _step(flow_of.flow(_agent(), _facts()), "audit")
    assert step["state"] == "ready" and "not verified" in step["detail"]
    assert step["evidence"]["unchecked"] == ["instagram", "youtube"]


def test_both_accounts_verified_finishes_the_step(flow_of):
    audited = {"accounts": _signed_in("instagram", "im_cybermythic") | _signed_in("youtube", "@Iam_CyberMythic")}
    step = _step(flow_of.flow(_agent(audit=audited), _facts()), "audit")
    assert step["state"] == "done" and "im_cybermythic" in step["detail"] and not step["blocked_on"]


def test_the_plan_counts_the_days_the_plan_itself_reports(flow_of):
    done = _step(flow_of.flow(_agent(), _facts(current_plan=_plan())), "plan")
    assert done["state"] == "done" and "7 of 7 days briefed" in done["detail"]
    part = _step(flow_of.flow(_agent(), _facts(current_plan=_plan(briefed=2))), "plan")
    assert part["state"] == "ready" and "2 of 7" in part["detail"]
    none = _step(flow_of.flow(_agent(), _facts()), "plan")
    assert none["state"] == "ready" and "No plan chosen" in none["detail"]


def test_research_is_only_skipped_when_a_plan_is_already_chosen(flow_of):
    chosen = _step(flow_of.flow(_agent(), _facts(current_plan=_plan())), "research")
    assert chosen["state"] == "skipped" and "skips research" in chosen["detail"]
    open_ = _step(flow_of.flow(_agent(), _facts()), "research")
    assert open_["state"] == "ready"
    found = _step(flow_of.flow(_agent(), _facts(research={"at": "2026-11-12T10:00:00", "trends": [{}, {}, {}]})),
                  "research")
    assert found["state"] == "done" and found["evidence"]["trends"] == 3


def test_a_reel_is_only_done_when_the_render_verified_it(flow_of):
    made = _facts(current_plan=_plan(), next={"plan_id": "a-plan", "day": 1, "title": "Incognito", "made": "ok"})
    assert _step(flow_of.flow(_agent(), made), "render")["state"] == "done"
    pending = _facts(current_plan=_plan(), next={"plan_id": "a-plan", "day": 1, "title": "Incognito", "made": ""})
    step = _step(flow_of.flow(_agent(), pending), "render")
    assert step["state"] == "ready" and "not rendered yet" in step["detail"]
    assert _step(flow_of.flow(_agent(), _facts()), "render")["state"] == "blocked"


def test_a_failed_run_is_shown_as_failed_with_its_reason(flow_of):
    runs = [{"stage": "render", "status": "failed", "error": "The renderer did not produce a verified reel.",
             "finished_at": "2026-11-13T01:00:00+00:00"}]
    facts = _facts(current_plan=_plan(), next={"plan_id": "a-plan", "day": 1, "title": "X", "made": ""})
    step = _step(flow_of.flow(_agent(runs=runs), facts), "render")
    assert step["state"] == "failed" and "verified reel" in step["detail"]


def test_a_stale_package_blocks_review_instead_of_inviting_approval(flow_of):
    draft = {"id": "d1", "revision": "r1", "created_at": "2026-11-13T03:00:00+00:00",
             "assets": {"avatar": {}, "banner": {}}, "content_metadata": {"video": {"url": "/v.mp4"}}}
    fresh = flow_of.flow(_agent(draft=draft), _facts())
    assert _step(fresh, "prepare")["state"] == "done" and "the reel" in _step(fresh, "prepare")["detail"]
    assert _step(fresh, "review")["state"] == "waiting"
    assert "instagram" in _step(fresh, "review")["detail"]

    stale = flow_of.flow(_agent(draft=draft, review_stale=True, review_stale_reason="The brief changed."), _facts())
    assert _step(stale, "prepare")["state"] == "blocked"
    assert _step(stale, "review")["state"] == "blocked" and "new package" in _step(stale, "review")["blocked_on"]
    assert _step(stale, "publish")["state"] == "blocked"


def test_an_uncertain_public_action_refuses_to_look_runnable(flow_of):
    draft = {"id": "d1", "revision": "r1", "created_at": "2026-11-13T03:00:00+00:00", "assets": {},
             "content_metadata": {}}
    operations = [{"action": "publish", "platform": "instagram", "status": "needs_verification",
                   "revision": "r1", "started_at": "2026-11-13T04:00:00+00:00"}]
    step = _step(flow_of.flow(_agent(draft=draft, operations=operations), _facts()), "publish")
    assert step["state"] == "blocked" and "uncertain" in step["detail"]
    assert "automatic retry is refused" in step["blocked_on"]


def test_applied_profiles_on_every_platform_complete_the_step(flow_of):
    draft = {"id": "d1", "revision": "r1", "created_at": "2026-11-13T03:00:00+00:00", "assets": {},
             "content_metadata": {}}
    operations = [{"action": "profile", "platform": platform, "status": "complete", "revision": "r1",
                   "finished_at": "2026-11-13T05:00:00+00:00"} for platform in ("instagram", "youtube")]
    flow = flow_of.flow(_agent(draft=draft, operations=operations), _facts())
    assert _step(flow, "apply-profile")["state"] == "done"
    assert _step(flow, "review")["state"] == "done"


def test_measure_and_learn_wait_for_something_real_to_measure(flow_of):
    empty = flow_of.flow(_agent(), _facts())
    assert _step(empty, "measure")["state"] == "blocked" and "Nothing published" in _step(empty, "measure")["detail"]
    assert _step(empty, "learn")["state"] == "blocked"

    posted = _facts(posts=[{"status": "posted", "metrics": {}}])
    assert _step(flow_of.flow(_agent(), posted), "measure")["state"] == "ready"

    measured = _facts(posts=[{"status": "posted", "metrics": {"measured_at": "2026-11-13T06:00:00"}}])
    flow = flow_of.flow(_agent(), measured)
    assert _step(flow, "measure")["state"] == "done"
    assert _step(flow, "learn")["state"] == "ready", "there is data, so learning is now possible"

    learned = _facts(posts=measured["posts"], learnings={"at": "2026-11-13T07:00:00", "summary": "Hooks win."})
    assert _step(flow_of.flow(_agent(), learned), "learn")["state"] == "done"


def test_a_single_stage_run_lights_up_its_own_step_only(flow_of):
    runs = [{"id": "run-1", "stage": "audit", "status": "running", "checkpoint": "starting",
             "started_at": "2026-11-13T04:40:00+00:00", "steps": []}]
    flow = flow_of.flow(_agent(runs=runs, running={"action": "audit"}), _facts())
    assert flow["running_stage"] == "audit" and flow["run_id"] == "run-1"
    assert _step(flow, "audit")["state"] == "running"
    assert _step(flow, "identity")["state"] != "running", "a starting run must not light up the first step"


def test_a_stage_named_differently_elsewhere_still_finds_its_step(flow_of):
    for stage, key in (("check", "audit"), ("make", "render"), ("metadata", "prepare")):
        flow = flow_of.flow(_agent(running={"action": stage}), _facts())
        assert flow["running_stage"] == key, stage
        assert _step(flow, key)["state"] == "running", stage
    unknown = flow_of.flow(_agent(running={"action": "cycle"}), _facts())
    assert unknown["running_stage"] == "", "an unknown stage must not light up a wrong step"


def test_the_pipeline_is_placed_by_its_checkpoint_and_marks_what_it_passed(flow_of):
    runs = [{"id": "run-2", "stage": "pipeline", "status": "running", "checkpoint": "rendering",
             "started_at": "2026-11-13T04:40:00+00:00",
             "steps": [{"stage": "identity"}, {"stage": "audit"}, {"stage": "research"}, {"stage": "plan"}]}]
    flow = flow_of.flow(_agent(runs=runs), _facts())
    assert flow["running_stage"] == "render" and _step(flow, "render")["state"] == "running"
    for passed in ("identity", "audit", "research", "plan"):
        assert _step(flow, passed)["state"] == "done", passed
    assert _step(flow, "publish")["state"] != "done"


def test_you_are_here_is_the_first_step_still_to_do(flow_of):
    audited = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    facts = _facts(current_plan=_plan(), next={"plan_id": "a-plan", "day": 1, "title": "X", "made": "ok"})
    flow = flow_of.flow(_agent(audit=audited), facts)
    assert flow["steps"][flow["position"]]["key"] == "prepare"
    assert flow["steps"][flow["position"]]["state"] not in ("done", "skipped", "not_due")
    assert flow["blocked_on"] == "" or isinstance(flow["blocked_on"], str)


def test_nothing_is_sent_to_an_account_whose_sign_in_is_unconfirmed(flow_of):
    draft = {"id": "d1", "revision": "r1", "created_at": "2026-11-13T03:00:00+00:00", "assets": {},
             "content_metadata": {}}
    audited = {"accounts": {"instagram": {"logged_in": False, "handle": "im_cybermythic"},
                            "youtube": {"logged_in": False, "handle": "@Iam_CyberMythic"}}}
    flow = flow_of.flow(_agent(draft=draft, audit=audited), _facts())
    for key in ("apply-profile", "publish"):
        step = _step(flow, key)
        assert step["state"] == "blocked", key
        assert "Confirm the sign-in" in step["blocked_on"], key
        assert step["evidence"]["unverified"] == ["instagram", "youtube"], key
    assert _step(flow, "review")["state"] == "waiting", "reading and editing the package is still possible"

    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    ready = flow_of.flow(_agent(draft=draft, audit=verified), _facts())
    assert _step(ready, "apply-profile")["state"] == "waiting"
