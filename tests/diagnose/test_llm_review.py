import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from diagnose import gmail, llm_review, report
from diagnose.trail import Trail


class FakeClient:
    """Answers each complete_json call from a queue; None entries mimic a timeout."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else None


LOCAL = {"applications": [
    {"company": "Incubyte", "status": "applied_platform"}, {"company": "Incubyte", "status": "applied_platform"},
    {"company": "Techjays", "status": "applied"}, {"company": "Nope Inc", "status": "external_skipped"},
    {"company": "Go", "status": "applied"},
], "funnel_all": {"submitted_total": 1725, "days_running": 14, "submitted_by_status": {}, "submitted_by_day": {}},
    "fit": {"score_bands": {}, "median_score": 48, "below_min_score": 1044, "min_score": 40, "mismatched_titles": 480, "top_gaps": []},
    "profile": {"years": 2.9}, "answers": {"suspicious": []}, "replies": {}}


def test_validate_query_normalises_and_rejects():
    assert llm_review.validate_query("from:cutshort.io subject:(RE: OR questionnaire)", 45) == \
        "in:anywhere from:cutshort.io subject:(RE: OR questionnaire) newer_than:45d"
    assert llm_review.validate_query("in:anywhere subject:interview newer_than:2y", 45) == \
        "in:anywhere subject:interview newer_than:180d"
    assert llm_review.validate_query('subject:"unbalanced', 45) is None
    assert llm_review.validate_query("deleteall:yes subject:x", 45) is None
    assert llm_review.validate_query("subject:(a OR b", 45) is None
    assert llm_review.validate_query("x" * 300, 45) is None
    assert llm_review.validate_query("", 45) is None


def test_rule_queries_cover_applied_companies_and_skip_unsubmitted():
    queries = llm_review.rule_queries(LOCAL, 30)
    joined = " ".join(q["query"] for q in queries)
    assert '"Incubyte"' in joined and '"Techjays"' in joined
    assert "Nope Inc" not in joined and '"Go"' not in joined  # not submitted / too short a name
    assert all(q["source"] == "rules" and "newer_than:30d" in q["query"] for q in queries)


def test_propose_queries_lints_model_output_and_records_the_trail():
    client = FakeClient([{"queries": [
        {"query": "from:incubyte.com subject:(interview OR assignment)", "purpose": "Incubyte replies"},
        {"query": "label:nope purge:all", "purpose": "bad operator"},
        {"query": 'subject:"unbalanced', "purpose": "bad quotes"},
    ]}])
    trail = Trail()
    queries = llm_review.propose_queries(llm_review.Model(client), LOCAL, 45, trail)
    model_made = [q for q in queries if q["source"] == "model"]
    assert len(model_made) == 1 and model_made[0]["query"].startswith("in:anywhere from:incubyte.com")
    step = trail.steps[-1]
    assert step.ok and step.numbers["model"] == 1 and step.numbers["rejected"] == 2
    assert "<data>" in client.prompts[0] and "Incubyte" in client.prompts[0]


def test_propose_queries_without_a_model_runs_rules_only():
    trail = Trail()
    queries = llm_review.propose_queries(None, LOCAL, 45, trail)
    assert queries and all(q["source"] == "rules" for q in queries)
    assert trail.steps[-1].ok and trail.steps[-1].numbers["model"] == 0


def test_run_queries_adds_new_rows_marks_seen_and_drops_too_broad():
    records = [gmail.make_record("search:all-mail", "jobs@hirist.tech", "You applied to X", "2026-11-01")]
    results = {
        "q1": [{"from": "jobs@hirist.tech", "subject": "You applied to X", "date": "2026-11-01"},
               {"from": "hr@acme.com", "subject": "Interview invitation for Software Engineer", "date": "2026-11-02"}],
        "q2": [],
        "q3": [{"from": "x", "subject": str(i), "date": ""} for i in range(llm_review.MAX_ROWS_PER_QUERY + 1)],
    }
    queries = [{"query": "q1", "purpose": "one", "source": "rules"}, {"query": "q2", "purpose": "two", "source": "rules"},
               {"query": "q3", "purpose": "three", "source": "model"}]
    trail = Trail()
    stats = llm_review.run_queries(lambda q: results[q], queries, records, gmail.make_record, trail)
    assert [s["status"] for s in stats] == ["ok", "empty", "too-broad"]
    assert stats[0]["rows"] == 2 and stats[0]["new_rows"] == 1 and stats[0]["positives"] == 1
    assert len(records) == 2 and records[0]["targeted"] and records[1]["targeted"]
    assert records[1]["kind"] == "INTERVIEW"
    assert trail.steps[-1].numbers["new_rows"] == 1


def _records():
    rows = [
        ("hr@acme.com", "Interview invitation for Software Engineer"),      # INTERVIEW
        ("talent@beta.io", "You are shortlisted for the next round"),        # SHORTLIST
        ("noreply@naukri.com", "Jobs for you: 25 new openings"),              # JOB_ALERT (never verified)
        ("careers@gamma.com", "Thank you for applying to Gamma"),             # ACKNOWLEDGEMENT
        ("people@delta.com", "Update on your application"),                   # likely OTHER, hiring-related
        ("sam@startup.com", "Quick question about your availability"),        # QUESTION-ish
    ]
    return [gmail.make_record("search:all-mail", sender, subject, "2026-11-0%d" % (i + 1)) for i, (sender, subject) in enumerate(rows)]


def test_verify_kinds_applies_confident_changes_and_measures_agreement():
    records = _records()
    order = llm_review.verification_order(records)
    assert all(r["kind"] != "JOB_ALERT" for r in order)
    reply = {"items": []}
    for i, record in enumerate(order):
        kind = record["kind"]
        confidence = 0.9
        if record["subject"].startswith("Update on your application"):
            kind, confidence = "REJECTION", 0.95          # OTHER -> REJECTION, changes
        if record["subject"].startswith("Thank you for applying"):
            kind, confidence = "INTERVIEW", 0.4           # below MIN_CONFIDENCE, ignored
        reply["items"].append({"i": i, "kind": kind, "company": "", "confidence": confidence, "why": "subject says so"})
    trail = Trail()
    summary = llm_review.verify_kinds(llm_review.Model(FakeClient([reply])), records, trail)
    assert summary["used"] and summary["batches"] == 1 and summary["distrusted_batches"] == 0
    assert summary["changed"] == 1 and summary["promoted"] == 0 and summary["demoted"] == 0
    changed = [r for r in records if r.get("rule", "").startswith("llm-verified")]
    assert len(changed) == 1 and changed[0]["kind"] == "REJECTION"
    ack = [r for r in records if r["subject"].startswith("Thank you")][0]
    assert ack["kind"] == "ACKNOWLEDGEMENT" and ack["model_kind"] == "INTERVIEW"
    # Three mails had a rule kind (INTERVIEW, SHORTLIST, ACKNOWLEDGEMENT); the low-confidence INTERVIEW on the
    # acknowledgement still counts as a disagreement, so agreement is 2 of 3 while nothing was applied from it.
    assert summary["compared"] == 3 and summary["agreement_positive"] == 0.67 and summary["agreement_kind"] == 0.67
    assert trail.steps[-1].ok


def test_verify_kinds_distrusts_a_batch_that_contradicts_the_rules():
    records = []
    for i in range(8):
        records.append(gmail.make_record("search:all-mail", "hr%d@co.com" % i, "Interview invitation for role %d" % i, "2026-11-01"))
    order = llm_review.verification_order(records)
    reply = {"items": [{"i": i, "kind": "PROMO", "company": "", "confidence": 0.99, "why": ""} for i in range(len(order))]}
    trail = Trail()
    summary = llm_review.verify_kinds(llm_review.Model(FakeClient([reply, reply])), records, trail)
    assert summary["distrusted_batches"] == 1 and summary["changed"] == 0
    assert all(r["kind"] == "INTERVIEW" for r in records)
    assert not trail.steps[-1].ok and "distrusted" in trail.steps[-1].check


def test_verify_kinds_reasks_once_when_an_index_is_missing():
    records = _records()
    order = llm_review.verification_order(records)
    short = {"items": [{"i": 0, "kind": order[0]["kind"], "confidence": 0.9}]}
    full = {"items": [{"i": i, "kind": r["kind"], "confidence": 0.9} for i, r in enumerate(order)]}
    client = FakeClient([short, full])
    summary = llm_review.verify_kinds(llm_review.Model(client), records, Trail())
    assert len(client.prompts) == 2 and "refused" in client.prompts[1]
    assert summary["used"] and summary["changed"] == 0


def test_model_gives_up_after_two_silent_calls_and_later_steps_skip():
    model = llm_review.Model(FakeClient([None, None, {"items": []}]))
    records = [gmail.make_record("f", "hr%d@co.com" % i, "Interview invitation %d" % i, "2026-11-01") for i in range(llm_review.MAX_BATCH + 1)]
    trail = Trail()
    summary = llm_review.verify_kinds(model, records, trail)
    assert not summary["used"] and model.dead and summary["failures"] == 2 and summary["batches"] == 2
    # The budget is run-wide: the next step does not even call.
    causes, review = llm_review.review_causes(model, "digest 1725", [{"id": "low-fit", "severity": "critical", "title": "t",
                                                                      "evidence": [], "fix": [], "fix_kind": "env", "confidence": 0.8}], trail)
    assert not review["used"] and "gave up" in trail.steps[-1].check and not trail.steps[-1].ok
    assert gmail.read_bodies(model, records, lambda r: "body", {"llm_used": 0}, trail) == 0


def test_review_causes_grounds_additions_and_moves_confidence():
    causes = [
        {"id": "low-fit", "severity": "critical", "title": "Low fit", "evidence": ["1044 of 1705 below 50"], "fix": ["raise"],
         "fix_kind": "env", "confidence": 0.8},
        {"id": "volume", "severity": "high", "title": "Volume", "evidence": ["58 a day"], "fix": ["slow"], "fix_kind": "env", "confidence": 0.7},
    ]
    text = llm_review.digest(LOCAL, None, None, {}, causes)
    assert "1725" in text and "low-fit" in text
    reply = {"verdict": "Fit is the problem.",
             "ranked": [{"id": "low-fit", "agree": True, "severity": "critical", "why": "numbers say so"},
                        {"id": "volume", "agree": False, "severity": "medium", "why": "volume is fine"}],
             "missing": [{"title": "Median score 48 is below pass", "evidence": "median score 48 of 1725 submissions", "fix": "raise", "severity": "critical"},
                         {"title": "Ungrounded claim", "evidence": "recruiters hate blue resumes", "fix": "x", "severity": "high"}],
             "first_three_actions": ["Fix MIN_SCORE", "Answer Cutshort", "Rewrite headline"]}
    trail = Trail()
    ranked, review = llm_review.review_causes(llm_review.Model(FakeClient([reply])), text, causes, trail)
    assert review["used"] and review["agreed"] == 1 and review["disagreed"] == 1
    assert review["added"] == 1 and review["rejected_additions"] == 1
    by_id = {c["id"]: c for c in ranked}
    assert by_id["low-fit"]["confidence"] == 0.85 and by_id["volume"]["confidence"] == 0.55
    assert by_id["volume"]["model_note"].startswith("The model disagrees")
    added = [c for c in ranked if c["id"].startswith("model-")][0]
    assert added["severity"] == "medium" and added["confidence"] == 0.5 and added["fix_kind"] == "manual"
    assert ranked[0]["id"] == "low-fit"
    assert review["first_three_actions"] == ["Fix MIN_SCORE", "Answer Cutshort", "Rewrite headline"]


def test_review_causes_rejects_unknown_ids_through_the_reask():
    causes = [{"id": "low-fit", "severity": "critical", "title": "Low fit", "evidence": [], "fix": [], "fix_kind": "env", "confidence": 0.8}]
    bad = {"verdict": "", "ranked": [{"id": "made-up", "agree": True, "severity": "high", "why": ""}], "missing": [], "first_three_actions": ["a"]}
    good = {"verdict": "ok", "ranked": [{"id": "low-fit", "agree": True, "severity": "critical", "why": ""}], "missing": [], "first_three_actions": ["a"]}
    client = FakeClient([bad, good])
    ranked, review = llm_review.review_causes(llm_review.Model(client), "digest", causes, Trail())
    assert len(client.prompts) == 2 and review["used"] and review["agreed"] == 1


def test_tally_recomputes_every_count_from_records():
    records = _records()
    records[4]["kind"], records[4]["verified"] = "REJECTION", True
    result = gmail.tally(gmail.empty_result("me@x", 45), records)
    assert result["scanned"] == 6 and result["positive_total"] >= 2
    assert result["by_platform"]["naukri"]["JOB_ALERT"] == 1
    assert result["verified_total"] == 1
    assert all(r["kind"] != "OTHER" for r in result["unplaced"]) or not result["unplaced"]


def test_report_shows_review_searches_and_trail():
    local = {"generated_at": "2026-11-11T10:00", "funnel_all": {"submitted_total": 100, "days_running": 10, "status_counts": {}, "submitted_by_status": {},
                                                                 "submitted_by_channel": {}, "submitted_by_day": {}, "first_at": "2026-11-01", "last_at": "2026-11-11"},
             "funnel_live": {"submitted_total": 10}, "ledgers": {}, "company_sites": {}, "fit": {"score_bands": {}, "median_score": 50, "below_min_score": 1,
                                                                                                "min_score": 40, "mismatched_titles": 0, "top_gaps": []},
             "answers": {"rows": 0, "never_used": 0, "suspicious": []}, "replies": {"rows": 0, "kinds": {}, "sender_platforms": {}, "contacts_known": 0, "cold_emails_sent": 0}}
    mail = dict(gmail.empty_result("me@x", 45), positive_total=0, positive_by_platform={}, positive_by_kind={},
                queries=[{"query": "in:anywhere from:a.com newer_than:45d", "purpose": "p", "source": "model", "rows": 3, "new_rows": 1, "positives": 1, "status": "ok"}],
                verification={"used": True, "items": 25, "batches": 1, "agreement_kind": 0.8, "agreement_positive": 0.92, "changed": 2,
                              "promoted": 1, "demoted": 1, "distrusted_batches": 0}, model="3 calls, 3 answered")
    causes = [{"id": "low-fit", "severity": "critical", "title": "Low fit", "evidence": ["e"], "fix": ["f"], "fix_kind": "env",
               "confidence": 0.85, "where": [], "plain": "", "model_note": "The model agrees: yes"}]
    review = {"used": True, "verdict": "Fit.", "first_three_actions": ["Do A"], "agreed": 1, "disagreed": 0, "added": 0, "rejected_additions": 0}
    trail = Trail()
    trail.add("Targeted Gmail searches", research="r", verify="v", check="c", execute="e", ok=False)
    text = report.build_markdown(local, mail, None, {"error": "no resume"}, causes, review, trail.as_dicts())
    assert "## Model review" in text and "Verdict: Fit." in text and "1. Do A" in text
    assert "### Targeted searches (1)" in text and "from:a.com" in text
    assert "Model verification: 25 mails re-judged" in text
    assert "_The model agrees: yes_ (confidence now 0.85)" in text
    assert "## How each step was checked" in text and "| **no** |" in text
    payload = json.loads(json.dumps({"trail": trail.as_dicts()}))
    assert payload["trail"][0]["ok"] is False
