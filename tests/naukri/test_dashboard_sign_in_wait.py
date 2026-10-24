"""Interactive sign-in pauses use fake pages and a synthetic browser registry."""
from contextlib import contextmanager
import json
import logging
from types import SimpleNamespace

import pytest

from common import browser, browser_preview
from common.models import Settings
from naukri_bot import auth, update_profile


IDENTIFIER = "a" * 32
INSTANCE = "00000000-0000-4000-8000-000000000001"
LOGIN = "https://www.naukri.com/nlogin/login"
SIGNED_IN = ".nI-gNb-drawer__icon"


class Page:
    def __init__(self):
        self.current_url, self.text, self.title = LOGIN, "", ""
        self.window_handles, self.visible = ["page"], set()
        self.quit_calls = 0

    def find_elements(self, by, selector):
        return [SimpleNamespace(is_displayed=lambda: True)] if selector in self.visible else []

    def find_element(self, by, selector):
        return SimpleNamespace(text=self.text)

    def quit(self):
        self.quit_calls += 1


@pytest.fixture
def paused_browser(tmp_path, monkeypatch):
    directory = tmp_path / "registry"
    directory.mkdir(mode=0o700)
    manifest = directory / (IDENTIFIER + ".json")
    manifest.write_text(json.dumps(dict(version=1, id=IDENTIFIER, label="Chrome",
                                        endpoint="http://127.0.0.1:9222", browser_instance=INSTANCE)))
    manifest.chmod(0o600)
    driver = Page()
    driver._morrow_browser_preview_registration = dict(directory=str(directory), id=IDENTIFIER, browser_instance=INSTANCE)
    settings = Settings(session_only=True, headless=True, browser_profile_dir=str(tmp_path / "profile"))
    clock = SimpleNamespace(now=0.0, sleeps=[], on_sleep=lambda: None, visits=[])

    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds
        clock.on_sleep()

    def navigate(*args):
        clock.visits.append(args[1])
        return True

    monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", "true")
    monkeypatch.setenv(browser_preview.ENV_NAME, str(directory))
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(auth.time, "sleep", sleep)
    monkeypatch.setattr(auth, "safe_get", navigate)
    monkeypatch.setattr(auth, "_wait_for_signed_in", lambda *args: False)
    monkeypatch.setattr(auth, "login", lambda *args: pytest.fail("Managed assistance must never type stored credentials"))
    return driver, settings, directory / (IDENTIFIER + ".assist"), clock


def sign_in(driver):
    driver.current_url = auth._DASHBOARD_URL
    driver.visible.add(SIGNED_IN)


def test_same_background_browser_waits_for_sign_in_then_revokes_controls_before_resuming(paused_browser, caplog):
    driver, settings, marker, clock = paused_browser
    def user_finishes():
        assert marker.exists() and settings.headless and driver.quit_calls == 0
        if len(clock.sleeps) == 2:
            sign_in(driver)
    clock.on_sleep = user_finishes
    caplog.set_level(logging.INFO, logger=auth.__name__)
    result = auth.ensure_logged_in(driver, settings)
    assert result.ok and result.reason == "dashboard_session_verified"
    assert clock.sleeps == [2, 2] and clock.visits == [auth._DASHBOARD_URL]
    assert not marker.exists() and driver.quit_calls == 0 and settings.headless
    assert "Open browser in Activity" in caplog.text
    assert "Closing the viewer does not stop the agent" in caplog.text
    assert "Resuming this agent in the background" in caplog.text


@pytest.mark.parametrize("gate", ["flag", "registration", "identity", "unmanaged", "visible"])
def test_unavailable_interactive_browser_does_not_wait_or_grant_controls(paused_browser, monkeypatch, gate):
    driver, settings, marker, clock = paused_browser
    if gate == "flag":
        monkeypatch.delenv("MORROW_BROWSER_INTERACTIVE")
    elif gate == "registration":
        del driver._morrow_browser_preview_registration
    elif gate == "identity":
        driver._morrow_browser_preview_registration["browser_instance"] = "00000000-0000-4000-8000-000000000002"
    elif gate == "unmanaged":
        settings.session_only = False
    else:
        settings.headless = False
    failure = auth.LoginResult(ok=False, reason="Specific initial failure", needs_manual=True)
    assert auth._wait_for_dashboard_sign_in(driver, settings, failure) is failure
    assert clock.sleeps == [] and not marker.exists()


@pytest.mark.parametrize("kind,prefix,needs_manual", [
    ("sign-in", "Naukri is not connected", True),
    ("security", "Naukri needs a security check", True),
    ("blocked", "Naukri is blocking access", False),
    ("unverified", "Naukri loaded, but its sign-in status could not be verified", False),
    ("navigation", "Could not load Naukri", False),
])
def test_timeout_preserves_observed_problem_without_expiry_claim_or_reloads(paused_browser, monkeypatch, caplog, kind, prefix, needs_manual):
    driver, settings, marker, clock = paused_browser
    if kind == "security":
        driver.text = "Enter the verification code"
    elif kind in ("blocked", "unverified"):
        driver.current_url = auth._DASHBOARD_URL
        if kind == "blocked":
            driver.title = "Access Denied"
            driver.text = "You don’t have permission to access this page on this server. Reference #synthetic"
        else:
            driver.text = "Loading"
    elif kind == "navigation":
        def navigate(*args):
            clock.visits.append(args[1])
            return False
        monkeypatch.setattr(auth, "safe_get", navigate)
    clock.on_sleep = lambda: (marker.exists() or pytest.fail("Waiting browser lost its assistance lease"))
    result = auth.ensure_logged_in(driver, settings)
    assert not result.ok and result.needs_manual is needs_manual
    assert result.reason.startswith(prefix) and "within 5 minutes" in result.reason
    assert "expired" not in result.reason and clock.now == 300
    assert clock.visits == [auth._DASHBOARD_URL] and not marker.exists()
    assert driver.quit_calls == 0
    assert prefix in caplog.text
    assert "Reference #synthetic" not in caplog.text


def test_dashboard_url_alone_cannot_resume_the_waiting_agent(paused_browser):
    driver, settings, marker, clock = paused_browser
    clock.on_sleep = lambda: setattr(driver, "current_url", auth._DASHBOARD_URL)
    assert not auth.ensure_logged_in(driver, settings).ok
    assert clock.now == 300 and not marker.exists()


@pytest.mark.parametrize("url", ["https://example.test/mnjuser/homepage", "https://naukri.com.example.test/mnjuser/homepage", "about:blank"])
def test_other_origins_cannot_supply_a_success_marker(url):
    driver = Page()
    driver.current_url, driver.visible = url, {SIGNED_IN}
    assert not auth.is_logged_in(driver, trust_url=False)


def test_closed_driver_ends_wait_early_and_removes_control_lease(paused_browser):
    driver, settings, marker, clock = paused_browser
    clock.on_sleep = lambda: setattr(driver, "window_handles", [])
    result = auth.ensure_logged_in(driver, settings)
    assert not result.ok and not result.needs_manual and "browser closed" in result.reason
    assert clock.now == 2 and not marker.exists()


def test_stop_interrupts_wait_and_revokes_controls_without_owning_driver_teardown(paused_browser):
    driver, settings, marker, clock = paused_browser
    def stop():
        raise KeyboardInterrupt()
    clock.on_sleep = stop
    with pytest.raises(KeyboardInterrupt):
        auth.ensure_logged_in(driver, settings)
    assert not marker.exists() and driver.quit_calls == 0


def test_sign_in_is_rechecked_after_in_flight_controls_finish(paused_browser, monkeypatch):
    driver, settings, marker, clock = paused_browser
    clock.on_sleep = lambda: sign_in(driver)
    original = browser_preview.assistance
    @contextmanager
    def changing_session(*args, **kwargs):
        with original(*args, **kwargs) as enabled:
            yield enabled
        driver.current_url, driver.visible = LOGIN, set()
    monkeypatch.setattr(browser_preview, "assistance", changing_session)
    result = auth.ensure_logged_in(driver, settings)
    assert not result.ok and not result.needs_manual and "changed before" in result.reason
    assert not marker.exists()


def test_profile_work_starts_only_after_controls_are_revoked_and_uses_same_driver(paused_browser, monkeypatch):
    driver, settings, marker, clock = paused_browser
    clock.on_sleep = lambda: sign_in(driver)
    monkeypatch.setattr(browser, "create_driver", lambda configured: driver)
    def work(current):
        assert current is driver and not marker.exists() and driver.quit_calls == 0
        return "synthetic work completed"
    assert update_profile.with_session(settings, work) == "synthetic work completed"
    assert driver.quit_calls == 1


def test_profile_timeout_is_expected_login_failure_without_starting_work(paused_browser, monkeypatch):
    driver, settings, marker, clock = paused_browser
    driver.current_url = auth._DASHBOARD_URL
    monkeypatch.setattr(browser, "create_driver", lambda configured: driver)
    with pytest.raises(update_profile._LoginUnavailable, match="within 5 minutes"):
        update_profile.with_session(settings, lambda driver: pytest.fail("Unverified session reached profile work"))
    assert driver.quit_calls == 1 and not marker.exists()


def test_visible_managed_run_uses_existing_chrome_without_remote_controls(paused_browser, monkeypatch, caplog):
    driver, settings, marker, clock = paused_browser
    settings.headless = False
    monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", "false")
    def finish():
        assert not marker.exists() and driver.quit_calls == 0
        sign_in(driver)
    clock.on_sleep = finish
    caplog.set_level(logging.INFO, logger=auth.__name__)
    result = auth.ensure_logged_in(driver, settings)
    assert result.ok and result.reason == "visible_session_verified"
    assert clock.sleeps == [2] and clock.visits == [auth._DASHBOARD_URL]
    assert "Finish sign-in in the open Chrome window" in caplog.text
    assert "current Chrome window" in caplog.text
    assert "Open browser in Activity" not in caplog.text
    assert driver.quit_calls == 0 and not marker.exists()


def test_visible_profile_timeout_waits_once_and_never_starts_work(paused_browser, monkeypatch):
    driver, settings, marker, clock = paused_browser
    settings.headless = False
    monkeypatch.setattr(browser, "create_driver", lambda configured: driver)
    with pytest.raises(update_profile._LoginUnavailable, match="within 5 minutes"):
        update_profile.with_session(settings, lambda driver: pytest.fail("Unverified session reached profile work"))
    assert clock.now == 300 and driver.quit_calls == 1 and not marker.exists()


def test_visible_closed_window_ends_wait_promptly(paused_browser):
    driver, settings, marker, clock = paused_browser
    settings.headless = False
    clock.on_sleep = lambda: setattr(driver, "window_handles", [])
    result = auth.ensure_logged_in(driver, settings)
    assert not result.ok and not result.needs_manual and "browser closed" in result.reason
    assert clock.now == 2 and not marker.exists()


def test_visible_navigation_failure_does_not_wait_on_an_empty_browser(paused_browser, monkeypatch):
    driver, settings, marker, clock = paused_browser
    settings.headless = False
    monkeypatch.setattr(auth, "safe_get", lambda *args: False)
    result = auth.ensure_logged_in(driver, settings)
    assert not result.ok and "Could not load Naukri" in result.reason
    assert clock.sleeps == [] and not marker.exists()


def test_background_run_without_viewer_fails_instead_of_waiting_invisibly(paused_browser, monkeypatch):
    driver, settings, marker, clock = paused_browser
    monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", "false")
    result = auth.ensure_logged_in(driver, settings)
    assert not result.ok and result.needs_manual
    assert clock.sleeps == [] and not marker.exists()
