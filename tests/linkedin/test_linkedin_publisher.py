"""Publishing is verified at every stage; nothing is posted twice or half-done."""

import os
import sys

import pytest
from selenium.webdriver.common.keys import Keys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from linkedin_bot import publisher
from linkedin_bot.config import LinkedInSettings

POST = "First paragraph of the post.\n\nSecond one, with a detail.\n\nhttps://example.com/a"


class _El:
    def __init__(self, text="", displayed=True, enabled=True, on_click=None, on_send=None):
        self.text = text
        self.displayed = displayed
        self.enabled = enabled
        self.on_click = on_click
        self.on_send = on_send
        self.children = {}
        self.clicks = 0
        self.sent = []

    def find_elements(self, by, value):
        return list(self.children.get(value, []))

    def is_displayed(self):
        return self.displayed

    def is_enabled(self):
        return self.enabled

    def get_attribute(self, name):
        return None

    def click(self):
        self.clicks += 1
        if self.on_click:
            self.on_click()

    def send_keys(self, *keys):
        self.sent.append(keys)
        if self.on_send:
            self.on_send(keys)


class _Editor(_El):
    def __init__(self, mangle=False):
        _El.__init__(self)
        self.mangle = mangle
        self.buffer = []

    def send_keys(self, *keys):
        if Keys.DELETE in keys:
            self.buffer = []
        elif len(keys) == 2 and keys[0] in (Keys.COMMAND, Keys.CONTROL):
            return
        else:
            for key in keys:
                self.buffer.append("\n" if key == Keys.ENTER else key)

    @property
    def text(self):
        value = "".join(self.buffer)
        return value[:-1] if self.mangle and value else value

    @text.setter
    def text(self, value):
        self.buffer = [value] if value else []


class _Driver:
    def __init__(self, url="https://www.linkedin.com/feed/"):
        self.current_url = url
        self.page = {}
        self.window_handles = ["w"]
        self.body = _El("")
        self.screenshots = 0

    def find_elements(self, by, value):
        return list(self.page.get(value, []))

    def find_element(self, by, value):
        return self.body

    def get(self, url):
        self.current_url = url

    def save_screenshot(self, path):
        self.screenshots += 1
        return True


def _browser(mangle=False, file_input=True, confirm="toast"):
    driver = _Driver()
    dialog = _El()
    editor = _Editor(mangle=mangle)
    dialog.children["div.ql-editor[contenteditable='true']"] = [editor]
    post_button = _El(enabled=True)

    def attach(keys):
        dialog.children["img[src^='blob:']"] = [_El()]

    if file_input:
        dialog.children["input[type='file']"] = [_El(displayed=False, on_send=attach)]

    def open_composer():
        driver.page["[role='dialog']"] = [dialog]
        driver.page["button.share-actions__primary-action"] = [post_button]

    def posted():
        if confirm == "toast":
            driver.page["[data-test-artdeco-toast-item-type='success']"] = [_El("Post successful.")]
        elif confirm == "feed":
            driver.page.pop("[role='dialog']", None)
            driver.page["div.feed-shared-update-v2"] = [_El("Soujanya Gupta  " + POST)]

    post_button.on_click = posted
    driver.page["button.share-box-feed-entry__trigger"] = [_El("Start a post", on_click=open_composer)]
    return driver, editor, post_button


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(publisher, "POLL_S", 0)
    monkeypatch.setattr(publisher, "EDITOR_WAIT_S", 0.01)
    monkeypatch.setattr(publisher, "IMAGE_WAIT_S", 0.01)
    monkeypatch.setattr(publisher, "VERIFY_WAIT_S", 0.01)
    monkeypatch.setattr(publisher, "LOGIN_WAIT_S", 0.01)
    monkeypatch.setattr(publisher, "human_pause", lambda *a, **k: None)
    monkeypatch.setattr(publisher, "human_type", lambda el, text, *a, **k: el.send_keys(text))


@pytest.fixture
def card(tmp_path):
    path = tmp_path / "card.png"
    path.write_bytes(b"png")
    return str(path)


def test_success_is_confirmed_by_the_toast(card):
    driver, editor, post_button = _browser(confirm="toast")
    result = publisher.publish(driver, POST, card)
    assert (result.ok, result.stage) == (True, "posted")
    assert post_button.clicks == 1
    assert editor.text == POST
    assert driver.screenshots == 0


def test_success_is_confirmed_by_the_feed_when_there_is_no_toast(card):
    driver, _, _ = _browser(confirm="feed")
    result = publisher.publish(driver, POST, card)
    assert (result.ok, result.stage) == (True, "posted")


def test_mismatched_editor_text_means_post_is_never_clicked(card):
    driver, editor, post_button = _browser(mangle=True)
    result = publisher.publish(driver, POST, card)
    assert (result.ok, result.stage) == (False, "compose")
    assert post_button.clicks == 0
    assert driver.screenshots == 1


def test_missing_file_input_stops_before_posting(card):
    driver, _, post_button = _browser(file_input=False)
    result = publisher.publish(driver, POST, card)
    assert (result.ok, result.stage) == (False, "image")
    assert post_button.clicks == 0


def test_a_missing_card_file_never_opens_the_feed(tmp_path):
    driver, _, _ = _browser()
    result = publisher.publish(driver, POST, str(tmp_path / "nope.png"))
    assert result.stage == "image"
    assert driver.current_url == "https://www.linkedin.com/feed/"


def test_post_clicked_but_nothing_confirms_is_unconfirmed(card):
    driver, _, post_button = _browser(confirm=None)
    result = publisher.publish(driver, POST, card)
    assert (result.ok, result.stage) == (False, "unconfirmed")
    assert post_button.clicks == 1, "never clicked twice"


def _settings():
    return LinkedInSettings(linkedin_email="me@example.com", linkedin_password="pw")


def test_a_saved_session_is_reused():
    driver = _Driver()
    driver.page["button.share-box-feed-entry__trigger"] = [_El()]
    result = publisher.ensure_logged_in(driver, _settings())
    assert (result.ok, result.reason) == (True, "session")


def test_wrong_password_is_reported_without_asking_for_a_human():
    driver = _Driver(url="https://www.linkedin.com/login")
    email, password = _El(), _El()

    def submit():
        driver.page["div#error-for-password"] = [_El("Wrong email or password")]

    driver.page["input#username"] = [email]
    driver.page["input#password"] = [password]
    driver.page["button[type='submit']"] = [_El(on_click=submit)]
    result = publisher.ensure_logged_in(driver, _settings())
    assert (result.ok, result.reason, result.needs_manual) == (False, "bad_credentials", False)
    assert email.sent == [("me@example.com",)]


def test_a_security_check_needs_a_human():
    driver = _Driver(url="https://www.linkedin.com/login")

    def submit():
        driver.current_url = "https://www.linkedin.com/checkpoint/challenge/x"

    driver.page["input#username"] = [_El()]
    driver.page["input#password"] = [_El()]
    driver.page["button[type='submit']"] = [_El(on_click=submit)]
    result = publisher.ensure_logged_in(driver, _settings())
    assert (result.ok, result.needs_manual) == (False, True)


def test_manual_wait_ends_when_the_feed_appears_or_the_window_closes():
    driver = _Driver()
    assert publisher.wait_for_manual_login(driver, timeout_s=0.01) is False
    driver.page["button.share-box-feed-entry__trigger"] = [_El()]
    assert publisher.wait_for_manual_login(driver, timeout_s=0.01) is True
    driver.window_handles = []
    assert publisher.wait_for_manual_login(driver, timeout_s=5) is False
