import json

from common import browser as common_browser
from common.models import Settings
from common.profile_plan import ProfilePlan
from sites_bot import browser_agent, profile_agent
from sites_bot.board import Board
from sites_bot.profile_agent import Section

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


def test_verify_tolerates_layout_but_not_missing_text():
    page = "Resume headline AI Engineer | LLM Evaluation | LangChain | Python  Key skills LangChain FastAPI"
    assert profile_agent.verify("AI Engineer | LLM Evaluation | LangChain | Python", page)[0] is True
    assert profile_agent.verify("Senior Data Scientist with Spark and Hadoop", page)[0] is False


def test_short_skills_are_checked_instead_of_passing_for_free():
    """"Go", "R" and "C#" are too short for a 3-letter pattern, so they used to count as found."""
    assert profile_agent.verify("Go, R, C#", "a page about none of them") == (False, ["Go", "R", "C#"])
    assert profile_agent.verify("Go, Python", "I use Go and Python daily") == (True, [])
    assert profile_agent.verify("Go", "Django Golang gone") == (False, ["Go"])


def test_a_skill_the_board_spells_its_own_way_still_counts():
    """Naukri saves "FastAPI" as "Fast API", "Next.js" as "Nextjs" and "React" as "React.js"; a live run
    sent every one of them back for repair as "not on the page"."""
    page = "Key skills Python, Fast API, Nextjs, React.js, Langchain, Node.js, Pytest"
    assert profile_agent.verify("FastAPI, Next.js, React, LangChain, Node.js, pytest", page, "Key skills") == (True, [])
    assert profile_agent.verify("FastAPI, Go", page, "Key skills") == (False, ["Go"])
    assert profile_agent.verify("AWS Bedrock", "Key skills AWSBedrock")[0] is True
    assert profile_agent.verify("AWS", "Key skills AWSBedrock") == (False, ["AWS"])      # not a prefix match


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


def test_a_short_sentence_with_a_comma_is_prose_not_two_things_to_find_word_for_word():
    """Its clauses are short enough to look like list items, so they used to be demanded verbatim."""
    assert profile_agent._items("Building scalable python systems on aws, with a focus on retrieval.") == []
    assert profile_agent._items("Python, Go.") == ["Python", "Go"]
    assert profile_agent._items("LangChain, Natural Language Processing, Node.js") == [
        "LangChain", "Natural Language Processing", "Node.js"]
    page = "I write python systems that run on aws with a focus on retrieval at scale"
    assert profile_agent.verify("Building python systems on aws, with a focus on retrieval.", page)[0] is False


def test_the_best_matching_place_for_a_heading_wins_not_the_first():
    """The menu entry comes first and has none of the skills; the section itself has them all."""
    page = ("Key skills Profile Settings Logout " + "x" * 1400
            + " Key skills LangChain FastAPI AWS Bedrock")
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock", page, "Key skills") == (True, [])
    partial = ("Key skills LangChain FastAPI Education " + "x" * 1400
               + " Key skills LangChain FastAPI AWS Bedrock")
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock", partial, "Key skills") == (True, [])


def test_a_heading_repeated_in_the_navigation_still_finds_the_section():
    page = "Key skills Profile Resume .... Key skills LangChain FastAPI AWS Bedrock"
    assert profile_agent.verify("LangChain, FastAPI, AWS Bedrock", page, "Key skills") == (True, [])


def test_a_heading_the_page_does_not_use_falls_back_to_the_whole_page():
    page = "Skills & expertise LangChain FastAPI"
    assert profile_agent.verify("LangChain, FastAPI", page, "Key skills") == (True, [])


def test_nothing_to_compare_is_unknown_never_a_free_pass():
    assert profile_agent.verify("", "a page") == (None, [])
    assert profile_agent.verify("a headline", "") == (None, [])
    assert profile_agent.verify("", "a page", "Key skills") == (None, [])


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


def test_a_skill_that_did_not_land_is_redone_even_though_the_section_is_there(monkeypatch, tmp_path):
    """Three of four skills is over the threshold, so the section counted as saved and was left alone."""
    page = ("AI Engineer | LLM Evaluation | LangChain | Python "
            "Key skills LangChain FastAPI Go Education B.Tech")
    report = _report(sections=[
        {"name": "Resume headline", "action": "updated",
         "after": "AI Engineer | LLM Evaluation | LangChain | Python", "verified": True},
        {"name": "Key skills", "action": "filled", "after": "LangChain, FastAPI, AWS Bedrock, Go",
         "verified": True},
    ])
    asked = []
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "facts_text", lambda profile, settings: "facts")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")
    monkeypatch.setattr(profile_agent, "_vision_check", lambda settings, image, plan: {})
    monkeypatch.setattr(profile_agent, "edit_plan", lambda *a, **k: [])

    def agent(driver_, settings, prompt_text, workdir, files=(), system=""):
        asked.append(prompt_text)
        return browser_agent.AgentRun(report=report, workdir=workdir, seconds=1.0)

    monkeypatch.setattr(browser_agent, "run_agent", agent)
    plan = ProfilePlan(headline="AI Engineer | LLM Evaluation | LangChain | Python")
    settings = Settings(report_dir=str(tmp_path / "reports"), profile_repair_passes=1)
    saved, notes = profile_agent.run(FakeDriver(page), BOARD, settings, None, "task", (), plan, "profile")

    assert len(asked) == 2 and "AWS Bedrock" in asked[1], "the skill that did not land must be redone"
    assert "Resume headline" not in asked[1]
    assert saved and "not seen: AWS Bedrock" in notes
    latest = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())
    assert latest["naukri"]["missing"] == ["AWS Bedrock"]
    assert latest["naukri"]["why"] == "confirmed on the reloaded page, except: AWS Bedrock"


def test_sections_the_bot_could_not_check_do_not_count_as_missing():
    """One real confirmation plus three sections with no value to look for is not "1 of 4"."""
    sections = [Section(name="Headline", action="updated", after="x", on_page=True)]
    sections += [Section(name=name, action="updated") for name in ("Summary", "Skills", "Projects")]
    result = profile_agent.ProfileCheck(saved=False, why="", sections=sections)
    assert profile_agent._verdict(result) == (True, "confirmed on the reloaded page")
    result.sections[1].on_page = False
    assert profile_agent._verdict(result) == (False, "Summary still not on the reloaded page")


def test_the_run_folder_and_the_index_agree_on_the_same_run(monkeypatch, tmp_path):
    page = "AI Engineer | LLM Evaluation | LangChain | Python  Key skills LangChain FastAPI AWS Bedrock"
    _run(monkeypatch, tmp_path, page, _report())
    run_json = json.loads((tmp_path / "run" / "profile-report.json").read_text())
    indexed = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert run_json["at"] == indexed["at"]
    assert {key: run_json[key] for key in indexed} == indexed
    assert "plan_source" in run_json and "plan_source" not in indexed


def test_a_repair_keeps_each_section_its_own(monkeypatch, tmp_path):
    """Two sections whose names differ only in case used to end up as one object in both slots."""
    first = profile_agent.ProfileCheck(saved=False, why="", sections=[
        Section(name="Skills", action="updated", after="one", note="first"),
        Section(name="skills", action="updated", after="two"),
    ])
    repaired = profile_agent.ProfileCheck(saved=False, why="", sections=[
        Section(name="Skills", action="updated", after="fixed", on_page=True),
    ])
    merged = profile_agent._merge(first, repaired)
    assert merged.sections[0] is not merged.sections[1]
    assert merged.sections[0].note == "first" and merged.sections[1].note == ""


def test_repair_passes_can_be_turned_off(monkeypatch, tmp_path):
    saved, _ = _run(monkeypatch, tmp_path, "Some unrelated old profile text", _report())
    assert not saved and not (tmp_path / "run" / "repair-1").exists()


def test_needs_you_is_reported_with_its_sections(monkeypatch, tmp_path):
    saved, reason = _run(monkeypatch, tmp_path, "", _report(status="needs_you", why="OTP asked"))
    assert not saved and reason == "OTP asked"
    assert "OTP asked" in (tmp_path / "run" / "profile-report.md").read_text()


# --- a run that stops short is finished, not lost ------------------------------------


def _staged(monkeypatch, tmp_path, pages, reports, edits, passes=1, files=(), opens=None):
    """Drive profile_agent.run with a page per agent pass and a report per pass; returns (saved, notes, asked).

    `opens` stands in for common.browser.safe_get (every navigation succeeds when it is not given).
    """
    pages, reports = iter(pages), iter(reports)
    driver = FakeDriver(next(pages))
    monkeypatch.setattr(common_browser, "safe_get", opens or (lambda d, url: True))
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "facts_text", lambda profile, settings: "facts")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")
    monkeypatch.setattr(profile_agent, "_vision_check", lambda settings, image, plan: {})
    monkeypatch.setattr(profile_agent, "edit_plan", lambda *a, **k: list(edits))
    asked = []

    def agent(driver_, settings, prompt_text, workdir, files=(), system=""):
        asked.append((prompt_text, files))
        if len(asked) > 1:
            driver_.page = next(pages)
        run = next(reports)
        if isinstance(run, browser_agent.AgentRun):
            return run
        return browser_agent.AgentRun(report=run, workdir=workdir, seconds=1.0)

    monkeypatch.setattr(browser_agent, "run_agent", agent)
    plan = ProfilePlan(headline="AI Engineer | LLM Evaluation | LangChain | Python")
    settings = Settings(report_dir=str(tmp_path / "reports"), profile_repair_passes=passes)
    saved, notes = profile_agent.run(driver, BOARD, settings, None, "task", files, plan, "profile")
    return saved, notes, asked


HEADLINE = "AI Engineer | LLM Evaluation | LangChain | Python"
_EDITS = [{"name": "Resume headline", "action": "update", "current": "old", "target": HEADLINE, "why": ""},
          {"name": "Key skills", "action": "update", "current": "Python", "target": "LangChain, FastAPI, AWS Bedrock",
           "why": "adds the planned skills"},
          {"name": "Education", "action": "keep", "current": "B.Tech", "target": "", "why": ""}]
_HEADLINE_ONLY = {"status": "done", "why": "saved", "sections": [
    {"name": "Resume headline", "action": "updated", "after": HEADLINE, "verified": True}]}
_SKILLS_DONE = {"status": "done", "why": "saved", "sections": [
    {"name": "Key skills", "action": "updated", "after": "LangChain, FastAPI, AWS Bedrock", "verified": True}]}


def test_the_agent_is_told_the_copy_in_its_run_folder_not_the_original(monkeypatch, tmp_path):
    """The browser tool may only upload from the run folder; the original path is refused."""
    original = tmp_path / "private" / "resume.pdf"
    original.parent.mkdir()
    original.write_bytes(b"%PDF")
    saved, notes, asked = _staged(monkeypatch, tmp_path, ["Resume headline " + HEADLINE + " Key skills LangChain "
                                                          "FastAPI AWS Bedrock"], [_report()], _EDITS,
                                  files=(original,))
    prompt_text, files = asked[0]
    copy = tmp_path / "run" / "resume.pdf"
    assert copy.is_file() and files == (copy.resolve(),)
    assert str(copy.resolve()) in prompt_text and str(original) not in prompt_text


def test_a_planned_section_the_agent_never_reported_is_finished_by_the_repair_pass(monkeypatch, tmp_path):
    """The agent ran out of turns after the headline; the plan still wanted the skills."""
    saved, notes, asked = _staged(
        monkeypatch, tmp_path,
        ["Resume headline " + HEADLINE + " Key skills Python",
         "Resume headline " + HEADLINE + " Key skills Python LangChain FastAPI AWS Bedrock"],
        [_HEADLINE_ONLY, _SKILLS_DONE], _EDITS)
    assert len(asked) == 2
    repair_prompt = asked[1][0]
    assert "Key skills" in repair_prompt and "not done yet" in repair_prompt and "AWS Bedrock" in repair_prompt
    assert "Resume headline" not in repair_prompt.split("Fix ONLY")[1].split("For each one")[0]
    assert saved and "2/2 changed sections confirmed" in notes
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert [(s["name"], s["action"], s["confirmed"]) for s in record["sections"]] == [
        ("Resume headline", "updated", True), ("Key skills", "updated", True)]


def test_a_planned_section_the_page_already_shows_is_not_redone(monkeypatch, tmp_path):
    page = "Resume headline " + HEADLINE + " Key skills LangChain FastAPI AWS Bedrock"
    saved, notes, asked = _staged(monkeypatch, tmp_path, [page], [_HEADLINE_ONLY], _EDITS)
    assert len(asked) == 1 and saved
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert ("Key skills", "already_ok", True) in [(s["name"], s["action"], s["confirmed"]) for s in record["sections"]]


def test_an_agent_that_died_without_a_report_still_has_its_plan_finished(monkeypatch, tmp_path):
    """Out of budget before the JSON report: the plan says what was wanted, the page says what landed."""
    died = browser_agent.AgentRun(report=None, workdir=tmp_path / "run", seconds=600.0,
                                  problem="claude stopped: error_max_budget_usd")
    saved, notes, asked = _staged(
        monkeypatch, tmp_path,
        ["Resume headline " + HEADLINE + " Key skills Python",
         "Resume headline " + HEADLINE + " Key skills Python LangChain FastAPI AWS Bedrock"],
        [died, _SKILLS_DONE], _EDITS)
    assert len(asked) == 2 and "Key skills" in asked[1][0]
    assert "Resume headline" not in asked[1][0].split("Fix ONLY")[1].split("For each one")[0]
    assert saved
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert record["saved"] is True and ("Key skills", "updated") in [(s["name"], s["action"]) for s in record["sections"]]


def test_without_a_repair_pass_a_dead_agent_leaves_an_honest_record(monkeypatch, tmp_path):
    died = browser_agent.AgentRun(report=None, workdir=tmp_path / "run", seconds=600.0,
                                  problem="claude stopped: error_max_budget_usd")
    saved, notes, asked = _staged(monkeypatch, tmp_path, ["Resume headline " + HEADLINE + " Key skills Python"],
                                  [died], _EDITS, passes=0)
    assert not saved and len(asked) == 1
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert record["saved"] is False
    assert record["why"].startswith("not done: Key skills") and "error_max_budget_usd" in record["why"]
    assert ("Key skills", "pending", False) in [(s["name"], s["action"], s["confirmed"]) for s in record["sections"]]
    assert "not done: Key skills" in (tmp_path / "run" / "profile-report.md").read_text()


def test_a_section_the_agent_reports_failed_is_sent_back(monkeypatch, tmp_path):
    first = {"status": "failed", "why": "ran low on turns", "sections": [
        {"name": "Resume headline", "action": "updated", "after": HEADLINE, "verified": True},
        {"name": "Key skills", "action": "failed", "note": "not reached"}]}
    saved, notes, asked = _staged(
        monkeypatch, tmp_path,
        ["Resume headline " + HEADLINE + " Key skills Python",
         "Resume headline " + HEADLINE + " Key skills Python LangChain FastAPI AWS Bedrock"],
        [first, _SKILLS_DONE], _EDITS)
    assert len(asked) == 2
    assert "could not save it: not reached" in asked[1][0] and "AWS Bedrock" in asked[1][0]
    assert saved and "2/2 changed sections confirmed" in notes


def test_a_failed_section_the_repair_pass_skips_stops_being_counted(monkeypatch, tmp_path):
    first = {"status": "failed", "why": "ran low on turns", "sections": [
        {"name": "Resume headline", "action": "updated", "after": HEADLINE, "verified": True},
        {"name": "Key skills", "action": "failed", "note": "not reached"}]}
    skipped = {"status": "done", "why": "no such field", "sections": [
        {"name": "Key skills", "action": "skipped", "note": "the board has no skills section"}]}
    saved, notes, asked = _staged(
        monkeypatch, tmp_path, ["Resume headline " + HEADLINE, "Resume headline " + HEADLINE],
        [first, skipped], _EDITS)
    assert saved and "1/1 changed sections confirmed" in notes


def test_a_run_the_agent_could_not_start_is_still_recorded(monkeypatch, tmp_path):
    dead = browser_agent.AgentRun(report=None, workdir=tmp_path / "run", seconds=0.1,
                                  problem="the claude command is not on PATH")
    saved, notes, asked = _staged(monkeypatch, tmp_path, ["whatever"], [dead], [])
    assert not saved and notes == "the claude command is not on PATH"
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert record["saved"] is False and record["why"] == "the claude command is not on PATH"


def test_needs_you_is_recorded_with_what_landed_but_not_sent_back(monkeypatch, tmp_path):
    report = _report(status="needs_you", why="OTP asked")
    page = "Resume headline " + HEADLINE + " Key skills LangChain FastAPI AWS Bedrock"
    saved, notes, asked = _staged(monkeypatch, tmp_path, [page], [report], _EDITS)
    assert not saved and notes == "OTP asked" and len(asked) == 1
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert record["saved"] is False and record["confirmed"] == 2


def test_years_are_matched_the_way_the_board_shows_them():
    """Naukri shows "2.5 years" as "2 Years 6 Months" (or "2 Year(s) 6 Month(s)"); a live run sent every
    IT skill back as "not on the page: 2.5 years"."""
    assert profile_agent._forms("2.5 years") == ["2.5 years", "2 years 6 months", "2.5 years"]
    assert profile_agent._forms("2 yrs")[:2] == ["2 yrs", "2 years 0 months"]
    page = "IT skills Python 2 Years 6 Months Last used 2026 editOneTheme FastAPI 2 Year(s) 0 Month(s) 2026"
    assert profile_agent.verify("Python, 2.5 years, 2026", page, "IT skills") == (True, [])
    assert profile_agent.verify("FastAPI, 2 years, 2026", page, "IT skills") == (True, [])
    assert profile_agent.verify("Docker, 3 years", page, "IT skills") == (False, ["Docker", "3 years"])


def test_the_reload_unfolds_read_more_before_the_page_is_read(monkeypatch):
    """Naukri folds the summary and each job profile behind "Read More"; the bot used to read the cut
    text and report both as not on the page."""
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)

    class Recorder(FakeDriver):
        scripts = []

        def execute_script(self, script):
            self.scripts.append(script)
            return 2 if "more" in script else None

    driver = Recorder("page")
    profile_agent._load_all(driver)
    unfold = [script for script in driver.scripts if "more" in script]
    assert len(unfold) == 1 and "el.click()" in unfold[0]
    assert driver.scripts.index(unfold[0]) < driver.scripts.index("window.scrollTo(0, 0);")


def test_a_repair_pass_that_finds_a_section_already_there_leaves_page_evidence(monkeypatch, tmp_path):
    """The repair agent reported Key skills "already_ok" (the first save had taken effect); the merged
    record then showed it as never checked, and the run as not saved."""
    first = _report()
    again = _report(sections=[{"name": "Key skills", "action": "already_ok",
                               "after": "LangChain, FastAPI, AWS Bedrock",
                               "note": "all three were already on the page"}])
    folded = "AI Engineer | LLM Evaluation | LangChain | Python  Key skills (folded)"
    unfolded = folded + " LangChain FastAPI AWS Bedrock"
    driver = FakeDriver(folded)

    def agent(driver, settings, prompt, workdir, files=(), system=""):
        if "An agent already worked on this profile" in prompt:
            driver.page = unfolded
            return browser_agent.AgentRun(report=again, workdir=workdir, seconds=1.0)
        return browser_agent.AgentRun(report=first, workdir=workdir, seconds=1.0)

    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    monkeypatch.setattr(browser_agent, "facts_text", lambda profile, settings: "facts")
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")
    monkeypatch.setattr(profile_agent, "_vision_check", lambda settings, image, plan: {})
    monkeypatch.setattr(profile_agent, "edit_plan", lambda *a, **k: [])
    monkeypatch.setattr(browser_agent, "run_agent", agent)
    plan = ProfilePlan(headline="AI Engineer | LLM Evaluation | LangChain | Python")
    settings = Settings(report_dir=str(tmp_path / "reports"), profile_repair_passes=1)
    saved, notes = profile_agent.run(driver, BOARD, settings, None, "task", (), plan, "profile")
    assert saved and "2/2 changed sections confirmed" in notes
    data = json.loads((tmp_path / "run" / "profile-report.json").read_text())
    skills = next(s for s in data["sections"] if s["name"] == "Key skills")
    assert skills["action"] == "filled" and skills["confirmed"] is True
    assert "all three were already on the page" in skills["note"]


def _full_plan():
    return ProfilePlan(
        headline="AI Engineer | LLM Evaluation | LangChain | Python",
        key_skills=["LangChain", "FastAPI", "AWS Bedrock", "Docker"],
        summary="Built an agent evaluation platform that benchmarks 5 sub-agents in 600 seconds.",
        experience=[{"title": "Software Engineer", "company": "Ethara AI", "start": "Mar 2024", "end": "Present",
                     "description": "Built 101 FastAPI mock services and a three judge council.", "skills": "Python"}],
        projects=[{"name": "EvalAgentFlow", "description": "Multi provider agent evaluation with a judge council."}],
        it_skills=[{"name": "Python", "years": "2.5", "last_used": "2026"}],
        certifications=["AWS Academy Cloud Architecting"],
        links=["https://github.com/GuptaSoujanya"],
    )


def test_the_score_checks_every_part_of_the_plan_made_from_the_resume():
    names = [section.name for section in profile_agent.planned_sections(_full_plan())]
    assert names == ["Resume headline", "Key skills", "Profile summary", "Employment: Ethara AI",
                     "Job profile: Ethara AI", "Project: EvalAgentFlow", "IT skill: Python",
                     "Certifications", "Online profiles"]
    assert all(section.action == profile_agent.SCORED for section in profile_agent.planned_sections(_full_plan()))
    it_skill = profile_agent.planned_sections(_full_plan())[6]
    assert it_skill.wanted == "Python, 2.5 years, 2026"
    assert profile_agent.planned_sections(ProfilePlan()) == []


def test_the_score_names_what_the_profile_lacks_and_reads_the_completeness(monkeypatch, tmp_path):
    """The page has the headline, three of four skills, the job and the certification; the summary, the
    job profile, the project, the IT skill and the link are not there."""
    page = ("9 1 85% Soujanya Gupta Resume headline AI Engineer | LLM Evaluation | LangChain | Python "
            "Key skills LangChain Fast API Docker Employment Software Engineer Ethara AI Mar 2024 to Present "
            "Certifications AWS Academy Cloud Architecting")
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    result = profile_agent.score(FakeDriver(page), BOARD, _full_plan(), tmp_path)
    assert result.completeness_after == "85%"
    assert not result.saved
    assert result.why.startswith("4 of 9 planned sections are on the profile; not on it: Profile summary, "
                                 "Job profile: Ethara AI, Project: EvalAgentFlow, IT skill: Python, Online profiles")
    assert "partly: Key skills (AWS Bedrock)" in result.why
    assert (tmp_path / "page.txt").read_text() == page and (tmp_path / "profile.png").exists()
    text = profile_agent.score_text(BOARD, result, _full_plan())
    assert "Completeness shown by Naukri: 85%" in text and "NO  Profile summary" in text
    assert "not on the page: AWS Bedrock" in text


def test_a_profile_that_matches_the_whole_plan_scores_full(monkeypatch, tmp_path):
    plan = ProfilePlan(headline="AI Engineer | LangChain", key_skills=["LangChain", "Python"])
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    result = profile_agent.score(FakeDriver("93% Resume headline AI Engineer | LangChain Key skills LangChain Python"),
                                 BOARD, plan, tmp_path)
    assert result.saved and result.why == "2 of 2 planned sections are on the profile"
    assert result.completeness_after == "93%"


def test_a_score_that_cannot_read_the_page_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: False)
    result = profile_agent.score(FakeDriver(""), BOARD, _full_plan(), tmp_path)
    assert not result.saved and result.why == "could not read the profile page"
    assert all(section.on_page is None for section in result.sections)


def test_a_score_is_recorded_in_the_index_as_a_score_not_a_run(monkeypatch, tmp_path):
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    settings = Settings(report_dir=str(tmp_path / "reports"))
    plan = ProfilePlan(headline="AI Engineer | LangChain", key_skills=["LangChain", "Python"])
    (tmp_path / "run").mkdir()
    result = profile_agent.score(FakeDriver("Resume headline AI Engineer | LangChain Key skills LangChain"),
                                 BOARD, plan, tmp_path / "run")
    report = profile_agent.keep_score(tmp_path / "run", BOARD, result, plan, settings)
    assert report.exists()
    latest = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())
    assert latest["naukri"]["kind"] == "score" and latest["naukri"]["saved"] is False
    assert latest["naukri"]["changed"] == 2 and latest["naukri"]["confirmed"] == 1
    assert latest["naukri"]["unconfirmed"] == ["Key skills"] and latest["naukri"]["missing"] == ["Python"]


def test_the_page_is_read_only_once_its_sections_have_rendered(monkeypatch):
    """Naukri draws the menu first and fetches the profile afterwards; a score read 3 seconds after the
    navigation saw only "Jobs Companies Services Search jobs here" and marked all 22 sections missing."""
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    header = "Jobs 1 Companies Services 1 Search jobs here 9 1 ;"
    full = (header + " 93% Soujanya Gupta Resume headline AI Engineer | LangChain " + "Key skills Python " * 20).strip()

    class Loading(FakeDriver):
        reads = 0

        def find_element(self, by, value):
            self.reads += 1
            return Body(header if self.reads < 3 else full)

    driver = Loading(header)
    assert profile_agent._read_profile(driver, BOARD) == full

    class Short(FakeDriver):
        reads = 0

        def find_element(self, by, value):
            self.reads += 1
            return Body(self.page)

    short = Short("a profile with little on it")
    assert profile_agent._read_profile(short, BOARD) == short.page
    assert short.reads == profile_agent._STABLE_READS + 1, "three unchanged reads end the wait; one more after unfolding"


# --- the page cannot be re-read after the run ----------------------------------------


def test_an_unreadable_page_after_the_run_is_said_so_and_not_sent_to_repair(monkeypatch, tmp_path):
    """The network dropped right after the agent: nothing on the page can be confirmed or denied."""
    saved, notes, asked = _staged(monkeypatch, tmp_path, ["Resume headline old Key skills Python"],
                                  [_HEADLINE_ONLY], _EDITS, opens=lambda d, url: False)
    assert not saved
    assert "the page could not be re-read; unconfirmed: Resume headline, Key skills" in notes
    assert "not done" not in notes, "absence from a page the bot never read is not evidence"
    assert len(asked) == 1, "a repair pass against a page the bot cannot read would only spend budget"
    report = (tmp_path / "run" / "profile-report.md").read_text()
    assert "the profile page could not be re-read after the run; unconfirmed: Resume headline, Key skills" in report
    record = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())["naukri"]
    assert record["confirmed"] == 0 and all(s["confirmed"] is None for s in record["sections"])


def test_the_page_is_read_once_more_before_giving_up_on_it(monkeypatch, tmp_path):
    """The first reload fails, the second (after a pause) works: the run is confirmed as usual."""
    attempts = []

    def opens(driver, url):
        attempts.append(url)
        return len(attempts) > 1

    page = "Resume headline " + HEADLINE + " Key skills Python LangChain FastAPI AWS Bedrock"
    saved, notes, asked = _staged(monkeypatch, tmp_path, [page], [_report()], _EDITS, opens=opens)
    assert saved and len(attempts) == 2 and len(asked) == 1
    assert "2/2 changed sections confirmed" in notes


def test_a_check_with_no_page_keeps_its_sections_unverified_and_skips_repair():
    result = profile_agent.ProfileCheck(saved=False, why="", page_read=False, sections=[
        Section(name="Resume headline", action="updated", after=HEADLINE)])
    assert result.needs_repair == []
    assert profile_agent._verdict(result) == (
        False, "the profile page could not be re-read after the run; unconfirmed: Resume headline")


# --- reading a board's page the way a person sees it ---------------------------------


def test_the_page_is_read_with_a_space_between_chips():
    """Selenium's body text runs Naukri's skill chips together ("PythonJavascriptMongoDB"); the live
    score found 1 of 22 sections because no chip could be matched."""
    class Chips(FakeDriver):
        def execute_script(self, script):
            return "Key skills Python Javascript MongoDB" if "createTreeWalker" in script else None

    assert profile_agent.page_text(Chips("Key skills PythonJavascriptMongoDB")) == \
        "Key skills Python Javascript MongoDB"
    assert profile_agent.page_text(FakeDriver("Key skills PythonJavascriptMongoDB")) == \
        "Key skills PythonJavascriptMongoDB", "a driver without scripts still gives the body text"
    spaced, run_together = "Key skills Python Javascript MongoDB", "Key skills PythonJavascriptMongoDB"
    assert profile_agent.verify("Python, Javascript, MongoDB", spaced, "Key skills") == (True, [])
    assert profile_agent.verify("Python, Javascript, MongoDB", run_together, "Key skills")[0] is False


def test_the_page_is_scrolled_a_screen_at_a_time_so_sections_that_render_on_sight_do(monkeypatch):
    """Naukri draws IT skills, projects, the summary and accomplishments only when they scroll into
    view; a jump to the bottom left them out of the text."""
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)

    class Recorder(FakeDriver):
        def __init__(self, page):
            super().__init__(page)
            self.scripts = []

        def execute_script(self, script):
            self.scripts.append(script)
            if "scrollBy" in script:
                return len([s for s in self.scripts if "scrollBy" in s]) >= 3
            return None

    driver = Recorder("page")
    profile_agent._load_all(driver)
    steps = [s for s in driver.scripts if "scrollBy" in s]
    assert len(steps) == 3 and "innerHeight" in steps[0]
    assert driver.scripts[-1] == "window.scrollTo(0, 0);"


def test_the_score_wants_the_company_name_the_board_shows_and_the_year_a_skill_was_last_used():
    """Naukri shows "Ethara AI", not the resume's "Ethara AI (formerly Green Rider Technology)", and
    lists an IT skill as a row "React - 2026 2 Years 6 Months" under the headings Last used / Experience."""
    plan = ProfilePlan(
        experience=[{"title": "Software Engineer", "company": "Ethara AI (formerly Green Rider Technology)",
                     "description": "Built 101 FastAPI mock services."}],
        it_skills=[{"name": "React", "years": "2.5", "last_used": "2026"}])
    sections = profile_agent.planned_sections(plan)
    assert [s.name for s in sections] == ["Employment: Ethara AI", "Job profile: Ethara AI", "IT skill: React"]
    assert sections[0].wanted == "Software Engineer, Ethara AI"
    page = ("IT skills Skills Version Last used Experience React - 2026 2 Years 6 Months editOneTheme "
            "Next.Js - 2026 2 Years 6 Months editOneTheme Employment Software Engineer editOneTheme Ethara AI Full-time")
    assert profile_agent.verify(sections[2].wanted, page, "IT skills") == (True, [])
    assert profile_agent.verify(sections[0].wanted, page, "Employment") == (True, [])


# --- each planned section is looked for where the board puts it ------------------------


def test_the_completeness_figure_is_not_the_promotion_banner():
    assert profile_agent.completeness_on("Flat 25% off on Naukri 360 Search jobs here 9 1 93 % Soujanya") == "93%"
    assert profile_agent.completeness_on("no figure here") == ""


def test_a_job_a_project_and_an_it_skill_are_looked_for_under_their_own_heading():
    """"IT skill: TypeScript" is not a heading on any page, so the check fell back to the whole page and
    found TypeScript among the key skills, "2 Years 6 Months" in another row and 2026 in the resume date."""
    assert profile_agent._locate("IT skill: Python") == ("IT skills", 0)
    assert profile_agent._locate("Employment: Ethara AI") == ("Ethara AI", profile_agent._LEAD_CHARS)
    assert profile_agent._locate("Job profile: Ethara AI") == ("Ethara AI", profile_agent._LEAD_CHARS)
    assert profile_agent._locate("Project: RideMate") == ("RideMate", 0)
    assert profile_agent._locate("Key skills") == ("Key skills", 0)
    page = ("Key skills editOneTheme Python Javascript TypeScript Fast API Resume Uploaded on Oct 26, 2026 "
            "Employment Software Engineer editOneTheme Ethara AI Full-time Mar 2024 to Oct 2026 "
            "IT skills Skills Version Last used Experience React - 2026 2 Years 6 Months editOneTheme "
            "Python - 2026 2 Years 6 Months editOneTheme")
    assert profile_agent.verify("TypeScript, 2.5 years, 2026", page,
                                *profile_agent._locate("IT skill: TypeScript")) == (False, ["TypeScript"])
    assert profile_agent.verify("Python, 2.5 years, 2026", page, *profile_agent._locate("IT skill: Python")) == (True, [])


def test_a_job_title_just_before_its_company_counts_for_that_job():
    """Naukri lists "Full Stack Developer editOneTheme Robotronix Engineering Tech": the title comes before
    the company the section is found by, and the second job sits past the first job's long profile."""
    page = ("Employment Add employment Software Engineer editOneTheme Ethara AI Full-time Mar 2024 to Oct 2026 "
            + "word " * 300
            + "Full Stack Developer editOneTheme Robotronix Engineering Tech Internship Feb 2021 to Apr 2021 "
            "Sole developer on Indore Carbonic, a carbon-product ordering platform.")
    assert profile_agent.verify("Full Stack Developer, Robotronix Engineering Tech", page,
                                *profile_agent._locate("Employment: Robotronix Engineering Tech")) == (True, [])
    assert profile_agent.verify("Sole developer on Indore Carbonic, a carbon-product ordering platform.", page,
                                *profile_agent._locate("Job profile: Robotronix Engineering Tech")) == (True, [])
    assert profile_agent.verify("Software Engineer, Ethara AI", page,
                                *profile_agent._locate("Employment: Ethara AI")) == (True, [])


def test_headings_match_in_the_singular_or_the_plural_and_links_are_checked_one_by_one():
    """Naukri heads the sections "Online profile" and "Certification"; the plan says "Online profiles" and
    "Certifications". A URL longer than a label used to turn the whole link list into prose."""
    page = ("Accomplishments Add Online profile Add link to online professional profiles LinkedIn editOneTheme "
            "https://linkedin.com/in/soujanya-gupta-0224621ba Portfolio editOneTheme https://soujanyalab.in "
            "Add Work sample GitHub editOneTheme https://github.com/GuptaSoujanya Duration: - "
            "Certification Add details of certifications AWS Academy Cloud Architecting editOneTheme AWS Academy "
            "AWS Academy Cloud Foundations editOneTheme AWS Academy")
    links = "https://soujanyalab.in, https://github.com/GuptaSoujanya, https://linkedin.com/in/soujanya-gupta-0224621ba"
    assert profile_agent._items(links) == links.split(", ")
    assert profile_agent.verify(links, page, "Online profiles") == (True, [])
    assert profile_agent.verify(links + ", https://x.dev/me", page, "Online profiles") == (True, ["https://x.dev/me"])
    assert profile_agent.verify("AWS Academy Cloud Architecting, AWS Academy Cloud Foundations", page,
                                "Certifications") == (True, [])
    assert profile_agent._windows("Key skills", "Key skill Python") and not profile_agent._windows("Key skills",
                                                                                                   "Keys killset")


# --- a board that spreads the profile over form pages ----------------------------------


def _wizard(monkeypatch, pages):
    class Wizard(FakeDriver):
        opened = []

        def get(self, url):
            self.opened.append(url)
            self.page = pages.get(url, "")

    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: (d.get(url), url in pages)[1])
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    return Wizard("")


def test_a_board_spread_over_form_pages_is_read_page_by_page(monkeypatch):
    """Hirist's My Profile lists roles and projects; the About text and the skills used sit on its
    registration steps, so a verifier that read one page called a saved summary NOT on the page."""
    from dataclasses import replace

    pages = {"https://b/myprofile": "Soujanya Gupta Professional Details Software Engineer Ethara AI",
             "https://b/registration/addAdditionalDetails": "About I build agent-evaluation systems for frontier models.",
             "https://b/registration/addWorkExperience": "Skills Used Python LangChain"}
    board = replace(BOARD, profile_url="https://b/myprofile",
                    profile_pages=("https://b/registration/addWorkExperience",
                                   "https://b/registration/addAdditionalDetails",
                                   "https://b/registration/gone"))
    driver = _wizard(monkeypatch, pages)
    text = profile_agent._read_profile(driver, board)
    assert driver.opened == ["https://b/myprofile", "https://b/registration/addWorkExperience",
                             "https://b/registration/addAdditionalDetails", "https://b/registration/gone"]
    assert profile_agent.verify("I build agent-evaluation systems for frontier models.", text, "About") == (True, [])
    assert profile_agent.verify("Python, LangChain", text, "Skills Used") == (True, [])
    assert "Software Engineer Ethara AI" in text, "a form page that cannot be opened does not void the rest"

    nothing = _wizard(monkeypatch, {"https://b/registration/addAdditionalDetails": "About all of it"})
    assert profile_agent._read_profile(nothing, board) == "", "without the profile page itself there is no read"


def test_a_sentence_written_around_the_value_is_checked_by_its_quoted_part():
    """The Hirist agent reported `after` as "After reload, My Profile shows '...'" for every section;
    the sentence is on no page, so eleven saved sections were recorded as NOT on it."""
    page = ("Professional Details Software Engineer Ethara AI (formerly Green Rider Technology) Mar 2024 to Present "
            "Educational Details B Tech / BE (Full Time) Medi-Caps University, Indore 2020 - 2024 "
            "Skills Used Python LangChain")
    told = "After reload, My Profile shows 'B Tech / BE (Full Time) — Medi-Caps University, Indore — 2020 - 2024'"
    assert profile_agent.verify(told, page)[0] is False
    assert profile_agent.confirm(Section(name="Education", action="already_ok", evidence=told), page) == (True, [])
    assert profile_agent._quoted("Hirist's rows couldn't hold it; she said \"fine\" and 'ok go'") == "fine, ok go"
    projects = Section(name="AI Projects", action="already_ok",
                       evidence="My Profile lists all three projects ending 'Role: Developer.' and 'Open project'")
    assert profile_agent.confirm(projects, page + " EvalAgentFlow ... Role: Developer. Python Open project") == (True, [])

    skills = Section(name="Key skills (Skills Used)", action="already_ok",
                     after="Skills Used chips on registration/addWorkExperience: Python, LangChain, RAG",
                     evidence="Python, LangChain, RAG")
    assert profile_agent.confirm(skills, page) == (False, ["RAG"]), "the claim that names its gaps wins"
    assert profile_agent.confirm(Section(name="Resume", action="updated"), page) == (None, [])


def test_the_page_the_verdict_rests_on_is_kept_in_the_run_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(common_browser, "safe_get", lambda d, url: True)
    monkeypatch.setattr(profile_agent, "_SETTLE_S", 0)
    monkeypatch.setattr(profile_agent.time, "sleep", lambda s: None)
    page = "Resume headline AI Engineer | LLM Evaluation | LangChain | Python Key skills LangChain FastAPI AWS Bedrock"
    result = profile_agent.check(FakeDriver(page), BOARD, Settings(), _report(), None, tmp_path)
    assert result.saved and (tmp_path / "page-after.txt").read_text() == page
