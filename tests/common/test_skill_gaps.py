"""What a job asks that the profile lacks: proposed by the scorer, kept only when true, shown in the report.

From Dossier's gap report (AienTech/dossier): the model may only name gaps, code
decides, so a skill on the profile is never reported missing.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import llm, report
from common.ledger import Ledger
from common.models import JobPosting, Profile


class _Client:
    def __init__(self, reply):
        self.reply = reply

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        return self.reply


def test_a_gap_naming_a_listed_skill_is_dropped_however_it_is_worded():
    gaps = llm.real_gaps(["Strong APIs design", "Kubernetes", "node.js", "Kubernetes", 7], ["API", "Node.js"])
    assert gaps == ["Kubernetes"]


def test_gaps_are_capped_at_three():
    assert llm.real_gaps(["a1", "b2", "c3", "d4"], []) == ["a1", "b2", "c3"]


def test_scoring_returns_the_filtered_gaps():
    job = JobPosting(job_id="j1", url="", title="Backend", company="X", description="Python, Go, Kafka")
    client = _Client({"jobs": [{"job_id": "j1", "score": 70, "verdict": "possible", "reasons": [],
                                "gaps": ["Go", "Python 3"]}]})
    scores = llm.score_jobs(client, Profile(skills=["Python"]), [job])
    assert scores["j1"]["gaps"] == ["Go"]


def test_the_ledger_keeps_gaps_and_a_rescore_without_them_does_not_erase_them(tmp_path):
    ledger = Ledger(str(tmp_path / "l.db"))
    job = JobPosting(job_id="j1", url="u", title="Backend", company="X")
    ledger.record_seen(job, 70.0, ["Go"])
    ledger.record_seen(job, 72.0)
    rows = ledger.gaps_between("0000", "9999")
    ledger.close()
    assert rows[0]["gaps"] == ["Go"] and rows[0]["score"] == 72.0


def test_the_report_counts_the_most_common_gaps():
    jobs = [{"title": "A", "company": "X", "score": 80, "gaps": ["Go", "Kafka"]},
            {"title": "B", "company": "Y", "score": 60, "gaps": ["go"]}]
    lines = report.skill_gaps_text(jobs)
    assert "- Go: 2 jobs" in lines
    assert "- Kafka: 1 job" in lines


def test_the_report_says_so_when_there_are_no_gaps():
    assert report.skill_gaps_text([]) == ["- No job scored today named a requirement your profile lacks."]
