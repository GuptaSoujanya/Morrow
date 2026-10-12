"""Naukri authentication with explicit outcome verification."""

import logging
import time
from typing import List, Optional, Tuple

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from common.browser import human_pause, human_type, safe_get
from common.models import LoginResult, Settings


logger = logging.getLogger(__name__)

_LOGIN_URLS = (
    "https://www.naukri.com/nlogin/login",
    "https://login.naukri.com/",
)
# Measured in both states on 8 October. Each of these is present signed in and
# absent signed out. [class*='nI-gNb-menuItems'] used to be here and is not
# evidence of anything: it matched 39 elements signed in and 55 on Naukri's own
# login page, so a first run with no saved session reported "Reusing the saved
# Naukri session" while sitting on the login form.
_SUCCESS_SELECTORS = (
    ".nI-gNb-drawer__icon",
    ".view-profile-wrapper",
)
# Naukri shows these only to anonymous users, so each is proof of the opposite.
# The log-reg block was qualified with "#root" on the assumption that signed-in
# pages carry it too. Measured: they do not -- it is 0 signed in and 1 signed
# out -- and the qualifier cost us the login page, which renders outside #root,
# leaving nothing at all to contradict a false success marker.
_SIGNED_OUT_SELECTORS = (".nI-gNb-log-reg", "#login_Layer")
# Naukri serves this path to anonymous users only, so landing on it settles the
# question before any selector is consulted.
_LOGIN_URL_MARKER = "/nlogin/login"
_CHALLENGE_SELECTORS = (
    "iframe[src*='recaptcha']",
    "[class*='captcha']",
    "[id*='captcha']",
    "[class*='otp']",
    "[id*='otp']",
    "input[name*='otp']",
)
_ERROR_SELECTORS = (".erLbl", ".commonErrorMsg", "[class*='error']")
# Phrases that mean a challenge is actually being asked for. "otp" alone
# matched Naukri's "Login using OTP" alternative, which is offered on every
# login page, so every login was reported as needing a human.
_CHALLENGE_TEXT = (
    "enter otp",
    "enter the otp",
    "otp sent",
    "verify otp",
    "otp has been sent",
    "enter captcha",
    "verification code",
    "i'm not a robot",
)
_CREDENTIAL_TEXT = (
    "invalid username",
    "invalid password",
    "invalid email",
    "incorrect username",
    "incorrect password",
    "wrong password",
    "username or password",
    "email or password",
    "credentials",
)


def _masked_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "%s****" % local[:1]
    if len(local) == 1:
        masked_local = "%s****" % local
    else:
        masked_local = "%s****%s" % (local[0], local[-1])
    return "%s@%s" % (masked_local, domain)


def _find_login_form(driver: WebDriver) -> Optional[WebElement]:
    for url in _LOGIN_URLS:
        if not safe_get(driver, url):
            continue
        try:
            return WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "usernameField"))
            )
        except (
            StaleElementReferenceException,
            TimeoutException,
            WebDriverException,
        ) as exc:
            logger.warning(
                "Login form did not appear at %s (%s)", url, type(exc).__name__
            )
    return None


def _selector_present(driver: WebDriver, selectors: Tuple[str, ...]) -> bool:
    for selector in selectors:
        try:
            if driver.find_elements(By.CSS_SELECTOR, selector):
                return True
        except (StaleElementReferenceException, WebDriverException) as exc:
            logger.warning(
                "Could not inspect selector %s (%s): %s",
                selector,
                type(exc).__name__,
                exc,
            )
    return False


def _visible_page_text(driver: WebDriver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text.lower()
    except (
        NoSuchElementException,
        StaleElementReferenceException,
        WebDriverException,
    ) as exc:
        logger.warning("Could not read page text (%s): %s", type(exc).__name__, exc)
        return ""


def _credential_error(driver: WebDriver) -> Optional[str]:
    for selector in _ERROR_SELECTORS:
        try:
            elements: List[WebElement] = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                text = element.text.strip()
                lowered = text.lower()
                if text and any(marker in lowered for marker in _CREDENTIAL_TEXT):
                    return text
        except (StaleElementReferenceException, WebDriverException) as exc:
            logger.warning(
                "Could not inspect login error selector %s (%s): %s",
                selector,
                type(exc).__name__,
                exc,
            )
    return None


def is_logged_in(driver: WebDriver, trust_url: bool = True) -> bool:
    """Return whether the current page shows a verified login marker.

    trust_url must be False when the caller navigated to a /mnjuser/ address
    itself: the URL check would then only confirm its own navigation. A run
    reported "Reusing the saved Naukri session" against a signed-out browser
    for exactly that reason.
    """
    # Being on the login page is decisive and cannot be faked by markup that
    # happens to appear in both states.
    try:
        if _LOGIN_URL_MARKER in (driver.current_url or "").lower():
            return False
    except WebDriverException as exc:
        logger.warning(
            "Could not inspect current URL (%s): %s", type(exc).__name__, exc
        )

    # A real signed-in marker settles it next. _selector_present matches DOM
    # presence rather than visibility, and Naukri keeps login links in the
    # markup of signed-in pages, so checking signed-out markers first reported
    # a valid session as anonymous.
    if _selector_present(driver, _SUCCESS_SELECTORS):
        return True
    if _selector_present(driver, _SIGNED_OUT_SELECTORS):
        return False
    if trust_url:
        try:
            if "naukri.com/mnjuser" in driver.current_url.lower():
                return True
        except WebDriverException as exc:
            logger.warning(
                "Could not inspect current URL (%s): %s", type(exc).__name__, exc
            )
    return _selector_present(driver, _SUCCESS_SELECTORS)


def login(driver: WebDriver, settings: Settings) -> LoginResult:
    """Log in and return only after reaching a verified terminal outcome."""
    logger.info("Logging in to Naukri as %s", _masked_email(settings.email))
    username = _find_login_form(driver)
    if username is None:
        return LoginResult(
            ok=False,
            reason="login_form_unavailable",
            needs_manual=False,
        )

    try:
        human_type(username, settings.email)
        password = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "passwordField"))
        )
        human_type(password, settings.password)
        try:
            submit = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit.click()
        except (
            NoSuchElementException,
            StaleElementReferenceException,
            WebDriverException,
        ) as exc:
            logger.warning(
                "Submit button was unavailable (%s); pressing Enter instead",
                type(exc).__name__,
            )
            password.send_keys(Keys.ENTER)
    except (
        TimeoutException,
        NoSuchElementException,
        StaleElementReferenceException,
        WebDriverException,
    ) as exc:
        logger.error("Login form interaction failed (%s): %s", type(exc).__name__, exc)
        return LoginResult(
            ok=False,
            reason="login_interaction_failed",
            needs_manual=False,
        )

    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if is_logged_in(driver):
            logger.info("Naukri login verified")
            return LoginResult(ok=True, reason="verified", needs_manual=False)

        page_text = _visible_page_text(driver)
        if _selector_present(driver, _CHALLENGE_SELECTORS) or any(
            marker in page_text for marker in _CHALLENGE_TEXT
        ):
            logger.warning("Naukri login requires captcha, OTP, or 2FA intervention")
            return LoginResult(
                ok=False,
                reason="captcha_or_otp",
                needs_manual=True,
            )

        credential_error = _credential_error(driver)
        if credential_error is not None:
            logger.warning("Naukri rejected the supplied login credentials")
            return LoginResult(
                ok=False,
                reason=credential_error,
                needs_manual=False,
            )

        human_pause(0.4, 0.8)

    logger.warning("Naukri login could not be verified within 45 seconds")
    return LoginResult(
        ok=False,
        reason="login_unverified_timeout",
        needs_manual=True,
    )


_DASHBOARD_URL = "https://www.naukri.com/mnjuser/homepage"


def _wait_for_signed_in(driver: WebDriver, timeout: float = 8.0) -> bool:
    """Wait briefly for a signed-in marker to render, then report."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: _selector_present(d, _SUCCESS_SELECTORS)
        )
        return True
    except TimeoutException:
        return is_logged_in(driver, trust_url=False)
    except WebDriverException as exc:
        logger.warning(
            "Could not wait for the signed-in marker (%s): %s", type(exc).__name__, exc
        )
        return False


def ensure_logged_in(driver: WebDriver, settings: Settings) -> LoginResult:
    """Reuse a saved session if there is one, otherwise log in.

    is_logged_in only inspects the page already open, and a fresh driver sits on
    about:blank, so the dashboard is loaded first. With a persistent browser
    profile this is normally all that happens: the login form is never touched,
    and that form is what intermittently reports itself as not interactable.
    """
    if is_logged_in(driver):
        return LoginResult(ok=True, reason="session_reused", needs_manual=False)

    # trust_url=False: we just navigated to /mnjuser/ ourselves, so the URL
    # proves nothing. Only a real signed-in marker counts -- and the dashboard
    # paints those client-side, so checking the instant the navigation returns
    # found nothing and fell through to the login form, which Naukri does not
    # even serve to a browser that is already signed in.
    if safe_get(driver, _DASHBOARD_URL) and _wait_for_signed_in(driver):
        logger.info("Reusing the saved Naukri session; no login needed")
        return LoginResult(ok=True, reason="session_reused", needs_manual=False)

    logger.info("No saved session to reuse; logging in")

    return login(driver, settings)


def wait_for_manual_login(
    driver: WebDriver, timeout_s: float = 300.0, poll_s: float = 2.0
) -> bool:
    """Hold the window open while a person finishes a captcha or OTP challenge.

    login() returns the moment Naukri asks for a challenge, and the first
    profile-update run quit the browser right after, so the person was told to
    "sign in manually when the window opens" while the window was already gone.
    Only a verified signed-in marker ends the wait: that is what the persistent
    browser profile must hold for later runs to skip the login form.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if not driver.window_handles:
                logger.warning("The browser window was closed before the sign-in finished")
                return False
        except WebDriverException as exc:
            logger.warning(
                "The browser went away before the sign-in finished (%s): %s",
                type(exc).__name__,
                exc,
            )
            return False
        if is_logged_in(driver):
            logger.info("Manual sign-in verified; the session is saved in the browser profile")
            return True
        if time.monotonic() >= deadline:
            logger.warning("Nobody finished the sign-in within %.0f seconds", timeout_s)
            return False
        time.sleep(poll_s)
