"""The reading material in the repository's user/research/: every week, resume file and link is sound.

The suite's conftest moves each test into a temporary folder, so the real
user/research/ is found from this file's own location.
"""

import pytest

from pathlib import Path

from pipeline import content, learning

RESEARCH = Path(__file__).resolve().parents[2] / "user" / "research"

pytestmark = pytest.mark.skipif(not (RESEARCH / "learning" / "weeks").is_dir(), reason="no user/research/ here")


@pytest.mark.parametrize("week", range(1, learning.week_of(learning.LAST_DAY) + 1))
def test_every_week_has_its_days_parts_and_working_links(week):
    assert content.week_problems(week, RESEARCH / "learning") == []


def test_the_plan_covers_all_90_days_once():
    days = []
    for week in range(1, learning.week_of(learning.LAST_DAY) + 1):
        days += sorted(learning.split_days(learning.week_path(week, RESEARCH / "learning").read_text()))
    assert days == list(range(1, learning.LAST_DAY + 1))


def test_every_resume_area_has_a_complete_study_file():
    assert content.resume_problems(RESEARCH / "resume-learning") == []


@pytest.mark.parametrize("name", ["tech-radar.md", "companies-to-watch.md", "learning/README.md",
                                  "learning/today.md", "TODAY.md"])
def test_reading_pages_have_working_links(name):
    path = RESEARCH / name
    if not path.exists():
        pytest.skip("%s not written yet" % name)
    assert content.link_problems(path) == []


def test_every_briefing_day_on_disk_is_complete():
    days = sorted(p.name for p in (RESEARCH / "daily").glob("20??-??-??") if p.is_dir())
    if not days:
        pytest.skip("no briefing written yet")
    from datetime import date

    for day in days:
        problems = content.day_problems(date.fromisoformat(day), RESEARCH / "learning", RESEARCH / "daily")
        assert [p for p in problems if "learning/today.md" not in p] == [], day


COURSE = RESEARCH.parent.parent / "database" / "course"
course_here = pytest.mark.skipif(not (COURSE / "_sidebar.md").exists(), reason="no database/course/ here")


@course_here
def test_the_course_site_is_whole_and_the_plan_uses_its_tracks():
    from pipeline import course

    assert course.problems(COURSE, RESEARCH / "learning") == []


@course_here
@pytest.mark.parametrize("day", range(1, learning.LAST_DAY + 1))
def test_each_days_course_reading_links_back_to_the_course(day, tmp_path):
    from pipeline import course

    week = learning.week_path(learning.week_of(day), RESEARCH / "learning")
    section = learning.split_days(week.read_text())[day]
    notes = tmp_path / "notes.md"
    notes.write_text(course.reading(day, section, week.parent, tmp_path, RESEARCH / "learning", COURSE))
    assert content.link_problems(notes) == []
    assert "**Extra from the course**" in notes.read_text()


@course_here
def test_over_90_days_every_course_chapter_comes_up():
    from pipeline import course

    seen = set(course.linked_by_plan(RESEARCH / "learning", COURSE))
    seen |= {course.extra_chapter(day, RESEARCH / "learning", COURSE).resolve()
             for day in range(1, learning.LAST_DAY + 1)}
    assert [path for path in course.chapters(COURSE) if path.resolve() not in seen] == []
