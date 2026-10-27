import hashlib
import json

from common import profile_plan
from common.models import Profile, Settings

RESUME = """Asha Rao  asha@example.com  +91 98765 43210  github.com/asharao
Experience
Senior Data Engineer, Acme (2019-2024): built Spark pipelines on AWS cutting cost 40%.
Scaled Kafka ingestion to 2 million events a day; reduced latency by 30%.
Led 5 engineers; migrated 120 Airflow DAGs to Python 3.
Projects
Lakehouse Migration: moved 14 TB of Hive tables to Delta Lake on Spark; nightly runs 2 hours faster.
Education
B.Tech Computer Science
Certifications: AWS Certified Data Analytics
Skills
Python, SQL, Spark, Kafka, AWS, Airflow, Delta Lake, Hive, Data Engineering, ETL, Streaming
""" + "Delivered data platform work. " * 70

GOOD_SUMMARY = (
    "I build the data platforms that keep analytics honest: Spark pipelines on AWS that cut compute cost 40% "
    "and Kafka ingestion that carries 2 million events a day. At Acme I led 5 engineers through a migration "
    "of 120 Airflow DAGs to Python 3 and brought pipeline latency down 30%, and I moved 14 TB of Hive tables "
    "to Delta Lake so the nightly runs finish 2 hours faster. I own the design, the SQL and the on-call for "
    "what I ship. Stack: Python, SQL, Spark, Kafka, AWS, Airflow, Delta Lake and Hive. Looking for a senior "
    "data engineering role on streaming or lakehouse platforms, in Bengaluru or fully remote."
)
GOOD_ABOUT = ("I build the data platforms that keep analytics honest: Spark on AWS, 2 million Kafka events a day.\n\n"
              + GOOD_SUMMARY + "\n\n" + "Delivered data platform work. " * 30).strip()
GOOD = {
    "headline": "Senior Data Engineer | Spark, Kafka, AWS, Airflow, Python | 5 yrs | Streaming & lakehouse platforms",
    "designation": "Senior Data Engineer",
    "summary": GOOD_SUMMARY,
    "short_summary": "I build data platforms on Spark and AWS that cut compute cost 40% and carry 2 million "
                     "Kafka events a day.",
    "about": GOOD_ABOUT,
    "key_skills": ["Spark", "Kafka", "AWS", "Airflow", "Python", "SQL", "Delta Lake", "Hive", "Kubernetes",
                   "Data Engineering", "ETL", "Streaming"],
    "experience": [{"title": "Senior Data Engineer", "company": "Acme", "location": "", "start": "2019",
                    "end": "2024", "skills": "Spark, Kafka, AWS, Airflow, Python",
                    "description": "Built Spark pipelines on AWS that cut compute cost 40%.\nScaled Kafka "
                                   "ingestion to 2 million events a day and cut latency 30%.\nLed 5 engineers "
                                   "and migrated 120 Airflow DAGs to Python 3."}],
    "projects": [{"name": "Lakehouse Migration", "role": "Lead", "skills": "Spark, Delta Lake, Hive",
                  "description": "Moved 14 TB of Hive tables to Delta Lake on Spark; the nightly runs finish "
                                 "2 hours faster.", "url": ""}],
    "it_skills": [{"name": "Spark", "years": "5", "last_used": "2024"}, {"name": "Kafka", "years": "4",
                                                                          "last_used": "2024"}],
    "certifications": ["AWS Certified Data Analytics"],
    "links": ["https://github.com/asharao"],
    "target_roles": ["Data Engineer", "Senior Data Engineer"],
    "target_keywords": ["Spark", "Kafka", "dbt"],
    "suggestions": ["Add dbt if you have used it."],
}
BAD = dict(GOOD, headline="Data Engineer | Spark",
           summary="I am a passionate, results-driven data engineer. I build data platforms on AWS. "
                   "I cut cost 40% with Spark. I managed 50 engineers.",
           about="", short_summary="", experience=[], it_skills=[], key_skills=["Spark", "Kafka", "Kubernetes",
                                                                                    "Python"])


class FakeClient:
    """Answers with one reply, or with each reply of a list in turn (the last one repeats)."""

    def __init__(self, reply):
        self.replies = list(reply) if isinstance(reply, list) else [reply]
        self.prompts = []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]


def _profile():
    return Profile(full_name="Asha Rao", total_experience_years=5, titles=["Data Engineer"],
                   skills=["Python", "Spark"], resume_text=RESUME)


def test_ats_report_scores_keywords_and_structure():
    report = profile_plan.ats_report(RESUME, ["Python", "Spark", "dbt", "Snowflake"])
    assert report.keyword_score == 50
    assert report.matched == ["Python", "Spark"] and report.missing == ["dbt", "Snowflake"]
    assert report.structure_score == 100
    assert report.score == round(0.6 * 50 + 40)
    assert any("dbt" in issue for issue in report.issues)
    bare = profile_plan.ats_report("Python developer", ["Python"])
    assert bare.structure_score < 50 and any("email" in issue for issue in bare.issues)


def test_plan_drops_invented_skills_and_numbers_and_is_cached(tmp_path):
    client = FakeClient(BAD)
    path = tmp_path / "plan.json"
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=path)
    assert plan.source == "llm"
    assert plan.key_skills == ["Spark", "Kafka", "Python"]          # Kubernetes is not in the facts
    assert "50 engineers" not in plan.summary and "40%" in plan.summary
    assert plan.about == plan.summary
    assert plan.ats.missing == ["dbt"]
    brief = profile_plan.agent_brief(plan)
    assert plan.headline in brief and "Spark, Kafka, Python" in brief
    assert len(client.prompts) == 2                                  # the draft, then the editor's pass

    again = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=path)
    assert len(client.prompts) == 2 and again.headline == plan.headline and again.ats.score == plan.ats.score
    assert again.review == plan.review
    profile_plan.build_plan(_profile(), Settings(), facts=RESUME + " new fact", client=client, path=path)
    assert len(client.prompts) == 4


def test_a_plan_cached_by_an_older_planner_is_written_again(tmp_path):
    path = tmp_path / "plan.json"
    old_key = hashlib.sha256(RESUME.encode("utf-8")).hexdigest()[:16]
    path.write_text(json.dumps({"key": old_key, "plan": {"headline": "Old", "summary": "Old.", "source": "llm"}}))
    client = FakeClient(GOOD)
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=path)
    assert plan.headline == GOOD["headline"] and client.prompts


def test_the_model_reads_the_whole_resume_before_the_answer_key(tmp_path):
    answers = "\n".join("- Q: question %d\n  A: answer %d" % (n, n) for n in range(900))
    facts = "- full name: Asha Rao\n\nTheir own answers to screening questions:\n" + answers + \
            "\nTheir resume (plain text):\n" + RESUME[:200]
    assert len(answers) > profile_plan._PROMPT_FACTS_CHARS // 2
    client = FakeClient(GOOD)
    profile_plan.build_plan(_profile(), Settings(), facts=facts, client=client, path=tmp_path / "p.json")
    prompt = client.prompts[0]
    body = prompt.split("The facts:\n", 1)[1]
    assert body.startswith("Their resume (plain text):\nAsha Rao")
    assert "migrated 120 Airflow DAGs" in body                      # the whole resume, not a cut copy
    assert body.index("Airflow DAGs") < body.index("- Q: question 0")
    assert body.count("Asha Rao  asha@example.com") == 1           # the facts' own resume copy is not repeated


def test_the_reviewer_sends_a_weak_draft_back_and_keeps_the_better_one(tmp_path):
    client = FakeClient([BAD, GOOD])
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=tmp_path / "p.json")
    assert len(client.prompts) == 2
    editor = client.prompts[1]
    assert "Reviewer's notes" in editor and "opens with 'I am a'" in editor and "uses filler" in editor
    assert '"headline": "Data Engineer | Spark"' in editor         # the draft travels with the notes
    assert plan.summary == GOOD_SUMMARY and plan.review == []
    assert plan.experience[0]["company"] == "Acme" and plan.it_skills[0]["name"] == "Spark"


def test_a_revision_that_reads_worse_is_dropped(tmp_path):
    client = FakeClient([GOOD, BAD])
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=tmp_path / "p.json")
    assert plan.summary == GOOD_SUMMARY and plan.review == []
    assert len(client.prompts) == 1                                  # a passing draft is not sent back

    worse = FakeClient([dict(GOOD, summary="I am a Spark engineer. I like data."), BAD])
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=worse, path=tmp_path / "q.json")
    assert plan.summary.startswith("I am a Spark engineer") and len(plan.review) < len(profile_plan.quality_report(
        profile_plan._parse(BAD, _profile(), RESUME)))


def test_quality_report_reads_like_a_recruiter():
    good = profile_plan._parse(GOOD, _profile(), RESUME)
    assert profile_plan.quality_report(good) == []
    bad = profile_plan._parse(BAD, _profile(), RESUME)
    notes = " ".join(profile_plan.quality_report(bad))
    assert "passionate" in notes and "opens with 'I am a'" in notes and "what they want next" in notes
    assert "experience: no roles" in notes and "it_skills: empty" in notes and "about: missing" in notes
    long_hook = profile_plan._parse(dict(GOOD, about=("x" * 250) + "\n\nmore " * 300), _profile(), RESUME)
    assert any("hook" in note for note in profile_plan.quality_report(long_hook))
    no_role = profile_plan._parse(dict(GOOD, headline="Streaming & Lakehouse Specialist | Spark, Kafka, AWS, "
                                                      "Airflow | 5 yrs"), _profile(), RESUME)
    assert any("start with one of their target roles (Data Engineer" in note
               for note in profile_plan.quality_report(no_role))
    intern = profile_plan._parse(dict(GOOD, experience=GOOD["experience"] + [
        {"title": "Senior Data Engineer", "company": "Acme", "start": "2019", "end": "2019",
         "description": "Built the first ingestion job for the team and kept it running through the "
                        "migration, with weekly checks of the Spark output.", "skills": "Spark"}]), _profile(), RESUME)
    assert profile_plan.quality_report(intern) == []              # an older role may have no figure to give


def test_experience_projects_skills_and_links_are_grounded_in_the_facts():
    raw = dict(GOOD)
    raw["experience"] = GOOD["experience"] + [
        {"title": "CTO", "company": "Globex", "start": "2010", "end": "2012", "description": "Ran it.", "skills": ""},
        {"title": "Senior Data Engineer", "company": "Acme (Bengaluru)", "start": "2019", "end": "2024",
         "description": "Cut cost 40%. Served 9 million users a day. Led 5 engineers.", "skills": "Spark, Flink"},
    ]
    raw["projects"] = GOOD["projects"] + [{"name": "Secret Project", "description": "Invented.", "skills": "Spark"}]
    this_year = str(__import__("datetime").datetime.now().year)
    raw["it_skills"] = [{"name": "Spark", "years": "7", "last_used": "2024"}, {"name": "Snowflake", "years": "2"},
                        {"name": "Kafka", "years": "3", "last_used": this_year},
                        {"name": "Airflow", "years": "2", "last_used": "1999"}]
    raw["certifications"] = ["AWS Certified Data Analytics", "Google Cloud Architect"]
    raw["links"] = ["https://github.com/asharao", "https://example.com/not-hers"]
    plan = profile_plan._parse(raw, _profile(), RESUME)
    assert [role["company"] for role in plan.experience] == ["Acme", "Acme (Bengaluru)"]   # Globex is nowhere
    assert "9 million" not in plan.experience[1]["description"] and "Led 5 engineers" in plan.experience[1]["description"]
    assert plan.experience[1]["skills"] == "Spark"                 # Flink is not in the facts
    assert [project["name"] for project in plan.projects] == ["Lakehouse Migration"]
    assert plan.it_skills == [{"name": "Spark", "years": "5", "last_used": "2024"},   # 7 years: her total instead
                              {"name": "Kafka", "years": "3", "last_used": this_year},  # this year is always allowed
                              {"name": "Airflow", "years": "2", "last_used": ""}]       # 1999 is nowhere in the facts
    assert plan.certifications == ["AWS Certified Data Analytics"]
    assert plan.links == ["https://github.com/asharao"]


def test_the_brief_carries_every_planned_section(tmp_path):
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=FakeClient(GOOD),
                                   path=tmp_path / "p.json")
    brief = profile_plan.agent_brief(plan)
    for text in ("- Employment, newest first", "1. Senior Data Engineer, Acme, 2019 - 2024",
                 "Skills used: Spark, Kafka, AWS, Airflow, Python", "Job profile / description:",
                 "Built Spark pipelines on AWS that cut compute cost 40%.", "- Projects (add",
                 "1. Lakehouse Migration (Spark, Delta Lake, Hive), role: Lead", "- IT skills",
                 "Spark, 5 yrs, last used 2024", "- Certifications: AWS Certified Data Analytics",
                 "- Online profiles / links: https://github.com/asharao", "- Short summary", "- About (long fields",
                 "do not guess"):
        assert text in brief, text


def test_the_plan_comes_only_from_the_llm(tmp_path):
    import pytest

    class Offline(FakeClient):
        def available(self):
            return False

    with pytest.raises(profile_plan.PlanError):
        profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=Offline(None), path=tmp_path / "p.json")
    useless = FakeClient(None)
    with pytest.raises(profile_plan.PlanError):
        profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=useless, path=tmp_path / "p.json")
    assert len(useless.prompts) == 2                      # one retry, then no canned text
    assert profile_plan.plan_for(None, Settings()) is None


def test_the_brief_carries_the_ats_keywords(tmp_path):
    client = FakeClient({"headline": "Data Engineer | Spark", "summary": "I build Spark pipelines on AWS.",
                         "target_keywords": ["Spark", "Kafka", "dbt"]})
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=tmp_path / "p.json")
    brief = profile_plan.agent_brief(plan)
    assert "ATS: their resume scores %d/100" % plan.ats.score in brief
    assert "they have; each must appear" in brief and "Spark, Kafka" in brief
    assert "never as a new claim: dbt" in brief
    assert plan.review and "Reviewer's notes still open" in profile_plan.review_text(plan)


def test_a_changed_answer_does_not_trade_the_better_plan_for_a_worse_draft(tmp_path):
    """The model writes a different headline every time it is asked: one added line in profile.yaml
    rebuilt the plan, the ATS score fell from 90 to 86 and every board got a new headline for nothing."""
    path = tmp_path / "plan.json"
    first = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=FakeClient(GOOD), path=path)
    weaker = dict(GOOD, headline="Data Engineer | Spark, Kafka, AWS, Airflow, Python | 5 yrs | Lakehouse platforms",
                  target_keywords=["Spark", "Kafka", "dbt", "Snowflake"])
    facts = RESUME + "\nnotice_period_days: 30"
    again = profile_plan.build_plan(_profile(), Settings(), facts=facts, client=FakeClient(weaker), path=path)
    assert again.headline == first.headline and again.ats.score == first.ats.score
    assert json.loads(path.read_text())["key"] == profile_plan._key(facts), "the kept plan is cached for the new facts"
    assert profile_plan.build_plan(_profile(), Settings(), facts=facts, client=FakeClient(BAD), path=path) is not None
    assert json.loads(path.read_text())["plan"]["headline"] == first.headline, "no LLM call, the cache answers"

    forced = profile_plan.build_plan(_profile(), Settings(), facts=facts, client=FakeClient(weaker), path=path,
                                     fresh=True)
    assert forced.headline.startswith("Data Engineer |"), "--fresh takes the new draft whatever it scores"

    better = dict(GOOD, target_keywords=["Spark", "Kafka", "AWS"])
    assert profile_plan.build_plan(_profile(), Settings(), facts=facts + "\nx: 1", client=FakeClient(better),
                                   path=path).ats.score > forced.ats.score, "a draft that scores higher replaces it"
