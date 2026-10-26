"""A persistent profile and a random pause between applications.

Both come from reading another Naukri bot that handles these better. The login
form intermittently reports itself as not interactable and cost two runs, and
a saved session means that form is never touched. Applying back to back is the
most machine-like thing the run does.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import browser, config
from naukri_bot import cli
from common.models import Settings


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


def test_legacy_background_is_headless_before_login_checks():
    settings = _settings(background=True, headless=False)
    assert settings.headless


def test_environment_background_normalizes_and_explicit_visible_mode_can_override_it(tmp_path, monkeypatch):
    env = tmp_path / "empty.env"
    env.write_text("")
    monkeypatch.setenv("BACKGROUND", "true")
    monkeypatch.setenv("HEADLESS", "false")
    quiet = config.load_settings(str(env))
    visible = config.load_settings(str(env), {"background": False, "headless": False})
    assert quiet.background and quiet.headless
    assert not visible.background and not visible.headless
    assert quiet.browser_profile_dir == visible.browser_profile_dir


@pytest.mark.parametrize("factory", [browser._chrome_options, browser._edge_options])
@pytest.mark.parametrize("mode", [{"headless": True}, {"background": True}])
def test_quiet_chrome_and_edge_keep_profile_without_desktop_window(factory, mode, tmp_path, monkeypatch):
    monkeypatch.delenv("CHROME_WINDOW_SIZE", raising=False)
    profile = str(tmp_path / "profile")
    options = factory(_settings(**mode), profile)
    assert "--headless=new" in options.arguments
    assert "--user-data-dir=" + profile in options.arguments
    assert "--window-size=1440,900" in options.arguments
    assert not any(flag.startswith("--window-position=") for flag in options.arguments)
    assert "--start-maximized" not in options.arguments


def test_visible_window_starts_near_origin_instead_of_restoring_old_corner(monkeypatch):
    monkeypatch.delenv("CHROME_WINDOW_SIZE", raising=False)
    options = browser._chrome_options(_settings())
    assert "--window-position=0,0" in options.arguments
    assert "--window-size=1440,900" in options.arguments
    assert "--headless=new" not in options.arguments
    assert "--start-maximized" not in options.arguments


class _Window:
    def __init__(self, geometry=None):
        self.geometry = geometry
        self.queries = 0
        self.rectangles = []

    def execute_script(self, script):
        self.queries += 1
        assert "screen.availLeft" in script and "screen.availTop" in script
        if isinstance(self.geometry, Exception):
            raise self.geometry
        return self.geometry

    def set_window_rect(self, **rectangle):
        self.rectangles.append(rectangle)


@pytest.mark.parametrize("geometry,rectangle", [
    ({"width": 1920, "height": 1080, "left": 0, "top": 23},
     {"x": 240, "y": 113, "width": 1440, "height": 900}),
    ({"width": 1024, "height": 640, "left": 0, "top": 40},
     {"x": 0, "y": 40, "width": 1024, "height": 640}),
    ({"width": 1920, "height": 1080, "left": -1920, "top": -1080},
     {"x": -1680, "y": -990, "width": 1440, "height": 900}),
    ({"width": 1920, "height": 1080},
     {"x": 240, "y": 90, "width": 1440, "height": 900}),
])
def test_visible_window_is_centered_once_within_available_monitor(geometry, rectangle, monkeypatch):
    monkeypatch.delenv("CHROME_WINDOW_SIZE", raising=False)
    window = _Window(geometry)
    monkeypatch.setattr(browser, "_try_create_driver", lambda settings, use_profile: window)
    assert browser.create_driver(_settings()) is window
    assert window.queries == 1
    assert window.rectangles == [rectangle]


@pytest.mark.parametrize("geometry", [None, {}, {"width": 0, "height": 900},
    {"width": "1920", "height": 1080}, {"width": float("nan"), "height": 1080},
    {"width": 1920, "height": 1080, "left": None},
    browser.WebDriverException("Screen unavailable")])
def test_missing_screen_geometry_keeps_safe_startup_position(geometry, monkeypatch):
    monkeypatch.delenv("CHROME_WINDOW_SIZE", raising=False)
    window = _Window(geometry)
    assert browser._position_visible_window(window, _settings()) is window
    assert window.rectangles == []


def test_quiet_profile_fallback_never_opens_or_positions_a_visible_browser(monkeypatch):
    window = _Window()
    attempts = []

    def create(settings, use_profile):
        attempts.append((settings.headless, use_profile, settings.browser_profile_dir))
        if use_profile:
            raise browser.BrowserError("Synthetic profile unavailable")
        return window

    settings = _settings(background=True)
    monkeypatch.setattr(browser, "_try_create_driver", create)
    assert browser.create_driver(settings) is window
    assert attempts == [(True, True, settings.browser_profile_dir), (True, False, settings.browser_profile_dir)]
    assert window.queries == 0 and window.rectangles == []


@pytest.mark.parametrize("headless", [False, True])
def test_virtual_desktop_size_keeps_origin_without_centering(headless, monkeypatch):
    monkeypatch.setenv("CHROME_WINDOW_SIZE", "1280,720")
    settings = _settings(headless=headless)
    options = browser._chrome_options(settings)
    assert "--window-position=0,0" in options.arguments
    assert "--window-size=1280,720" in options.arguments
    window = _Window()
    assert browser._position_visible_window(window, settings) is window
    assert window.queries == 0 and window.rectangles == []


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


class _SlowSite:
    """A driver whose navigation times out while the page is already on screen."""

    def __init__(self, landed="https://www.hirist.tech/jobfeed", state="interactive", fail=True):
        self.landed, self.state, self.fail, self.scripts, self.gets = landed, state, fail, [], 0

    def get(self, url):
        self.gets += 1
        if self.fail:
            from selenium.common.exceptions import TimeoutException
            raise TimeoutException("timeout: Timed out receiving message from renderer: -0.005")

    @property
    def current_url(self):
        return self.landed

    def execute_script(self, script):
        self.scripts.append(script)
        return self.state if "readyState" in script else None


def test_a_slow_board_that_is_already_on_screen_counts_as_opened(monkeypatch):
    """Hirist keeps a request open after the page is drawn, so Chrome's load timeout fired on a
    readable page and the profile update gave up with 'could not open'."""
    monkeypatch.setattr(browser.time, "sleep", lambda s: None)
    driver = _SlowSite()
    assert browser.safe_get(driver, "https://www.hirist.tech/jobfeed") is True
    assert driver.gets == 1 and "window.stop()" in driver.scripts[-1]


def test_a_timeout_on_another_site_or_a_blank_page_is_still_a_failure(monkeypatch):
    monkeypatch.setattr(browser.time, "sleep", lambda s: None)
    elsewhere = _SlowSite(landed="chrome://new-tab-page/")
    assert browser.safe_get(elsewhere, "https://www.hirist.tech/profile", attempts=2) is False
    assert elsewhere.gets == 2 and not any("window.stop" in s for s in elsewhere.scripts)
    loading = _SlowSite(state="loading")
    assert browser.safe_get(loading, "https://www.hirist.tech/jobfeed", attempts=2) is False
    assert loading.gets == 2
    assert browser.safe_get(_SlowSite(fail=False), "https://www.hirist.tech/jobfeed") is True
