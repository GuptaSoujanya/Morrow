import json

from common import browser as common_browser
from common.models import Settings
from common.profile_plan import ProfilePlan
from sites_bot import browser_agent, profile_agent
from sites_bot.board import Board

BOARD = Board(name="naukri", label="Naukri", home="https://www.naukri.com/", feeds=(), search="",
              job_link="", job_id="", apply="", applied="", profile_url="https://www.naukri.com/mnjuser/profile")


class Body:
    def __init__(self, text):
        self.text = text


class FakeDriver:
    def __init__(self, page):
        self.page = page

    def execute_cdp_cmd(self, name, args):
        raise RuntimeError("no devtools here")

    def save_screenshot(self, path):
        open(path, "wb").write(b"png")
        return True

    def execute_script(self, script):
        return None

    def find_element(self, by, value):
        return Body(self.page)


def _report(**extra):
    report = {"status": "done", "why": "saved", "completeness_before": "82%", "completeness_after": "100%",
              "board_confirmation": "Profile updated successfully", "notes": "all good",
              "sections": [
                  {"name": "Resume headline", "action": "updated", "before": "old",
                   "after": "AI Engineer | LLM Evaluation | LangChain | Python", "verified": True},
                  {"name": "Key skills", "action": "filled", "after": "LangChain, FastAPI, AWS Bedrock",
                   "verified": True},
                  {"name": "Education", "action": "already_ok", "before": "B.Tech"},
              ]}
    report.update(extra)
    return report


def test_shown_tolerates_layout_but_not_missing_text():
    page = "Resume headline AI Engineer | LLM Evaluation | LangChain | Python  Key skills LangChain FastAPI"
    assert profile_agent.shown("AI Engineer | LLM Evaluation | LangChain | Python", page)
    assert not profile_agent.shown("Senior Data Scientist with Spark and Hadoop", page)


def test_short_skills_are_checked_instead_of_passing_for_free():
    """"Go", "R" and "C#" are too short for a 3-letter pattern, so they used to count as found."""
    assert profile_agent.verify("Go, R, C#", "a page about none of them") == (False, ["Go", "R", "C#"])
    assert profile_agent.verify("Go, Python", "I use Go and Python daily") == (True, [])
    assert profile_agent.verify("Go", "Django Golang gone") == (False, ["Go"])


def test_a_list_value_names_the_items_that_did_not_land():
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock",
                                "Key skills LangChain FastAPI AWS Bedrock") == (True, [])
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock",
                                "Key skills LangChain FastAPI") == (False, ["AWS Bedrock"])


def test_prose_has_to_match_in_order_not_as_a_bag_of_words():
    page = "Senior Engineer python aws docker leading teams building scalable systems"
    assert profile_agent.verify("Building scalable python systems on aws", page) == (False, [])


def test_a_value_only_counts_where_its_own_section_is():
    """AWS Bedrock in the headline must not confirm the skills section, which never got it."""
    page = ("Resume headline AI Engineer | LangChain | Python | AWS Bedrock "
            "Key skills LangChain FastAPI Education B.Tech")
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock, Go", page, "Key skills") \
        == (False, ["AWS Bedrock", "Go"])
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock, Go", page)[0] is True


def test_a_heading_repeated_in_the_navigation_still_finds_the_section():
    page = "Key skills Profile Resume .... Key skills LangChain FastAPI AWS Bedrock"
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock", page, "Key skills") == (True, [])


def test_a_heading_the_page_does_not_use_falls_back_to_the_whole_page():
    page = "Skills & expertise LangChain FastAPI"
    assert profile_agent.verify("LangChain, FastAPI", page, "Key skills") == (True, [])


def test_nothing_to_compare_is_unknown_never_a_free_pass():
    assert profile_agent.verify("", "a page") == (None, [])
    assert profile_agent.verify("a headline", "") == (None, [])
    assert profile_agent.shown("", "a page") is False


def test_agent_settings_turn_on_vision_and_give_more_room():
    settings = profile_agent.agent_settings(Settings(browser_agent_timeout_s=900, browser_agent_budget_usd=5))
    assert "--caps vision" in settings.browser_agent_mcp and "--save-session" in settings.browser_agent_mcp
    assert settings.browser_agent_timeout_s == 2400 and settings.browser_agent_budget_usd == 10
    assert profile_agent.agent_settings(settings).browser_agent_mcp.count("--caps") == 1


def test_each_board_agent_gets_its_own_system_prompt_with_the_skill():
    system = profile_agent.system_prompt(BOARD)
    assert system.startswith("# Naukri profile agent") and "Phase 1 - Audit" in system and '"sections"' in system
    linkedin = Board(name="linkedin", label="LinkedIn", home="", feeds=(), search="", job_link="", job_id="",
                     apply="", applied="", profile_url="")
    assert "Share with network" in profile_agent.system_prompt(linkedin)
    for name in ("hirist", "instahyre", "cutshort", "wellfound"):
        assert profile_agent.board_prompt(Board(name=name, label=name, home="", feeds=(), search="", job_link="",
                                                job_id="", apply="", applied="", profile_url="")) \
            != profile_agent.board_prompt(Board(name="nowhere", label="x", home="", feeds=(), search="",
                                                job_link="", job_id="", apply="", applied="", profile_url=""))
    text = profile_agent.prompt("Board task.", BOARD.profile_url, "facts", "a@b.c", (), True,
                                [{"name": "Resume headline", "action": "update", "current": "old",
                                  "target": "AI Engineer | Python", "why": "adds Python"}])
    assert text.count("Board task.") == 1 and "Phase 1 - Audit" not in text and "Your report" in text
    assert "1. Resume headline - update\n   now: old\n   write: AI Engineer | Python" in text


class FakeClient:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def available(self):
        return True

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        return self.reply


def test_the_edit_plan_compares_the_live_page_with_the_plan():
    client = FakeClient({"sections": [
        {"name": "Resume headline", "current": "Old headline", "target": "AI Engineer | Python",
         "action": "update", "why": "adds Python"},
        {"name": "Profile summary", "current": "", "target": "I led 40 engineers.", "action": "fill"},
        {"name": "Education", "current": "B.Tech", "target": "", "action": "keep"},
        {"name": "Date of birth", "action": "invent"},
    ]})
    plan = ProfilePlan(headline="AI Engineer | Python", summary="I build LLM apps.")
    edits = profile_agent.edit_plan(Settings(), BOARD, plan, "facts: Python, 5 years", "Old headline B.Tech",
                                    client=client)
    assert [(e["name"], e["action"]) for e in edits] == [
        ("Resume headline", "update"), ("Profile summary", "skip"), ("Education", "keep"), ("Date of birth", "skip")]
    asked = client.prompts[0]
    assert "# Naukri profile agent" in asked and "Old headline B.Tech" in asked and plan.headline in asked
    assert profile_agent.edit_plan(Settings(), BOARD, plan, "facts", "", client=client) == []


def _run(monkeypatch, tmp_path, page, report):
    monkeypatch.setattr(common_browser, "safe_get", lambda driver, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "facts_text", lambda profile, settings: "facts")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")
    monkeypatch.setattr(profile_agent, "_vision_check", lambda settings, image, plan: {"completeness": "100%"})
    monkeypatch.setattr(profile_agent, "edit_plan", lambda settings, board, plan, facts, current:
                        [{"name": "Resume headline", "action": "update", "current": current[:20],
                          "target": plan.headline, "why": ""}])
    monkeypatch.setattr(browser_agent, "run_agent", lambda driver, settings, prompt, workdir, files=(), system="":
                        browser_agent.AgentRun(report=report, workdir=workdir, seconds=1.0))
    plan = ProfilePlan(headline="AI Engineer | LLM Evaluation | LangChain | Python")
    settings = Settings(report_dir=str(tmp_path / "reports"), profile_repair_passes=0)
    return profile_agent.run(FakeDriver(page), BOARD, settings, None, "task", (), plan, "profile")


def test_a_run_counts_only_what_the_reloaded_page_shows(monkeypatch, tmp_path):
    page = "AI Engineer | LLM Evaluation | LangChain | Python  Key skills LangChain FastAPI AWS Bedrock"
    saved, notes = _run(monkeypatch, tmp_path, page, _report())
    assert saved and "2/2 changed sections confirmed" in notes and "82% -> 100%" in notes
    data = json.loads((tmp_path / "run" / "profile-report.json").read_text())
    assert [s["confirmed"] for s in data["sections"]] == [True, True, None]
    assert (tmp_path / "run" / "before.png").exists() and (tmp_path / "run" / "after.png").exists()
    assert "Key skills LangChain" in (tmp_path / "run" / "before.txt").read_text()
    assert json.loads((tmp_path / "run" / "edit-plan.json").read_text())[0]["action"] == "update"
    assert "| Resume headline | updated | yes |" in (tmp_path / "run" / "profile-report.md").read_text()


def test_every_run_lands_in_the_shared_index(monkeypatch, tmp_path):
    page = "AI Engineer | LLM Evaluation | LangChain | Python  Key skills LangChain FastAPI AWS Bedrock"
    _run(monkeypatch, tmp_path, page, _report())
    latest = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())
    assert list(latest) == ["naukri"]
    assert latest["naukri"]["saved"] is True and latest["naukri"]["confirmed"] == 2
    assert latest["naukri"]["unconfirmed"] == [] and latest["naukri"]["ats_score"] is None
    assert latest["naukri"]["report"].endswith("profile-report.md")
    assert len((tmp_path / "reports" / "profile" / "history.jsonl").read_text().splitlines()) == 1


def test_claimed_changes_missing_after_reload_are_not_counted(monkeypatch, tmp_path):
    saved, notes = _run(monkeypatch, tmp_path, "Some unrelated old profile text", _report())
    assert not saved and "NOT on the page: Resume headline, Key skills" in notes
    report = (tmp_path / "run" / "profile-report.md").read_text()
    assert "**NO**" in report and "missing: LangChain, FastAPI, AWS Bedrock" in report
    latest = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())
    assert latest["naukri"]["saved"] is False
    assert latest["naukri"]["unconfirmed"] == ["Resume headline", "Key skills"]
    assert "AWS Bedrock" in latest["naukri"]["missing"]


def test_a_section_the_page_did_not_show_gets_a_second_targeted_pass(monkeypatch, tmp_path):
    """The first pass claims two sections; only the headline is really there, so the skills are redone."""
    pages = iter(["AI Engineer | LLM Evaluation | LangChain | Python",
                  "AI Engineer | LLM Evaluation | LangChain | Python Key skills LangChain FastAPI AWS Bedrock"])
    driver = FakeDriver(next(pages))
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "facts_text", lambda profile, settings: "facts")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")
    monkeypatch.setattr(profile_agent, "_vision_check", lambda settings, image, plan: {})
    monkeypatch.setattr(profile_agent, "edit_plan", lambda *a, **k: [])
    asked = []

    def agent(driver_, settings, prompt_text, workdir, files=(), system=""):
        asked.append(prompt_text)
        if len(asked) > 1:
            driver_.page = next(pages)
        return browser_agent.AgentRun(report=_report(), workdir=workdir, seconds=1.0)

    monkeypatch.setattr(browser_agent, "run_agent", agent)
    plan = ProfilePlan(headline="AI Engineer | LLM Evaluation | LangChain | Python")
    settings = Settings(report_dir=str(tmp_path / "reports"), profile_repair_passes=1)
    saved, notes = profile_agent.run(driver, BOARD, settings, None, "task", (), plan, "profile")

    assert len(asked) == 2, "the agent should be sent back for the section the page did not show"
    assert "Key skills" in asked[1] and "AWS Bedrock" in asked[1]
    assert "Resume headline" not in asked[1], "a repair pass must not touch sections that were fine"
    assert saved and "2/2 changed sections confirmed" in notes
    assert (tmp_path / "run" / "repair-1").is_dir()


def test_repair_passes_can_be_turned_off(monkeypatch, tmp_path):
    saved, _ = _run(monkeypatch, tmp_path, "Some unrelated old profile text", _report())
    assert not saved and not (tmp_path / "run" / "repair-1").exists()


def test_needs_you_is_reported_with_its_sections(monkeypatch, tmp_path):
    saved, reason = _run(monkeypatch, tmp_path, "", _report(status="needs_you", why="OTP asked"))
    assert not saved and reason == "OTP asked"
    assert "OTP asked" in (tmp_path / "run" / "profile-report.md").read_text()
