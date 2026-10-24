"""Naukri authentication with explicit outcome verification."""

import logging
from pathlib import Path
import time
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

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
        current_url = driver.current_url or ""
        location = urlsplit(current_url)
        host = (location.hostname or "").lower()
        if (location.scheme != "https" or not (host == "naukri.com" or host.endswith(".naukri.com"))
                or host == "login.naukri.com" or _LOGIN_URL_MARKER in location.path.lower()):
            return False
    except (ValueError, WebDriverException) as exc:
        logger.warning(
            "Could not inspect current URL (%s): %s", type(exc).__name__, exc
        )
        return False

    # A real signed-in marker settles it next. _selector_present matches DOM
    # presence rather than visibility, and Naukri keeps login links in the
    # markup of signed-in pages, so checking signed-out markers first reported
    # a valid session as anonymous.
    if _selector_present(driver, _SUCCESS_SELECTORS):
        return True
    if _selector_present(driver, _SIGNED_OUT_SELECTORS):
        return False
    if trust_url and location.path.lower().startswith("/mnjuser"):
        return True
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
DASHBOARD_SIGN_IN_TIMEOUT_S = 300.0


def _wait_for_signed_in(driver: WebDriver, timeout: float = 8.0) -> bool:
    """Wait briefly for a signed-in marker to render, then report."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: is_logged_in(d, trust_url=False)
        )
        return True
    except TimeoutException:
        return is_logged_in(driver, trust_url=False)
    except WebDriverException as exc:
        logger.warning(
            "Could not wait for the signed-in marker (%s): %s", type(exc).__name__, exc
        )
        return False


def _visible_selector_present(driver: WebDriver, selectors: Tuple[str, ...]) -> bool:
    """Hidden login alternatives do not establish a sign-out or challenge."""
    for selector in selectors:
        try:
            if any(element.is_displayed() for element in driver.find_elements(By.CSS_SELECTOR, selector)):
                return True
        except (StaleElementReferenceException, WebDriverException):
            continue
    return False


def _managed_session_failure(driver: WebDriver, settings: Settings) -> LoginResult:
    """Explain observed evidence without treating every failed check as expiry."""
    text = _visible_page_text(driver)
    try:
        title = (getattr(driver, "title", "") or "").lower()
    except WebDriverException:
        title = ""
    denied = any(marker in text for marker in (
        "access denied", "request blocked", "you have been blocked", "unusual traffic",
        "you don’t have permission to access", "you don't have permission to access",
        "you do not have permission to access",
    )) or "access denied" in title
    if denied:
        return LoginResult(ok=False, needs_manual=False, reason=
            "Naukri is blocking access to this browser. Inspect the page for the site's instructions; "
            "this run cannot continue until Naukri allows access.")

    challenge = any(marker in text for marker in (*_CHALLENGE_TEXT, "verify you are human", "confirm it’s you"))
    # The login page offers "Login using OTP" to everyone. Only a request for
    # verification or an actual visible code field establishes a challenge.
    challenge = challenge or _visible_selector_present(driver, (
        "input[autocomplete='one-time-code']", "input[name*='otp']", "input[id*='otp']",
        "input[name*='captcha']", "input[id*='captcha']",
    ))
    if challenge:
        return LoginResult(ok=False, needs_manual=True, reason=
            "Naukri needs a security check. Open Connections → Naukri → Sign in, complete the verification, "
            "check sign-in, and close the browser before trying again.")

    login_page = False
    try:
        location = urlsplit(driver.current_url or "")
        host = (location.hostname or "").lower()
        login_page = (host == "login.naukri.com" or
                      (host in ("naukri.com", "www.naukri.com") and location.path.startswith(_LOGIN_URL_MARKER)))
    except (ValueError, WebDriverException):
        pass
    if login_page or _visible_selector_present(driver, _SIGNED_OUT_SELECTORS):
        from common.connections import read_metadata
        metadata = read_metadata(Path(settings.browser_profile_dir)) if settings.browser_profile_dir else {}
        recorded = metadata.get("naukri")
        previously_verified = isinstance(recorded, dict) and (
            recorded.get("state") == "connected" or bool(recorded.get("last_verified_at")))
        if previously_verified:
            reason = ("Naukri needs you to sign in again. Reconnect Naukri in Connections, check sign-in, "
                      "and close the browser before trying again.")
        else:
            reason = ("Naukri is not connected in this automation browser. Open Connections → Naukri → Sign in, "
                      "complete sign-in, check it, and close the browser before trying again.")
        return LoginResult(ok=False, reason=reason, needs_manual=True)

    return LoginResult(ok=False, needs_manual=False, reason=
        "Naukri loaded, but its sign-in status could not be verified. Try again in a moment. "
        "If this continues, check Naukri in Connections.")


def _wait_for_dashboard_sign_in(driver: WebDriver, settings: Settings, failure: LoginResult) -> LoginResult:
    """Pause only a verified, explicitly enabled dashboard browser for help."""
    if not settings.session_only or not settings.headless:
        return failure
    from common.browser_preview import assistance
    with assistance(driver, timeout_s=DASHBOARD_SIGN_IN_TIMEOUT_S, provider="naukri") as available:
        if not available:
            return failure
        # Keep the observed problem, but do not direct a person to Connections
        # while this run owns that profile. The live viewer uses this exact
        # browser and the lease prevents input after automation resumes.
        observed = failure.reason.split(". ", 1)[0].rstrip(".") + "."
        logger.warning(
            "%s Open browser in Activity to inspect the page and finish any sign-in or security check. "
            "Waiting up to %d minutes in this same background browser. Closing the viewer does not stop the agent.",
            observed, int(DASHBOARD_SIGN_IN_TIMEOUT_S / 60),
        )
        if not wait_for_manual_login(driver, timeout_s=DASHBOARD_SIGN_IN_TIMEOUT_S):
            try:
                closed = not driver.window_handles
            except WebDriverException:
                closed = True
            if closed:
                return LoginResult(ok=False, needs_manual=False, reason=
                    "The Naukri browser closed before sign-in could be verified. Start this agent again when you are ready.")
            return LoginResult(ok=False, needs_manual=failure.needs_manual, reason=
                f"{observed} Sign-in was not verified within {int(DASHBOARD_SIGN_IN_TIMEOUT_S / 60)} minutes. "
                "This run did not continue past sign-in. Start it again when you are ready to open its browser.")
    if not is_logged_in(driver, trust_url=False):
        return LoginResult(ok=False, needs_manual=False, reason=
            "Naukri sign-in changed before the agent could resume. Start this agent again and check its browser.")
    logger.info("Naukri sign-in verified. Resuming this agent in the background.")
    return LoginResult(ok=True, reason="dashboard_session_verified", needs_manual=False)


def _wait_for_visible_sign_in(driver: WebDriver, failure: LoginResult) -> LoginResult:
    """Use the agent's actual window, without creating a second browser session."""
    observed = failure.reason.split(". ", 1)[0].rstrip(".") + "."
    logger.warning(
        "%s Finish sign-in in the open Chrome window. Waiting up to %d minutes; "
        "keep this browser open. Stop the run from Activity if you want to cancel.",
        observed, int(DASHBOARD_SIGN_IN_TIMEOUT_S / 60),
    )
    if wait_for_manual_login(driver, timeout_s=DASHBOARD_SIGN_IN_TIMEOUT_S):
        logger.info("Naukri sign-in verified. Resuming this agent in the current Chrome window.")
        return LoginResult(ok=True, reason="visible_session_verified", needs_manual=False)
    try:
        closed = not driver.window_handles
    except WebDriverException:
        closed = True
    if closed:
        return LoginResult(ok=False, needs_manual=False, reason=
            "The Naukri browser closed before sign-in could be verified. Start this agent again when you are ready.")
    # The profile updater must not start another five-minute wait after this one.
    return LoginResult(ok=False, needs_manual=False, reason=
        f"{observed} Sign-in was not verified within {int(DASHBOARD_SIGN_IN_TIMEOUT_S / 60)} minutes. "
        "This run stopped before doing any application or profile work. Start it again when you are ready to sign in.")


def ensure_logged_in(driver: WebDriver, settings: Settings) -> LoginResult:
    """Reuse a saved session if there is one, otherwise log in.

    is_logged_in only inspects the page already open, and a fresh driver sits on
    about:blank, so the dashboard is loaded first. With a persistent browser
    profile this is normally all that happens: the login form is never touched,
    and that form is what intermittently reports itself as not interactable.
    """
    if is_logged_in(driver, trust_url=False):
        return LoginResult(ok=True, reason="session_reused", needs_manual=False)

    # trust_url=False: we just navigated to /mnjuser/ ourselves, so the URL
    # proves nothing. Only a real signed-in marker counts -- and the dashboard
    # paints those client-side, so checking the instant the navigation returns
    # found nothing and fell through to the login form, which Naukri does not
    # even serve to a browser that is already signed in.
    loaded = safe_get(driver, _DASHBOARD_URL)
    if loaded and _wait_for_signed_in(driver):
        logger.info("Reusing the saved Naukri session; no login needed")
        return LoginResult(ok=True, reason="session_reused", needs_manual=False)

    if settings.session_only:
        if not loaded:
            failure = LoginResult(ok=False, needs_manual=False, reason=
                "Could not load Naukri to check your saved sign-in. Check your connection and try again. "
                "Your saved connection has not been changed.")
        else:
            failure = _managed_session_failure(driver, settings)
        if loaded and not settings.headless:
            return _wait_for_visible_sign_in(driver, failure)
        return _wait_for_dashboard_sign_in(driver, settings, failure)

    logger.info("No saved session to reuse; logging in")

    return login(driver, settings)


def wait_for_manual_login(
    driver: WebDriver, timeout_s: float = 300.0, poll_s: float = 2.0
) -> bool:
    """Keep the same browser alive while a person finishes sign-in.

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
                logger.warning("The Naukri browser closed before sign-in could be verified")
                return False
        except WebDriverException as exc:
            logger.warning(
                "The browser went away before the sign-in finished (%s): %s",
                type(exc).__name__,
                exc,
            )
            return False
        if is_logged_in(driver, trust_url=False):
            logger.info("Naukri sign-in verified in the current browser session")
            return True
        if time.monotonic() >= deadline:
            logger.warning("Naukri sign-in was not verified within %.0f seconds", timeout_s)
            return False
        time.sleep(poll_s)
