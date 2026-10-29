"""Reading the code a career site emailed: from Gmail over IMAP, or from the signed-in Gmail."""

import imaplib
import os
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import pytest
from selenium.common.exceptions import WebDriverException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sites_bot import inbox as ib
from common.models import Settings

CODE_MAIL = "Your verification code is 483920. It expires in 10 minutes."
LINK_MAIL = ("Welcome. Please confirm your email address:\n"
             "https://jobs.acme.test/verify?token=abc123\n\n"
             "To stop these messages, unsubscribe at https://jobs.acme.test/unsubscribe")


def _settings(**extra):
    values = {"google_email": "jane.jobs@example.org", "gmail_app_password": "abcdefghijklmnop"}
    values.update(extra)
    return Settings(**values)


def _raw(subject, body, sender="no-reply@jobs.acme.test", ago_s=30):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["Date"] = format_datetime(datetime.now(timezone.utc) - timedelta(seconds=ago_s))
    message.set_content(body)
    return message.as_bytes()


class _Imap:
    """Gmail over IMAP, as much of it as the reader uses."""

    def __init__(self, mails, refuse=False):
        self.mails = mails
        self.refuse = refuse
        self.selected = None
        self.logged_out = False

    def login(self, account, password):
        if self.refuse:
            raise imaplib.IMAP4.error("Invalid credentials")
        self.account = account

    def select(self, box, readonly=False):
        self.selected = (box, readonly)
        return "OK", [b"1"]

    def search(self, charset, *terms):
        if not self.mails:
            return "OK", [b""]
        return "OK", [b" ".join(str(n + 1).encode() for n in range(len(self.mails)))]

    def fetch(self, number, spec):
        self.spec = spec
        return "OK", [(b"1 (BODY[] {1}", self.mails[int(number) - 1])]

    def logout(self):
        self.logged_out = True


@pytest.fixture
def imap(monkeypatch):
    held = {}

    def use(mails, refuse=False):
        held["server"] = _Imap(mails, refuse)
        monkeypatch.setattr(ib.imaplib, "IMAP4_SSL", lambda *args, **kwargs: held["server"])
        return held["server"]

    return use


@pytest.mark.parametrize("text, code", [
    ("Your verification code is 483920", "483920"),
    ("Use code 483920 to verify your email", "483920"),
    ("483920 is your Accenture one-time password", "483920"),
    ("Enter this code: A1B2C3", "A1B2C3"),
    ("Your verification code\n\n483920\n\nThanks", "483920"),
    ("Your one-time PIN is 7281.", "7281"),
    ("Security code: 90210", "90210"),
])
def test_the_code_a_message_spells_out_is_read(text, code):
    assert ib.extract_code(text) == code


@pytest.mark.parametrize("text", [
    "This link expires in 10 minutes.",
    "Your application is saved. Sign in within 15 minutes to finish.",
    "The link is good for 24 hours.",
    "Copyright 2026 Acme Labs. All rights reserved.",
    "Call us on +91 88789 50951 for help.",
    "Your payment of $2500 was received.",
    "Reference number 99004483920115 is on your application.",
    "Open https://jobs.acme.test/verify/483920 to continue.",
    "Thanks for applying to Acme Labs.",
])
def test_what_is_not_a_code_is_not_read_as_one(text):
    assert ib.extract_code(text) == ""


def test_the_confirmation_link_is_preferred_over_the_unsubscribe_one():
    assert ib.extract_link(LINK_MAIL) == "https://jobs.acme.test/verify?token=abc123"


def test_a_link_on_the_site_being_applied_to_wins():
    text = ("Confirm here: https://mailer.vendor.test/c/1 or verify at "
            "https://jobs.acme.test/activate?t=9")
    assert ib.extract_link(text, "jobs.acme.test") == "https://jobs.acme.test/activate?t=9"


def test_a_message_with_only_housekeeping_links_offers_none():
    assert ib.extract_link("See our privacy policy at https://acme.test/privacy") == ""


@pytest.mark.parametrize("subject, body, is_one", [
    ("Verify your email", "", True),
    ("Your one-time code", "", True),
    ("Confirm your account", "", True),
    ("Activate your candidate profile", "", True),
    ("", "Your security code is 1234", True),
    ("Your application was received", "Thanks for applying, we will be in touch", False),
    ("Weekly jobs digest", "Ten new roles for you", False),
])
def test_a_verification_message_is_told_apart_from_the_rest(subject, body, is_one):
    assert ib.looks_like_verification(subject, body) is is_one


def test_a_code_emailed_a_moment_ago_is_read_over_imap(imap):
    server = imap([_raw("Verify your email", CODE_MAIL)])

    found = ib.verification(_settings(), domain="jobs.acme.test", wait_s=0)

    assert found.code == "483920"
    assert found.subject == "Verify your email"
    assert found.sender == "no-reply@jobs.acme.test"
    assert found.why == ""
    assert server.selected == ("INBOX", True)
    assert "PEEK" in server.spec
    assert server.logged_out


def test_a_verification_link_is_read_when_there_is_no_code(imap):
    imap([_raw("Confirm your email address", LINK_MAIL)])

    found = ib.verification(_settings(), domain="jobs.acme.test", wait_s=0)

    assert found.link == "https://jobs.acme.test/verify?token=abc123"
    assert found.code == ""


def test_a_code_from_an_earlier_attempt_is_refused_as_too_old(imap):
    imap([_raw("Verify your email", CODE_MAIL, ago_s=3600)])

    found = ib.verification(_settings(), domain="jobs.acme.test", within_s=300, wait_s=0)

    assert found.code == ""
    assert "60 minutes old" in found.why


def test_a_code_for_another_site_is_not_used_here(imap):
    imap([_raw("Verify your email", "Your verification code is 483920", sender="no-reply@other.test")])

    found = ib.verification(_settings(), domain="jobs.acme.test", wait_s=0)

    assert found.code == ""
    assert "does not mention jobs.acme.test" in found.why


def test_an_inbox_with_nothing_to_verify_says_so(imap):
    imap([_raw("Your application was received", "Thanks for applying to Acme Labs")])

    assert ib.verification(_settings(), wait_s=0).why == "no verification mail in the inbox"


def test_a_refused_app_password_comes_back_as_a_reason_not_a_crash(imap):
    imap([_raw("Verify your email", CODE_MAIL)], refuse=True)

    found = ib.verification(_settings(), wait_s=0)

    assert found.code == ""
    assert "refused the app password" in found.why


def test_gmail_being_unreachable_comes_back_as_a_reason(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("Name or service not known")

    monkeypatch.setattr(ib.imaplib, "IMAP4_SSL", refuse)

    assert "could not reach Gmail" in ib.verification(_settings(), wait_s=0).why


def test_without_an_app_password_or_a_browser_there_is_nowhere_to_read(monkeypatch):
    found = ib.verification(_settings(gmail_app_password=""), wait_s=0)

    assert found.why == "no GMAIL_APP_PASSWORD and no browser to read Gmail in"


def test_without_an_account_email_it_says_which_setting_is_missing():
    found = ib.verification(Settings(gmail_app_password="x", email="", google_email=""), wait_s=0)

    assert "COMPANY_SITE_EMAIL" in found.why


class _Driver:
    """A browser with the application form in one tab, and a Gmail that answers scripts."""

    def __init__(self, rows=(), message="", url="https://mail.google.com/mail/u/0/#inbox", explode=False):
        self.handles = ["form"]
        self.current = "form"
        self.rows = list(rows)
        self.message = message
        self.current_url = url
        self.explode = explode
        self.opened = []
        self.switch_to = _Switch(self)

    @property
    def window_handles(self):
        return list(self.handles)

    @property
    def current_window_handle(self):
        return self.current

    def get(self, url):
        if self.explode:
            raise WebDriverException("the tab crashed")
        self.opened.append(url)

    def execute_script(self, script, *args):
        if "tr.zA" in script and "slice" in script:
            return self.rows
        if "r.click()" in script:
            return True
        if "div.a3s" in script:
            return self.message
        return None

    def close(self):
        self.handles.remove(self.current)
        self.current = self.handles[0] if self.handles else ""


class _Switch:
    def __init__(self, driver):
        self.driver = driver

    def new_window(self, kind):
        self.driver.handles.append("gmail")
        self.driver.current = "gmail"

    def window(self, handle):
        self.driver.current = handle


def _row(subject="Verify your email", snippet="Your verification code is 483920",
         stamp="", sender="no-reply@jobs.acme.test"):
    if not stamp:
        stamp = (datetime.now() - timedelta(seconds=30)).strftime("%a, %b %d, %Y, %I:%M %p")
    return {"subject": subject, "snippet": snippet, "stamp": stamp, "from": sender}


def test_a_code_is_read_from_the_signed_in_gmail_and_the_form_tab_comes_back():
    driver = _Driver(rows=[_row()])

    found = ib.verification(_settings(gmail_app_password=""), driver, domain="jobs.acme.test", wait_s=0)

    assert found.code == "483920"
    assert driver.opened == [ib.search_url("jobs.acme.test")]
    assert driver.window_handles == ["form"]
    assert driver.current_window_handle == "form"


def test_a_code_only_inside_the_message_is_read_by_opening_it():
    driver = _Driver(rows=[_row(snippet="Please verify your email address to continue")],
                     message="Hello,\n\nYour security code is 771234\n")

    found = ib.verification(_settings(gmail_app_password=""), driver, wait_s=0)

    assert found.code == "771234"
    assert driver.window_handles == ["form"]


def test_a_gmail_that_asks_for_a_sign_in_is_reported_not_guessed_at():
    driver = _Driver(url="https://accounts.google.com/ServiceLogin?service=mail")

    found = ib.verification(_settings(gmail_app_password=""), driver, wait_s=0)

    assert found.why == "the bot's browser is not signed in to Gmail"
    assert driver.window_handles == ["form"]


def test_a_browser_that_breaks_while_reading_gmail_still_leaves_the_form_in_front():
    driver = _Driver(rows=[_row()], explode=True)

    found = ib.verification(_settings(gmail_app_password=""), driver, wait_s=0)

    assert found.code == ""
    assert "could not read Gmail" in found.why
    assert driver.window_handles == ["form"]
    assert driver.current_window_handle == "form"


def test_an_old_mail_at_the_top_of_the_inbox_is_refused():
    old = (datetime.now() - timedelta(hours=3)).strftime("%a, %b %d, %Y, %I:%M %p")
    driver = _Driver(rows=[_row(stamp=old)])

    found = ib.verification(_settings(gmail_app_password=""), driver, within_s=300, wait_s=0)

    assert found.code == ""
    assert "minutes old" in found.why


def test_the_browser_is_read_when_the_app_password_does_not_work(imap):
    imap([], refuse=True)
    driver = _Driver(rows=[_row()])

    found = ib.verification(_settings(), driver, domain="jobs.acme.test", wait_s=0)

    assert found.code == "483920"
    assert driver.window_handles == ["form"]


# ---------------------------------------------------------------------------
# Finding the mail at all: tabs, spam, and what a hiring system calls itself
# ---------------------------------------------------------------------------


def test_gmail_is_searched_rather_than_the_primary_tab_alone():
    """A Barclays Workday verification sat in Updates while the bot reported no mail had come."""
    url = ib.search_url("barclays.wd3.myworkdayjobs.com")
    assert "#search/" in url
    assert "in%3Aanywhere" in url, "spam and every tab are included"
    assert "newer_than%3A1d" in url


def test_the_search_does_not_narrow_to_the_employers_name():
    """Workday's mail names Workday, not the employer, so a name in the query would hide it."""
    assert ib.search_url("barclays.wd3.myworkdayjobs.com") == ib.search_url("itron.wd5.myworkdayjobs.com")


@pytest.mark.parametrize("text", [
    "Barclays: please verify your account",
    "Your Workday account needs verification",
    "Workday verification code: 418203",
])
def test_mail_naming_either_the_employer_or_its_hiring_system_is_accepted(text):
    assert ib._matches_site(text, "barclays.wd3.myworkdayjobs.com", "")


@pytest.mark.parametrize("domain,word", [
    ("barclays.wd3.myworkdayjobs.com", "workday"),
    ("globalcareers-msci.icims.com", "icims"),
    ("jobs.smartrecruiters.com", "smartrecruiters"),
    ("b2cprejoinerprod.b2clogin.com", "microsoft"),
])
def test_a_hosts_hiring_system_is_one_of_the_names_to_look_for(domain, word):
    assert word in ib.site_words(domain, "")


def test_mail_from_an_unrelated_site_is_still_turned_away():
    assert not ib._matches_site("Netflix: verify your sign-in", "barclays.wd3.myworkdayjobs.com", "")
