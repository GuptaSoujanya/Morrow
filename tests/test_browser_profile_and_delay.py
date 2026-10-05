"""A persistent profile and a random pause between applications.

Both come from reading another Naukri bot that handles these better. The login
form intermittently reports itself as not interactable and cost two runs, and
a saved session means that form is never touched. Applying back to back is the
most machine-like thing the run does.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import browser, cli
from naukri_bot.models import Settings


def _settings(**overrides):
    values = dict(email="t@e.com", password="p")
    values.update(overrides)
    return Settings(**values)


def test_chrome_and_edge_get_separate_profile_directories():
    """Sharing one user-data dir between browsers corrupts it."""
    settings = _settings(browser_profile_dir="/tmp/naukri-test-profile")
    chrome = browser.profile_dir_for(settings, "chrome")
    edge = browser.profile_dir_for(settings, "edge")
    assert chrome != edge
    assert chrome.endswith("/chrome") and edge.endswith("/edge")
    assert os.path.isabs(chrome), "must be absolute: Chrome resolves it itself"


def test_an_empty_setting_disables_the_profile():
    for value in ("", "   "):
        assert browser.profile_dir_for(_settings(browser_profile_dir=value), "chrome") is None


def test_the_profile_is_passed_to_chrome_as_user_data_dir(tmp_path):
    settings = _settings(browser_profile_dir=str(tmp_path / "prof"))
    options = browser._chrome_options(settings, browser.profile_dir_for(settings, "chrome"))
    flags = [a for a in options.arguments if a.startswith("--user-data-dir=")]
    assert len(flags) == 1, "Chrome was not told where the profile lives"
    assert os.path.isdir(flags[0].split("=", 1)[1]), "directory was not created"


def test_no_user_data_dir_when_disabled():
    options = browser._chrome_options(_settings(browser_profile_dir=""), None)
    assert not [a for a in options.arguments if a.startswith("--user-data-dir=")]


def test_the_pause_waits_within_the_configured_range(monkeypatch):
    slept = []
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    cli._pause_between_applications(_settings(apply_delay_min_s=10, apply_delay_max_s=30))
    assert len(slept) == 1
    assert 10 <= slept[0] <= 30


def test_zero_disables_the_pause(monkeypatch):
    slept = []
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    cli._pause_between_applications(_settings(apply_delay_min_s=0, apply_delay_max_s=0))
    assert slept == [], "a disabled pause must not sleep at all"


def test_a_reversed_range_does_not_raise(monkeypatch):
    """max below min would make random.uniform misbehave rather than fail loudly."""
    slept = []
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))
    cli._pause_between_applications(_settings(apply_delay_min_s=30, apply_delay_max_s=5))
    assert len(slept) == 1 and slept[0] == 30
