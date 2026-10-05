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

from .browser import human_pause, human_type, safe_get
from .models import LoginResult, Settings


logger = logging.getLogger(__name__)

_LOGIN_URLS = (
    "https://www.naukri.com/nlogin/login",
    "https://login.naukri.com/",
)
_SUCCESS_SELECTORS = (
    ".nI-gNb-drawer__icon",
    "[class*='nI-gNb-menuItems']",
    ".view-profile-wrapper",
    "#root .nI-gNb-log-reg",
)
_CHALLENGE_SELECTORS = (
    "iframe[src*='recaptcha']",
    "[class*='captcha']",
    "[id*='captcha']",
    "[class*='otp']",
    "[id*='otp']",
    "input[name*='otp']",
)
_ERROR_SELECTORS = (".erLbl", ".commonErrorMsg", "[class*='error']")
_CHALLENGE_TEXT = ("captcha", "otp", "verification code", "recaptcha")
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


def is_logged_in(driver: WebDriver) -> bool:
    """Return whether the current page contains a verified login marker."""
    try:
        if "naukri.com/mnjuser" in driver.current_url.lower():
            return True
    except WebDriverException as exc:
        logger.warning("Could not inspect current URL (%s): %s", type(exc).__name__, exc)
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


def ensure_logged_in(driver: WebDriver, settings: Settings) -> LoginResult:
    """Reuse a saved session if there is one, otherwise log in.

    is_logged_in only inspects the page already open, and a fresh driver sits on
    about:blank, so the dashboard is loaded first. With a persistent browser
    profile this is normally all that happens: the login form is never touched,
    and that form is what intermittently reports itself as not interactable.
    """
    if is_logged_in(driver):
        return LoginResult(ok=True, reason="session_reused", needs_manual=False)

    if safe_get(driver, _DASHBOARD_URL) and is_logged_in(driver):
        logger.info("Reusing the saved Naukri session; no login needed")
        return LoginResult(ok=True, reason="session_reused", needs_manual=False)

    return login(driver, settings)
