"""Company-site applications: fill what is known, never submit a half-filled form.

The fakes stand in for an employer's career page. The form is read through the
same one-round-trip script the real page runs, and every write goes through the
element, so the tests see exactly what a recruiter would receive.
"""

import os
import sys
from types import SimpleNamespace

import pytest
from selenium.common.exceptions import NoSuchWindowException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import accounts as acc
from naukri_bot import apply as apply_module
from naukri_bot import external as ext
from naukri_bot.answers import AnswerEngine
from naukri_bot.ledger import Ledger
from naukri_bot.models import (
    Answer,
    AnswerResolution,
    AnswerSource,
    ApplyStatus,
    JobPosting,
    Profile,
    Settings,
)


PROFILE = Profile(
    full_name="Jane Doe",
    email="jane@example.com",
    phone="+91 90000 00000",
    current_location="Indore",
    extra_facts={"linkedin_url": "https://linkedin.com/in/jane", "country": "India"},
)
JOB = JobPosting(job_id="j1", url="https://www.naukri.com/job-listings-j1", title="LangChain Engineer", company="Acme")
GREENHOUSE = "https://job-boards.greenhouse.io/acme/jobs/1"
ANSWERS = {
    "How did you hear about this job?": "Naukri",
    "Are you legally authorized to work in India?": "Yes",
}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ext, "human_type", lambda element, text: element.send_keys(text))
    monkeypatch.setattr(ext, "human_pause", lambda *args, **kwargs: None)
    monkeypatch.setattr(ext, "POLL_S", 0)
    for name in ("OPEN_WAIT_S", "FORM_WAIT_S", "FILE_WAIT_S", "CONFIRM_WAIT_S", "GOOGLE_WAIT_S", "OPTION_WAIT_S"):
        monkeypatch.setattr(ext, name, 0.05)
    monkeypatch.setattr(acc, "POLL_S", 0)
    for name in ("SIGN_IN_WAIT_S", "FORM_WAIT_S"):
        monkeypatch.setattr(acc, name, 0.05)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Control:
    def __init__(self, kind, label, required=False, group="", name="", options=None, value="", accept=""):
        self.kind = kind
        self.label = label
        self.required = required
        self.group = group
        self.name = name
        self.options = options or []
        self.value = value
        self.accept = accept
        self.checked = False
        self.text = ""

    def as_dict(self):
        return {
            "el": self,
            "kind": self.kind,
            "name": self.name,
            "label": self.label,
            "required": self.required,
            "group": self.group,
            "value": "" if self.kind == "select" else self.value,
            "options": list(self.options),
            "role": "",
            "autocomplete": "",
            "checked": self.checked,
            "accept": self.accept,
        }

    def send_keys(self, text):
        if self.kind == "file":
            self.value = text
        elif Keys.DELETE in text:
            self.value = ""
        elif text and text[0] in (Keys.COMMAND, Keys.CONTROL, Keys.ENTER):
            return
        else:
            self.value += text

    def get_attribute(self, name):
        return {"value": self.value, "type": self.kind}.get(name, "")

    def click(self):
        if self.kind == "radio":
            self.checked = True
        elif self.kind == "checkbox":
            self.checked = not self.checked

    def is_selected(self):
        return self.checked

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True


class _Button:
    def __init__(self, text, on_click=None, kind="button"):
        self.text = text
        self.on_click = on_click
        self.kind = kind
        self.clicks = 0

    def click(self):
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()

    def get_attribute(self, name):
        return {"type": self.kind}.get(name, "")

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True


class _Combo(_Control):
    """A React-Select style dropdown: a search box whose typed text is dropped on blur unless an option was clicked."""

    def __init__(self, label, menu, required=False, name="", search=False):
        super().__init__("text", label, required=required, name=name)
        self.menu = list(menu)
        self.search = search
        self.open = False
        self.selected = ""
        self.typed = []

    def as_dict(self):
        data = super().as_dict()
        data.update(role="combobox", ident=self.name)
        return data

    def click(self):
        self.open = True

    def send_keys(self, text):
        if text == Keys.ESCAPE:
            self.open = False
        elif text == Keys.ARROW_DOWN:
            self.open = True
        else:
            super().send_keys(text)
            if self.value:
                self.typed.append(self.value)
                self.open = True

    def offered(self):
        if self.search and not self.value:
            return []
        return [option for option in self.menu if self.value.lower() in option.lower()]

    def choose(self, text):
        self.selected, self.open, self.value = text, False, ""

    def blur(self):
        self.open, self.value = False, ""


class _Suggest(_Combo):
    """A plain text box with a suggestion list (Lever's location): unpicked text is wiped on blur."""

    def __init__(self, label, menu, required=False, name=""):
        super().__init__(label, menu, required=required, name=name, search=True)
        self.picked = False

    def as_dict(self):
        data = _Control.as_dict(self)
        data.update(ident=self.name)
        return data

    def choose(self, text):
        self.value, self.picked, self.open = text, True, False

    def blur(self):
        self.open = False
        if not self.picked:
            self.value = ""


class _Fading(_Control):
    """A field the site empties again once focus moves on."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = 0

    def get_attribute(self, name):
        if name == "value":
            self.reads += 1
            return self.value if self.reads == 1 else ""
        return super().get_attribute(name)


class _Page:
    def __init__(self, url, fields=None, buttons=None, body="Apply for Acme"):
        self.url = url
        self.fields = list(fields or [])
        self.buttons = list(buttons or [])
        self.body = body
        self.errors = []
        self.accounts = []
        self.scripts = []
        self.header = []
        self.google_email = []
        self.google_password = []
        self.challenges = []

    def script(self, script, *args):
        self.scripts.append(script)
        if script is acc._FOLLOWS_SCRIPT:
            return args[1] not in self.header
        if script is ext._FIELDS_SCRIPT:
            return [item.as_dict() for item in self.fields]
        if script is ext._SELECT_SCRIPT:
            element, wanted = args
            if wanted in element.options:
                element.value = wanted
                return wanted
            return ""
        if script is ext._OPTIONS_SCRIPT:
            for combo in self.fields:
                if isinstance(combo, _Combo) and combo.open:
                    return [[_Button(text, lambda text=text, combo=combo: combo.choose(text)), text] for text in combo.offered()]
            return []
        if script is ext._CONTROL_TEXT_SCRIPT:
            shown = args[0].selected
            if shown and getattr(args[0], "short", False):
                shown = shown.split()[-1]
            return shown or "Select..."
        if script is ext._BLUR_SCRIPT:
            if isinstance(args[0], _Combo):
                args[0].blur()
        elif script is ext._SET_VALUE_SCRIPT:
            args[0].value = args[1]
        elif script is ext._CLICK_SCRIPT:
            args[0].click()
        return None


class _Browser:
    def __init__(self, tabs, current):
        self.tabs = dict(tabs)
        self.handle = current
        self.switch_to = SimpleNamespace(window=self._switch)

    def _switch(self, handle):
        if handle not in self.tabs:
            raise NoSuchWindowException(handle)
        self.handle = handle

    def _page(self):
        if self.handle not in self.tabs:
            raise NoSuchWindowException(self.handle)
        return self.tabs[self.handle]

    @property
    def window_handles(self):
        return list(self.tabs)

    @property
    def current_window_handle(self):
        return self.handle

    @property
    def current_url(self):
        return self._page().url

    def close(self):
        del self.tabs[self.handle]

    def get(self, url):
        page = self._page()
        page.url = url
        if getattr(page, "on_get", None) is not None:
            page.on_get()

    def execute_script(self, script, *args):
        return self._page().script(script, *args)

    def find_element(self, by, value):
        assert (by, value) == (By.TAG_NAME, "body")
        return SimpleNamespace(text=self._page().body)

    def find_elements(self, by, value):
        page = self._page()
        if value == ext._CLICKABLE_XPATH:
            return list(page.buttons)
        if value == ext._GOOGLE_BUTTON_XPATH:
            return [button for button in page.buttons if "google" in button.text.lower()]
        if "data-identifier" in value:
            return list(page.accounts)
        if "aria-invalid" in value:
            return list(page.errors)
        if value == ext._CHALLENGE_CSS:
            return list(page.challenges)
        if value == acc.GOOGLE_EMAIL_CSS:
            return list(page.google_email)
        if value == acc.GOOGLE_PASSWORD_CSS:
            return list(page.google_password)
        return []


def _browser(page):
    return _Browser({"main": page}, "main")


class _Engine:
    """Answers from a fixed table; anything else is an abstain, like an unknown question."""

    def __init__(self, answers=None):
        self.answers = dict(ANSWERS if answers is None else answers)
        self.asked = []
        self.context = None

    def resolve(self, question, options=None, field_type="text"):
        self.asked.append(question)
        text = self.answers.get(question)
        if text is None:
            return AnswerResolution.abstain("not in the test table")
        return AnswerResolution(answer=Answer(text=text, grounded_in="test", source=AnswerSource.DATA, confidence=1.0))

    def resolve_many(self, question, options):
        return None, "not in the test table"

    def own_answer(self, question, options=None):
        return self.answers.get(question)

    def set_job_context(self, job):
        self.context = job


def _form(why_required=False):
    return [
        _Control("text", "First Name *", required=True, name="first_name"),
        _Control("text", "Last Name *", required=True, name="last_name"),
        _Control("email", "Email *", required=True, name="email"),
        _Control("tel", "Phone", name="phone"),
        _Control("url", "LinkedIn Profile", name="linkedin"),
        _Control("file", "Resume/CV *", required=True, name="resume", accept=".pdf,.docx"),
        _Control("file", "Cover Letter", name="cover"),
        _Control("select", "How did you hear about this job?", name="source", options=["Select...", "LinkedIn", "Naukri", "Referral"]),
        _Control("select", "Gender", name="gender", options=["Select...", "Male", "Female", "Decline to self-identify"]),
        _Control("radio", "Yes", required=True, group="Are you legally authorized to work in India?", name="auth"),
        _Control("radio", "No", required=True, group="Are you legally authorized to work in India?", name="auth"),
        _Control("checkbox", "I agree to the privacy policy", required=True, name="consent"),
        _Control("checkbox", "Subscribe to job alerts", name="alerts"),
        _Control("textarea", "Why do you want to join us?", required=why_required, name="why"),
    ]


def _by_name(page, name):
    return next(item for item in page.fields if item.name == name)


def _resume(tmp_path):
    pdf = tmp_path / "Jane_Doe_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    return pdf


def _settings(**overrides):
    values = {"email": "t@example.com", "password": "secret"}
    values.update(overrides)
    return Settings(**values)


def _confirming_page(**kwargs):
    page = _Page(GREENHOUSE, fields=_form(**kwargs))

    def submitted():
        page.body = "Thank you for applying! We will be in touch."
        page.fields = []

    page.buttons = [_Button("Submit application", submitted, kind="submit")]
    return page


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, key",
    [
        ("First Name *", "first_name"),
        ("Surname", "last_name"),
        ("Email address", "email"),
        ("Mobile number", "phone"),
        ("LinkedIn Profile", "linkedin_url"),
        ("GitHub", "github_url"),
        ("Current Location", "current_location"),
        ("Preferred location", None),
        ("Why do you want to join us?", None),
        ("What is your current country of residence?*", "country"),
        ("Are you subject to any post-employment restrictions with your current employer?*", None),
        ("Will you now or in the future require sponsorship to remain in your current location?*", None),
    ],
)
def test_labels_map_to_known_values_only_when_unambiguous(label, key):
    assert ext.classify_label(label) == key


def test_known_values_split_the_full_name_and_read_the_extra_facts():
    values = ext.known_values(PROFILE)
    assert values["first_name"] == "Jane"
    assert values["last_name"] == "Doe"
    assert values["linkedin_url"] == "https://linkedin.com/in/jane"
    assert values["country"] == "India"
    assert "github_url" not in values


@pytest.mark.parametrize(
    "url, ats",
    [
        (GREENHOUSE, "greenhouse"),
        ("https://jobs.lever.co/acme/123/apply", "lever"),
        ("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1", "workday"),
        ("https://careers.acme.in/jobs/1", "website"),
    ],
)
def test_the_tracking_system_is_named_from_the_host(url, ats):
    assert ext.detect_ats(url) == ats


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------


def test_the_form_is_filled_from_the_facts_the_answers_and_the_resume(tmp_path):
    page = _Page(GREENHOUSE, fields=_form())
    pdf = _resume(tmp_path)

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine(), pdf)

    assert outcome.missing == []
    assert outcome.resume_attached
    assert _by_name(page, "first_name").value == "Jane"
    assert _by_name(page, "last_name").value == "Doe"
    assert _by_name(page, "email").value == "jane@example.com"
    assert _by_name(page, "phone").value == "+91 90000 00000"
    assert _by_name(page, "linkedin").value == "https://linkedin.com/in/jane"
    assert _by_name(page, "resume").value == str(pdf.resolve())
    assert _by_name(page, "cover").value == ""
    assert _by_name(page, "source").value == "Naukri"
    assert _by_name(page, "gender").value == "Decline to self-identify"
    assert [item.checked for item in page.fields if item.name == "auth"] == [True, False]
    assert _by_name(page, "consent").checked
    assert not _by_name(page, "alerts").checked
    assert _by_name(page, "why").value == ""
    assert "Why do you want to join us?" in outcome.skipped


def test_a_value_already_on_the_form_is_left_alone(tmp_path):
    page = _Page(GREENHOUSE, fields=_form())
    _by_name(page, "email").value = "picked-by-the-site@example.com"

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine(), _resume(tmp_path))

    assert _by_name(page, "email").value == "picked-by-the-site@example.com"
    assert "Email *" in outcome.skipped


def test_a_password_field_is_never_filled(tmp_path):
    page = _Page(GREENHOUSE, fields=_form() + [_Control("password", "Create a password", required=True, name="pw")])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine(), _resume(tmp_path))

    assert _by_name(page, "pw").value == ""
    assert "Create a password" in outcome.missing


def test_a_consent_question_asked_as_radio_buttons_is_agreed_to(tmp_path):
    group = "Do you consent to Acme keeping your data for future roles?"
    page = _Page(GREENHOUSE, fields=[
        _Control("radio", "Yes, I consent", required=True, group=group, name="keep"),
        _Control("radio", "No, I do not consent", required=True, group=group, name="keep"),
    ])
    engine = _Engine({})

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, engine, None)

    assert [item.checked for item in page.fields] == [True, False]
    assert outcome.filled == [group]
    assert engine.asked == []


def test_long_answers_never_come_from_the_model(tmp_path):
    page = _Page(GREENHOUSE, fields=[_Control("textarea", "What is your proudest accomplishment?", name="proud")])
    engine = _Engine({"What is your proudest accomplishment?": "A paragraph the model wrote."})

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, engine, None)

    assert _by_name(page, "proud").value == ""
    assert engine.asked == []
    assert outcome.skipped == ["What is your proudest accomplishment?"]


def test_long_answers_come_from_answers_txt_and_missing_ones_are_added_there(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "answers.txt").write_text(
        "Q: What is your proudest accomplishment?\nA: Growing WildClawBench into a platform other teams use.\n",
        encoding="utf-8",
    )
    settings = _settings()
    engine = AnswerEngine(Ledger(":memory:"), _NoLLM(), PROFILE, settings)
    engine.set_job_context(JOB)
    page = _Page(GREENHOUSE, fields=[
        _Control("textarea", "What is your proudest accomplishment?", name="proud"),
        _Control("textarea", "Why Acme?", required=True, name="why"),
    ])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, engine, None)

    assert _by_name(page, "proud").value == "Growing WildClawBench into a platform other teams use."
    assert outcome.missing == ["Why Acme?"]
    text = (tmp_path / "data" / "answers.txt").read_text(encoding="utf-8")
    assert "LangChain Engineer at Acme | long answers are yours to write\nQ: Why Acme?\nA:\n" in text


@pytest.mark.parametrize(
    "options, picked",
    [
        (["Indore, WV, USA", "Indore, Ashoknagar, Madhya Pradesh, IND", "Indore, Madhya Pradesh, IND"], "Indore, Madhya Pradesh, IND"),
        (["Indore, Madhya Pradesh, India", "Indianapolis, Indiana, United States"], "Indore, Madhya Pradesh, India"),
        (["Indore"], "Indore"),
        (["Bhopal, Madhya Pradesh, IND"], None),
    ],
)
def test_a_city_picks_the_suggestion_in_your_country(options, picked):
    assert ext.pick_place("Indore", options, "India") == picked


def test_a_location_box_with_suggestions_gets_the_suggestion_clicked(tmp_path):
    menu = ["Indore, WV, USA", "Indore, Madhya Pradesh, IND", "Indore, Ashoknagar, Madhya Pradesh, IND"]
    page = _Page(GREENHOUSE, fields=[_Suggest("Current location ✱", menu, required=True, name="location")])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine({}), None)

    assert _by_name(page, "location").value == "Indore, Madhya Pradesh, IND"
    assert outcome.filled == ["Current location ✱"]


def test_a_location_the_site_wipes_is_left_for_you(tmp_path):
    page = _Page(GREENHOUSE, fields=[_Suggest("Current location ✱", ["Bhopal, Madhya Pradesh, IND"], required=True, name="location")])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine({}), None)

    assert _by_name(page, "location").value == ""
    assert outcome.missing == ["Current location ✱"]


def test_a_value_that_vanishes_after_filling_is_not_counted(tmp_path):
    page = _Page(GREENHOUSE, fields=[_Fading("text", "Email *", required=True, name="email")])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine({}), None)

    assert outcome.filled == []
    assert outcome.missing == ["Email *"]


# ---------------------------------------------------------------------------
# Applying on the page
# ---------------------------------------------------------------------------


def test_a_dry_run_fills_everything_and_never_clicks_submit(tmp_path):
    page = _confirming_page()

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=True)

    assert result.status == ext.DRY_RUN
    assert page.buttons[0].clicks == 0
    assert _by_name(page, "first_name").value == "Jane"
    applied = result.to_apply_result(JOB)
    assert applied.status == ApplyStatus.EXTERNAL_SKIPPED
    assert not applied.quota_consumed


def test_a_complete_form_is_submitted_once_and_counted_after_the_site_confirms(tmp_path):
    page = _confirming_page()

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.APPLIED_EXTERNAL
    assert page.buttons[0].clicks == 1
    assert "thank you for applying" in result.detail
    applied = result.to_apply_result(JOB)
    assert applied.status == ApplyStatus.APPLIED_EXTERNAL
    assert not applied.quota_consumed
    assert applied.questions_answered == len(result.filled)


def test_a_required_question_without_an_answer_stops_short_of_submitting(tmp_path):
    page = _confirming_page(why_required=True)

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert page.buttons[0].clicks == 0
    assert result.missing == ["Why do you want to join us?"]
    assert result.detail == "needs you for: Why do you want to join us?"
    assert "First Name *" in result.filled


def test_the_site_reporting_an_error_after_submit_is_not_counted(tmp_path):
    page = _Page(GREENHOUSE, fields=_form())

    def rejected():
        page.errors = [SimpleNamespace(text="Phone number is invalid", is_displayed=lambda: True)]

    page.buttons = [_Button("Submit application", rejected, kind="submit")]

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.ERROR
    assert result.detail == "Submit was clicked but the site reported: Phone number is invalid"
    assert result.to_apply_result(JOB).status == ApplyStatus.ERROR


def test_silence_after_submit_is_not_a_confirmation():
    page = _Page(GREENHOUSE, fields=_form())

    confirmed, detail = ext.wait_for_confirmation(_browser(page), timeout_s=0)

    assert not confirmed
    assert detail == "no confirmation within 0 seconds"


def test_the_form_submit_button_wins_over_a_page_top_apply_link():
    page = _Page(GREENHOUSE, buttons=[_Button("Apply"), _Button("Apply with LinkedIn"), _Button("Submit application", kind="submit")])

    assert ext.find_submit(_browser(page)) is page.buttons[2]


def test_workday_is_filled_like_any_other_career_site(tmp_path):
    page = _Page("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1", fields=_form())
    page.buttons = [_Button("Submit", kind="submit")]

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=True)

    assert result.status == ext.DRY_RUN
    assert _by_name(page, "first_name").value == "Jane"


def test_linkedin_postings_are_left_for_a_person(tmp_path):
    page = _Page("https://www.linkedin.com/jobs/view/1", fields=_form())

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.detail.startswith("linkedin applications need a linkedin session")
    assert page.scripts == []


def test_an_apply_button_in_front_of_the_form_is_clicked_through(tmp_path):
    page = _Page("https://jobs.lever.co/acme/123")

    def open_form():
        page.url = "https://jobs.lever.co/acme/123/apply"
        page.fields = _form()
        page.buttons = [_Button("Submit application", kind="submit")]

    page.buttons = [_Button("Apply for this job", open_form)]

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=True)

    assert result.status == ext.DRY_RUN
    assert _by_name(page, "first_name").value == "Jane"


def test_a_form_without_a_file_upload_is_not_sent_without_the_resume(tmp_path):
    page = _confirming_page()
    page.fields = [item for item in page.fields if item.kind != "file"]

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.missing == ["Resume (the form has no file upload)"]
    assert page.buttons[0].clicks == 0


def test_a_sign_in_wall_with_no_form_behind_it_is_left_for_a_person(tmp_path):
    page = _Page(GREENHOUSE, buttons=[_Button("Sign in with Google"), _Button("Create account")])

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.detail == "the site asks for an account: no sign-in or sign-up form found on job-boards.greenhouse.io"
    assert page.buttons[0].clicks == 0


def test_google_sign_in_picks_the_saved_account_and_the_form_appears(tmp_path):
    page = _Page(GREENHOUSE)
    browser = _browser(page)
    popup = _Page("https://accounts.google.com/o/oauth2/auth?client_id=x")

    def chosen():
        del browser.tabs["popup"]
        page.fields = _form()
        page.buttons = [_Button("Submit application", kind="submit")]

    account = _Button("Jane Doe jane@gmail.com", chosen)
    account.get_attribute = lambda name: "jane@gmail.com" if name == "data-identifier" else ""
    popup.accounts = [account]

    def open_popup():
        browser.tabs["popup"] = popup

    page.buttons = [_Button("Continue with Google", open_popup), _Button("Sign in")]

    result = ext.apply_here(browser, JOB, PROFILE, _Engine(), _settings(google_email="Jane@gmail.com"), _resume(tmp_path), dry_run=True)

    assert account.clicks == 1
    assert browser.handle == "main"
    assert result.status == ext.DRY_RUN
    assert _by_name(page, "email").value == "jane@example.com"


def _greenhouse_form(worked_required=True, city_menu=("Indore, Madhya Pradesh, India", "Indianapolis, Indiana, United States")):
    return [
        _Control("text", "First Name*", required=True, name="first_name"),
        _Control("text", "Email*", required=True, name="email"),
        _Control("file", "Attach", name="resume", accept=".pdf,.doc,.docx"),
        _Control("file", "Attach", name="cover_letter", accept=".pdf,.doc,.docx"),
        _Combo("Have you previously worked at Acme?*", ["Yes", "No"], required=worked_required, name="worked"),
        _Combo("What is your current country of residence?*", ["India", "Indonesia", "United States"], required=True, name="country"),
        _Combo("Gender", ["Male", "Female", "Decline To Self Identify"], name="gender"),
        _Combo("Location (City)", list(city_menu), required=True, name="city", search=True),
    ]


def _with_idents(page):
    for item in page.fields:
        if item.kind == "file":
            item.as_dict = (lambda item: lambda: dict(_Control.as_dict(item), ident=item.name))(item)
    return page


def test_custom_dropdowns_get_a_real_option_and_show_it(tmp_path):
    page = _with_idents(_Page(GREENHOUSE, fields=_greenhouse_form()))
    engine = _Engine({"Have you previously worked at Acme?*": "No, never"})
    pdf = _resume(tmp_path)

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, engine, pdf)

    assert outcome.missing == []
    assert _by_name(page, "worked").selected == "No"
    assert _by_name(page, "country").selected == "India"
    assert _by_name(page, "gender").selected == "Decline To Self Identify"
    assert _by_name(page, "city").selected == "Indore, Madhya Pradesh, India"
    assert engine.asked == ["Have you previously worked at Acme?*"]


def test_the_resume_goes_to_the_resume_slot_only_when_both_say_attach(tmp_path):
    page = _with_idents(_Page(GREENHOUSE, fields=_greenhouse_form()))
    pdf = _resume(tmp_path)

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine({"Have you previously worked at Acme?*": "No"}), pdf)

    assert _by_name(page, "resume").value == str(pdf.resolve())
    assert _by_name(page, "cover_letter").value == ""
    assert outcome.resume_attached


def test_a_dropdown_answer_that_fits_no_option_is_not_typed_in_but_asked_about(tmp_path):
    page = _with_idents(_Page(GREENHOUSE, fields=_greenhouse_form()))
    engine = _Engine({"Have you previously worked at Acme?*": "Maybe"})
    engine.mismatches = []
    engine.record_option_mismatch = lambda question, value, options: engine.mismatches.append((question, value, options))

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, engine, _resume(tmp_path))

    worked = _by_name(page, "worked")
    assert worked.selected == "" and worked.typed == []
    assert outcome.missing == ["Have you previously worked at Acme?*"]
    assert engine.mismatches == [("Have you previously worked at Acme?*", "Maybe", ["Yes", "No"])]


def _dial_code_picker(sticks=True, drops_first=False):
    picker = _Combo("Country*", ["United States +1", "India +91", "Indonesia +62"], required=True, name="country")
    picker.short = True
    if not sticks:
        picker.choose = lambda text: picker.blur()
    if drops_first:
        keep = picker.choose

        def drop_once(text):
            picker.choose = keep
            picker.blur()

        picker.choose = drop_once
    return picker


def test_a_dropdown_that_drops_the_first_pick_gets_a_second_one(tmp_path):
    picker = _dial_code_picker(drops_first=True)
    page = _Page(GREENHOUSE, fields=[_Control("text", "First Name*", required=True, name="first_name"), picker])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine(), None)

    assert picker.selected == "India +91"
    assert picker.typed == ["India +91", "India +91"]
    assert outcome.missing == []


def test_a_picker_that_shows_only_the_dial_code_counts_as_chosen(tmp_path):
    picker = _dial_code_picker()
    page = _Page(GREENHOUSE, fields=[_Control("text", "First Name*", required=True, name="first_name"), picker])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine(), None)

    assert picker.selected == "India +91"
    assert outcome.filled == ["First Name*", "Country*"]
    assert outcome.missing == []


def test_a_dial_code_picker_that_kept_nothing_is_still_missing(tmp_path):
    picker = _dial_code_picker(sticks=False)
    page = _Page(GREENHOUSE, fields=[_Control("text", "First Name*", required=True, name="first_name"), picker])

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine(), None)

    assert picker.selected == ""
    assert outcome.missing == ["Country*"]


def test_typed_search_text_is_not_mistaken_for_a_choice(tmp_path):
    page = _with_idents(_Page(GREENHOUSE, fields=_greenhouse_form(city_menu=("Bhopal, Madhya Pradesh, India",))))

    outcome = ext.fill_form(_browser(page), ext.discover_fields(_browser(page)), PROFILE, _Engine({"Have you previously worked at Acme?*": "No"}), _resume(tmp_path))

    city = _by_name(page, "city")
    assert city.typed == ["Indore"]
    assert city.selected == ""
    assert outcome.missing == ["Location (City)"]


# ---------------------------------------------------------------------------
# From the Naukri job page
# ---------------------------------------------------------------------------


def _from_naukri(monkeypatch, company_page):
    naukri = _Page(JOB.url, body="Apply on company site")
    browser = _Browser({"naukri": naukri}, "naukri")

    def open_site():
        browser.tabs["site"] = company_page

    button = _Button("Apply on company site", open_site)
    monkeypatch.setattr(apply_module, "classify_apply_button", lambda driver: (button, "external"))
    return browser


def test_an_unfinished_company_application_is_recorded_and_the_tab_closed(monkeypatch, tmp_path):
    browser = _from_naukri(monkeypatch, _confirming_page(why_required=True))
    engine = _Engine()

    result = ext.apply_on_company_site(browser, JOB, PROFILE, engine, _settings(), _resume(tmp_path))

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert engine.context is JOB
    assert browser.handle == "naukri"
    assert list(browser.tabs) == ["naukri"]
    [entry] = ext.pending_company_sites(_settings())
    assert (entry["company"], entry["title"]) == ("Acme", "LangChain Engineer")
    assert entry["status"] == "needs you"
    assert entry["left for you"] == "Why do you want to join us?"
    assert entry["site"] == GREENHOUSE
    assert entry["resume to send"].endswith("Jane_Doe_Resume.pdf")


def test_a_dry_run_from_naukri_records_nothing(monkeypatch, tmp_path):
    browser = _from_naukri(monkeypatch, _confirming_page())

    result = ext.apply_on_company_site(browser, JOB, PROFILE, _Engine(), _settings(dry_run=True), _resume(tmp_path))

    assert result.status == ext.DRY_RUN
    assert list(browser.tabs) == ["naukri"]
    assert ext.pending_company_sites(_settings()) == []


def test_the_worklist_header_is_written_once(tmp_path):
    settings = _settings()
    first = ext.ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, url=GREENHOUSE, detail="needs you for: Why us")
    ext.record_company_site(settings, JOB, first)
    ext.record_company_site(settings, JobPosting(job_id="j2", url="u2", title="SDE", company="Beta"), first)

    text = (tmp_path / "data" / "company_sites.md").read_text()
    assert text.count("# Applications on company websites that need you") == 1
    assert [entry["company"] for entry in ext.pending_company_sites(settings)] == ["Acme", "Beta"]


def test_trying_a_job_again_replaces_its_entry_and_applying_removes_it(tmp_path):
    settings = _settings()
    other = JobPosting(job_id="j2", url="u2", title="SDE", company="Beta")
    ext.record_company_site(settings, JOB, ext.ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, detail="needs you for: Why us"))
    ext.record_company_site(settings, other, ext.ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, detail="no form"))
    ext.record_company_site(settings, JOB, ext.ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, detail="needs you for: Notice"))

    entries = ext.pending_company_sites(settings)
    assert [(entry["company"], entry["why"]) for entry in entries] == [("Beta", "no form"), ("Acme", "needs you for: Notice")]

    ext.forget_company_site(settings, JOB)
    assert [entry["company"] for entry in ext.pending_company_sites(settings)] == ["Beta"]
    assert (tmp_path / "data" / "company_sites.md").read_text().startswith("# Applications on company websites")


# ---------------------------------------------------------------------------
# With the real answer engine and data/answers.txt
# ---------------------------------------------------------------------------


class _NoLLM:
    def available(self):
        return False


def test_answers_txt_fills_the_form_and_collects_what_it_cannot_answer(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "answers.txt").write_text(
        "Q: How did you hear about this job?\nA: Naukri\n\n"
        "Q: Are you legally authorized to work in India?\nA: Yes\n",
        encoding="utf-8",
    )
    settings = _settings()
    engine = AnswerEngine(Ledger(":memory:"), _NoLLM(), PROFILE, settings)
    engine.set_job_context(JOB)
    page = _confirming_page(why_required=True)

    result = ext.apply_here(_browser(page), JOB, PROFILE, engine, settings, _resume(tmp_path), dry_run=False)

    assert _by_name(page, "source").value == "Naukri"
    assert [item.checked for item in page.fields if item.name == "auth"] == [True, False]
    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert page.buttons[0].clicks == 0
    text = (tmp_path / "data" / "answers.txt").read_text(encoding="utf-8")
    assert "Q: Why do you want to join us?\nA:\n" in text
    assert "LangChain Engineer at Acme" in text


# ---------------------------------------------------------------------------
# Inside the morning run
# ---------------------------------------------------------------------------

from naukri_bot import auth, browser, cli, llm, ranking, sources  # noqa: E402
from naukri_bot import resume as rs  # noqa: E402
from naukri_bot.models import ApplyResult, LoginResult, ScoredJob  # noqa: E402


def _queued(jid):
    job = JobPosting(job_id=jid, url="https://www.naukri.com/job-listings-%s" % jid, title="Role %s" % jid, company="Co %s" % jid, posted_days_ago=1)
    return ScoredJob(job=job, score=80.0, llm_score=80.0)


@pytest.fixture
def morning(monkeypatch, tmp_path):
    """cli.run() with Naukri scripted: `on_naukri` maps job id -> status, `on_site` job id -> company-site status."""
    calls = []
    on_naukri = {}
    on_site = {}
    queue = [_queued(jid) for jid in ("a", "b", "c")]

    class _LLM:
        def available(self):
            return True

    class _Tabs:
        def __init__(self):
            self.window_handles = ["apply"]
            self.current_window_handle = "apply"
            self.switch_to = self

        def new_window(self, kind):
            self.window_handles.append("resume")
            self.current_window_handle = "resume"

        def window(self, handle):
            self.current_window_handle = handle

        def quit(self):
            pass

    monkeypatch.setattr(llm, "build_client", lambda settings: _LLM())
    monkeypatch.setattr(browser, "create_driver", lambda settings: _Tabs())
    monkeypatch.setattr(auth, "ensure_logged_in", lambda d, s: LoginResult(ok=True, reason="session_reused"))
    monkeypatch.setattr(sources, "collect_candidates", lambda *a, **k: [s.job for s in queue])
    monkeypatch.setattr(ranking, "rank", lambda *a, **k: list(queue))

    def _apply(driver, job, profile, engine, settings):
        assert driver.current_window_handle == "apply"
        status = on_naukri.get(job.job_id, ApplyStatus.APPLIED)
        return ApplyResult(job_id=job.job_id, url=job.url, status=status, quota_consumed=status == ApplyStatus.APPLIED)

    def _site(driver, job, profile, engine, settings, resume_pdf=None):
        calls.append((job.job_id, resume_pdf.name if resume_pdf else None))
        return ext.ExternalResult(status=on_site.get(job.job_id, ApplyStatus.APPLIED_EXTERNAL), url="https://site/%s" % job.job_id, detail="scripted")

    monkeypatch.setattr(apply_module, "apply_to_job", _apply)
    monkeypatch.setattr(ext, "apply_on_company_site", _site)
    monkeypatch.setattr(rs, "build_base_pdf", lambda settings: calls.append("base") or tmp_path / "Base_Resume.pdf")
    monkeypatch.setattr(rs, "build_tailored_pdf", lambda settings, client, job: (tmp_path / ("%s.pdf" % job.job_id), []))
    monkeypatch.setattr(rs, "upload_resume", lambda d, p, dry_run=False: rs.ResumeUpload(p.name, "today", True))

    def _run(**overrides):
        values = dict(email="t@example.com", password="secret", apply_delay_min_s=0.0, apply_delay_max_s=0.0,
                      max_days_old=3, db_path=str(tmp_path / "test.db"))
        values.update(overrides)
        return cli.run(Settings(**values), Profile(full_name="T"))

    return _run, on_naukri, on_site, calls


def test_company_sites_are_left_alone_unless_switched_on(morning):
    run, on_naukri, _, calls = morning
    on_naukri.update(a=ApplyStatus.EXTERNAL_SKIPPED)

    summary = run()

    assert calls == []
    assert summary.skipped_external == 1
    assert summary.applied == 2


def test_company_sites_are_tried_up_to_the_limit_with_the_base_resume(morning, tmp_path):
    run, on_naukri, on_site, calls = morning
    on_naukri.update(a=ApplyStatus.EXTERNAL_SKIPPED, b=ApplyStatus.EXTERNAL_SKIPPED, c=ApplyStatus.EXTERNAL_SKIPPED)
    on_site.update(b=ApplyStatus.EXTERNAL_MANUAL)

    summary = run(external_apply=True, external_apply_limit=2)

    assert calls == ["base", ("a", "Base_Resume.pdf"), ("b", "Base_Resume.pdf")]
    assert (summary.applied_external, summary.external_manual, summary.skipped_external) == (1, 1, 1)
    assert summary.quota_after == 0
    ledger = Ledger(str(tmp_path / "test.db"))
    try:
        assert ledger.has_applied("a")
        assert not ledger.has_applied("b")
        [record] = ledger.runs_between("2000-01-01", "2999-01-01")
        assert record["summary"]["applied_external"] == 1
        assert record["summary"]["external_manual"] == 1
    finally:
        ledger.close()
    worklist = (tmp_path / "external_jobs.md").read_text()
    assert "Role b" in worklist and "Role c" in worklist and "Role a" not in worklist


def test_a_tailored_resume_goes_to_the_company_site_too(morning):
    run, on_naukri, _, calls = morning
    on_naukri.update(b=ApplyStatus.EXTERNAL_SKIPPED)

    summary = run(external_apply=True, tailor_resume=True)

    assert ("b", "b.pdf") in calls
    assert "base" in calls  # only for putting the base resume back at the end
    assert (summary.applied, summary.applied_external) == (2, 1)


# ---------------------------------------------------------------------------
# Career-site accounts
# ---------------------------------------------------------------------------

WORKDAY = "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1/apply/applyManually"


def _account_settings(tmp_path, **overrides):
    values = dict(env_file=str(tmp_path / ".env"), data_dir=str(tmp_path / "data"), google_email="", email="jane@gmail.com")
    values.update(overrides)
    return _settings(**values)


def _honeypot():
    return _Control("text", "Enter website. This input is for robots only, do not enter if you're human.", name="website")


def _error(text):
    return SimpleNamespace(text=text, is_displayed=lambda: True)


def _workday_wall(on_create=None, on_sign_in=None):
    """Workday's account step: Google / email choice, then sign-in, then sign-up behind a link."""
    page = _Page(WORKDAY, body="Create Account/Sign In")
    page.header = [_Button("Sign In", kind="submit")]

    def sign_up_form():
        page.errors = []
        page.fields = [
            _Control("text", "Email Address*", required=True, name="email"),
            _Control("password", "Password*", required=True, name="password"),
            _Control("password", "Verify New Password*", required=True, name="verifyPassword"),
            _Control("checkbox", "I agree", required=True, name="agree"),
            _honeypot(),
        ]
        page.buttons = page.header + [_Button("Create Account", lambda: on_create(page), kind="submit"), _Button("Sign In", kind="submit")]

    def sign_in_form():
        page.fields = [
            _Control("text", "Email Address*", required=True, name="email"),
            _Control("password", "Password*", required=True, name="password"),
            _honeypot(),
        ]
        page.buttons = page.header + [
            _Button("Sign In", lambda: on_sign_in(page), kind="submit"),
            _Button("Create Account", sign_up_form, kind="submit"),
        ]

    page.buttons = page.header + [_Button("Sign in with Google"), _Button("Sign in with email", sign_in_form, kind="submit")]
    return page


def _application(page):
    page.body = "My Information"
    page.fields = _form()
    page.buttons = [_Button("Submit", kind="submit")]


def _never(page):
    pytest.fail("this step must not happen here")


def test_a_new_site_gets_an_account_with_a_generated_password_saved_to_env(tmp_path):
    (tmp_path / ".env").write_text("NAUKRI_EMAIL=jane@gmail.com\n", encoding="utf-8")
    seen = {}

    def created(page):
        seen.update({item.name: item.value for item in page.fields})
        seen["agree"] = _by_name(page, "agree").checked
        _application(page)

    page = _workday_wall(on_create=created, on_sign_in=_never)
    settings = _account_settings(tmp_path)

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), settings, _resume(tmp_path), dry_run=False)

    password = settings.company_site_password
    assert len(password) == 16
    assert seen["email"] == "jane@gmail.com"
    assert seen["password"] == seen["verifyPassword"] == password
    assert seen["agree"] is True
    assert seen["website"] == ""
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "NAUKRI_EMAIL=jane@gmail.com\nCOMPANY_SITE_PASSWORD=%s\n" % password
    accounts = (tmp_path / "data" / "accounts.md").read_text(encoding="utf-8")
    assert "| acme.wd5.myworkdayjobs.com | jane@gmail.com | account created |" in accounts
    assert password not in accounts
    assert not result.detail.startswith("the site asks for an account")
    assert _by_name(page, "first_name").value == "Jane"
    assert page.header[0].clicks == 0


def test_a_dry_run_never_creates_an_account(tmp_path):
    page = _workday_wall(on_create=_never, on_sign_in=_never)
    settings = _account_settings(tmp_path)

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), settings, _resume(tmp_path), dry_run=True)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.detail == (
        "the site asks for an account: dry run: would create an account on acme.wd5.myworkdayjobs.com for jane@gmail.com"
    )
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "data" / "accounts.md").exists()


def test_the_saved_password_signs_in_with_the_forms_own_button(tmp_path):
    typed = {}

    def signed_in(page):
        typed["password"] = _by_name(page, "password").value
        typed["website"] = _by_name(page, "website").value
        _application(page)

    page = _workday_wall(on_create=_never, on_sign_in=signed_in)
    settings = _account_settings(tmp_path, company_site_password="Saved#Pass123")

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), settings, _resume(tmp_path), dry_run=True)

    assert typed == {"password": "Saved#Pass123", "website": ""}
    assert page.header[0].clicks == 0
    assert result.status == ext.DRY_RUN
    assert "| signed in |" in (tmp_path / "data" / "accounts.md").read_text(encoding="utf-8")


def test_an_account_made_elsewhere_with_another_password_is_left_for_a_person(tmp_path):
    def wrong_password(page):
        page.errors = [_error("Wrong email address or password.")]

    def exists(page):
        page.errors = [_error("An account with this email already exists.")]

    page = _workday_wall(on_create=exists, on_sign_in=wrong_password)
    settings = _account_settings(tmp_path, company_site_password="Saved#Pass123")

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), settings, _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert "already exists on acme.wd5.myworkdayjobs.com with another password" in result.detail
    assert settings.company_site_password == "Saved#Pass123"


def test_a_site_that_wants_the_email_verified_stops_and_says_so(tmp_path):
    def verify(page):
        page.body = "We've sent you an email. Verify your email address to continue."

    page = _workday_wall(on_create=verify, on_sign_in=_never)
    settings = _account_settings(tmp_path)

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), settings, _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.detail.endswith("sent a verification email to jane@gmail.com; click the link in it, then apply again")
    assert "waiting for email verification" in (tmp_path / "data" / "accounts.md").read_text(encoding="utf-8")


def test_apply_manually_wins_over_apply_again():
    page = _Page("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1")
    clicked = []

    def manual():
        clicked.append("manual")
        page.fields = _form()

    page.buttons = [_Button("Apply", lambda: clicked.append("apply")), _Button("Autofill with Resume"), _Button("Apply Manually", manual)]

    fields = ext.reveal_form(_browser(page))

    assert clicked == ["manual"]
    assert len(fields) == len(_form())


def test_a_honeypot_box_is_never_filled(tmp_path):
    page = _Page(GREENHOUSE, fields=_form() + [_honeypot()])
    browser = _browser(page)

    ext.fill_form(browser, ext.discover_fields(browser), PROFILE, _Engine(), _resume(tmp_path))

    assert _by_name(page, "website").value == ""


def _two_page_form(page, submitted):
    def second():
        page.fields = [_Control("select", "How did you hear about this job?", name="source", options=["Select...", "Naukri"])]
        page.buttons = [_Button("Back"), _Button("Submit", submitted, kind="submit")]

    page.fields = [
        _Control("text", "First Name *", required=True, name="first_name"),
        _Control("file", "Resume/CV *", required=True, name="resume", accept=".pdf"),
    ]
    page.buttons = [_Button("Save and Continue", second)]


def test_a_form_over_several_pages_is_filled_page_by_page_then_submitted(tmp_path):
    page = _Page(GREENHOUSE)

    def submitted():
        page.body = "Thank you for applying!"
        page.fields = []

    _two_page_form(page, submitted)

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.APPLIED_EXTERNAL
    assert result.filled == ["First Name *", "Resume/CV *", "How did you hear about this job?"]


def test_a_dry_run_stops_on_the_first_page_of_several(tmp_path):
    page = _Page(GREENHOUSE)
    _two_page_form(page, lambda: pytest.fail("submitted on a dry run"))

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=True)

    assert result.status == ext.DRY_RUN
    assert page.buttons[0].clicks == 0
    assert result.detail == "dry run: page 1 filled (2 fields), the next page was not opened"


def test_a_page_the_site_refuses_to_leave_is_left_for_a_person(tmp_path):
    page = _Page(GREENHOUSE)

    def refuse():
        page.errors = [_error("Phone Number is required")]

    _two_page_form(page, lambda: None)
    page.buttons = [_Button("Save and Continue", refuse)]

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.detail == "page 1 did not move on: the site reported: Phone Number is required"


def test_a_google_sign_in_that_takes_the_tab_away_falls_back_to_email(tmp_path):
    def created(page):
        _application(page)

    page = _workday_wall(on_create=created, on_sign_in=_never)
    wall = list(page.buttons)

    def to_google():
        page.url = "https://accounts.google.com/v3/signin/identifier"
        page.buttons = []

    def back_to_the_wall():
        page.buttons = list(wall)

    page.buttons[1].on_click = to_google
    page.on_get = back_to_the_wall
    settings = _account_settings(tmp_path, google_email="jane@gmail.com")

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), settings, _resume(tmp_path), dry_run=False)

    assert page.url == WORKDAY
    assert "| jane@gmail.com | account created |" in (tmp_path / "data" / "accounts.md").read_text(encoding="utf-8")
    assert not result.detail.startswith("the site asks for an account")
    assert _by_name(page, "first_name").value == "Jane"


# ---------------------------------------------------------------------------
# Signing the browser in to Google
# ---------------------------------------------------------------------------


def _google(passkey_first=True):
    """accounts.google.com: email, then (for a passkey account) Try another way -> password."""
    page = _Page("about:blank", body="Sign in")
    email = _Control("text", "Email or phone", name="identifier")
    password = _Control("password", "Enter your password", name="Passwd")

    def signed_in():
        page.url = "https://myaccount.google.com/?pli=1"
        page.body = "Welcome, Jane Doe | jane@gmail.com"
        page.google_password = []
        page.buttons = []

    def password_page():
        page.body = "Enter your password"
        page.google_password = [password]
        page.buttons = [_Button("Next", signed_in)]

    def options():
        page.buttons = [_Button("Enter your password", password_page), _Button("Get a verification code")]

    def after_email():
        page.google_email = []
        if passkey_first:
            page.url = "https://accounts.google.com/v3/signin/challenge/pk"
            page.body = "Verifying it's you... Complete sign-in using your passkey"
            page.buttons = [_Button("Try another way", options)]
        else:
            password_page()

    def opened():
        page.url = "https://accounts.google.com/v3/signin/identifier"
        page.google_email = [email]
        page.buttons = [_Button("Next", after_email)]

    page.on_get = opened
    return page, email, password


def test_google_sign_in_types_the_email_then_finds_the_password_behind_the_passkey(tmp_path):
    page, email, password = _google()
    settings = _settings(google_email="jane@gmail.com", google_password="G00gle#pass")

    ok, how = acc.google_login(_browser(page), settings, timeout_s=0.05)

    assert (ok, how) == (True, "signed in to Google as jane@gmail.com")
    assert email.value == "jane@gmail.com"
    assert password.value == "G00gle#pass"


def test_a_saved_google_session_needs_nothing(tmp_path):
    page = _Page("about:blank")

    def home():
        page.url, page.body = "https://myaccount.google.com/", "Welcome | jane@gmail.com"

    page.on_get = home

    assert acc.google_login(_browser(page), _settings(google_email="jane@gmail.com"), timeout_s=0.05) == (
        True,
        "already signed in to Google as jane@gmail.com",
    )


def test_a_different_google_account_never_counts_and_the_right_one_is_added(tmp_path):
    page, email, password = _google(passkey_first=False)
    sign_in_page = page.on_get

    def opened():
        if page.url == acc.GOOGLE_HOME:
            page.url, page.body = "https://myaccount.google.com/", "Welcome | personal@gmail.com"
        else:
            sign_in_page()

    page.on_get = opened
    settings = _settings(google_email="jane@gmail.com", google_password="G00gle#pass")

    ok, how = acc.google_login(_browser(page), settings, timeout_s=0.05)

    assert (ok, how) == (True, "signed in to Google as jane@gmail.com")
    assert email.value == "jane@gmail.com"


def test_without_a_password_the_passkey_waits_for_a_person_then_gives_up(tmp_path):
    page, email, password = _google()
    settings = _settings(google_email="jane@gmail.com")

    ok, how = acc.google_login(_browser(page), settings, timeout_s=0.05)

    assert not ok and how == "Google sign-in was not finished within 1 minute"
    assert email.value == "jane@gmail.com"
    assert password.value == ""
    assert page.buttons[0].clicks == 0


def test_headless_google_sign_in_never_waits(tmp_path):
    page, _, _ = _google()

    ok, how = acc.google_login(_browser(page), _settings(google_email="jane@gmail.com", headless=True), timeout_s=60)

    assert not ok and how == "Google wants a person to finish signing in; run once without --headless"


def test_google_refusing_the_browser_stops_at_once_and_for_the_day(tmp_path):
    page, email, password = _google()

    def refused():
        page.google_email = []
        page.url = "https://accounts.google.com/v3/signin/rejected"
        page.body = "Couldn't sign you in | Google couldn't verify this account belongs to you."
        page.buttons = [_Button("Recover account")]

    page.buttons = []
    opened = page.on_get

    def start():
        opened()
        page.buttons = [_Button("Next", refused)]

    page.on_get = start
    settings = _settings(google_email="jane@gmail.com", google_password="G00gle#pass", report_dir=str(tmp_path / "reports"))

    ok, how = acc.google_login(_browser(page), settings, timeout_s=60)

    assert not ok and how.startswith("Google refused to sign this browser in to jane@gmail.com")
    assert password.value == ""
    assert acc.google_refused_today(settings)


def test_a_form_with_an_image_text_check_is_never_submitted(tmp_path):
    page = _confirming_page()
    page.fields.append(_Control("text", "Type below image text", name="captcha_text"))

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert "Type below image text (a check only a person may answer)" in result.missing
    assert page.buttons[0].clicks == 0
    assert _by_name(page, "captcha_text").value == ""


def test_a_recaptcha_on_the_page_stops_the_submit(tmp_path):
    page = _confirming_page()
    page.challenges = [SimpleNamespace(is_displayed=lambda: True)]

    result = ext.apply_here(_browser(page), JOB, PROFILE, _Engine(), _settings(), _resume(tmp_path), dry_run=False)

    assert result.status == ApplyStatus.EXTERNAL_MANUAL
    assert result.missing == ["captcha (a check only a person may answer)"]
    assert page.buttons[0].clicks == 0


def test_optional_boxes_take_only_your_own_answers_and_never_reach_the_model(tmp_path):
    page = _confirming_page()
    page.fields += [_Control("text", "Facebook", name="facebook"), _Control("text", "Loading", name="loading")]
    engine = _Engine()

    result = ext.apply_here(_browser(page), JOB, PROFILE, engine, _settings(), _resume(tmp_path), dry_run=True)

    assert "Facebook" not in engine.asked and "Loading" not in engine.asked
    assert result.status == ext.DRY_RUN
