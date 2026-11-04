"""Naukri's page blames itself; its apply call names the real reason.

A live check on 2026-10-28 recorded
POST /cloudgateway-workflow/workflow-services/apply-workflow/v1/apply
-> 403 {"message": "Daily quota of jobs exceeded", "validationErrors":
        [{"field": "Apply Quota", "customErrorCode": 403009}]}
while the page showed only "There was an error while processing your request".
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.models import ApplyStatus
from naukri_bot import apply as apply_module


class _Driver:
    def __init__(self, recorded):
        self.recorded = recorded

    def execute_script(self, script, *args):
        if script is apply_module._WATCH_APPLY_SCRIPT:
            return True
        return self.recorded


def test_the_daily_quota_is_named_and_ends_the_run():
    driver = _Driver({"status": 403, "message": "Daily quota of jobs exceeded", "body": "{}"})

    status, said = apply_module._server_refusal(driver)

    assert status == ApplyStatus.QUOTA_EXPIRED, "a used-up quota must stop the run, not look like a hiccup"
    assert status in ApplyStatus.TERMINAL
    assert "Daily quota of jobs exceeded" in said and "403" in said


def test_any_other_refusal_keeps_naukris_own_words():
    driver = _Driver({"status": 500, "message": "Service unavailable", "body": "{}"})

    status, said = apply_module._server_refusal(driver)

    assert status == ApplyStatus.NAUKRI_REFUSED and status not in ApplyStatus.TERMINAL
    assert said == "Naukri says: Service unavailable (500)"


def test_a_refusal_without_a_message_still_reports_the_code():
    status, said = apply_module._server_refusal(_Driver({"status": 403, "message": "", "body": ""}))
    assert (status, said) == (ApplyStatus.NAUKRI_REFUSED, "Naukri says: no reason given (403)")


@pytest.mark.parametrize("recorded", [None, {}, {"status": 200, "message": "ok"}, "nonsense"])
def test_an_apply_that_went_through_is_not_a_refusal(recorded):
    assert apply_module._server_refusal(_Driver(recorded)) == ("", "")


def test_the_watcher_survives_a_browser_that_will_not_run_it():
    class _Broken:
        def execute_script(self, script, *args):
            from selenium.common.exceptions import WebDriverException
            raise WebDriverException("no such window")

    apply_module._watch_apply_calls(_Broken())
    assert apply_module._server_refusal(_Broken()) == ("", "")


def test_the_quota_code_alone_ends_the_run_when_the_message_moved():
    body = '{"message": "", "validationErrors": [{"field": "Apply Quota", "customErrorCode": 403009}]}'
    status, said = apply_module._server_refusal(_Driver({"status": 403, "message": "", "body": body}))
    assert status == ApplyStatus.QUOTA_EXPIRED
    assert "403009" in said
    assert apply_module.QUOTA_ERROR_CODE == 403009


def test_other_error_codes_are_not_the_quota():
    body = '{"message": "Something else", "validationErrors": [{"customErrorCode": 403001}]}'
    status, _ = apply_module._server_refusal(_Driver({"status": 403, "message": "Something else", "body": body}))
    assert status == ApplyStatus.NAUKRI_REFUSED


def test_a_quota_refusal_after_the_questionnaire_stops_naukri_instead_of_reading_as_an_error(monkeypatch, tmp_path):
    """The questionnaire's last answer sends the application. When Naukri refuses that with 403009
    the page shows only a generic toast, and without this check the job was recorded as an
    unverified error, which never stops the run, so Apply was pressed again on the next job."""
    from common.models import ChatbotOutcome, JobPosting, Profile, Settings

    submitted = []

    class _Page:
        def execute_script(self, script, *args):
            if script is apply_module._WATCH_APPLY_SCRIPT:
                return True
            return {"status": 403, "message": "Daily quota of jobs exceeded", "body": ""} if submitted else None

    class _Button:
        def click(self):
            pass

    monkeypatch.setattr(apply_module, "safe_get", lambda driver, url: True)
    monkeypatch.setattr(apply_module, "_on_job_page", lambda driver: True)
    monkeypatch.setattr(apply_module, "_looks_logged_out", lambda driver: False)
    monkeypatch.setattr(apply_module, "_wait_for_apply_controls", lambda driver: True)
    monkeypatch.setattr(apply_module, "classify_apply_button", lambda driver: (_Button(), "native"))
    monkeypatch.setattr(apply_module, "_visible_message", lambda driver, xpath: "")
    monkeypatch.setattr(apply_module, "_find_visible", lambda driver, by, selector: object())
    monkeypatch.setattr(apply_module, "verify_applied", lambda driver: (False, "no confirmation"))
    monkeypatch.setattr(apply_module, "_reload_and_check_applied", lambda driver, job: "")

    def _questionnaire(driver, profile, engine, settings):
        submitted.append(True)
        return ChatbotOutcome(completed=True, answered=3)

    monkeypatch.setattr(apply_module, "handle_chatbot", _questionnaire)
    job = JobPosting("j1", "https://www.naukri.com/job-listings-j1", title="AI Engineer", company="Acme")

    result = apply_module.apply_to_job(_Page(), job, Profile(full_name="T"), object(),
                                       Settings(dry_run=False, data_dir=str(tmp_path)))

    assert result.status == ApplyStatus.QUOTA_EXPIRED, result.detail
    assert result.status in ApplyStatus.TERMINAL
    assert result.questions_answered == 3 and not result.quota_consumed
