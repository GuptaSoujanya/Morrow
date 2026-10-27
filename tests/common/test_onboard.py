"""The first run: python3 -m pipeline onboard writes everything under user/ and .env."""

import json
import re
from pathlib import Path

import pytest
import yaml

from common import answers as answers_module
from common import onboard, persona, resume
from common.config import load_settings

REPO = Path(__file__).resolve().parents[2]

#: The keys onboarding writes to .env; write_env_value also exports them, so each test unsets them first.
ENV_KEYS = ("NAUKRI_EMAIL", "NAUKRI_PASSWORD", "PLATFORMS", "LLM_BACKEND", "ANTHROPIC_API_KEY", "PROFILE_PATH",
            "RESUME_PATH", "TAILOR_RESUME", "LINKEDIN_TOPICS", "MORROW_USER_DIR", "MORROW_DATABASE_DIR")

RESUME_TXT = """Asha Rao
asha@example.com | +91 98765 43210 | Pune
Data engineer with 4 years building streaming pipelines on Kafka and Spark at Acme Data.
Skills: Python, Kafka, Spark, Airflow, AWS, PostgreSQL
B.Tech Computer Science, Pune University, 2021
"""

PROFILE_READ = {
    "full_name": "Asha Rao", "first_name": "Asha", "last_name": "Rao", "email": "asha@example.com",
    "phone": "+91 98765 43210", "current_location": "Pune", "total_experience_years": 4,
    "highest_qualification": "B.Tech", "titles": ["Data Engineer"], "skills": ["Python", "Kafka", "Spark", "Airflow"],
    "current_company": "Acme Data", "current_designation": "Data Engineer", "degree": "B.Tech Computer Science",
    "university": "Pune University", "graduation_year": 2021, "github_url": "https://github.com/asha",
    "portfolio_url": "https://asha.example/",
}
PERSONA_READ = {
    "headline": "data engineer at Acme Data", "employer": "Acme Data", "location": "Pune",
    "focus": "streaming pipelines", "facts": ["Built the Kafka ingestion at Acme Data"],
    "topics": ["Kafka", "Spark"], "study_areas": [{"slug": "kafka", "title": "Kafka and streams"}, {"title": "Spark jobs"}],
    "voice_sample": "I move data from A to B without losing any.",
}


def good_tex() -> str:
    """The template with a name in the header: the shape the tailoring code parses."""
    return onboard.TEMPLATE_TEX.read_text(encoding="utf-8").replace("FIRST LAST", "ASHA RAO")


class FakeClient:
    def __init__(self, tex=None, up=True):
        self.tex = good_tex() if tex is None else tex
        self.up = up
        self.prompts = []

    def available(self):
        return self.up

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        if schema == onboard._TEX_SCHEMA:
            return {"tex": self.tex}
        if schema == onboard._PROFILE_SCHEMA:
            return dict(PROFILE_READ)
        if schema == onboard._PERSONA_SCHEMA:
            return dict(PERSONA_READ)
        raise AssertionError("unexpected schema %s" % schema)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A repo root with .env.example and the templates, and a resume to read."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env.example").write_text((REPO / ".env.example").read_text(encoding="utf-8"))
    (tmp_path / "resume.txt").write_text(RESUME_TXT)
    return tmp_path


def _run(home, client=None, answers=None, resume="resume.txt", user_dir="user"):
    run = onboard.Onboarding(root=home, user_dir=home / user_dir, env_path=home / ".env",
                             resume=home / resume if resume else None,
                             prompter=onboard.Prompter(answers or {}, yes=True), client=client or FakeClient())
    assert run.run() == 0
    return run


def _env(home):
    text = (home / ".env").read_text()
    return dict(re.findall(r"^([A-Z_]+)=(.*)$", text, re.M))


def test_the_template_resume_fits_the_tailoring_code():
    sections = resume.parse_sections(good_tex())
    assert sections is not None and resume._HEADER_NAME.search(good_tex())


def test_a_first_run_writes_every_file_the_bots_read(home):
    assert onboard.needs_onboarding(home / "user")
    run = _run(home, answers={"naukri_email": "asha@example.com", "naukri_password": "hunter2",
                              "expected_ctc_lpa": 18, "notice_period_days": 60, "pronouns": "she/her"})
    inputs = home / "user" / "inputs"
    assert not onboard.needs_onboarding(home / "user")

    env = _env(home)
    assert env["NAUKRI_EMAIL"] == "asha@example.com" and env["NAUKRI_PASSWORD"] == "hunter2"
    assert env["PROFILE_PATH"] == "user/inputs/profile.yaml" and env["RESUME_PATH"] == "user/resume/base.tex"
    assert env["TAILOR_RESUME"] == "true" and env["LINKEDIN_TOPICS"] == ""
    assert "MORROW_USER_DIR" not in env or env["MORROW_USER_DIR"] == ""   # the default folder needs no override
    assert oct((home / ".env").stat().st_mode)[-3:] == "600"

    profile = yaml.safe_load((inputs / "profile.yaml").read_text())
    assert profile["full_name"] == "Asha Rao" and profile["email"] == "asha@example.com"
    assert profile["expected_ctc_lpa"] == 18 and profile["notice_period_days"] == 60
    assert profile["current_ctc_lpa"] is None                          # not given: the bot abstains
    assert profile["skills"] == ["Python", "Kafka", "Spark", "Airflow"] and profile["titles"] == ["Data Engineer"]
    extra = profile["extra_facts"]
    assert extra["current_company"] == "Acme Data" and extra["github_url"] == "https://github.com/asha"
    assert "Naukri" in extra["job_discovery_source"] and extra["skill_experience_years"].startswith("4 years")
    assert oct((inputs / "profile.yaml").stat().st_mode)[-3:] == "600"
    settings = load_settings(str(home / ".env"))
    assert settings.profile_path.endswith("user/inputs/profile.yaml") and settings.tailor_resume

    who = persona.load_persona(inputs / "persona.yaml")
    assert who.name == "Asha Rao" and who.pronouns == "she/her" and who.they == "she"
    assert who.headline == "data engineer at Acme Data" and who.site == "asha.example"
    assert who.topics == ["Kafka", "Spark"] and who.experience_years == 4 and who.location == "Pune"
    assert [a.slug for a in who.study_areas] == ["kafka", "spark-jobs"]
    assert "Built the Kafka ingestion" in who.voice_block()

    tex = (home / "user" / "resume" / "base.tex").read_text()
    assert "ASHA RAO" in tex and resume.parse_sections(tex)
    assert (home / "user" / "resume" / "resume.txt").is_file()        # the original is kept next to it

    book = answers_module.parse_answers((inputs / "answers.txt").read_text())
    pairs = {q.lower(): a for q, a in book.items()} if isinstance(book, dict) else {}
    text = (inputs / "answers.txt").read_text()
    assert text.rstrip().endswith(onboard.UNANSWERED_MARKER)
    assert "# ----- money and notice" in text and "A: 18" in text and "A: 60" in text
    assert "[AI writes this for each job]" in text
    assert pairs or book                                                 # parses as a question book

    assert (inputs / "accounts.md").read_text().startswith("# Career-site accounts")
    assert (inputs / "company_sites.md").read_text().startswith("# Applications on company websites")
    assert (home / "user" / ".gitignore").is_file()
    memory = home / "user" / "memory"
    assert json.loads((memory / "progress.json").read_text()) == {"days": {}}
    assert json.loads((memory / "profiles.json").read_text()) == {}
    assert (memory / "README.md").is_file() and (memory / "learning.json").is_file()
    for folder in ("resume/out", "db", "reports", "research", "worklists"):
        assert (home / "user" / folder).is_dir()
    assert inputs / "profile.yaml" in run.written and inputs / "persona.yaml" in run.written


def test_without_a_model_the_pdf_or_text_resume_is_kept_and_tailoring_is_off(home):
    run = _run(home, client=FakeClient(up=False), answers={"full_name": "Asha Rao", "skills": "Python, Kafka, Spark, Airflow",
                                                           "titles": "Data Engineer", "total_experience_years": "4"})
    env = _env(home)
    assert env["RESUME_PATH"] == "user/resume/resume.txt" and env["TAILOR_RESUME"] == "false"
    assert not (home / "user" / "resume" / "base.tex").exists()
    profile = yaml.safe_load((home / "user" / "inputs" / "profile.yaml").read_text())
    assert profile["full_name"] == "Asha Rao" and profile["skills"] == ["Python", "Kafka", "Spark", "Airflow"]
    assert profile["total_experience_years"] == 4
    who = persona.load_persona(home / "user" / "inputs" / "persona.yaml")
    assert who.name == "Asha Rao" and who.pronouns == "they/them"
    assert [a.title for a in who.study_areas] == ["Python, Kafka, Spark", "Airflow"]   # one area per three skills
    assert not onboard.needs_onboarding(home / "user")
    assert run.tailoring is False


def test_latex_the_model_gets_wrong_falls_back_to_the_original_file(home, caplog):
    _run(home, client=FakeClient(tex="\\documentclass{article}\\begin{document}hi\\end{document}"))
    env = _env(home)
    assert env["RESUME_PATH"] == "user/resume/resume.txt" and env["TAILOR_RESUME"] == "false"
    assert not (home / "user" / "resume" / "base.tex").exists()


def test_a_tex_resume_is_copied_as_is(home):
    (home / "mine.tex").write_text(good_tex())
    _run(home, resume="mine.tex")
    assert (home / "user" / "resume" / "base.tex").read_text() == good_tex()
    assert _env(home)["TAILOR_RESUME"] == "true"


def test_a_second_run_keeps_hand_written_answers_and_extra_facts(home):
    _run(home)
    inputs = home / "user" / "inputs"
    answers_path = inputs / "answers.txt"
    answers_path.write_text(onboard.ANSWERS_HEADER + "\nQ: Favourite editor?\nA: vim\n" * 3)
    profile_path = inputs / "profile.yaml"
    profile = yaml.safe_load(profile_path.read_text())
    profile["extra_facts"]["pan_number"] = "ABCDE1234F"
    profile_path.write_text(yaml.safe_dump(profile))
    _run(home, answers={"current_location": "Bengaluru"})
    assert "Favourite editor?" in answers_path.read_text()
    again = yaml.safe_load(profile_path.read_text())
    assert again["current_location"] == "Bengaluru" and again["full_name"] == "Asha Rao"
    assert again["extra_facts"]["pan_number"] == "ABCDE1234F"


def test_a_user_dir_elsewhere_is_written_to_env_with_absolute_paths(home):
    elsewhere = home / "elsewhere"
    _run(home, user_dir="elsewhere")
    env = _env(home)
    assert env["MORROW_USER_DIR"] == str(elsewhere)
    assert env["PROFILE_PATH"] == str(elsewhere / "inputs" / "profile.yaml")
    assert env["RESUME_PATH"] == str(elsewhere / "resume" / "base.tex")
    assert (elsewhere / "inputs" / "persona.yaml").is_file()


def test_needs_onboarding_until_the_profile_has_a_real_name(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    assert onboard.needs_onboarding(tmp_path)
    (inputs / "profile.yaml").write_text('full_name: "Your Full Name"\n')
    assert onboard.needs_onboarding(tmp_path)
    (inputs / "profile.yaml").write_text("full_name: Asha Rao\n")
    assert not onboard.needs_onboarding(tmp_path)
    (inputs / "profile.yaml").write_text("full_name: [unclosed\n")
    assert not onboard.needs_onboarding(tmp_path)        # load_profile reports a broken file itself


def test_main_takes_answers_from_a_json_file_and_builds_no_model_without_a_backend(home, monkeypatch):
    monkeypatch.setattr(onboard.Onboarding, "_client", lambda self: FakeClient(up=False))
    (home / "a.json").write_text(json.dumps({"full_name": "Asha Rao", "llm_backend": "none"}))
    code = onboard.main(["--yes", "--resume", str(home / "resume.txt"), "--answers", str(home / "a.json"),
                         "--user-dir", str(home / "user"), "--env", str(home / ".env")])
    assert code == 0
    assert _env(home)["LLM_BACKEND"] == "none"
    assert yaml.safe_load((home / "user" / "inputs" / "profile.yaml").read_text())["full_name"] == "Asha Rao"
    (home / "bad.json").write_text("[]")
    assert onboard.main(["--yes", "--answers", str(home / "bad.json"), "--env", str(home / ".env")]) == 2


def test_the_prompter_prefers_given_answers_then_defaults_then_the_terminal():
    asked = []
    prompter = onboard.Prompter({"email": "a@b.c"}, yes=False, ask=lambda q: asked.append(q) or "typed",
                                secret=lambda q: "s3cret", out=lambda s: None)
    assert prompter.ask("email", "Email", "x") == "a@b.c"
    assert prompter.ask("city", "City", "Pune") == "typed" and asked == ["City [Pune]: "]
    assert prompter.ask("password", "Password", "", secret=True) == "s3cret"
    blank = onboard.Prompter(yes=False, ask=lambda q: "   ", out=lambda s: None)
    assert blank.ask("city", "City", "Pune") == "Pune"
    assert blank.confirm("ok", "Go on?", True) is True
    assert onboard.Prompter(yes=True).ask("city", "City", "Pune") == "Pune"
