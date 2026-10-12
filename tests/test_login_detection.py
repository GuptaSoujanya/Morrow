"""A signed-out browser must never be reported as logged in.

On 5 October two runs logged "Reusing the saved Naukri session; no login
needed" against a browser that was visibly not signed in. ensure_logged_in
navigated to https://www.naukri.com/mnjuser/homepage and then called
is_logged_in, whose first check was whether the URL contained "naukri.com/
mnjuser" -- so it only confirmed its own navigation. Separately, the global-nav
login/register block was listed as a success marker, although Naukri shows it
only to anonymous users.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naukri_bot import auth
from common.models import Settings


class _FakeDriver:
    """Minimal stand-in: a URL plus the selectors the page would match."""

    def __init__(self, url, present=()):
        self.current_url = url
        self._present = set(present)

    def find_elements(self, by, selector):
        return [object()] if selector in self._present else []


SIGNED_IN = ".nI-gNb-drawer__icon"
SIGNED_OUT = ".nI-gNb-log-reg"
# Present in both states: 39 elements signed in, 55 on Naukri's own login page.
AMBIGUOUS = "[class*='nI-gNb-menuItems']"
LOGIN_URL = "https://www.naukri.com/nlogin/login?URL=//www.naukri.com/mnjuser/profile"


def test_the_url_alone_does_not_prove_a_session_when_we_navigated_there():
    """The exact 5 October failure."""
    driver = _FakeDriver("https://www.naukri.com/mnjuser/homepage")
    assert auth.is_logged_in(driver, trust_url=False) is False


def test_a_real_signed_in_marker_wins_over_login_markup():
    """Naukri keeps login markup in the DOM of signed-in pages.

    An earlier version of this test asserted the opposite, and that ordering
    reported a valid session as anonymous: _selector_present matches DOM
    presence rather than what is on screen.
    """
    driver = _FakeDriver("https://www.naukri.com/mnjuser/homepage",
                         present=[SIGNED_OUT, SIGNED_IN])
    assert auth.is_logged_in(driver, trust_url=False) is True


def test_the_anonymous_nav_alone_means_signed_out():
    driver = _FakeDriver("https://www.naukri.com/mnjuser/homepage",
                         present=[SIGNED_OUT])
    assert auth.is_logged_in(driver, trust_url=False) is False


def test_a_login_link_is_not_evidence_of_being_signed_out():
    """The selector that broke it: signed-in pages carry login links too."""
    assert "a[href*='nlogin/login']" not in auth._SIGNED_OUT_SELECTORS


@pytest.mark.parametrize("page_text", [
    "login using otp",          # Naukri offers this on every login page
    "use otp to login",
    "login with password or otp",
])
def test_the_otp_login_option_is_not_a_challenge(page_text):
    """Every login was reported as needing a human because "otp" matched here."""
    assert not any(m in page_text for m in auth._CHALLENGE_TEXT), (
        "%r was treated as a captcha/OTP challenge" % page_text
    )


@pytest.mark.parametrize("page_text", [
    "enter otp sent to your mobile",
    "please enter the otp",
    "otp sent to +91xxxxx",
    "enter captcha to continue",
    "i'm not a robot",
])
def test_a_genuine_challenge_is_still_detected(page_text):
    assert any(m in page_text for m in auth._CHALLENGE_TEXT), (
        "%r should have been detected as a challenge" % page_text
    )


def test_a_real_signed_in_marker_is_accepted():
    driver = _FakeDriver("https://www.naukri.com/mnjuser/homepage", present=[SIGNED_IN])
    assert auth.is_logged_in(driver, trust_url=False) is True


def test_the_login_register_block_is_not_a_success_marker():
    assert SIGNED_OUT not in auth._SUCCESS_SELECTORS
    assert SIGNED_OUT in auth._SIGNED_OUT_SELECTORS


def test_organic_mnjuser_url_is_still_trusted():
    """After a real login the driver lands on /mnjuser/ by itself; that counts."""
    driver = _FakeDriver("https://www.naukri.com/mnjuser/profile")
    assert auth.is_logged_in(driver) is True


def test_ensure_logged_in_falls_through_to_login_when_no_session(monkeypatch):
    """A signed-out dashboard must reach the login form, not claim success."""
    driver = _FakeDriver("about:blank")

    def _nav(d, url, attempts=3):
        d.current_url = url
        d._present = {SIGNED_OUT}      # Naukri shows the anonymous nav
        return True

    called = {}

    def _login(d, s):
        called["login"] = True
        return auth.LoginResult(ok=True, reason="verified", needs_manual=False)

    monkeypatch.setattr(auth, "safe_get", _nav)
    monkeypatch.setattr(auth, "login", _login)

    result = auth.ensure_logged_in(driver, Settings(email="t@e.com", password="p"))
    assert called.get("login"), "did not fall through to a real login"
    assert result.reason != "session_reused"


def test_the_login_page_is_never_a_session():
    """The first-run failure: no saved session, so Naukri redirects every
    /mnjuser/ address to /nlogin/login -- and the run reported "Reusing the
    saved Naukri session" from there, because the only success marker it had
    was global-nav markup the login page also carries.
    """
    driver = _FakeDriver(LOGIN_URL, present=[AMBIGUOUS])

    assert auth.is_logged_in(driver) is False
    assert auth.is_logged_in(driver, trust_url=False) is False


def test_the_login_page_wins_even_against_a_real_marker():
    """Markup can lag a redirect; the URL cannot."""
    driver = _FakeDriver(LOGIN_URL, present=[SIGNED_IN])

    assert auth.is_logged_in(driver) is False


def test_global_nav_markup_is_not_a_success_marker():
    """It matched more elements signed out than signed in, so it proves nothing."""
    assert AMBIGUOUS not in auth._SUCCESS_SELECTORS

    driver = _FakeDriver("https://www.naukri.com/", present=[AMBIGUOUS])

    assert auth.is_logged_in(driver, trust_url=False) is False


def test_the_unqualified_login_block_counts_as_signed_out():
    """Measured 0 signed in and 1 signed out, so the "#root" qualifier only
    ever excluded the login page."""
    driver = _FakeDriver("https://www.naukri.com/", present=[SIGNED_OUT])

    assert auth.is_logged_in(driver, trust_url=False) is False


def test_a_signed_in_dashboard_is_still_recognised():
    """The fix must not make the normal path stricter: this is the shape of a
    real signed-in page, measured on 8 October."""
    driver = _FakeDriver(
        "https://www.naukri.com/mnjuser/recommendedjobs",
        present=[SIGNED_IN, AMBIGUOUS],
    )

    assert auth.is_logged_in(driver, trust_url=False) is True


# --- waiting for a person to answer a captcha or OTP ------------------------------


def test_the_wait_ends_once_the_person_has_signed_in(monkeypatch):
    """The 10 October failure: the updater quit the browser the instant Naukri
    asked for an OTP, while telling the person to sign in through that window."""
    driver = _FakeDriver(LOGIN_URL, present=[AMBIGUOUS])
    driver.window_handles = ["main"]
    pauses = []

    def _the_person_types_the_otp(seconds):
        pauses.append(seconds)
        if len(pauses) == 2:
            driver.current_url = "https://www.naukri.com/mnjuser/homepage"
            driver._present = {SIGNED_IN}

    monkeypatch.setattr(auth.time, "sleep", _the_person_types_the_otp)

    assert auth.wait_for_manual_login(driver, timeout_s=60, poll_s=2) is True
    assert pauses == [2, 2]


def test_the_wait_gives_up_when_nobody_signs_in(monkeypatch):
    driver = _FakeDriver(LOGIN_URL, present=[AMBIGUOUS])
    driver.window_handles = ["main"]
    monkeypatch.setattr(auth.time, "sleep", lambda seconds: None)

    assert auth.wait_for_manual_login(driver, timeout_s=0, poll_s=0) is False


def test_a_closed_window_ends_the_wait_early():
    driver = _FakeDriver(LOGIN_URL)
    driver.window_handles = []

    assert auth.wait_for_manual_login(driver, timeout_s=60, poll_s=0) is False
