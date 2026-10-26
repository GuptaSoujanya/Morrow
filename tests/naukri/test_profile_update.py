"""The profile updater, ported from the standalone naukri-auto-updater.

Three things must hold: the dot toggle round-trips, a missed slot is caught up
once rather than once per slot, and the headline is saved only when the editor
holds exactly the intended text and the profile page shows it afterwards.
"""

import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from naukri_bot import update_profile as up


# --- the dot toggle -----------------------------------------------------------


def test_adds_a_dot():
    assert up.toggle_trailing_dot("Backend Engineer") == "Backend Engineer."


def test_removes_the_dot():
    assert up.toggle_trailing_dot("Backend Engineer.") == "Backend Engineer"


def test_strips_trailing_whitespace_either_way():
    assert up.toggle_trailing_dot("Backend Engineer.  ") == "Backend Engineer"
    assert up.toggle_trailing_dot("Backend Engineer \n") == "Backend Engineer."


def test_two_toggles_round_trip():
    original = "Python | Django | AWS"
    assert up.toggle_trailing_dot(up.toggle_trailing_dot(original)) == original


# --- slot memory ----------------------------------------------------------------


def test_nothing_is_due_before_the_first_slot():
    assert up.due_slot(datetime(2026, 10, 10, 8, 59), {}) is None


def test_the_first_slot_is_due_after_nine():
    assert up.due_slot(datetime(2026, 10, 10, 9, 5), {}) == "2026-10-10 09:00"


def test_a_done_slot_is_not_repeated():
    state = {"2026-10-10 09:00": {"done": True, "attempts": 1}}
    assert up.due_slot(datetime(2026, 10, 10, 10, 0), state) is None


def test_a_laptop_that_slept_through_two_slots_catches_up_once():
    """Asleep through 09:00 and 13:30, awake at 14:10: one run, for 13:30."""
    assert up.due_slot(datetime(2026, 10, 10, 14, 10), {}) == "2026-10-10 13:30"


def test_a_slot_is_given_up_after_its_attempts():
    state = {
        "2026-10-10 18:30": {"done": False, "attempts": up.MAX_ATTEMPTS_PER_SLOT}
    }
    assert up.due_slot(datetime(2026, 10, 10, 19, 0), state) is None


def test_mark_records_the_attempt_and_then_the_success(tmp_path):
    path = tmp_path / "logs" / "profile_update.json"
    up.mark(path, "2026-10-10 09:00", done=False)
    up.mark(path, "2026-10-10 09:00", done=True)
    entry = json.loads(path.read_text())["2026-10-10 09:00"]
    assert entry["attempts"] == 1
    assert entry["done"] is True
    assert up.due_slot(datetime(2026, 10, 10, 9, 30), up.load_state(path)) is None


# --- the headline flow against a fake profile page -------------------------------


class _Element:
    def __init__(self, page, kind):
        self.page = page
        self.kind = kind

    def is_displayed(self):
        return True

    @property
    def text(self):
        if self.kind == "card":
            return "Resume headline\n%s" % self.page.headline
        return ""

    def get_attribute(self, name):
        if self.kind == "editor" and name == "value":
            return self.page.editor_value
        return None

    def click(self):
        self.page.click(self.kind)

    def send_keys(self, *keys):
        self.page.send_keys(keys)


class _FakeProfilePage:
    """The profile page as Selenium sees it: a headline card, an edit icon and,
    once the icon is clicked, the editor with its Save button."""

    capabilities = {"platformName": "mac"}

    def __init__(self, headline, mangle=False, save_does_not_stick=False):
        self.headline = headline
        self.mangle = mangle  # the page drops the last character written
        self.save_does_not_stick = save_does_not_stick
        self.editor_open = False
        self.editor_value = ""
        self.selected_all = False
        self.saves = 0
        self.navigations = []
        self.current_url = "about:blank"

    # Selenium surface ---------------------------------------------------------
    def get(self, url):
        self.navigations.append(url)
        self.current_url = url
        self.editor_open = False  # a reload discards an open editor

    def find_elements(self, by, selector):
        if selector == up._HEADLINE_CARD:
            return [_Element(self, "card")]
        if selector == up._EDIT_ICON:
            return [_Element(self, "edit")]
        if selector == up._EDITOR and self.editor_open:
            return [_Element(self, "editor")]
        if selector == up._SAVE_BUTTON and self.editor_open:
            return [_Element(self, "save")]
        return []

    def execute_script(self, script, *args):
        if "scrollIntoView" in script:
            return None
        if "arguments[0].click()" in script:
            return args[0].click()
        if "'value'" in script:  # the native setter fallback
            self._accept(args[1])
            return None
        raise AssertionError("unexpected script: %s" % script)

    # Page behaviour -------------------------------------------------------------
    def click(self, kind):
        if kind == "edit":
            self.editor_open = True
            self.editor_value = self.headline
            self.selected_all = False
        elif kind == "save":
            self.saves += 1
            if not self.save_does_not_stick:
                self.headline = self.editor_value
            self.editor_open = False

    def send_keys(self, keys):
        if keys[0] in (up.Keys.COMMAND, up.Keys.CONTROL):
            self.selected_all = True
        elif keys[0] == up.Keys.DELETE:
            if self.selected_all:
                self.editor_value = ""
                self.selected_all = False
        else:
            self._accept(self.editor_value + "".join(keys))

    def _accept(self, value):
        self.editor_value = value[:-1] if self.mangle else value


@pytest.fixture(autouse=True)
def _no_pauses(monkeypatch):
    monkeypatch.setattr(up, "human_pause", lambda *args, **kwargs: None)


def test_a_dry_run_opens_the_editor_but_saves_nothing():
    page = _FakeProfilePage("Backend Engineer")

    result = up.update_resume_headline(page, dry_run=True)

    assert result.saved is False
    assert result.after == "Backend Engineer."
    assert page.saves == 0
    assert page.headline == "Backend Engineer"
    assert not page.editor_open, "a dry run must not leave the editor open"


def test_a_real_run_saves_the_toggled_headline_and_verifies_it():
    page = _FakeProfilePage("Backend Engineer.")

    result = up.update_resume_headline(page)

    assert result.saved is True
    assert page.saves == 1
    assert page.headline == "Backend Engineer"
    assert page.navigations.count(up.PROFILE_URL) == 2, "verification needs a reload"


def test_a_mangled_editor_is_never_saved():
    """A headline is public: the exact text must be in the editor before Save."""
    page = _FakeProfilePage("Backend Engineer", mangle=True)

    with pytest.raises(up.ProfileUpdateError, match="nothing was saved"):
        up.update_resume_headline(page)

    assert page.saves == 0
    assert page.headline == "Backend Engineer"


def test_a_save_the_profile_page_does_not_show_is_an_error():
    page = _FakeProfilePage("Backend Engineer", save_does_not_stick=True)

    with pytest.raises(up.ProfileUpdateError, match="after reload"):
        up.update_resume_headline(page)


def test_a_removed_dot_that_is_still_shown_fails_verification():
    """Removing the dot makes the new headline a prefix of the old one, so its
    presence alone would pass even when the save did nothing."""
    page = _FakeProfilePage("Backend Engineer.", save_does_not_stick=True)

    with pytest.raises(up.ProfileUpdateError, match="after reload"):
        up.update_resume_headline(page)


def test_an_empty_headline_is_refused():
    page = _FakeProfilePage("   ")

    with pytest.raises(up.ProfileUpdateError, match="empty"):
        up.update_resume_headline(page)

    assert page.saves == 0


# --- the first login from a new browser profile ----------------------------------


class _Browser:
    def __init__(self):
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


def _first_login(monkeypatch, headless, answered):
    """Naukri answers the credentials with an OTP challenge; `answered` is
    whether a person types it in before the wait runs out."""
    from naukri_bot import auth
    from common import browser
    from common.models import LoginResult, Settings

    driver = _Browser()
    waited = []

    def _wait(d, timeout_s):
        waited.append(timeout_s)
        return answered

    monkeypatch.setattr(browser, "create_driver", lambda settings: driver)
    monkeypatch.setattr(
        auth,
        "ensure_logged_in",
        lambda d, s: LoginResult(ok=False, reason="captcha_or_otp", needs_manual=True),
    )
    monkeypatch.setattr(auth, "wait_for_manual_login", _wait)
    monkeypatch.setattr(
        up,
        "update_resume_headline",
        lambda d, dry_run=False: up.HeadlineUpdate("A", "A.", saved=not dry_run),
    )
    monkeypatch.setattr(up, "_screenshot", lambda d, s: None)
    return driver, waited, Settings(email="t@e.com", password="p", headless=headless)


def test_a_visible_window_waits_for_the_person_to_answer_the_otp(monkeypatch):
    driver, waited, settings = _first_login(monkeypatch, headless=False, answered=True)

    result = up.run_once(settings, dry_run=True)

    assert waited == [up.MANUAL_LOGIN_TIMEOUT_S]
    assert result.saved is False
    assert driver.quit_calls == 1


def test_an_unanswered_otp_still_needs_a_human(monkeypatch):
    driver, waited, settings = _first_login(monkeypatch, headless=False, answered=False)

    with pytest.raises(up._NeedsHuman, match="nobody finished"):
        up.run_once(settings, dry_run=True)

    assert driver.quit_calls == 1


def test_an_unregistered_headless_run_does_not_start_a_visible_manual_wait(monkeypatch):
    driver, waited, settings = _first_login(monkeypatch, headless=True, answered=True)

    with pytest.raises(up._NeedsHuman):
        up.run_once(settings, dry_run=True)

    assert waited == [], "Only a registered dashboard browser can offer remote sign-in assistance"
    assert driver.quit_calls == 1


# --- the scheduled whole-profile review -------------------------------------------


def test_a_review_is_due_when_none_was_ever_confirmed():
    assert up.review_due({}, datetime(2026, 10, 26, 9, 5), 1)


def test_a_review_confirmed_today_is_not_repeated_today():
    state = {"review": {"date": "2026-10-26", "saved": True, "attempts": 1}}
    assert not up.review_due(state, datetime(2026, 10, 26, 13, 35), 1)
    assert up.review_due(state, datetime(2026, 10, 27, 9, 5), 1)


def test_the_review_interval_is_counted_in_days_since_the_last_confirmed_one():
    state = {"review": {"date": "2026-10-24", "saved": True, "attempts": 1}}
    assert not up.review_due(state, datetime(2026, 10, 26, 9, 5), 3)
    assert up.review_due(state, datetime(2026, 10, 27, 9, 5), 3)


def test_zero_days_keeps_the_schedule_to_the_headline():
    assert not up.review_due({}, datetime(2026, 10, 26, 9, 5), 0)


def test_a_failed_review_is_retried_at_the_next_slot_but_not_all_day(tmp_path):
    path = tmp_path / "profile_update.json"
    now = datetime(2026, 10, 26, 9, 10)
    up.mark_review(path, saved=False, why="the agent gave no report", now=now)
    assert up.review_due(up.load_state(path), datetime(2026, 10, 26, 13, 35), 1)
    up.mark_review(path, saved=False, why="budget", now=datetime(2026, 10, 26, 13, 40))
    state = up.load_state(path)
    assert state["review"]["attempts"] == 2 and state["review"]["why"] == "budget"
    assert not up.review_due(state, datetime(2026, 10, 26, 18, 35), 1)
    assert up.review_due(state, datetime(2026, 10, 27, 9, 5), 1), "a new day gets fresh attempts"
    up.mark_review(path, saved=True, why="confirmed", now=datetime(2026, 10, 27, 9, 20))
    assert up.load_state(path)["review"] == {"date": "2026-10-27", "saved": True, "attempts": 1,
                                             "why": "confirmed", "last": "2026-10-27T09:20:00"}


def test_a_review_that_blows_up_does_not_undo_the_saved_headline(monkeypatch):
    from common.models import Settings

    monkeypatch.setattr(up, "with_session", lambda settings, work: work(object()))
    monkeypatch.setattr(up, "update_resume_headline", lambda d, dry_run=False: up.HeadlineUpdate("A", "A.", saved=True))
    monkeypatch.setattr(up, "_screenshot", lambda d, s: None)

    def explode(driver, settings, profile, dry_run=False):
        raise RuntimeError("the browser exposes no DevTools address")

    monkeypatch.setattr(up, "review_profile", explode)
    result = up.run_once(Settings(email="t@e.com", password="p"), profile=object())
    assert result.saved is True
    assert result.review_error == "the profile review failed: the browser exposes no DevTools address"


def test_score_reads_the_profile_prints_the_score_and_records_it(monkeypatch, tmp_path, capsys):
    """--score: the plan from the resume is checked against the live page, nothing is saved."""
    from common import profile as profile_module
    from common import profile_plan
    from common.models import Settings
    from common.profile_plan import AtsReport, ProfilePlan
    from sites_bot import browser_agent, profile_agent
    from sites_bot.profile_agent import ProfileCheck, Section

    plan = ProfilePlan(headline="AI Engineer | LangChain", key_skills=["LangChain", "Python"],
                       ats=AtsReport(score=90, keyword_score=84, structure_score=100))
    monkeypatch.setattr(profile_module, "load_profile", lambda settings: object())
    monkeypatch.setattr(profile_plan, "plan_for", lambda profile, settings: plan)
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")
    scored = ProfileCheck(saved=False, why="1 of 2 planned sections are on the profile; not on it: Key skills",
                          completeness_after="93%",
                          sections=[Section(name="Resume headline", action="checked",
                                            after="AI Engineer | LangChain", on_page=True),
                                    Section(name="Key skills", action="checked", after="LangChain, Python",
                                            on_page=False, missing=["LangChain", "Python"])])
    seen = {}

    def session(settings, work):
        seen["driver"] = object()
        return scored

    monkeypatch.setattr(up, "with_session", session)
    monkeypatch.setattr(profile_agent, "score", lambda driver, board, plan, workdir: scored)
    settings = Settings(email="t@e.com", password="p", report_dir=str(tmp_path / "reports"))

    assert up.score_profile(settings) == up.EXIT_OK
    out = capsys.readouterr().out
    assert "Naukri profile score" in out and "Completeness shown by Naukri: 93%" in out
    assert "Resume ATS: 90/100" in out and "NO  Key skills" in out
    assert "1 of 2 planned sections are on the profile" in out
    latest = json.loads((tmp_path / "reports" / "profile" / "latest.json").read_text())
    assert latest["naukri"]["kind"] == "score" and latest["naukri"]["confirmed"] == 1


def test_score_is_its_own_command_and_touches_no_slot(monkeypatch):
    args = up.parse_args(["--score"])
    assert args.score and not args.review and not args.if_due
    from common.models import Settings

    monkeypatch.setattr(up, "score_profile", lambda settings: 42)
    monkeypatch.setattr(up, "due_slot", lambda now, state: pytest.fail("a score must not touch the slots"))
    from common import config

    monkeypatch.setattr(config, "load_settings", lambda env, overrides: Settings(email="t@e.com", password="p"))
    assert up.main(["--score"]) == 42


def test_a_score_that_cannot_open_the_browser_fails_cleanly(monkeypatch, tmp_path):
    """The shared automation browser was busy with another board; the score used to die with a traceback."""
    from common import profile as profile_module
    from common import profile_plan
    from common.models import Settings
    from common.profile_plan import ProfilePlan
    from sites_bot import browser_agent

    monkeypatch.setattr(profile_module, "load_profile", lambda settings: object())
    monkeypatch.setattr(profile_plan, "plan_for", lambda profile, settings: ProfilePlan(headline="x"))
    monkeypatch.setattr(browser_agent, "workdir_for", lambda settings, label: tmp_path / "run")

    def busy(settings, work):
        raise ValueError("This automation browser is already open. Close it before starting a run.")

    monkeypatch.setattr(up, "with_session", busy)
    assert up.score_profile(Settings(email="t@e.com", password="p")) == up.EXIT_FAILED
