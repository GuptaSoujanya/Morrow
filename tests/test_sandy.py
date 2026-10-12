"""The Sandy screen: the commands it builds and the to-dos it reads."""
import asyncio
import datetime as dt

import pytest

from sandy import state
from sandy.app import CourseViewer, SandyApp, StudyScreen


def test_naukri_command_passes_only_the_options_you_set():
    assert state.naukri_command().argv[1:] == ("-m", "naukri_bot")
    command = state.naukri_command(dry_run=True, limit=5, answer_mode="propose", keywords=" LLM, RAG ")
    assert command.argv[1:] == (
        "-m", "naukri_bot", "--dry-run", "--limit", "5", "--answer-mode", "propose", "--keywords", "LLM, RAG",
    )
    assert command.label == "Practice run on Naukri"
    assert command.shown.startswith("venv/bin/python -m naukri_bot --dry-run")


def test_early_access_only_wins_over_early_access():
    argv = state.naukri_command(early_access=True, early_access_only=True).argv
    assert "--early-access-only" in argv and "--early-access" not in argv


def test_bad_limit_is_refused():
    with pytest.raises(ValueError):
        state.naukri_command(limit=0)


def test_external_needs_a_link():
    with pytest.raises(ValueError):
        state.external_command(url="")
    with pytest.raises(ValueError):
        state.external_command(url="jobs.example.com")
    argv = state.external_command(url="https://jobs.example.com/1", company="Acme", dry_run=True).argv
    assert argv[1:] == ("-m", "naukri_bot.external", "--url", "https://jobs.example.com/1", "--company", "Acme", "--dry-run")


def test_linkedin_post_takes_an_optional_draft():
    assert state.linkedin_command(mode="post").argv[1:] == ("-m", "linkedin_bot", "--post")
    assert state.linkedin_command(mode="post", draft="d.md").argv[-1] == "d.md"
    assert state.linkedin_command(mode="dry-run", draft="d.md").argv[1:] == ("-m", "linkedin_bot", "--dry-run")


def test_report_date_is_checked():
    assert state.report_command().argv[1:] == ("-m", "naukri_bot.report")
    assert state.report_command(day="2026-01-02").argv[-2:] == ("--date", "2026-01-02")
    with pytest.raises(ValueError):
        state.report_command(day="yesterday")


def test_resume_needs_an_existing_file(tmp_path):
    with pytest.raises(ValueError):
        state.resume_command(jd_file=str(tmp_path / "missing.txt"))
    jd = tmp_path / "jd.txt"
    jd.write_text("Build RAG systems")
    assert state.resume_command(jd_file=str(jd), company="Acme").argv[3:] == ("--tailor", str(jd), "--company", "Acme")


def test_reads_what_is_waiting_for_you(tmp_path):
    answers = tmp_path / "answers.txt"
    answers.write_text("# comment\nQ: Notice period?\nA: 15 days\n\nQ: Country*\nQ: Where do you live?\nA:\nQ: CTC?\nA:   \n")
    assert state.unanswered_questions(answers) == [(7, ["Country*", "Where do you live?"]), (9, ["CTC?"])]

    profile = tmp_path / "profile.yaml"
    profile.write_text('first_name: "Sam"\nctc: 16  # FILL\npan: null  # FILL only if asked\nnote: ""  # FILL\nother:  # FILL\n')
    assert state.blank_facts(profile) == [(3, "pan"), (4, "note"), (5, "other")]
    assert state.first_name(profile) == "Sam"

    sites = tmp_path / "company_sites.md"
    sites.write_text("# Applications\n\n## 2026-10-10 22:05 | Dscout | Applied AI Engineer\n- Status: needs you\n")
    assert state.waiting_company_sites(sites) == ["Dscout - Applied AI Engineer"]


def test_screen_starts_and_moves_between_sections():
    async def drive():
        app = SandyApp()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            assert app.query_one("#panels").current == "p-today"
            await pilot.press("2")
            await pilot.pause()
            assert app.query_one("#panels").current == "p-naukri"
            await pilot.press("0")
            await pilot.pause()
            assert app.query_one("#panels").current == "p-setup"
            assert "naukri_bot" in str(app.query_one("#nk-preview").render())

    asyncio.run(drive())


def make_course(root):
    for path in ("README.md", "news.md", "01-sd/README.md", "01-sd/01-basics.md", "02-dsa/01-arrays.md", "02-dsa/02-graphs.md"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(f"# {path}\n")
    (root / "_sidebar.md").write_text(
        "- [Home](README.md)\n- [News](news.md)\n\n"
        "- **1. System Design**\n  - [Overview](01-sd/README.md)\n  - [1.1 Basics](01-sd/01-basics.md)\n"
        "  - [1.2 Missing](01-sd/02-missing.md)\n\n"
        "- **2. DSA**\n  - [2.1 Arrays](02-dsa/01-arrays.md)\n  - [2.2 Graphs](02-dsa/02-graphs.md)\n"
    )
    return root


def test_course_modules_follow_the_sidebar(tmp_path):
    modules = state.course_modules(make_course(tmp_path))
    assert [(m.track, m.title) for m in modules] == [
        ("Start here", "Home"),
        ("1. System Design", "Overview"),
        ("1. System Design", "1.1 Basics"),
        ("2. DSA", "2.1 Arrays"),
        ("2. DSA", "2.2 Graphs"),
    ]
    assert modules[2].file == (tmp_path / "01-sd/01-basics.md").resolve()


def test_todays_module_matches_the_report_plan(tmp_path, monkeypatch):
    course = make_course(tmp_path)
    modules = state.course_modules(course)
    monkeypatch.setattr(state, "REPORTS", tmp_path / "reports")
    monkeypatch.setenv("COURSE_START_DATE", "2026-01-01")
    first = state.todays_module(modules, dt.date(2026, 1, 1), course)
    assert (first.module.title, first.number, first.total, first.tomorrow.title) == ("2.1 Arrays", 1, 3, "2.2 Graphs")
    later = state.todays_module(modules, dt.date(2026, 1, 3), course)
    assert later.module.title == "1.1 Basics" and not later.revising
    assert state.todays_module(modules, dt.date(2026, 1, 4), course).revising
    assert state.todays_module(modules, dt.date(2025, 12, 31), course) is None


def test_read_marks_are_saved(tmp_path):
    saved = tmp_path / "studied.json"
    assert state.studied(saved) == set()
    state.mark_studied("02-dsa/01-arrays.md", path=saved)
    state.mark_studied("01-sd/01-basics.md", path=saved)
    state.mark_studied("02-dsa/01-arrays.md", done=False, path=saved)
    assert state.studied(saved) == {"01-sd/01-basics.md"}
    saved.write_text("not json")
    assert state.studied(saved) == set()


def test_study_reads_modules_and_follows_links(tmp_path, monkeypatch):
    if not state.course_modules():
        pytest.skip("the course is not next to apply/")
    monkeypatch.setattr(state, "STUDIED", tmp_path / "studied.json")

    async def drive():
        app = SandyApp()
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.press("8")
            await pilot.pause()
            assert app.query_one("#panels").current == "p-study"
            app.study(app.modules[0])
            await pilot.pause()
            await app.workers.wait_for_complete()
            screen = app.screen
            assert isinstance(screen, StudyScreen) and screen.page == app.modules[0].file
            viewer = screen.query_one(CourseViewer)
            assert viewer.document.children

            viewer.post_message(CourseViewer.Follow("01-system-design/01-fundamentals.md"))
            await pilot.pause()
            fundamentals = screen.page
            assert fundamentals.name == "01-fundamentals.md"
            await pilot.press("n")
            await pilot.press("m")
            await pilot.pause()
            following = app.modules[[m.file for m in app.modules].index(fundamentals) + 1]
            assert screen.page == following.file
            assert state.studied() == {following.path}
            await pilot.press("b")
            await pilot.pause()
            assert screen.page == fundamentals
            await app.workers.wait_for_complete()
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is app.home

    asyncio.run(drive())


def test_greeting_follows_the_clock():
    assert state.greeting(dt.datetime(2026, 1, 1, 9)) == "Good morning"
    assert state.greeting(dt.datetime(2026, 1, 1, 20)) == "Good evening"
