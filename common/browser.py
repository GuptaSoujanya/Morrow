"""Browser creation and human-like interaction helpers."""

import logging
import math
import os
import random
import time
from typing import List, Optional

from requests.exceptions import RequestException
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from .models import Settings


logger = logging.getLogger(__name__)


class BrowserError(Exception):
    """Raised when no supported browser driver can be started."""


_CHROME_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_EDGE_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
)
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
"""


def profile_dir_for(settings: Settings, browser: str) -> Optional[str]:
    """Absolute per-browser profile directory, or None when disabled.

    Chrome and Edge must not share a user-data directory, so each gets its own
    subdirectory under the configured base.
    """
    raw = (settings.browser_profile_dir or "").strip()
    if not raw:
        return None
    return os.path.join(os.path.abspath(os.path.expanduser(raw)), browser)


def _add_common_options(options, user_agent: str, headless: bool,
                        profile: Optional[str] = None, background: bool = False) -> None:
    headless = headless or background
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if user_agent:
        options.add_argument("--user-agent=%s" % user_agent)
    if os.environ.get("CHROME_WINDOW_SIZE"):
        # A virtual screen (docker/) has no window manager to maximise to, so fill it exactly.
        options.add_argument("--window-position=0,0")
        options.add_argument("--window-size=%s" % os.environ["CHROME_WINDOW_SIZE"])
    else:
        options.add_argument("--window-size=1440,900")
        if not headless:
            # Override a corner position saved by the previous off-screen
            # mode before Chrome can restore it. Centre once after startup.
            options.add_argument("--window-position=0,0")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    if profile:
        # Keeps cookies between runs, so a verified session is reused and the
        # login form is never touched while it holds.
        os.makedirs(profile, exist_ok=True)
        options.add_argument("--user-data-dir=%s" % profile)
    if headless:
        options.add_argument("--headless=new")


def _chrome_options(
    settings: Settings, profile: Optional[str] = None
) -> webdriver.ChromeOptions:
    options = webdriver.ChromeOptions()
    if os.environ.get("CHROME_BINARY"):  # set in the Docker image: Debian's chromium
        options.binary_location = os.environ["CHROME_BINARY"]
    _add_common_options(options, settings.user_agent, settings.headless, profile, settings.background)
    return options


def _edge_options(
    settings: Settings, profile: Optional[str] = None
) -> webdriver.EdgeOptions:
    options = webdriver.EdgeOptions()
    _add_common_options(options, settings.user_agent, settings.headless, profile, settings.background)
    return options


def _configure_driver(driver: WebDriver) -> WebDriver:
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(0)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _STEALTH_SCRIPT},
        )
    except (AttributeError, WebDriverException) as exc:
        logger.warning(
            "Could not install the browser anti-detection script (%s): %s",
            type(exc).__name__,
            exc,
        )
    return driver


def _discard_driver(driver: WebDriver) -> None:
    try:
        driver.quit()
    except WebDriverException as exc:
        logger.warning(
            "Could not close a failed browser session (%s): %s",
            type(exc).__name__,
            exc,
        )


def create_driver(settings: Settings) -> webdriver.Remote:
    """Create a stealth-configured Chrome or Edge WebDriver.

    Tries the persistent profile first and falls back to a throwaway session if
    that fails, because a profile directory already held open by another Chrome
    window cannot be reused and must not block the morning run.
    """
    if settings.session_only:
        from .connections import create_driver as managed_driver
        return _register_preview(managed_driver(settings))
    if settings.background:
        settings.headless = True
    if profile_dir_for(settings, "chrome") is None:
        return _register_preview(_position_visible_window(_try_create_driver(settings, use_profile=False), settings))
    try:
        return _register_preview(_position_visible_window(_try_create_driver(settings, use_profile=True), settings))
    except BrowserError as exc:
        logger.warning(
            "Could not start a browser with the persistent profile (%s). Close "
            "any Chrome window using it. Continuing without it, so this run "
            "will log in from scratch.",
            exc,
        )
        return _register_preview(_position_visible_window(_try_create_driver(settings, use_profile=False), settings))


def _register_preview(driver):
    from .browser_preview import register
    register(driver)
    return driver


def _position_visible_window(driver: webdriver.Remote, settings: Settings) -> webdriver.Remote:
    """Place an intentional visible window once; never move it between tabs."""
    if settings.headless or settings.background or os.environ.get("CHROME_WINDOW_SIZE"):
        return driver
    try:
        screen = driver.execute_script(
            "return {width: screen.availWidth, height: screen.availHeight, "
            "left: screen.availLeft ?? 0, top: screen.availTop ?? 0};"
        )
        if not isinstance(screen, dict):
            return driver

        def number(value) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

        available_width, available_height = screen.get("width"), screen.get("height")
        if not all(number(value) and value >= 1 for value in (available_width, available_height)):
            return driver
        left, top = screen.get("left", 0), screen.get("top", 0)
        if not all(number(value) for value in (left, top)):
            return driver
        width, height = int(min(1440, available_width)), int(min(900, available_height))
        driver.set_window_rect(
            x=int(left + (available_width - width) / 2),
            y=int(top + (available_height - height) / 2),
            width=width, height=height,
        )
    except (AttributeError, TypeError, ValueError, WebDriverException) as exc:
        # Startup arguments still leave a usable window near the origin when
        # a remote driver or desktop cannot report its screen geometry.
        logger.debug("Could not centre the browser window: %s", exc)
    return driver


def _try_create_driver(settings: Settings, use_profile: bool) -> webdriver.Remote:
    if settings.headless:
        logger.info("Browser is running in the background without a window.")

    failures: List[str] = []
    driver = None
    try:
        driver = webdriver.Chrome(
            # CHROMEDRIVER (the Docker image) skips the download: there is no linux-arm64 build to fetch.
            service=ChromeService(os.environ.get("CHROMEDRIVER") or ChromeDriverManager().install()),
            options=_chrome_options(
                settings, profile_dir_for(settings, "chrome") if use_profile else None
            ),
        )
        configured = _configure_driver(driver)
        logger.info(
            "Using Chrome with webdriver-manager%s",
            " and the persistent profile" if use_profile else "",
        )
        return configured
    except (WebDriverException, RequestException, OSError) as exc:
        failures.append("Chrome/webdriver-manager: %s" % type(exc).__name__)
        logger.warning(
            "Chrome via webdriver-manager failed (%s): %s",
            type(exc).__name__,
            exc,
        )
        if driver is not None:
            _discard_driver(driver)

    driver = None
    try:
        driver = webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=_edge_options(
                settings, profile_dir_for(settings, "edge") if use_profile else None
            ),
        )
        configured = _configure_driver(driver)
        logger.info("Using Edge with webdriver-manager")
        return configured
    except (WebDriverException, RequestException, OSError) as exc:
        failures.append("Edge/webdriver-manager: %s" % type(exc).__name__)
        logger.warning(
            "Edge via webdriver-manager failed (%s): %s",
            type(exc).__name__,
            exc,
        )
        if driver is not None:
            _discard_driver(driver)

    driver = None
    try:
        driver = webdriver.Chrome(
            options=_chrome_options(
                settings, profile_dir_for(settings, "chrome") if use_profile else None
            )
        )
        configured = _configure_driver(driver)
        logger.info("Using Chrome with Selenium Manager")
        return configured
    except (WebDriverException, OSError) as exc:
        failures.append("Chrome/Selenium Manager: %s" % type(exc).__name__)
        logger.error(
            "Chrome via Selenium Manager failed (%s): %s",
            type(exc).__name__,
            exc,
        )
        if driver is not None:
            _discard_driver(driver)

    raise BrowserError(
        "Could not start Chrome or Edge. Install a supported browser, check network "
        "access for webdriver-manager, and ensure Selenium Manager can write its "
        "driver cache. Attempts: %s" % "; ".join(failures)
    )


def human_pause(low: float = 0.8, high: float = 2.4) -> None:
    """Pause for a random human-like interval."""
    time.sleep(random.uniform(low, high))


def human_type(
    element: WebElement,
    text: str,
    min_delay: float = 0.04,
    max_delay: float = 0.14,
) -> None:
    """Type text character by character with a randomized delay."""
    for character in text:
        element.send_keys(character)
        time.sleep(random.uniform(min_delay, max_delay))


def safe_get(driver: WebDriver, url: str, attempts: int = 3) -> bool:
    """Navigate with bounded retries and exponential jittered backoff."""
    for attempt in range(attempts):
        try:
            driver.get(url)
            return True
        except (TimeoutException, WebDriverException) as exc:
            logger.warning(
                "Navigation to %s failed on attempt %d/%d (%s): %s",
                url,
                attempt + 1,
                attempts,
                type(exc).__name__,
                exc,
            )
            if attempt + 1 < attempts:
                delay = (2.0 ** attempt) + random.uniform(0.0, 0.75)
                time.sleep(delay)
    return False
