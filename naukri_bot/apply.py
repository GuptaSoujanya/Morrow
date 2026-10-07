"""Verified application submission on Naukri job pages."""

import logging
import time
from typing import List, Optional, Tuple

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from .browser import human_pause, safe_get
from .chatbot import AnswerEngine, handle_chatbot
from .models import ApplyResult, ApplyStatus, JobPosting, Profile, Settings


logger = logging.getLogger(__name__)

_EXTERNAL_TEXT_XPATH = (
    "//button[contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply on company site')]"
    " | //a[contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply on company site')]"
)
_APPLY_TEXT_XPATH = (
    "//button[contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply')]"
    " | //a[contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'apply')]"
)
_SUCCESS_XPATH = (
    "//*[contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'successfully applied')"
    " or contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'application sent')]"
)
_QUOTA_XPATH = (
    "//*[contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'daily quota')"
    " or contains(translate(normalize-space(.),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'quota has been expired')]"
)
_APPLY_CONTROL_CSS = (
    "button#company-site-button, a#company-site-button, "
    "button[class*='company-site'], a[class*='company-site'], "
    "[class*='apply-button-container'] button, "
    "button#apply-button, a#apply-button, "
    "button[class*='apply-button'], a[class*='apply-button']"
)
_CONTROL_RENDER_TIMEOUT = 15.0


def _safe_url(driver: WebDriver) -> str:
    try:
        return driver.current_url or ""
    except WebDriverException as exc:
        logger.debug("Could not read the current URL: %s", exc)
        return ""


def _on_job_page(driver: WebDriver) -> bool:
    return "job-listings" in _safe_url(driver)


def _apply_controls_present(driver: WebDriver) -> bool:
    """Report whether a *visible* apply control or applied marker has rendered.

    Visibility matters, not mere presence. A Naukri job page ships two
    #apply-button elements and one of them is hidden, so a presence check
    matched instantly and the wait never waited: classification then looked for
    a visible control, found only the footer, and reported "no actionable apply
    control" on a perfectly live posting.
    """
    if _find_visible(driver, By.CSS_SELECTOR, _APPLY_CONTROL_CSS) is not None:
        return True
    if _find_visible(driver, By.XPATH, _EXTERNAL_TEXT_XPATH) is not None:
        return True
    if _find_visible(driver, By.XPATH, _APPLY_TEXT_XPATH) is not None:
        return True
    return bool(_applied_marker(driver))


def _wait_for_apply_controls(
    driver: WebDriver, timeout: float = _CONTROL_RENDER_TIMEOUT
) -> bool:
    """Wait for the apply control to render before classifying it.

    ``safe_get`` returns as soon as the shell document is ready, but Naukri
    paints the apply button client-side.  Classifying immediately finds an
    empty DOM, which is indistinguishable from a page that genuinely has no
    apply control - the failure mode that made a whole run report
    ``no_apply_button`` for every job.
    """
    try:
        WebDriverWait(driver, timeout).until(lambda d: _apply_controls_present(d))
        return True
    except TimeoutException:
        return False
    except WebDriverException as exc:
        logger.warning("Could not wait for the apply control: %s", exc)
        return False


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _displayed(elements: List[WebElement]) -> Optional[WebElement]:
    for element in elements:
        if element.is_displayed() and element.is_enabled():
            return element
    return None


def _find_visible(driver: WebDriver, by: str, selector: str) -> Optional[WebElement]:
    return _displayed(driver.find_elements(by, selector))


def _element_text(element: WebElement) -> str:
    return " ".join((element.text or element.get_attribute("innerText") or "").split())


def classify_apply_button(driver: WebDriver) -> Tuple[Optional[WebElement], str]:
    """Return the first actionable apply control and its destination class."""
    external_css = (
        "button#company-site-button, a#company-site-button, "
        "button[class*='company-site'], a[class*='company-site']"
    )
    external = _find_visible(driver, By.CSS_SELECTOR, external_css)
    if external is None:
        external = _find_visible(driver, By.XPATH, _EXTERNAL_TEXT_XPATH)
    if external is not None:
        return external, "external"

    # Naukri renders Save and Apply as siblings inside the apply container, with
    # Save first. Matching the container generically picks Save and silently
    # un-saves the job instead of applying, so the real id is tried first and the
    # container fallback refuses anything that looks like a save control.
    native_by_id = _find_visible(
        driver, By.CSS_SELECTOR, "button#apply-button, a#apply-button"
    )
    if native_by_id is not None:
        return native_by_id, "native"

    wrapper_button = _find_visible(
        driver,
        By.CSS_SELECTOR,
        "[class*='apply-button-container'] button:not([class*='save'])"
        ":not([class*='Save'])",
    )
    if wrapper_button is not None:
        return wrapper_button, "native"

    native_css = (
        "button#apply-button, a#apply-button, "
        "button[class*='apply-button']:not([class*='company-site']), "
        "a[class*='apply-button']:not([class*='company-site'])"
    )
    candidates = driver.find_elements(By.CSS_SELECTOR, native_css)
    candidates.extend(driver.find_elements(By.XPATH, _APPLY_TEXT_XPATH))
    for candidate in candidates:
        if not candidate.is_displayed() or not candidate.is_enabled():
            continue
        text = _normalise(_element_text(candidate))
        element_id = _normalise(candidate.get_attribute("id") or "")
        classes = _normalise(candidate.get_attribute("class") or "")
        if "company site" in text or "company-site" in classes:
            return candidate, "external"
        text_is_apply = (
            text == "apply"
            or text.startswith("apply ")
            or text.endswith(" apply")
            or " apply " in text
        )
        if element_id == "apply-button" or "apply-button" in classes or text_is_apply:
            return candidate, "native"
    return None, ""


def _visible_message(driver: WebDriver, xpath: str) -> str:
    for element in driver.find_elements(By.XPATH, xpath):
        if element.is_displayed():
            return _element_text(element)
    return ""


def _applied_marker(driver: WebDriver) -> str:
    selectors = (
        "button.already-applied, a.already-applied, .already-applied, "
        "[class*='applied'], [id='apply-button'][disabled]"
    )
    for element in driver.find_elements(By.CSS_SELECTOR, selectors):
        if element.is_displayed():
            text = _element_text(element)
            if _normalise(text) == "applied" or "already applied" in _normalise(text):
                return text or "Applied"
    exact = _find_visible(
        driver,
        By.XPATH,
        "//*[translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        "'abcdefghijklmnopqrstuvwxyz')='applied']",
    )
    return _element_text(exact) if exact is not None else ""


def verify_applied(driver: WebDriver, timeout: int = 15) -> Tuple[bool, str]:
    """Positively confirm submission using a success message or applied state."""
    deadline = time.monotonic() + timeout
    while True:
        message = _visible_message(driver, _SUCCESS_XPATH)
        if message:
            return True, "confirmation: %s" % message
        marker = _applied_marker(driver)
        if marker:
            return True, "applied state: %s" % marker
        if time.monotonic() >= deadline:
            break
        human_pause(0.25, 0.6)
    return False, "no success confirmation or applied-state marker"


def _result(
    job: JobPosting,
    status: str,
    detail: str,
    quota_consumed: bool = False,
    answered: int = 0,
    abstained: int = 0,
) -> ApplyResult:
    return ApplyResult(
        job_id=job.job_id,
        url=job.url,
        status=status,
        detail=detail,
        quota_consumed=quota_consumed,
        questions_answered=answered,
        questions_abstained=abstained,
    )


def _visible_control_texts(driver: WebDriver, limit: int = 10) -> str:
    """List the visible clickable labels on the page, for diagnosis.

    An apply control matched _apply_controls_present but classification found
    nothing to click, and the two are impossible to tell apart from the status
    alone. Naming what was actually on screen turns that into a one-line
    diagnosis, the way reporting 'continue with google' identified a signed-out
    session immediately.
    """
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button']")
    except WebDriverException as exc:
        logger.debug("Could not list page controls: %s", exc)
        return ""

    seen = []
    for element in elements:
        try:
            if not element.is_displayed():
                continue
            text = _normalise(_element_text(element) or "")
        except WebDriverException:
            continue
        if not text or len(text) > 40 or text in seen:
            continue
        seen.append(text)
        if len(seen) >= limit:
            break
    return repr(seen) if seen else ""


def _looks_logged_out(driver: WebDriver) -> bool:
    try:
        controls = driver.find_elements(
            By.XPATH,
            "//*[contains(translate(normalize-space(.),"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            "'continue with google')]",
        )
    except WebDriverException as exc:
        logger.debug("Could not check the sign-in state: %s", exc)
        return False
    return any(control.is_displayed() for control in controls)


def _reload_and_check_applied(driver: WebDriver, job: JobPosting) -> str:
    # Naukri never flips the apply container in place. Both confirmed
    # applications showed nothing for the full verification window, then
    # rendered span#already-applied on a fresh load of the same job page.
    if not safe_get(driver, job.url):
        return ""
    if not _on_job_page(driver):
        safe_get(driver, job.url)
    _wait_for_apply_controls(driver)
    return _applied_marker(driver)


def apply_to_job(
    driver: WebDriver,
    job: JobPosting,
    profile: Profile,
    answer_engine: AnswerEngine,
    settings: Settings,
) -> ApplyResult:
    """Attempt one Naukri-native application and report only verified outcomes."""
    if settings.dry_run:
        logger.info("[DRY RUN] Would apply to %s at %s", job.job_id, job.url)
        return _result(job, ApplyStatus.APPLIED, "dry_run_no_navigation_or_click")

    try:
        if not safe_get(driver, job.url):
            return _result(job, ApplyStatus.ERROR, "navigation_failed")

        # The first navigation of a fresh session bounces to the dashboard even
        # though the job URL is valid; the same load succeeds on a second try.
        if not _on_job_page(driver):
            logger.info("Job page bounced to %s; retrying once", _safe_url(driver))
            human_pause()
            if not safe_get(driver, job.url):
                return _result(job, ApplyStatus.ERROR, "navigation_failed")

        if _looks_logged_out(driver):
            return _result(job, ApplyStatus.SESSION_EXPIRED, "signed out of Naukri")

        rendered = _wait_for_apply_controls(driver)

        button, classification = classify_apply_button(driver)
        if button is None:
            marker = _applied_marker(driver)
            if marker:
                return _result(job, ApplyStatus.ALREADY_APPLIED, marker)
            if not rendered:
                return _result(
                    job,
                    ApplyStatus.NO_APPLY_BUTTON,
                    "no apply control rendered within %ds" % int(_CONTROL_RENDER_TIMEOUT),
                )
            return _result(
                job,
                ApplyStatus.NO_APPLY_BUTTON,
                "no actionable apply control; page offered %s"
                % (_visible_control_texts(driver) or "no visible buttons or links"),
            )
        if classification == "external":
            text = _element_text(button) or "Apply on company site"
            logger.info(
                "Skipping job %s: %r leaves Naukri, consumes no Naukri quota, "
                "and cannot be tracked as a Naukri application",
                job.job_id,
                text,
            )
            return _result(job, ApplyStatus.EXTERNAL_SKIPPED, "external button: %s" % text)

        try:
            button.click()
        except ElementClickInterceptedException as exc:
            logger.warning("Native apply click was intercepted; using JS fallback: %s", exc)
            driver.execute_script("arguments[0].click();", button)

        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            quota_message = _visible_message(driver, _QUOTA_XPATH)
            if quota_message:
                return _result(job, ApplyStatus.QUOTA_EXPIRED, quota_message)

            drawer = _find_visible(
                driver, By.CSS_SELECTOR, "[id*='ChatbotContainer'], .chatbot_Drawer"
            )
            if drawer is not None:
                outcome = handle_chatbot(driver, profile, answer_engine, settings)
                if outcome.abstained > 0:
                    return _result(
                        job,
                        ApplyStatus.ABSTAINED,
                        outcome.reason,
                        False,
                        outcome.answered,
                        outcome.abstained,
                    )
                if not outcome.completed:
                    return _result(
                        job,
                        ApplyStatus.CHATBOT_TIMEOUT,
                        outcome.reason,
                        False,
                        outcome.answered,
                        outcome.abstained,
                    )
                quota_message = _visible_message(driver, _QUOTA_XPATH)
                if quota_message:
                    return _result(
                        job,
                        ApplyStatus.QUOTA_EXPIRED,
                        quota_message,
                        False,
                        outcome.answered,
                        outcome.abstained,
                    )
                verified, detail = verify_applied(driver)
                if not verified:
                    marker = _reload_and_check_applied(driver, job)
                    if marker:
                        verified = True
                        detail = "applied state confirmed on reload: %s" % marker
                status = ApplyStatus.APPLIED if verified else ApplyStatus.ERROR
                return _result(
                    job,
                    status,
                    detail,
                    verified,
                    outcome.answered,
                    outcome.abstained,
                )

            if _visible_message(driver, _SUCCESS_XPATH) or _applied_marker(driver):
                verified, detail = verify_applied(driver)
                if verified:
                    return _result(job, ApplyStatus.APPLIED, detail, True)
                return _result(job, ApplyStatus.ERROR, detail)
            human_pause(0.25, 0.6)

        marker = _reload_and_check_applied(driver, job)
        if marker:
            return _result(
                job,
                ApplyStatus.APPLIED,
                "applied state confirmed on reload: %s" % marker,
                True,
            )

        controls: List[str] = []
        try:
            controls = [
                _normalise(_element_text(element))
                for element in driver.find_elements(By.CSS_SELECTOR, _APPLY_CONTROL_CSS)
                if element.is_displayed()
            ]
        except WebDriverException as exc:
            logger.debug("Could not inventory apply controls: %s", exc)
        return _result(
            job,
            ApplyStatus.ERROR,
            "application outcome was not verified (url=%s, controls=%s)"
            % (_safe_url(driver) or "unknown", controls or "none"),
        )
    except (
        TimeoutException,
        NoSuchElementException,
        StaleElementReferenceException,
        WebDriverException,
    ) as exc:
        detail = "%s: %s" % (type(exc).__name__, exc)
        logger.error("Apply failed for job %s (%s)", job.job_id, detail)
        return _result(job, ApplyStatus.ERROR, detail)


__all__ = ["apply_to_job", "classify_apply_button", "verify_applied"]
