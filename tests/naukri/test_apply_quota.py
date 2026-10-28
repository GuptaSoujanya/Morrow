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
