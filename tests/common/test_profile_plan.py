from common import profile_plan
from common.models import Profile, Settings

RESUME = """Asha Rao  asha@example.com  +91 98765 43210
Experience
Senior Data Engineer, Acme (2019-2024): built Spark pipelines on AWS cutting cost 40%.
Scaled Kafka ingestion to 2 million events a day; reduced latency by 30%.
Led 5 engineers; migrated 120 Airflow DAGs to Python 3.
Education
B.Tech Computer Science
Skills
Python, SQL, Spark, Kafka, AWS, Airflow
""" + "Delivered data platform work. " * 70


class FakeClient:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.reply


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
    client = FakeClient({
        "headline": "Senior Data Engineer | 5 years | Spark | Kafka | AWS",
        "designation": "Senior Data Engineer",
        "summary": "I build data platforms on AWS. I cut cost 40% with Spark. I managed 50 engineers.",
        "about": "",
        "key_skills": ["Spark", "Kafka", "Kubernetes", "Python"],
        "target_roles": ["Data Engineer", "Senior Data Engineer"],
        "target_keywords": ["Spark", "Kafka", "dbt"],
        "suggestions": ["Add dbt if you have used it."],
    })
    path = tmp_path / "plan.json"
    plan = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=path)
    assert plan.source == "llm"
    assert plan.key_skills == ["Spark", "Kafka", "Python"]          # Kubernetes is not in the facts
    assert "50 engineers" not in plan.summary and "40%" in plan.summary
    assert plan.about == plan.summary
    assert plan.ats.missing == ["dbt"]
    brief = profile_plan.agent_brief(plan)
    assert plan.headline in brief and "Spark, Kafka, Python" in brief

    again = profile_plan.build_plan(_profile(), Settings(), facts=RESUME, client=client, path=path)
    assert len(client.prompts) == 1 and again.headline == plan.headline and again.ats.score == plan.ats.score
    profile_plan.build_plan(_profile(), Settings(), facts=RESUME + " new fact", client=client, path=path)
    assert len(client.prompts) == 2


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
    assert "ATS: her resume scores %d/100" % plan.ats.score in brief
    assert "she has; each must appear" in brief and "Spark, Kafka" in brief
    assert "never as a new claim: dbt" in brief
