"""Reproductions for the sites lane (sites_bot/)."""

from email.message import EmailMessage

import pytest

from sites_bot import cold_email as ce
from sites_bot import external


class _Recorder:
    calls = []

    def __init__(self, *args, **kwargs):
        _Recorder.calls.append((args, kwargs))

    def login(self, *args):
        return "OK", []

    def append(self, *args):
        return "OK", []

    def logout(self):
        return "BYE", []


def test_sites_03_gmail_imap_uses_a_verified_context_and_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: an app password travels only over a verified TLS session that cannot hang forever."""
    _Recorder.calls.clear()
    monkeypatch.setattr(ce.imaplib, "IMAP4_SSL", _Recorder)
    message = EmailMessage()
    message["Subject"] = "x"
    message.set_content("y")
    assert ce.gmail_draft(message, "me@example.com", "app-password") == ""
    args, kwargs = _Recorder.calls[0]
    assert "ssl_context" in kwargs and "timeout" in kwargs, (args, kwargs)


class _Driver:
    current_url = "https://jobs.acme.test/careers/customer-success-engineer/apply"

    class _Body:
        text = "Customer Success Engineer. Apply below. Tell us about yourself."

    def find_element(self, by, value):
        return self._Body()

    def find_elements(self, by, value):
        return []

    def execute_script(self, script, *args):
        return []


def test_sites_05_a_url_word_is_not_a_confirmation() -> None:
    """Contract: the application counts only when the site confirms it."""
    confirmed, detail = external.wait_for_confirmation(_Driver(), timeout_s=0.2)
    assert confirmed is False, detail


def test_sites_07_a_person_named_chris_is_not_a_hiring_mailbox() -> None:
    """Contract: 'only an address a company published for applications'; no hiring words means left out."""
    assert ce.find_addresses("Meet our CEO chris@acme.com, she runs the company.") == []
    assert ce.find_addresses("Email bob@acme.com about press tickets.") == []
