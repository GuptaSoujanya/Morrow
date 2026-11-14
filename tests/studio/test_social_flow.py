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
            "audit": {"accounts": {}}, "running": None,
            # The reel and artwork reviews are their own steps; most tests start with both approved.
            "reviews": {"video": {"state": "approved"}, "artwork": {"state": "approved", "pieces": {}}}}
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


PIECES = {kind: {"kind": kind, "id": f"art-{kind}", "revision": f"rev-{kind}", "scope": "reel" if kind in ("cover", "thumbnail") else "channel"}
          for kind in ("cover", "thumbnail", "avatar", "banner")}


def _reviews(video="approved", art="approved", vid=None, artwork=None, profile="approved"):
    video_review = {"state": video, "made": "ok", "plan_id": "a-plan", "day": 1, "title": "X", "sha256": "cut-1",
                    "url": "/v?cut=1", "studio_url": "#studio?plan=a-plan&day=1"} | (vid or {})
    reel = {k: v for k, v in PIECES.items() if k in ("cover", "thumbnail")}
    art_review = {"state": art, "plan_id": "a-plan", "day": 1, "pieces": reel, "missing": [], "generic": [],
                  "fingerprint": {k: v["revision"] for k, v in reel.items()}} | (artwork or {})
    channel = {k: v for k, v in PIECES.items() if k in ("avatar", "banner")}
    profile_review = {"state": profile, "plan_id": "channel", "day": 0, "pieces": channel, "missing": [], "generic": [],
                      "fingerprint": {k: v["revision"] for k, v in channel.items()}}
    return {"video": video_review, "artwork": art_review, "profile": profile_review}


def _draft(sha="cut-1", **revisions):
    assets = {kind: {"source_artwork": {"id": f"art-{kind}", "revision": revisions.get(kind, f"rev-{kind}")}} for kind in PIECES}
    return {"id": "d1", "revision": "r1", "created_at": "2026-11-13T03:00:00+00:00", "assets": assets,
            "content_metadata": {"plan_id": "a-plan", "day": 1, "video": {"url": "/v.mp4", "sha256": sha}}}


def test_every_step_of_the_flow_is_reported_in_order(flow_of):
    flow = flow_of.flow(_agent(), _facts())
    assert [step["key"] for step in flow["steps"]] == [
        "identity", "audit", "profile-art", "profile-review", "apply-profile",
        "plan", "render", "video-review", "artwork", "artwork-review", "prepare", "bar", "review", "publish",
        "measure", "learn", "memory"]
    assert flow["total"] == 17 and flow["done"] <= flow["total"]
    assert all(step["label"] and step["blurb"] and step["state"] for step in flow["steps"])
    lanes = {lane["key"]: lane for lane in flow["lanes"]}
    assert list(lanes) == ["setup", "reel", "learn"] and lanes["setup"]["once"] and not lanes["reel"]["once"]
    assert lanes["setup"]["steps"] == ["identity", "audit", "profile-art", "profile-review", "apply-profile"]
    assert lanes["learn"]["steps"] == ["measure", "learn", "memory"]
    assert all(step["lane"] in lanes for step in flow["steps"])


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
    draft = _draft()
    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    fresh = flow_of.flow(_agent(draft=draft, audit=verified, bar=PASSED, reviews=_reviews()), _facts())
    assert _step(fresh, "prepare")["state"] == "done" and "the reel" in _step(fresh, "prepare")["detail"]
    assert _step(fresh, "review")["state"] == "waiting" and "upload to Instagram and YouTube" in _step(fresh, "review")["detail"]

    stale = flow_of.flow(_agent(draft=draft, audit=verified, bar=PASSED, reviews=_reviews(), review_stale=True,
                                review_stale_reason="The brief changed."), _facts())
    assert _step(stale, "prepare")["state"] == "blocked"
    assert _step(stale, "review")["state"] == "blocked" and "fresh package" in _step(stale, "review")["detail"]
    assert _step(stale, "publish")["state"] == "auto", "the upload only ever starts from the final review"


def test_measure_and_learn_wait_for_something_real_to_measure(flow_of):
    empty = flow_of.flow(_agent(), _facts())
    assert _step(empty, "measure")["state"] == "ready" and "Discover posts" in _step(empty, "measure")["detail"]
    assert _step(empty, "learn")["state"] == "blocked"
    assert _step(empty, "memory")["state"] == "blocked"

    posted = _facts(posts=[{"status": "posted", "plan_id": "a-plan", "day": 1, "metrics": {}}])
    assert _step(flow_of.flow(_agent(), posted), "measure")["state"] == "ready"

    measured = _facts(posts=[{"status": "posted", "plan_id": "a-plan", "day": 1, "platform": "instagram",
                              "metrics": {"measured_at": "2026-11-13T06:00:00"}}])
    flow = flow_of.flow(_agent(), measured)
    assert _step(flow, "measure")["state"] == "ready", "legacy snapshots do not prove current channel sync coverage"
    assert _step(flow, "learn")["state"] == "ready", "there is data, so learning is now possible"

    memo = {"level": 2, "stable": [{}], "candidates": [], "checklist": [{}] * 6,
            "last_analysis": {"at": "2026-11-13T07:00:00", "summary": "Hooks win.", "reels": ["a-plan:1"]}}
    learned = flow_of.flow(_agent(memory=memo), measured)
    assert _step(learned, "learn")["state"] == "done" and "Hooks win" in _step(learned, "learn")["detail"]
    assert _step(learned, "memory")["state"] == "done" and "Level 2" in _step(learned, "memory")["detail"]
    later = _facts(posts=measured["posts"] + [{"status": "posted", "plan_id": "a-plan", "day": 2, "platform": "youtube",
                                                "metrics": {"measured_at": "2026-11-14T06:00:00"}}])
    assert _step(flow_of.flow(_agent(memory=memo), later), "learn")["state"] == "ready", "a new measured reel asks for a new analysis"


def test_measurement_uses_discovery_coverage_and_drops_old_24_hour_gate(flow_of):
    old = [{"stage": "measure", "status": "not_due", "finished_at": "2026-11-13T04:00:00Z"}]
    step = _step(flow_of.flow(_agent(runs=old), _facts()), "measure")
    assert step["state"] == "ready" and "day" not in step["detail"]
    synced = {"status": "ok", "last_synced_at": "2026-11-14T10:00:00Z", "platforms": {
        "youtube": {"status": "ok", "posts_measured": 4, "posts_discovered": 4, "coverage": {"complete": True}}}}
    step = _step(flow_of.flow(_agent(), _facts(metrics_sync=synced)), "measure")
    assert step["state"] == "done" and step["evidence"]["discovered"] == 4
    assert step["at"] == synced["last_synced_at"]
    synced["platforms"]["youtube"]["coverage"]["complete"] = False
    assert _step(flow_of.flow(_agent(), _facts(metrics_sync=synced)), "measure")["state"] == "ready"
    synced["platforms"]["youtube"].update(status="auth_required", error="Sign in to the channel")
    step = _step(flow_of.flow(_agent(), _facts(metrics_sync=synced)), "measure")
    assert step["state"] == "blocked" and "Sign in" in step["detail"]


def test_external_measured_posts_are_safe_in_social_flow_and_have_stable_learning_keys(flow_of):
    post = {"id": 24, "plan_id": None, "day": None, "status": "posted", "platform": "youtube",
            "url": "https://www.youtube.com/shorts/abcdef12345?feature=share", "metrics": {"measured_at": "2026-11-14T10:00:00Z", "views": 123}}
    facts = _facts(posts=[post])
    assert _step(flow_of.flow(_agent(), facts), "learn")["state"] == "ready"
    key = flow_of._learning_post_key(post)
    assert key == flow_of._learning_post_key({**post, "url": "https://youtu.be/abcdef12345"})
    memo = {"last_analysis": {"at": "2026-11-14T11:00:00Z", "summary": "Observed counts reviewed.", "reels": [key]}}
    assert _step(flow_of.flow(_agent(memory=memo), facts), "learn")["state"] == "done"
    assert facts["posts"][0] is post and post["plan_id"] is None and post["metrics"]["views"] == 123


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
    for passed in ("identity", "audit", "plan"):
        assert _step(flow, passed)["state"] == "done", passed
    assert _step(flow, "publish")["state"] != "done"


def test_you_are_here_is_the_first_step_still_to_do(flow_of):
    audited = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    facts = _facts(current_plan=_plan(), next={"plan_id": "a-plan", "day": 1, "title": "X", "made": "ok"})
    setup_open = flow_of.flow(_agent(audit=audited, reviews=_reviews()), facts)
    assert setup_open["steps"][setup_open["position"]]["key"] == "apply-profile", "the one-time setup comes first"
    done = [{"action": "apply-profile", "platform": p, "status": "complete"} for p in ("instagram", "youtube")]
    flow = flow_of.flow(_agent(audit=audited, reviews=_reviews(), operations=done), facts)
    assert flow["steps"][flow["position"]]["key"] == "prepare"
    assert next(lane for lane in flow["lanes"] if lane["key"] == "reel")["position"] == "prepare"


def test_nothing_is_sent_to_an_account_whose_sign_in_is_unconfirmed(flow_of):
    audited = {"accounts": {"instagram": {"logged_in": False, "handle": "im_cybermythic"},
                            "youtube": {"logged_in": False, "handle": "@Iam_CyberMythic"}}}
    flow = flow_of.flow(_agent(draft=_draft(), audit=audited, bar=PASSED, reviews=_reviews()), _facts())
    step = _step(flow, "apply-profile")
    assert step["state"] == "blocked" and step["evidence"]["unverified"] == ["instagram", "youtube"]
    review = _step(flow, "review")
    assert review["state"] == "blocked" and "connected Instagram and YouTube accounts" in review["detail"]


def test_the_reel_is_watched_before_anything_is_packaged(flow_of):
    blocked = _step(flow_of.flow(_agent(reviews=_reviews(video="missing", vid={"made": ""})), _facts()), "video-review")
    assert blocked["state"] == "blocked" and "Render the reel first" in blocked["blocked_on"]

    pending = _step(flow_of.flow(_agent(reviews=_reviews(video="pending")), _facts()), "video-review")
    assert pending["state"] == "waiting" and "ready to watch" in pending["detail"]
    assert pending["evidence"]["url"] == "/v?cut=1", "the step points at the exact cut to watch"

    asked = _reviews(video="changes", vid={"note": "Hold the hook longer"})
    step = _step(flow_of.flow(_agent(reviews=asked), _facts()), "video-review")
    assert step["state"] == "waiting" and "Hold the hook longer" in step["detail"]
    assert "new cut" in step["blocked_on"]

    recut = _reviews(video="pending", vid={"earlier_note": "Hold the hook longer"})
    assert "it was asked to fix" in _step(flow_of.flow(_agent(reviews=recut), _facts()), "video-review")["detail"]
    assert _step(flow_of.flow(_agent(reviews=_reviews()), _facts()), "video-review")["state"] == "done"


def test_artwork_must_be_made_for_this_reel_before_it_can_be_checked(flow_of):
    gaps = _reviews(art="missing", artwork={"missing": ["thumbnail"], "generic": ["cover"]})
    flow = flow_of.flow(_agent(reviews=gaps), _facts())
    step = _step(flow, "artwork")
    assert step["state"] == "ready" and "thumbnail" in step["detail"] and "not made for this reel" in step["detail"]
    assert _step(flow, "artwork-review")["state"] == "blocked"

    full = flow_of.flow(_agent(reviews=_reviews(art="pending")), _facts())
    assert _step(full, "artwork")["state"] == "done" and "cover · thumbnail chosen" in _step(full, "artwork")["detail"]
    assert _step(full, "artwork-review")["state"] == "waiting"
    asked = _reviews(art="changes", artwork={"note": "Bigger headline"})
    assert "Bigger headline" in _step(flow_of.flow(_agent(reviews=asked), _facts()), "artwork-review")["detail"]
    nothing = flow_of.flow(_agent(reviews={"video": {}, "artwork": {"plan_id": "a-plan"}, "profile": {}}), _facts())
    assert _step(nothing, "profile-art")["state"] == "ready", "no pieces at all is not a finished step"


def test_a_package_holding_older_files_must_be_prepared_again(flow_of):
    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    for draft, wanted in ((_draft(sha="cut-0"), "older cut"), (_draft(cover="rev-old"), "different cover")):
        flow = flow_of.flow(_agent(draft=draft, audit=verified, reviews=_reviews()), _facts())
        step = _step(flow, "prepare")
        assert step["state"] == "ready" and "out of date" in step["detail"] and wanted in step["blocked_on"], wanted
        assert _step(flow, "review")["state"] == "blocked", wanted
    assert _step(flow_of.flow(_agent(draft=_draft(), reviews=_reviews()), _facts()), "prepare")["state"] == "done"


def test_studio_jobs_for_reels_and_artwork_find_their_steps(flow_of):
    for action, key in (("edit", "render"), ("generate", "artwork")):
        flow = flow_of.flow(_agent(running={"action": action}), _facts())
        assert flow["running_stage"] == key, action


@pytest.fixture()
def desk(flow_of, tmp_path, monkeypatch):
    """A real reviews file over a fake reel folder and a fake artwork selection."""
    monkeypatch.setattr(flow_of, "HOME", tmp_path / "agent")
    folder = tmp_path / "day-01"
    folder.mkdir()
    (folder / "reel.mp4").write_bytes(b"first cut")
    plan, item = {"id": "a-plan"}, {"day": 1, "title": "Incognito"}
    made = {"status": "ok"}
    active = {kind: {"id": piece["id"], "revision": piece["revision"], "scope": piece["scope"],
                     "path": str(tmp_path / "art" / piece["id"] / "artwork.png")} for kind, piece in PIECES.items()}
    monkeypatch.setattr(flow_of, "REVIEWS", tmp_path / "reviews.json")
    monkeypatch.setattr(flow_of, "_selection", lambda plan_id="", day=None: (plan, item))
    monkeypatch.setattr(flow_of.planner, "day_dir", lambda plan, day: folder)
    monkeypatch.setattr(flow_of.social, "made_record", lambda plan, day, state=None: made)
    monkeypatch.setattr(flow_of, "_active_artwork", lambda plan_id="", day=None: active)
    monkeypatch.setattr(flow_of, "_artwork_module", lambda: None)
    monkeypatch.setattr(flow_of, "load_config", lambda: {"avatar_file": ""})
    return {"folder": folder, "made": made, "active": active}


def test_an_approval_belongs_to_the_exact_cut(flow_of, desk):
    assert flow_of.video_review()["state"] == "pending"
    with pytest.raises(flow_of.AgentError, match="what should change"):
        flow_of.review("video", "changes", "")
    asked = flow_of.review("video", "changes", "Hold the hook longer")
    assert asked["state"] == "changes" and asked["note"] == "Hold the hook longer"

    (desk["folder"] / "reel.mp4").write_bytes(b"second cut")
    recut = flow_of.video_review()
    assert recut["state"] == "pending" and recut["earlier_note"] == "Hold the hook longer", \
        "a new cut comes back for another look, carrying what it was asked to fix"
    assert flow_of.review("video", "approve")["state"] == "approved"
    (desk["folder"] / "reel.mp4").write_bytes(b"third cut")
    assert flow_of.video_review()["state"] == "pending", "an approval never carries over to a different file"


def test_a_cut_that_failed_its_checks_cannot_be_approved(flow_of, desk):
    desk["made"]["status"] = "failed"
    with pytest.raises(flow_of.AgentError, match="did not pass its own checks"):
        flow_of.review("video", "approve")
    (desk["folder"] / "reel.mp4").unlink()
    with pytest.raises(flow_of.AgentError, match="no finished reel"):
        flow_of.review("video", "approve")


def test_an_artwork_approval_belongs_to_the_exact_pieces(flow_of, desk):
    assert flow_of.review("artwork", "approve")["state"] == "approved"
    desk["active"]["avatar"] = dict(desk["active"]["avatar"], revision="rev-avatar-2", id="art-avatar-2")
    assert flow_of.artwork_review()["state"] == "approved", "the profile picture is not part of a reel's artwork"
    assert flow_of.profile_review()["state"] == "pending"
    assert flow_of.review("profile", "approve")["state"] == "approved"
    desk["active"]["cover"] = dict(desk["active"]["cover"], revision="rev-cover-2", id="art-cover-2")
    assert flow_of.artwork_review()["state"] == "pending", "choosing another cover needs a new approval"
    desk["active"]["cover"] = dict(desk["active"]["cover"], scope="channel")
    seen = flow_of.artwork_review()
    assert seen["state"] == "missing" and seen["generic"] == ["cover"]
    with pytest.raises(flow_of.AgentError, match="cover"):
        flow_of.review("artwork", "approve")
    del desk["active"]["avatar"]
    assert flow_of.profile_review()["missing"] == ["avatar"], "no banner is asked for: Shorts and Reels only"


def test_publishing_refuses_what_you_did_not_approve(flow_of, desk):
    draft = _draft(sha=flow_of._file_hash(desk["folder"] / "reel.mp4"))
    with pytest.raises(flow_of.AgentError, match="approve it first"):
        flow_of._require_reviews(draft, ("cover",))
    flow_of.review("video", "approve")
    with pytest.raises(flow_of.AgentError, match="cover and thumbnail"):
        flow_of._require_reviews(draft, ("cover",))
    flow_of.review("artwork", "approve")
    flow_of._require_reviews(draft, ("cover", "thumbnail"))
    with pytest.raises(flow_of.AgentError, match="profile picture and approve it"):
        flow_of._require_reviews(draft, ("avatar",), video=False)
    flow_of.review("profile", "approve")
    flow_of._require_reviews(draft, ("avatar",), video=False)
    with pytest.raises(flow_of.AgentError, match="different cut"):
        flow_of._require_reviews(_draft(sha="someone-elses"), ())
    with pytest.raises(flow_of.AgentError, match="cover you have not approved"):
        flow_of._require_reviews(_draft(sha=draft["content_metadata"]["video"]["sha256"], cover="rev-old"), ("cover",))


def test_a_package_made_before_the_sign_in_was_confirmed_must_be_prepared_again(flow_of):
    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    draft = _draft() | {"targets": {"instagram": {"logged_in": False, "handle": "a"},
                                    "youtube": {"logged_in": True, "handle": "b"}}}
    flow = flow_of.flow(_agent(draft=draft, audit=verified, reviews=_reviews()), _facts())
    step = _step(flow, "prepare")
    assert step["state"] == "ready" and "before Instagram was confirmed" in step["blocked_on"]
    assert _step(flow, "review")["state"] == "blocked"
    draft["targets"]["instagram"]["logged_in"] = True
    assert _step(flow_of.flow(_agent(draft=draft, audit=verified, reviews=_reviews()), _facts()), "prepare")["state"] == "done"


def test_a_new_blank_profile_still_counts_as_signed_in(flow_of, monkeypatch, tmp_path):
    asked = []
    def browse(platform, task, schema, label):
        asked.append((task, schema))
        return {"logged_in": True, "handle": "im_new", "profile_url": f"https://www.{platform}.com/im_new",
                "evidence": ["Edit profile is shown"], "notes": "No bio and no photo yet.", "problem": "",
                "_browser": {"profile": "/main"}, "_run": {"problem": ""}}
    state = {"accounts": {}}
    monkeypatch.setattr(flow_of, "HOME", tmp_path)
    monkeypatch.setattr(flow_of.social, "run_browser_task", browse)
    monkeypatch.setattr(flow_of.social, "load_state", lambda: state)
    monkeypatch.setattr(flow_of.social, "save_state", lambda value: None)
    result = flow_of._audit(["instagram"])
    assert result["accounts"]["instagram"]["logged_in"] is True and result["errors"] == []
    assert "empty bio" in asked[0][0] and '"notes"' in asked[0][1]
    assert state["accounts"]["instagram"]["notes"] == "No bio and no photo yet."


def test_every_reel_change_goes_into_one_numbered_brief(flow_of):
    summary, briefs = flow_of.change_brief("video", [{"text": "Hold the hook longer", "at": 3.4},
                                                     {"text": "  "}, {"text": "Louder voice"}])
    brief = briefs["video"]
    assert "1. At 0:03: Hold the hook longer" in brief and "2. Louder voice" in brief and "3." not in brief
    assert "Do not leave any out" in brief and summary == brief
    with pytest.raises(flow_of.AgentError):
        flow_of.change_brief("video", [{"text": ""}])


def test_artwork_notes_reach_only_their_piece_and_the_set_note_reaches_all(flow_of):
    _, own = flow_of.change_brief("artwork", pieces={"cover": "Bigger headline", "thumbnail": ""})
    assert set(own) == {"cover"} and "Bigger headline" in own["cover"]
    summary, every = flow_of.change_brief("artwork", pieces={"cover": "Bigger headline"}, general="Brighter red")
    assert set(every) == {"cover", "thumbnail"}, "the reel's set note reaches its own two pieces"
    assert "Bigger headline" in every["cover"] and "Bigger headline" not in every["thumbnail"]
    assert all("For the whole set: Brighter red" in text for text in every.values())
    assert "whole set: Brighter red" in summary
    _, channel = flow_of.change_brief("profile", pieces={"avatar": "Move the mascot left"}, general="Calmer red")
    assert set(channel) == {"avatar"} and "Move the mascot left" in channel["avatar"] and "Calmer red" in channel["avatar"]
    with pytest.raises(flow_of.AgentError):
        flow_of.change_brief("artwork", pieces={"cover": " "})


PASSED = {"current": True, "level": 1, "items": 5, "check": {"passed": True, "level": 1, "items": [{}] * 5, "failing": []}}


def test_the_content_step_mentions_research_waiting_for_a_plan(flow_of):
    found = _step(flow_of.flow(_agent(), _facts(research={"at": "2026-11-12T10:00:00", "trends": [{}, {}, {}]})), "plan")
    assert found["state"] == "ready" and "3 researched angles" in found["detail"]


def test_an_uncertain_public_action_can_be_settled_by_you(flow_of):
    operations = [{"id": "op1", "action": "publish", "platform": "instagram", "status": "needs_verification",
                   "error": "not read back", "report": {"evidence": ["Share clicked"]}, "started_at": "2026-11-13T04:00:00+00:00"}]
    step = _step(flow_of.flow(_agent(operations=operations), _facts()), "publish")
    assert step["state"] == "blocked" and "could not be read back" in step["detail"]
    assert "mark it done" in step["blocked_on"]
    assert step["evidence"]["uncertain"] == [{"id": "op1", "platform": "instagram", "error": "not read back",
                                              "evidence": ["Share clicked"], "fields": [], "at": "2026-11-13T04:00:00+00:00"}]


def test_settling_an_upload_marks_it_done_or_lets_it_run_again(flow_of, tmp_path, monkeypatch):
    monkeypatch.setattr(flow_of, "HOME", tmp_path)
    operations = tmp_path / "operations"
    operations.mkdir()
    for name in ("a1", "b2"):
        flow_of._write(operations / f"{name}.json", {"id": name, "action": "apply-profile", "platform": "instagram",
                                                     "status": "needs_verification"})
    assert flow_of.resolve_operation("a1", "done")["status"] == "complete"
    assert flow_of._read(operations / "a1.json")["resolved"]["by"] == "you"
    flow_of.resolve_operation("b2", "retry")
    assert not (operations / "b2.json").exists(), "a cleared upload may run again"
    assert list((operations / "settled").glob("b2-*.json"))
    with pytest.raises(flow_of.AgentError, match="already settled"):
        flow_of.resolve_operation("a1", "retry")
    with pytest.raises(flow_of.AgentError):
        flow_of.resolve_operation("../x", "done")


def test_applied_profiles_on_every_platform_complete_the_setup(flow_of):
    operations = [{"action": "apply-profile", "platform": platform, "status": "complete", "revision": "r1",
                   "finished_at": "2026-11-13T05:00:00+00:00"} for platform in ("instagram", "youtube")]
    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    flow = flow_of.flow(_agent(operations=operations, audit=verified, reviews=_reviews()), _facts())
    assert _step(flow, "apply-profile")["state"] == "done"
    setup = next(lane for lane in flow["lanes"] if lane["key"] == "setup")
    assert setup["complete"] and setup["done"] == setup["total"]


def test_the_profile_upload_waits_for_its_approval_then_is_ready(flow_of):
    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    waiting = _step(flow_of.flow(_agent(audit=verified, reviews=_reviews(profile="pending")), _facts()), "apply-profile")
    assert waiting["state"] == "blocked" and "profile picture" in waiting["blocked_on"]
    ready = _step(flow_of.flow(_agent(audit=verified, reviews=_reviews()), _facts()), "apply-profile")
    assert ready["state"] == "ready" and ready["run"] == "setup-profile"
    assert _step(flow_of.flow(_agent(audit=verified, reviews=_reviews(profile="pending")), _facts()), "profile-review")["state"] == "waiting"


def test_nothing_reaches_the_final_review_unreviewed_or_below_the_bar(flow_of):
    verified = {"accounts": _signed_in("instagram", "a") | _signed_in("youtube", "b")}
    flow = flow_of.flow(_agent(draft=_draft(), audit=verified, bar=PASSED, reviews=_reviews(video="pending", art="pending")), _facts())
    assert _step(flow, "review")["state"] == "blocked" and "the reel and the cover and thumbnail" in _step(flow, "review")["detail"]
    below = {"current": True, "level": 2, "check": {"passed": False, "items": [{}] * 6, "failing": ["The hook is 7 words or fewer — measured 11"]}}
    failed = flow_of.flow(_agent(draft=_draft(), audit=verified, bar=below, reviews=_reviews()), _facts())
    assert _step(failed, "bar")["state"] == "failed" and "hook" in _step(failed, "bar")["blocked_on"]
    assert _step(failed, "review")["state"] == "blocked" and "passing the bar" in _step(failed, "review")["detail"]
    unchecked = flow_of.flow(_agent(draft=_draft(), audit=verified, bar={"current": False, "level": 1}, reviews=_reviews()), _facts())
    assert _step(unchecked, "bar")["state"] == "ready" and _step(unchecked, "bar")["run"] == "check-bar"
    ready = flow_of.flow(_agent(draft=_draft(), audit=verified, bar=PASSED, reviews=_reviews()), _facts())
    assert _step(ready, "review")["state"] == "waiting" and _step(ready, "review")["run"] == "release"
    assert _step(ready, "publish")["state"] == "auto"


def test_a_reel_live_on_both_finishes_the_reel_flow(flow_of):
    posts = [{"status": "posted", "plan_id": "a-plan", "day": 1, "platform": p, "posted_at": "2026-11-14T10:00:00", "title": "X",
              "metrics": None} for p in ("instagram", "youtube")]
    flow = flow_of.flow(_agent(draft=_draft(), reviews=_reviews(), bar=PASSED), _facts(posts=posts))
    assert _step(flow, "publish")["state"] == "done" and _step(flow, "review")["state"] == "done"
    assert flow["last_post"]["plan_id"] == "a-plan"
    half = flow_of.flow(_agent(draft=_draft(), reviews=_reviews(), bar=PASSED), _facts(posts=posts[:1]))
    assert _step(half, "publish")["state"] == "failed" and "Instagram only" in _step(half, "publish")["detail"]
