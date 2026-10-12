"""Other job boards: cards read the same way everywhere, applied only when the board says so."""

import os
import re
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sites_bot import browser_agent
from sites_bot import external as ext
from sites_bot import platforms as pf
from common.ledger import Ledger
from common.models import ApplyStatus, JobPosting, Profile, ScoredJob, Settings

HIRIST = pf.BOARDS["hirist"]
INSTAHYRE = pf.BOARDS["instahyre"]


def test_hirist_cards_read_into_jobs():
    job = pf.card_to_job(
        HIRIST,
        "https://www.hirist.tech/j/eucloid-ai-engineer-1677001",
        "Eucloid - AI Engineer",
        ["Eucloid - AI Engineer", "3 - 6 yrs", "Chennai", "3.8", "23+ Reviews", "Artificial Intelligence",
         "Generative AI", "+1", "Posted 5 days ago"],
    )
    assert job.job_id == "hirist:1677001"
    assert (job.company, job.title, job.experience, job.location) == ("Eucloid", "AI Engineer", "3 - 6 yrs", "Chennai")
    assert job.tags == ["Artificial Intelligence", "Generative AI"]
    assert (job.posted_label, job.posted_days_ago) == ("5 days ago", 5.0)


def test_instahyre_cards_keep_the_company_blurb_as_description():
    blurb = ("Swimlane is a tech-led startup that provides cloud-scale, low-code security automation for "
             "security-forward organizations worldwide.")
    job = pf.card_to_job(
        INSTAHYRE,
        "https://www.instahyre.com/job-427622-ai-engineer-ai-ml-at-swimlane-work-from-home/",
        "Swimlane - AI Engineer (AI / ML)",
        ["Swimlane - AI Engineer (AI / ML)", "Work From Home", "Founded in 2014", "200-500 employees",
         "View job »", blurb, "Machine Learning", "Agentic AI"],
    )
    assert job.job_id == "instahyre:427622"
    assert (job.company, job.title, job.location) == ("Swimlane", "AI Engineer (AI / ML)", "Work From Home")
    assert job.description == blurb
    assert job.tags == ["Machine Learning", "Agentic AI"]
    assert job.posted_days_ago is None


def test_search_pages_follow_each_boards_address_scheme():
    assert pf.search_url(HIRIST, "LLM evaluation") == "https://www.hirist.tech/search/llm-evaluation"
    assert pf.search_url(INSTAHYRE, "AI Engineer") == "https://www.instahyre.com/ai-engineer-jobs/"


def test_boards_come_from_the_flag_then_the_setting():
    settings = Settings(platforms="instahyre, nope")
    assert [b.name for b in pf.chosen_boards(None, settings)] == ["instahyre"]
    assert [b.name for b in pf.chosen_boards(["hirist"], settings)] == ["hirist"]
    assert {b.name for b in pf.chosen_boards(["all"], settings)} == set(pf.BOARDS)


# ---------------------------------------------------------------------------
# One job
# ---------------------------------------------------------------------------


class _Switch:
    def window(self, handle):
        pass


class _Driver:
    current_window_handle = "board"
    window_handles = ["board"]
    switch_to = _Switch()


@pytest.fixture
def board_page(monkeypatch, tmp_path):
    """A board job page whose behaviour each test sets: what the Apply click leads to, and the reload."""
    state = {"applied_before": False, "landed": "applied", "verified": True, "form": (True, ["Phone"], []),
             "clicks": 0, "buttons": ["Apply"]}
    monkeypatch.setattr(pf, "safe_get", lambda driver, url: True)
    monkeypatch.setattr(pf, "PAGE_WAIT_S", 0)
    monkeypatch.setattr(pf, "human_pause", lambda *a: None)
    monkeypatch.setattr(pf, "shows_applied", lambda driver, board: state["applied_before"])
    monkeypatch.setattr(pf, "signed_out", lambda driver, board: False)
    monkeypatch.setattr(pf, "_controls", lambda driver, pattern: list(state["buttons"]) if "apply" in pattern else [])
    monkeypatch.setattr(pf, "_field_labels", lambda driver: set())
    monkeypatch.setattr(pf, "_wait_after_click", lambda *a: state["landed"])
    monkeypatch.setattr(pf, "_verified", lambda driver, board, job: state["verified"])
    monkeypatch.setattr(pf, "answer_form", lambda *a: state["form"])
    monkeypatch.setattr(ext, "_page_text", lambda driver: "AI Engineer at Acme")
    monkeypatch.setattr(ext, "_control_text", lambda control: control)
    monkeypatch.setattr(ext, "_current_url", lambda driver: "https://www.hirist.tech/j/acme-ai-engineer-1")
    monkeypatch.setattr(ext, "return_to", lambda *a: None)
    monkeypatch.setattr(pf, "_names_from_page", lambda *a: None)

    def click(driver, element):
        state["clicks"] += 1

    monkeypatch.setattr(ext, "_click", click)
    browser_agent.reset()
    return state


def _settings(tmp_path, **values):
    return Settings(data_dir=str(tmp_path / "data" / "inputs"), report_dir=str(tmp_path / "reports"), **values)


def _job(number="1"):
    return JobPosting(job_id="hirist:%s" % number, url="https://www.hirist.tech/j/acme-ai-engineer-%s" % number,
                      title="AI Engineer", company="Acme")


def _apply(tmp_path, dry_run=False, **values):
    return pf.apply_to(_Driver(), HIRIST, _job(), Profile(full_name="Jane"), None, _settings(tmp_path, **values),
                       None, dry_run)


def test_a_one_click_apply_counts_only_after_the_reload_shows_applied(board_page, tmp_path):
    result = _apply(tmp_path)
    assert result.status == ApplyStatus.APPLIED_PLATFORM
    assert result.quota_consumed is False
    assert board_page["clicks"] == 1

    board_page["verified"] = False
    result = _apply(tmp_path)
    assert result.status == ApplyStatus.ERROR
    assert result.detail.startswith("Submit was clicked")


def test_a_dry_run_finds_the_button_and_clicks_nothing(board_page, tmp_path):
    result = _apply(tmp_path, dry_run=True)
    assert result.status == pf.DRY_RUN
    assert "'Apply'" in result.detail
    assert board_page["clicks"] == 0


def test_a_job_already_applied_to_is_left_alone(board_page, tmp_path):
    board_page["applied_before"] = True
    assert _apply(tmp_path).status == ApplyStatus.ALREADY_APPLIED
    assert board_page["clicks"] == 0


def test_the_boards_own_form_is_answered_then_verified(board_page, tmp_path):
    board_page["landed"] = "form"
    result = _apply(tmp_path)
    assert result.status == ApplyStatus.APPLIED_PLATFORM
    assert result.questions_answered == 1


def test_a_form_question_without_an_answer_goes_to_her_list(board_page, tmp_path):
    board_page["landed"] = "form"
    board_page["form"] = (False, ["Phone"], ["Notice period buyout amount*"])
    result = _apply(tmp_path)
    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert "Notice period buyout amount*" in result.detail
    entry = ext.pending_company_sites(_settings(tmp_path))[0]
    assert entry["company"] == "Acme" and entry["left for you"] == "Notice period buyout amount*"


def test_a_company_site_redirect_is_listed_when_company_sites_are_off(board_page, tmp_path):
    board_page["landed"] = "site"
    result = _apply(tmp_path, external_apply=False)
    assert result.status == ApplyStatus.EXTERNAL_SKIPPED
    assert "EXTERNAL_APPLY is off" in ext.pending_company_sites(_settings(tmp_path))[0]["why"]


def test_no_apply_button_is_reported_with_what_was_there(board_page, tmp_path, monkeypatch):
    board_page["buttons"] = []
    monkeypatch.setattr(ext, "_visible_controls", lambda driver: ["Save", "Share"])
    result = _apply(tmp_path)
    assert result.status == ApplyStatus.NO_APPLY_BUTTON
    assert "Save, Share" in result.detail


# ---------------------------------------------------------------------------
# A run on one board
# ---------------------------------------------------------------------------


def test_a_board_run_applies_up_to_the_limit_without_touching_naukri_quota(board_page, tmp_path, monkeypatch):
    from naukri_bot import ranking
    from common import report

    jobs = [_job(str(n)) for n in range(1, 5)]
    monkeypatch.setattr(pf, "collect", lambda driver, board, keywords, limit: jobs)
    monkeypatch.setattr(ranking, "rank", lambda profile, found, client, settings: [
        ScoredJob(job=job, score=80.0 - i, reasons=[]) for i, job in enumerate(found)])
    monkeypatch.setattr("naukri_bot.cli._pause_between_applications", lambda settings: None)
    settings = _settings(tmp_path, db_path=str(tmp_path / "t.db"), min_score=50.0)
    ledger = Ledger(settings.db_path)

    summary = pf.run_board(_Driver(), HIRIST, settings, Profile(full_name="Jane"), ledger, None, None, 2, False, None)

    assert (summary.collected, summary.applied, summary.attempted) == (4, 2, 2)
    assert ledger.has_applied("hirist:1") and ledger.has_applied("hirist:2") and not ledger.has_applied("hirist:3")
    assert ledger.quota_used() == 0
    ledger.close()
    text = report.build_report(settings, date.today())
    assert "- Applied: 0 on Naukri, 2 on other job boards, 0 on company sites" in text
    assert "| Hirist | [job](https://www.hirist.tech/j/acme-ai-engineer-1) |" in text


def test_a_signed_out_board_stops_before_collecting(board_page, tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "signed_out", lambda driver, board: True)
    monkeypatch.setattr(pf, "collect", lambda *a: pytest.fail("collected while signed out"))
    settings = _settings(tmp_path, db_path=str(tmp_path / "t.db"))
    ledger = Ledger(settings.db_path)
    assert pf.run_board(_Driver(), HIRIST, settings, Profile(), ledger, None, None, 2, False, None).collected == 0
    ledger.close()


def test_a_similar_job_called_applied_scientist_is_not_an_applied_marker():
    import re

    assert re.search(HIRIST.applied, "Applied", re.I)
    assert re.search(HIRIST.applied, "Applied on 10 Oct", re.I)
    assert not re.search(HIRIST.applied, "Applied Scientist - Agentic AI 4 - 11 yrs Mumbai Posted 1 week ago", re.I)


def test_the_job_page_title_gives_the_real_company():
    class _Titled:
        title = "LLM Engineer - RAG/Prompt Engineering - HiringBlaze | hirist.tech"

    job = JobPosting(job_id="hirist:1", url="u", title="RAG/Prompt Engineering", company="LLM Engineer")
    pf._names_from_page(_Titled(), HIRIST, job)
    assert (job.title, job.company) == ("LLM Engineer - RAG/Prompt Engineering", "HiringBlaze")


def test_a_page_title_that_repeats_the_company_keeps_it_once():
    class _Titled:
        title = "SMARTnCODE - Generative AI Engineer/LLM Integration Specialist - SMARTnCODE | hirist.tech"

    job = JobPosting(job_id="hirist:2", url="u", title="Generative AI Engineer", company="SMARTnCODE")
    pf._names_from_page(_Titled(), HIRIST, job)
    assert (job.title, job.company) == ("Generative AI Engineer/LLM Integration Specialist", "SMARTnCODE")


class _ClosedDriver(_Driver):
    @property
    def window_handles(self):
        from selenium.common.exceptions import InvalidSessionIdException

        raise InvalidSessionIdException("invalid session id: the browser has closed the connection")


def test_a_browser_that_closed_mid_run_is_reopened_and_the_run_goes_on(board_page, tmp_path, monkeypatch):
    from naukri_bot import ranking

    jobs = [_job(str(n)) for n in range(1, 4)]
    monkeypatch.setattr(pf, "collect", lambda driver, board, keywords, limit: jobs)
    monkeypatch.setattr(ranking, "rank", lambda profile, found, client, settings: [
        ScoredJob(job=job, score=80.0 - i, reasons=[]) for i, job in enumerate(found)])
    monkeypatch.setattr("naukri_bot.cli._pause_between_applications", lambda settings: None)
    used = []
    real_apply = pf.apply_to
    monkeypatch.setattr(pf, "apply_to", lambda driver, *a: used.append(driver) or real_apply(driver, *a))
    settings = _settings(tmp_path, db_path=str(tmp_path / "t.db"), min_score=50.0)
    ledger = Ledger(settings.db_path)
    fresh = _Driver()

    summary = pf.run_board(_ClosedDriver(), HIRIST, settings, Profile(full_name="Jane"), ledger, None, None, 2, False,
                           None, restart=lambda: fresh)

    assert summary.applied == 2 and used == [fresh, fresh]
    ledger.close()


def test_without_a_way_to_reopen_the_browser_the_board_stops(board_page, tmp_path, monkeypatch):
    from naukri_bot import ranking

    monkeypatch.setattr(pf, "collect", lambda driver, board, keywords, limit: [_job("1")])
    monkeypatch.setattr(ranking, "rank", lambda profile, found, client, settings: [
        ScoredJob(job=job, score=80.0, reasons=[]) for job in found])
    monkeypatch.setattr(pf, "apply_to", lambda *a: pytest.fail("applied without a browser"))
    settings = _settings(tmp_path, db_path=str(tmp_path / "t.db"), min_score=50.0)
    ledger = Ledger(settings.db_path)

    summary = pf.run_board(_ClosedDriver(), HIRIST, settings, Profile(full_name="Jane"), ledger, None, None, 2, False,
                           None, restart=lambda: None)

    assert summary.attempted == 0
    ledger.close()


def test_hirists_applied_address_counts_as_applied(monkeypatch):
    monkeypatch.setattr(pf, "shows_applied", lambda driver, board: False)
    monkeypatch.setattr(pf, "_field_labels", lambda driver: set())
    monkeypatch.setattr(ext, "_current_url", lambda driver: "https://www.hirist.tech/job/applied?jobId=1677301")
    assert pf._wait_after_click(_Driver(), HIRIST, ["board"], 1.0, set()) == "applied"


def test_instahyres_application_sent_button_is_the_applied_marker():
    instahyre = pf.BOARDS["instahyre"]
    assert re.search(instahyre.applied, "Application sent!", re.I)
    assert not re.search(instahyre.applied, "Apply", re.I)


def test_an_instahyre_page_title_gives_title_and_company():
    class _Titled:
        title = "Staff LLM Data Scientist job at TIFIN - Instahyre"

    job = JobPosting(job_id="instahyre:1", url="u", title="Staff", company="?")
    pf._names_from_page(_Titled(), pf.BOARDS["instahyre"], job)
    assert (job.title, job.company) == ("Staff LLM Data Scientist", "TIFIN")


def test_two_applications_the_board_never_confirmed_stop_the_board(board_page, tmp_path, monkeypatch):
    from naukri_bot import ranking

    jobs = [_job(str(n)) for n in range(1, 5)]
    monkeypatch.setattr(pf, "collect", lambda driver, board, keywords, limit: jobs)
    monkeypatch.setattr(ranking, "rank", lambda profile, found, client, settings: [
        ScoredJob(job=job, score=80.0 - i, reasons=[]) for i, job in enumerate(found)])
    board_page["landed"], board_page["verified"] = "applied", False
    settings = _settings(tmp_path, db_path=str(tmp_path / "t.db"), min_score=50.0)
    ledger = Ledger(settings.db_path)

    summary = pf.run_board(_Driver(), HIRIST, settings, Profile(full_name="Jane"), ledger, None, None, 2, False, None)

    assert (summary.attempted, summary.errors, summary.applied) == (2, 2, 0)
    ledger.close()


class _MarkerPage(_Driver):
    """What _MARKERS_SCRIPT returns: the texts of shown controls outside the navigation."""

    def __init__(self, texts):
        self.texts = texts

    def execute_script(self, script, *args):
        assert script == pf._MARKERS_SCRIPT
        return self.texts


def test_a_disabled_application_sent_button_shows_the_job_applied():
    instahyre = pf.BOARDS["instahyre"]
    assert pf.shows_applied(_MarkerPage(["Application sent!"]), instahyre)
    assert not pf.shows_applied(_MarkerPage(["Apply"]), instahyre)


def test_the_applied_tab_in_the_top_bar_is_not_counted():
    assert "nav, header" in pf._MARKERS_SCRIPT and "[role='navigation']" in pf._MARKERS_SCRIPT
    assert not pf.shows_applied(_MarkerPage(["Save", "Apply"]), pf.BOARDS["wellfound"])


def test_cutshort_cards_read_company_meta_line_and_date():
    cutshort = pf.BOARDS["cutshort"]
    href = "https://cutshort.io/job/Data-Scientist-Agentic-AI-Bengaluru-VY-SYSTEMS-PRIVATE-LIMITED-Z13Xrplb"
    lines = ["Data Scientist – Agentic AI", "at VY SYSTEMS PRIVATE LIMITED", "Posted by Vaishnavi E", "Apply now",
             "Bengaluru (Bangalore), Hyderabad · 5 - 8 years · ₹2L - ₹15L / yr · Profitable · Posted 7 Oct 2026",
             "Python", "GenAI/LLM", "+8 more"]
    job = pf.card_to_job(cutshort, href, "Data Scientist – Agentic AI", lines)
    assert job.job_id == "cutshort:Z13Xrplb"
    assert (job.title, job.company) == ("Data Scientist – Agentic AI", "VY SYSTEMS PRIVATE LIMITED")
    assert (job.location, job.experience, job.posted_label) == ("Bengaluru (Bangalore), Hyderabad", "5 - 8 years", "7 Oct 2026")
    assert job.posted_days_ago is not None and job.tags == ["Profitable", "Python", "GenAI/LLM"]
    assert re.search(cutshort.apply, "Apply to this job", re.I) and not re.search(cutshort.apply, "Apply now", re.I)


def test_a_cutshort_page_title_gives_title_and_company():
    class _Titled:
        title = "VY SYSTEMS PRIVATE LIMITED is hiring Data Scientist – Agentic AI job in Bengaluru (Bangalore), Hyderabad | Cutshort"

    job = JobPosting(job_id="cutshort:1", url="u", title="?", company="?")
    pf._names_from_page(_Titled(), pf.BOARDS["cutshort"], job)
    assert (job.title, job.company) == ("Data Scientist – Agentic AI", "VY SYSTEMS PRIVATE LIMITED")


def test_cutshorts_second_apply_is_clicked_and_checked_on_its_own_job_view(board_page, tmp_path, monkeypatch):
    cutshort = pf.BOARDS["cutshort"]
    view = "https://cutshort.io/profile/all-jobs?jobid=6ac4"
    board_page["buttons"] = ["Apply to this job"]
    monkeypatch.setattr(pf, "_controls", lambda driver, pattern: (
        ["Apply now"] if pattern == cutshort.second_apply else list(board_page["buttons"]) if "apply" in pattern else []))
    monkeypatch.setattr(ext, "_current_url", lambda driver: view)
    checked = []
    monkeypatch.setattr(pf, "_verified", lambda driver, board, job: checked.append(job.url) or True)
    settings = _settings(tmp_path)
    job = JobPosting(job_id="cutshort:D0w2CmQz", url="https://cutshort.io/job/Python-AI-Developer-Wissen-D0w2CmQz",
                     title="Python + AI Developer", company="Wissen Technology")

    result = pf.apply_to(_Driver(), cutshort, job, Profile(full_name="Jane"), None, settings, None, False)

    assert result.status == ApplyStatus.APPLIED_PLATFORM
    assert board_page["clicks"] == 2 and checked == [view]
