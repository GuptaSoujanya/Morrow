"""Managed sign-in outcomes use fake pages and private temporary metadata only."""
from types import SimpleNamespace

import pytest
from selenium.common.exceptions import TimeoutException

from common import connections
from common.models import Settings
from naukri_bot import auth


LOGIN_URL = "https://www.naukri.com/nlogin/login"
DASHBOARD_URL = "https://www.naukri.com/mnjuser/homepage"
SIGNED_IN = ".nI-gNb-drawer__icon"
SIGNED_OUT = ".nI-gNb-log-reg"


class Page:
    def __init__(self, url=LOGIN_URL, text="", visible=(), hidden=(), title=""):
        self.current_url, self.text, self.title = url, text, title
        self.visible, self.hidden = set(visible), set(hidden)

    def find_elements(self, by, selector):
        if selector in self.visible | self.hidden:
            return [SimpleNamespace(is_displayed=lambda: selector in self.visible)]
        return []

    def find_element(self, by, selector):
        return SimpleNamespace(text=self.text)


@pytest.fixture
def managed(tmp_path, monkeypatch):
    connections.mark_managed(tmp_path)
    settings = Settings(session_only=True, headless=True, browser_profile_dir=str(tmp_path),
                        email="unused@example.test", password="unused-test-password")
    monkeypatch.setattr(auth, "safe_get", lambda *args: True)
    monkeypatch.setattr(auth, "_wait_for_signed_in", lambda driver: auth.is_logged_in(driver, trust_url=False))
    monkeypatch.setattr(auth, "login", lambda *args: pytest.fail("Managed runs must never attempt password login"))
    return settings, tmp_path


@pytest.mark.parametrize("metadata", [{}, {"google": {"state": "connected", "identity_verified": True}},
                                      {"naukri": {"state": "needs_sign_in", "last_verified_at": None}}])
def test_first_naukri_sign_in_is_not_misreported_as_an_expired_session(managed, metadata):
    settings, directory = managed
    connections.write_metadata(directory, metadata)
    before = (directory / connections.METADATA).read_bytes()
    result = auth.ensure_logged_in(Page(), settings)
    assert not result.ok and result.needs_manual
    assert result.reason.startswith("Naukri is not connected in this automation browser.")
    assert "Connections → Naukri → Sign in" in result.reason
    assert "expired" not in result.reason and "Reconnect" not in result.reason
    assert (directory / connections.METADATA).read_bytes() == before


def test_confirmed_sign_out_of_previously_verified_naukri_asks_to_reconnect(managed):
    settings, directory = managed
    connections.write_metadata(directory, {"naukri": {"state": "connected", "last_verified_at": "2026-10-24T11:00:00Z"},
                                           "google": {"state": "connected"}})
    before = (directory / connections.METADATA).read_bytes()
    result = auth.ensure_logged_in(Page(), settings)
    assert not result.ok and result.needs_manual
    assert result.reason.startswith("Naukri needs you to sign in again. Reconnect Naukri in Connections")
    assert "expired" not in result.reason
    assert (directory / connections.METADATA).read_bytes() == before


def test_navigation_failure_is_retryable_and_does_not_invalidate_saved_connection(managed, monkeypatch):
    settings, directory = managed
    connections.write_metadata(directory, {"naukri": {"state": "connected"}})
    before = (directory / connections.METADATA).read_bytes()
    monkeypatch.setattr(auth, "safe_get", lambda *args: False)
    monkeypatch.setattr(auth, "_wait_for_signed_in", lambda *args: pytest.fail("Failed navigation should not wait for page markers"))
    result = auth.ensure_logged_in(Page(url="about:blank"), settings)
    assert not result.ok and not result.needs_manual
    assert result.reason.startswith("Could not load Naukri") and "try again" in result.reason
    assert "expired" not in result.reason and "Reconnect" not in result.reason
    assert (directory / connections.METADATA).read_bytes() == before


@pytest.mark.parametrize("page", [Page(url=DASHBOARD_URL), Page(url="about:blank"),
                                  Page(url=DASHBOARD_URL, hidden=(SIGNED_OUT,))])
def test_unverified_page_is_retryable_and_never_treated_as_authenticated(managed, page):
    settings, _ = managed
    result = auth.ensure_logged_in(page, settings)
    assert not result.ok and not result.needs_manual
    assert "could not be verified" in result.reason and "Try again" in result.reason
    assert "expired" not in result.reason


@pytest.mark.parametrize("title,text", [
    ("Access Denied", "You don’t have permission to access this page on this server. Reference #synthetic"),
    ("Access Denied", ""),
    ("", "You don’t have permission to access this page on this server."),
    ("", "You don't have permission to access this page on this server."),
    ("", "You do not have permission to access this page on this server."),
])
def test_observed_site_access_denial_is_not_reported_as_expired_or_missing_sign_in(managed, title, text):
    settings, directory = managed
    connections.write_metadata(directory, {"naukri": {"state": "connected"}})
    before = (directory / connections.METADATA).read_bytes()
    result = auth.ensure_logged_in(Page(url=DASHBOARD_URL, title=title, text=text), settings)
    assert not result.ok and not result.needs_manual
    assert result.reason.startswith("Naukri is blocking access to this browser.")
    assert "until Naukri allows access" in result.reason
    assert not any(word in result.reason for word in ("expired", "Reconnect", "Reference", "not connected"))
    assert (directory / connections.METADATA).read_bytes() == before


@pytest.mark.parametrize("page", [Page(text="Enter the OTP sent to your phone"),
                                  Page(text="Verify you are human"),
                                  Page(visible=("input[autocomplete='one-time-code']",))])
def test_security_challenges_ask_for_verification_in_connections(managed, page):
    settings, _ = managed
    result = auth.ensure_logged_in(page, settings)
    assert not result.ok and result.needs_manual
    assert result.reason.startswith("Naukri needs a security check.")
    assert "complete the verification" in result.reason


def test_login_using_otp_option_and_hidden_code_field_are_not_a_security_challenge(managed):
    settings, _ = managed
    page = Page(text="Login using OTP", hidden=("input[autocomplete='one-time-code']",))
    result = auth.ensure_logged_in(page, settings)
    assert result.needs_manual and result.reason.startswith("Naukri is not connected")
    assert "security check" not in result.reason


def test_visible_anonymous_navigation_is_explicit_sign_out(managed):
    settings, _ = managed
    result = auth.ensure_logged_in(Page(url="https://www.naukri.com/", visible=(SIGNED_OUT,)), settings)
    assert not result.ok and result.needs_manual and "not connected" in result.reason


def test_positive_marker_still_reuses_the_session_without_navigation(managed, monkeypatch):
    settings, _ = managed
    monkeypatch.setattr(auth, "safe_get", lambda *args: pytest.fail("Already verified session should not navigate"))
    result = auth.ensure_logged_in(Page(url=DASHBOARD_URL, visible=(SIGNED_IN,), hidden=(SIGNED_OUT,)), settings)
    assert result.ok and result.reason == "session_reused"


def test_wait_rejects_stale_success_markup_on_the_login_page():
    page = Page(visible=(SIGNED_IN,))
    assert not auth._wait_for_signed_in(page, timeout=0)


def test_wait_recognizes_delayed_authentication_only_after_positive_markers_render(monkeypatch):
    page = Page(url=DASHBOARD_URL)
    observed = []

    class Wait:
        def __init__(self, driver, timeout):
            assert driver is page and timeout == 8

        def until(self, condition):
            observed.append(condition(page))
            page.visible.add(SIGNED_IN)
            observed.append(condition(page))
            if not observed[-1]:
                raise TimeoutException()

    monkeypatch.setattr(auth, "WebDriverWait", Wait)
    assert auth._wait_for_signed_in(page)
    assert observed == [False, True]


def test_dashboard_url_restored_by_browser_is_not_proof_of_a_session(managed, monkeypatch):
    settings, _ = managed
    page = Page(url=DASHBOARD_URL)
    visited = []

    def navigate(driver, url):
        visited.append(url)
        driver.current_url = LOGIN_URL
        return True

    monkeypatch.setattr(auth, "safe_get", navigate)
    result = auth.ensure_logged_in(page, settings)
    assert not result.ok and result.needs_manual and visited == [DASHBOARD_URL]
