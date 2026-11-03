"""No app password: drafts and replies go through the Gmail the bot's browser is signed in to. Nothing is sent."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sites_bot import gmail_web


class _Driver:
    def __init__(self, page_text="Draft saved", url="https://mail.google.com/mail/u/0/"):
        self.page_text, self.url, self.opened, self.clicked = page_text, url, [], []
        self.window_handles, self.current_window_handle = ["main"], "main"

    class _Switch:
        def __init__(self, driver):
            self.driver = driver

        def new_window(self, kind):
            self.driver.window_handles.append("tab")

        def window(self, handle):
            self.driver.current_window_handle = handle

    @property
    def switch_to(self):
        return self._Switch(self)

    @property
    def current_url(self):
        return self.url

    def get(self, url):
        self.opened.append(url)

    def close(self):
        self.window_handles.remove(self.current_window_handle)

    def find_elements(self, by, selector):
        return []

    def execute_script(self, script, *args):
        if "innerText : ''" in script:
            return self.page_text
        return None


def test_a_draft_is_saved_in_the_browser_and_never_sent(monkeypatch):
    monkeypatch.setattr(gmail_web.time, "sleep", lambda s: None)
    driver = _Driver()
    assert gmail_web.save_draft(driver, "jobs@a.io", "Engineer application", "Hello") == ""
    assert "view=cm" in driver.opened[0] and "to=jobs%40a.io" in driver.opened[0]
    assert driver.window_handles == ["main"]  # the compose tab is closed, the work tab kept


def test_a_signed_out_browser_says_so(monkeypatch):
    monkeypatch.setattr(gmail_web.time, "sleep", lambda s: None)
    driver = _Driver(url="https://accounts.google.com/signin")
    assert "not signed in" in gmail_web.save_draft(driver, "jobs@a.io", "s", "b")
    assert gmail_web.read_recent(driver) == []


def test_cold_email_uses_the_browser_when_there_is_no_app_password(monkeypatch, tmp_path):
    from common.models import Profile, Settings
    from sites_bot import cold_email

    saved = []
    monkeypatch.setattr(gmail_web, "save_draft", lambda d, to, subject, body, attachment=None: saved.append(to) or "")
    settings = Settings(gmail_app_password="")
    lead = cold_email.Lead("jobs@a.io", "A", "Engineer", "u", "hn")
    assert cold_email._gmail(settings, None, "me@x.io", lead, "s", "b", Profile(full_name="T"), None, object()) == ""
    assert saved == ["jobs@a.io"]
    assert cold_email._gmail(settings, None, "me@x.io", lead, "s", "b", Profile(), None, None) != ""
