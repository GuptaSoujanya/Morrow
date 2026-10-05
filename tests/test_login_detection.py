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
from naukri_bot.models import Settings


class _FakeDriver:
    """Minimal stand-in: a URL plus the selectors the page would match."""

    def __init__(self, url, present=()):
        self.current_url = url
        self._present = set(present)

    def find_elements(self, by, selector):
        return [object()] if selector in self._present else []


SIGNED_IN = ".nI-gNb-drawer__icon"
SIGNED_OUT = "#root .nI-gNb-log-reg"


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
