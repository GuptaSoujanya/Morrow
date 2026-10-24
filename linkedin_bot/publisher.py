"""Log in to LinkedIn and publish one post with an image, verifying each stage.

Every selector lives in the tuples at the top of this file, in the order they
are tried, so a LinkedIn markup change means editing one tuple, not the flow.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from common.browser import human_pause, human_type, safe_get
from common.models import LoginResult

from .config import LinkedInSettings

logger = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"
LOGIN_URL = "https://www.linkedin.com/login"

Selector = Tuple[str, str]

LOGGED_IN = (
    (By.CSS_SELECTOR, "button.share-box-feed-entry__trigger"),
    (By.CSS_SELECTOR, "[data-control-name='share.open_share_box']"),
    (By.CSS_SELECTOR, "button[aria-label*='Start a post']"),
)  # type: Tuple[Selector, ...]
LOGIN_EMAIL = ((By.CSS_SELECTOR, "input#username"),)  # type: Tuple[Selector, ...]
LOGIN_PASSWORD = ((By.CSS_SELECTOR, "input#password"),)  # type: Tuple[Selector, ...]
LOGIN_SUBMIT = (
    (By.CSS_SELECTOR, "form.login__form button[type='submit']"),
    (By.CSS_SELECTOR, "button[type='submit']"),
)  # type: Tuple[Selector, ...]
LOGIN_ERRORS = (
    (By.CSS_SELECTOR, "div#error-for-password"),
    (By.CSS_SELECTOR, "div#error-for-username"),
)  # type: Tuple[Selector, ...]
START_POST = LOGGED_IN + (
    (By.XPATH, "//button[contains(., 'Start a post')]"),
)  # type: Tuple[Selector, ...]
DIALOG = (
    (By.CSS_SELECTOR, "div.share-box"),
    (By.CSS_SELECTOR, "[role='dialog']"),
)  # type: Tuple[Selector, ...]
EDITOR = (
    (By.CSS_SELECTOR, "div.ql-editor[contenteditable='true']"),
    (By.CSS_SELECTOR, "div[role='textbox'][contenteditable='true']"),
)  # type: Tuple[Selector, ...]
FILE_INPUT = (
    (By.CSS_SELECTOR, "input#media-editor-file-composer-trigger"),
    (By.CSS_SELECTOR, "input[type='file'][accept*='image']"),
    (By.CSS_SELECTOR, "input[type='file']"),
)  # type: Tuple[Selector, ...]
IMAGE_PREVIEW = (
    (By.CSS_SELECTOR, "img[src^='blob:']"),
    (By.CSS_SELECTOR, "img[src^='https://media']"),
)  # type: Tuple[Selector, ...]
NEXT_BUTTON = (
    (By.CSS_SELECTOR, "button[aria-label='Next']"),
    (By.XPATH, ".//button[.//span[normalize-space()='Next']]"),
    (By.XPATH, ".//button[.//span[normalize-space()='Done']]"),
)  # type: Tuple[Selector, ...]
POST_BUTTON = (
    (By.CSS_SELECTOR, "button.share-actions__primary-action"),
    (By.XPATH, "//div[@role='dialog']//button[.//span[normalize-space()='Post']]"),
)  # type: Tuple[Selector, ...]
DOC_MORE = (
    (By.CSS_SELECTOR, "button[aria-label='More']"),
    (By.XPATH, ".//button[.//span[normalize-space()='More']]"),
)  # type: Tuple[Selector, ...]
DOC_ADD = (
    (By.CSS_SELECTOR, "button[aria-label='Add a document']"),
    (By.XPATH, ".//button[contains(@aria-label, 'document')]"),
    (By.XPATH, ".//button[.//span[contains(normalize-space(), 'Add a document')]]"),
)  # type: Tuple[Selector, ...]
DOC_FILE_INPUT = (
    (By.CSS_SELECTOR, "input[type='file'][accept*='pdf']"),
    (By.CSS_SELECTOR, "input[type='file'][accept*='application']"),
    (By.CSS_SELECTOR, "input[type='file']"),
)  # type: Tuple[Selector, ...]
DOC_TITLE = (
    (By.CSS_SELECTOR, "input[id*='document-title']"),
    (By.CSS_SELECTOR, "input[placeholder*='title' i]"),
    (By.CSS_SELECTOR, "input[aria-label*='title' i]"),
)  # type: Tuple[Selector, ...]
DOC_DONE = (
    (By.XPATH, "//div[@role='dialog']//button[.//span[normalize-space()='Done']]"),
    (By.CSS_SELECTOR, "button[aria-label='Done']"),
)  # type: Tuple[Selector, ...]
DISCARD = (
    (By.XPATH, "//button[.//span[normalize-space()='Discard']]"),
)  # type: Tuple[Selector, ...]
SUCCESS_TOAST = (
    (By.CSS_SELECTOR, "[data-test-artdeco-toast-item-type='success']"),
    (By.CSS_SELECTOR, ".artdeco-toast-item__message"),
)  # type: Tuple[Selector, ...]
FEED_UPDATE = (
    (By.CSS_SELECTOR, "div.feed-shared-update-v2"),
    (By.CSS_SELECTOR, "[data-urn^='urn:li:activity']"),
)  # type: Tuple[Selector, ...]

CHALLENGE_URL_MARKERS = ("/checkpoint/", "/challenge")
CHALLENGE_TEXT = ("verification", "security check", "verify")
BAD_CREDENTIALS_TEXT = ("wrong email or password",)
SUCCESS_TEXT = ("post successful", "your post was shared")

LOGIN_WAIT_S = 45.0
MANUAL_LOGIN_TIMEOUT_S = 300.0
EDITOR_WAIT_S = 20.0
IMAGE_WAIT_S = 30.0
DOCUMENT_WAIT_S = 60.0
VERIFY_WAIT_S = 30.0
POLL_S = 2.0


@dataclass
class PublishResult:
    ok: bool
    stage: str
    detail: str = ""


def _find(root: Any, candidates: Sequence[Selector], visible: bool = True) -> Optional[Any]:
    for by, value in candidates:
        try:
            for element in root.find_elements(by, value):
                if not visible or _displayed(element):
                    return element
        except WebDriverException:
            continue
    return None


def _displayed(element: Any) -> bool:
    try:
        return bool(element.is_displayed())
    except WebDriverException:
        return False


def _wait_for(root: Any, candidates: Sequence[Selector], timeout_s: float) -> Optional[Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        element = _find(root, candidates)
        if element is not None:
            return element
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL_S)


def _page_text(driver: Any) -> str:
    try:
        return (driver.find_element(By.TAG_NAME, "body").text or "").lower()
    except WebDriverException:
        return ""


def _url(driver: Any) -> str:
    try:
        return (driver.current_url or "").lower()
    except WebDriverException:
        return ""


def is_logged_in(driver: Any) -> bool:
    from .session import inspect_session

    return inspect_session(driver)["state"] == "connected"


def _challenged(driver: Any) -> bool:
    url = _url(driver)
    if any(marker in url for marker in CHALLENGE_URL_MARKERS):
        return True
    text = _page_text(driver)
    return any(marker in text for marker in CHALLENGE_TEXT)


def _bad_credentials(driver: Any) -> bool:
    if _find(driver, LOGIN_ERRORS) is not None:
        return True
    text = _page_text(driver)
    return any(marker in text for marker in BAD_CREDENTIALS_TEXT)


def wait_for_manual_login(driver: Any, timeout_s: float = MANUAL_LOGIN_TIMEOUT_S) -> bool:
    """Hold the window open while a person answers LinkedIn's security check."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if not driver.window_handles:
                logger.warning("The browser window was closed before the sign-in finished")
                return False
        except WebDriverException as exc:
            logger.warning("The browser went away before the sign-in finished: %s", exc)
            return False
        if is_logged_in(driver):
            logger.info("Manual sign-in verified; the session is saved in the browser profile")
            return True
        if time.monotonic() >= deadline:
            logger.warning("Nobody finished the sign-in within %.0f seconds", timeout_s)
            return False
        time.sleep(POLL_S)


def ensure_logged_in(driver: Any, settings: LinkedInSettings) -> LoginResult:
    """Reuse the saved session or sign in; a security check needs a person."""
    if not safe_get(driver, FEED_URL):
        return LoginResult(ok=False, reason="could not open the feed")
    human_pause(1.0, 2.0)
    if is_logged_in(driver):
        logger.info("Reusing the saved LinkedIn session")
        return LoginResult(ok=True, reason="session")

    if settings.naukri.session_only:
        return LoginResult(ok=False, reason="Saved LinkedIn sign-in expired. Reconnect LinkedIn in Connections, then resume this workflow.", needs_manual=True)

    email = _find(driver, LOGIN_EMAIL)
    password = _find(driver, LOGIN_PASSWORD)
    if email is None or password is None:
        safe_get(driver, LOGIN_URL)
        email = _wait_for(driver, LOGIN_EMAIL, 10.0)
        password = _find(driver, LOGIN_PASSWORD)
    if email is None or password is None:
        if _challenged(driver):
            return LoginResult(ok=False, reason="security check", needs_manual=True)
        return LoginResult(ok=False, reason="no login form found")

    email.click()
    human_type(email, settings.linkedin_email)
    human_pause(0.5, 1.2)
    password.click()
    human_type(password, settings.linkedin_password)
    human_pause(0.5, 1.2)
    submit = _find(driver, LOGIN_SUBMIT)
    if submit is None:
        password.send_keys(Keys.ENTER)
    else:
        submit.click()

    deadline = time.monotonic() + LOGIN_WAIT_S
    while True:
        if is_logged_in(driver):
            logger.info("Signed in to LinkedIn")
            return LoginResult(ok=True, reason="password")
        if _bad_credentials(driver):
            return LoginResult(ok=False, reason="bad_credentials")
        if _challenged(driver):
            return LoginResult(ok=False, reason="security check", needs_manual=True)
        if time.monotonic() >= deadline:
            return LoginResult(ok=False, reason="sign-in did not finish", needs_manual=True)
        time.sleep(POLL_S)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _type_post(editor: Any, text: str) -> None:
    editor.click()
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    for index, paragraph in enumerate(paragraphs):
        if index:
            editor.send_keys(Keys.ENTER)
            editor.send_keys(Keys.ENTER)
        editor.send_keys(paragraph.strip())
    human_pause(0.5, 1.0)


def _clear(editor: Any) -> None:
    editor.click()
    editor.send_keys(Keys.COMMAND, "a")
    editor.send_keys(Keys.CONTROL, "a")
    editor.send_keys(Keys.DELETE)


def _enabled(element: Any) -> bool:
    try:
        if element.get_attribute("disabled") or element.get_attribute("aria-disabled") == "true":
            return False
        return bool(element.is_enabled())
    except WebDriverException:
        return False


def screenshot(driver: Any, directory: str = "data/screenshots") -> Optional[Path]:
    try:
        folder = Path(directory or "data/screenshots")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("linkedin-%s.png" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        if driver.save_screenshot(str(path)):
            logger.error("Saved a screenshot of the failure to %s", path)
            return path
    except (OSError, WebDriverException) as exc:
        logger.warning("Could not save a failure screenshot: %s", exc)
    return None


def publish(
    driver: Any,
    text: str,
    image_path: str,
    screenshot_dir: str = "data/screenshots",
    document_path: str = "",
    document_title: str = "",
) -> PublishResult:
    """Compose, attach the PDF carousel (or the image), post, and confirm.

    Never clicks Post twice. A failure with stage "document" happened before
    Post was clicked, so the caller may safely retry with the image instead.
    """
    result = _publish(driver, text, image_path, document_path, document_title)
    if not result.ok:
        logger.error("Publishing stopped at stage %r: %s", result.stage, result.detail)
        screenshot(driver, screenshot_dir)
    return result


def discard_composer(driver: Any) -> None:
    """Close an unposted composer so the next attempt starts from a clean feed."""
    try:
        driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    except WebDriverException as exc:
        logger.debug("Escape did not reach the composer: %s", exc)
    human_pause(0.5, 1.0)
    button = _find(driver, DISCARD)
    if button is not None:
        button.click()
        human_pause(0.5, 1.0)


def _attach_document(driver: Any, dialog: Any, document: Path, title: str) -> Optional[str]:
    """Upload the PDF and name it; returns a failure detail, or None on success."""
    add = _find(dialog, DOC_ADD)
    if add is None:
        more = _find(dialog, DOC_MORE)
        if more is not None:
            more.click()
            human_pause(0.8, 1.5)
            add = _find(driver, DOC_ADD)
    if add is None:
        return "no 'Add a document' button in the composer"
    add.click()
    human_pause(1.0, 2.0)
    file_input = _find(driver, DOC_FILE_INPUT, visible=False)
    if file_input is None:
        return "no file input for the document"
    file_input.send_keys(str(document.resolve()))
    title_input = _wait_for(driver, DOC_TITLE, DOCUMENT_WAIT_S)
    if title_input is None:
        return "the document title box never appeared after the upload"
    title_input.click()
    title_input.send_keys(Keys.COMMAND, "a")
    title_input.send_keys(title[:58])
    human_pause(0.5, 1.0)
    done = None
    deadline = time.monotonic() + DOCUMENT_WAIT_S
    while time.monotonic() < deadline:
        done = _find(driver, DOC_DONE)
        if done is not None and _enabled(done):
            break
        time.sleep(POLL_S)
    if done is None or not _enabled(done):
        return "the document dialog never let us press Done"
    done.click()
    human_pause(1.0, 2.0)
    return None


def _publish(
    driver: Any, text: str, image_path: str, document_path: str = "", document_title: str = ""
) -> PublishResult:
    image = Path(image_path)
    document = Path(document_path) if document_path else None
    if document is not None and not document.is_file():
        return PublishResult(False, "document", "carousel not found: %s" % document)
    if document is None and not image.is_file():
        return PublishResult(False, "image", "card not found: %s" % image)

    if not safe_get(driver, FEED_URL):
        return PublishResult(False, "feed", "could not open the feed")
    human_pause(1.0, 2.5)

    trigger = _wait_for(driver, START_POST, EDITOR_WAIT_S)
    if trigger is None:
        return PublishResult(False, "open", "no 'Start a post' button on the feed")
    trigger.click()
    human_pause(1.0, 2.0)

    dialog = _wait_for(driver, DIALOG, EDITOR_WAIT_S)
    if dialog is None:
        return PublishResult(False, "open", "the composer did not open")
    editor = _wait_for(dialog, EDITOR, EDITOR_WAIT_S)
    if editor is None:
        return PublishResult(False, "open", "no editor inside the composer")

    intended = _normalise(text)
    for attempt in (1, 2):
        _type_post(editor, text)
        typed = _normalise(editor.text)
        if typed == intended:
            break
        logger.warning("Attempt %d: the editor text differs from the draft", attempt)
        if attempt == 2:
            return PublishResult(False, "compose", "editor text never matched the draft")
        _clear(editor)

    if document is not None:
        problem = _attach_document(driver, dialog, document, document_title or document.stem)
        if problem is not None:
            return PublishResult(False, "document", problem)
        dialog = _wait_for(driver, DIALOG, EDITOR_WAIT_S) or dialog
        if _wait_for(dialog, EDITOR, EDITOR_WAIT_S) is None:
            return PublishResult(False, "document", "the editor did not come back after the document step")
        return _click_post_and_verify(driver, text)

    file_input = _find(dialog, FILE_INPUT, visible=False)
    if file_input is None:
        return PublishResult(False, "image", "no file input in the composer")
    file_input.send_keys(str(image.resolve()))
    deadline = time.monotonic() + IMAGE_WAIT_S
    attached = False
    while time.monotonic() < deadline:
        if _find(dialog, IMAGE_PREVIEW, visible=False) is not None or _find(dialog, NEXT_BUTTON) is not None:
            attached = True
            break
        time.sleep(POLL_S)
    if not attached:
        return PublishResult(False, "image", "the image never showed in the composer")
    next_button = _find(dialog, NEXT_BUTTON)
    if next_button is not None:
        next_button.click()
        human_pause(1.0, 2.0)
        dialog = _wait_for(driver, DIALOG, EDITOR_WAIT_S) or dialog
        if _wait_for(dialog, EDITOR, EDITOR_WAIT_S) is None:
            return PublishResult(False, "image", "the editor did not come back after the image step")
    return _click_post_and_verify(driver, text)


def _click_post_and_verify(driver: Any, text: str) -> PublishResult:
    post_button = _find(driver, POST_BUTTON)
    if post_button is None or not _enabled(post_button):
        return PublishResult(False, "post", "the Post button is missing or disabled")
    # From the click on the post may be live: any browser error is "unconfirmed",
    # which ends the day, never an exception that would let the next run post again.
    try:
        post_button.click()
        snippet = _normalise(text)[:60]
        deadline = time.monotonic() + VERIFY_WAIT_S
        while True:
            toast = _find(driver, SUCCESS_TOAST)
            if toast is not None and any(m in _normalise(toast.text) for m in SUCCESS_TEXT):
                return PublishResult(True, "posted", "toast confirmed")
            if _find(driver, DIALOG) is None:
                update = _find(driver, FEED_UPDATE)
                if update is not None and snippet in _normalise(update.text):
                    return PublishResult(True, "posted", "post found at the top of the feed")
            if time.monotonic() >= deadline:
                return PublishResult(False, "unconfirmed", "Post was clicked but nothing confirmed it")
            time.sleep(POLL_S)
    except WebDriverException as exc:
        return PublishResult(False, "unconfirmed", "Post was clicked, then the browser failed: %s"
                             % type(exc).__name__)
