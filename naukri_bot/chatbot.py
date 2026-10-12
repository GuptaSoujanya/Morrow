"""Fail-closed handling of Naukri's application chatbot drawer."""

# noqa: SIZE_OK - the requested drawer state machine must remain in this module.

import logging
import time
from typing import Any, List, Optional, Protocol, Tuple

from selenium.common.exceptions import (
    ElementClickInterceptedException,
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

from common.browser import human_pause, human_type
from common.models import AnswerResolution, ChatbotOutcome, Profile, Settings


logger = logging.getLogger(__name__)

_DRAWER = "[id*='ChatbotContainer'], .chatbot_Drawer"
_BOT_MESSAGES = ".chatbot_ListItem.botItem .msg, .chatbot_ListItem .botMsg .msg"
_USER_MESSAGES = ".chatbot_ListItem.userItem .msg, .userMsg .msg"
_RADIO_CONTAINER = ".singleselect-radiobutton-container"
_RADIOS = ".ssrc__radio"
_RADIO_LABELS = ".ssrc__label"
_SEND = ".sendMsg, .sendMsgbtn_container .sendMsg, [class*='sendMsg']"
_TEXT_AREAS = (
    ".chatbot_SendMessageContainer .textArea[contenteditable='true'], "
    ".chatbot_InputContainer .textArea[contenteditable='true'], "
    "div.textArea[contenteditable='true'], [contenteditable='true']"
)
_PLAIN_INPUTS = "input:not([type]), input[type='text'], input[type='number'], textarea"
_CHECKBOXES = "input[type='checkbox'], [role='checkbox']"
# Naukri's multi-select renders hidden checkboxes styled through their labels,
# so the inputs are never displayed and a visibility filter discarded them all:
# "Please select the city you are currently residing in" stalled for thirty
# seconds with every handler reporting nothing to do.
_CHECKBOX_CONTAINER = ".multiselectcheckboxes, .multicheckboxes-container"
_CHECKBOX_LABELS = ".mcc__label"
_OVERALL_TIMEOUT = 180.0
_STALL_TIMEOUT = 30.0
_QUESTION_WAIT = 8.0


class AnswerEngine(Protocol):
    def resolve(
        self,
        question: str,
        options: Optional[List[str]] = None,
        field_type: str = "text",
    ) -> AnswerResolution:
        ...

    def set_job_context(self, job: Any) -> None:
        """Optional: name the posting these questions belong to.

        apply_to_job calls this when the engine provides it, so a question with
        no city in it can still be answered from the posting's location.
        """
        ...


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _visible(elements: List[WebElement]) -> List[WebElement]:
    return [element for element in elements if element.is_displayed()]


def _latest_question(driver: WebDriver, wait_s: float = 0.0) -> str:
    """Read the newest bot message, optionally waiting for it to paint.

    The drawer becomes visible before Naukri renders the question inside it.
    Reading immediately returns the placeholder, which the answer engine then
    dutifully abstains on - the question it was handed genuinely was not
    answerable. Handlers therefore wait; the state sampler does not.
    """
    deadline = time.monotonic() + max(0.0, wait_s)
    while True:
        messages = _visible(driver.find_elements(By.CSS_SELECTOR, _BOT_MESSAGES))
        if messages:
            text = " ".join(messages[-1].text.split())
            if text:
                return text
        if time.monotonic() >= deadline:
            return "unidentified chatbot question"
        time.sleep(0.25)


def is_drawer_open(driver: WebDriver) -> bool:
    """Return whether a visible chatbot drawer is present."""
    try:
        return bool(_visible(driver.find_elements(By.CSS_SELECTOR, _DRAWER)))
    except (StaleElementReferenceException, WebDriverException) as exc:
        logger.warning("Could not inspect chatbot drawer (%s): %s", type(exc).__name__, exc)
        raise


def find_chat_text_area(driver: WebDriver) -> Optional[WebElement]:
    """Find a visible, enabled contenteditable chatbot input."""
    try:
        for element in driver.find_elements(By.CSS_SELECTOR, _TEXT_AREAS):
            if element.is_displayed() and element.is_enabled():
                return element
    except (StaleElementReferenceException, WebDriverException) as exc:
        logger.warning("Could not locate chatbot text area (%s): %s", type(exc).__name__, exc)
    return None


def _read_contenteditable(element: WebElement) -> str:
    candidates = (
        element.text,
        element.get_attribute("innerText") or "",
        element.get_attribute("textContent") or "",
    )
    for candidate in candidates:
        if candidate.strip():
            return _normalise(candidate)
    return ""


_TYPE_KEY_BY_KEY_LIMIT = 120


def _insert_text(driver: WebDriver, element: WebElement, text: str) -> None:
    """Put text in a contenteditable in one step, firing the events a React
    chat box listens for."""
    driver.execute_script(
        "arguments[0].focus();"
        "var r=document.createRange();r.selectNodeContents(arguments[0]);"
        "var s=window.getSelection();s.removeAllRanges();s.addRange(r);"
        "document.execCommand('insertText',false,arguments[1]);"
        "arguments[0].dispatchEvent(new InputEvent('input',"
        "{bubbles:true,inputType:'insertText',data:arguments[1]}));"
        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
        element,
        text,
    )


def write_contenteditable(driver: WebDriver, element: WebElement, text: str) -> bool:
    """Type with real key events and return true only after DOM verification."""
    # Newlines are Enter in a chat box, which submits the message half-written,
    # so they never reach the keyboard.
    text = " ".join(text.split())
    intended = _normalise(text)
    try:
        element.click()
        platform_name = str(driver.capabilities.get("platformName", "")).casefold()
        modifier = Keys.COMMAND if "mac" in platform_name else Keys.CONTROL
        element.send_keys(modifier, "a")
        element.send_keys(Keys.DELETE)

        # Key-by-key typing runs at 40-140ms per character, so a long answer
        # takes close to a minute, and Naukri re-renders the drawer within that
        # window: three applications failed with a stale element mid-write. Keep
        # the human pacing for short answers and insert longer ones at once.
        if len(text) > _TYPE_KEY_BY_KEY_LIMIT:
            logger.info(
                "Inserting a %d character answer at once rather than typing it",
                len(text),
            )
            _insert_text(driver, element, text)
        else:
            human_type(element, text)

        if _read_contenteditable(element) == intended:
            return True
        logger.warning("Real key events did not produce the requested chatbot text; retrying")
        _insert_text(driver, element, text)
        verified = _read_contenteditable(element) == intended
        if not verified:
            logger.error("Chatbot contenteditable write could not be verified")
        return verified
    except (StaleElementReferenceException, ElementClickInterceptedException, WebDriverException) as exc:
        logger.error("Could not write chatbot text (%s): %s", type(exc).__name__, exc)
        return False


def _send_control(driver: WebDriver) -> Optional[WebElement]:
    for element in driver.find_elements(By.CSS_SELECTOR, _SEND):
        if element.is_displayed():
            return element
    return None


def _send_is_disabled(control: WebElement) -> bool:
    """Read disabled state from the button and any wrapper carrying it."""
    ancestors = control.find_elements(
        By.XPATH,
        "./ancestor::*[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
        "'abcdefghijklmnopqrstuvwxyz'),'send')]",
    )
    classes = " ".join(
        [control.get_attribute("class") or ""]
        + [ancestor.get_attribute("class") or "" for ancestor in ancestors]
    )
    if "disabled" in classes.casefold():
        return True
    if (control.get_attribute("aria-disabled") or "").casefold() == "true":
        return True
    return not control.is_enabled()


def click_send(driver: WebDriver, wait_s: float = 6.0) -> bool:
    """Click the send control, waiting briefly for it to become enabled.

    The chatbot enables the button in response to its own input handling, which
    happens after the text is in the DOM. Checking the instant the text was
    written found it still disabled and gave up, so every answer long enough to
    be inserted in one step was left unsent and the application never
    confirmed: four of four such jobs failed in one run. Short answers typed
    key by key took seconds, by which time the button had long since enabled,
    which is why only long answers were affected.
    """
    try:
        control = _send_control(driver)
        if control is None:
            return False

        deadline = time.monotonic() + max(0.0, wait_s)
        while _send_is_disabled(control) and time.monotonic() < deadline:
            time.sleep(0.25)
            refreshed = _send_control(driver)
            if refreshed is not None:
                control = refreshed
        if _send_is_disabled(control):
            logger.warning(
                "Send control still disabled after %.0fs; leaving the answer unsent",
                wait_s,
            )
            return False
        control.click()
        return True
    except (
        NoSuchElementException,
        StaleElementReferenceException,
        ElementClickInterceptedException,
        WebDriverException,
    ) as exc:
        logger.warning("Could not click chatbot send control (%s): %s", type(exc).__name__, exc)
        return False


def _wait_for_option_labels(
    container: WebElement, timeout: float = 4.0
) -> List[str]:
    """Read option labels, waiting briefly for their text to paint.

    Reading them the instant the drawer appears yields a list of blank strings,
    which is worse than none at all: the question still looks like a choice but
    there is nothing to choose from.
    """
    deadline = time.monotonic() + timeout
    options: List[str] = []
    while time.monotonic() < deadline:
        try:
            labels = container.find_elements(By.CSS_SELECTOR, _RADIO_LABELS)
            options = [" ".join(label.text.split()) for label in labels]
        except (StaleElementReferenceException, WebDriverException):
            return options
        if options and all(option for option in options):
            return options
        time.sleep(0.25)
    return options


def handle_radio(driver: WebDriver, answer_engine: AnswerEngine) -> Optional[bool]:
    """Resolve, select, verify, and send the visible radio question."""
    containers = _visible(driver.find_elements(By.CSS_SELECTOR, _RADIO_CONTAINER))
    if not containers:
        return False
    container = containers[0]
    radios = container.find_elements(By.CSS_SELECTOR, _RADIOS)
    asked_with = _wait_for_option_labels(container)
    question = _latest_question(driver, _QUESTION_WAIT)
    resolution = answer_engine.resolve(
        question, options=asked_with, field_type="radio"
    )
    if resolution.abstained or resolution.answer is None:
        return None
    # Resolving takes seconds - waiting for the question to paint, then an LLM
    # call - and Naukri re-renders the drawer in that window, so any handle
    # captured earlier is stale by now.
    containers = _visible(driver.find_elements(By.CSS_SELECTOR, _RADIO_CONTAINER))
    if not containers:
        logger.error("Radio options disappeared while the answer was resolved")
        return None
    container = containers[0]
    radios = container.find_elements(By.CSS_SELECTOR, _RADIOS)
    labels = container.find_elements(By.CSS_SELECTOR, _RADIO_LABELS)
    options = [" ".join(label.text.split()) for label in labels]
    usable = [option for option in options if option and option.strip()]
    wanted = _normalise(resolution.answer.text)
    for index, radio in enumerate(radios):
        label_text = options[index] if index < len(options) else ""
        value = radio.get_attribute("value") or ""
        if _normalise(label_text) != wanted and _normalise(value) != wanted:
            continue
        target = labels[index] if index < len(labels) else radio
        target.click()
        if not radio.is_selected():
            logger.error("Radio option %r did not become selected", resolution.answer.text)
            return False
        return click_send(driver)
    # The answer did not match. If it was resolved without usable options -- the
    # labels had not painted when it was asked -- ask again now that they have.
    # Three applications were abandoned this way with answers that plainly meant
    # one of the choices, phrased as prose: "No, cannot attend walk-in drives"
    # against ['Yes', 'No'].
    asked_usable = [o for o in asked_with if o and o.strip()]
    if usable and usable != asked_usable:
        logger.info(
            "Re-resolving %r now that the options have rendered: %s", question, usable
        )
        retry = answer_engine.resolve(question, options=usable, field_type="radio")
        if not retry.abstained and retry.answer is not None:
            for index, option in enumerate(options):
                if _normalise(option) != _normalise(retry.answer.text):
                    continue
                target = labels[index] if index < len(labels) else radios[index]
                target.click()
                if not radios[index].is_selected():
                    logger.error("Radio option %r did not become selected", option)
                    return False
                return click_send(driver)

    answer_engine.record_option_mismatch(question, resolution.answer.text, usable)
    return None


def handle_text(driver: WebDriver, answer_engine: AnswerEngine) -> Optional[bool]:
    """Resolve, verifiably type, and send a contenteditable question."""
    text_area = find_chat_text_area(driver)
    if text_area is None:
        return False
    question = _latest_question(driver, _QUESTION_WAIT)
    resolution = answer_engine.resolve(question, options=None, field_type="text")
    if resolution.abstained or resolution.answer is None:
        return None
    # Resolving takes seconds - waiting for the question to paint, then an LLM
    # call - and Naukri re-renders the drawer in that window, so any handle
    # captured earlier is stale by now.
    text_area = find_chat_text_area(driver)
    if text_area is None:
        logger.error("Chatbot input disappeared while the answer was resolved")
        return None
    if not write_contenteditable(driver, text_area, resolution.answer.text):
        return None
    return click_send(driver)


def _checkbox_target(container: WebElement, control: WebElement) -> WebElement:
    """The element to click for a checkbox: its label when the input is hidden."""
    control_id = control.get_attribute("id") or ""
    if control_id:
        labels = container.find_elements(
            By.CSS_SELECTOR, "label[for='%s']" % control_id.replace("'", "\\'")
        )
        for label in labels:
            try:
                if label.is_displayed():
                    return label
            except WebDriverException:
                continue
    return control


def _selectable_checkboxes(drawer: WebElement) -> List[WebElement]:
    """Checkboxes a person could tick, including ones hidden behind a label.

    Requiring the input itself to be displayed found nothing on Naukri's
    multi-select, because it hides the inputs and styles their labels.
    """
    controls = drawer.find_elements(By.CSS_SELECTOR, _CHECKBOXES)
    usable = []
    for control in controls:
        try:
            if control.is_displayed() or _checkbox_target(drawer, control) is not control:
                usable.append(control)
        except WebDriverException:
            continue
    return usable


def _option_label(container: WebElement, control: WebElement) -> str:
    control_id = control.get_attribute("id") or ""
    if control_id:
        labels = container.find_elements(By.CSS_SELECTOR, "label[for='%s']" % control_id)
        if labels:
            return " ".join(labels[0].text.split())
    return " ".join((control.get_attribute("value") or control.text).split())


def _handle_checkbox(driver: WebDriver, answer_engine: AnswerEngine) -> Optional[bool]:
    """Answer a select-all-that-apply question by ticking every match.

    Previously this resolved a single answer and ticked the one option equal to
    it, so a question wanting several was unanswerable and silently abandoned.
    """
    drawers = _visible(driver.find_elements(By.CSS_SELECTOR, _DRAWER))
    if not drawers:
        return False
    controls = _selectable_checkboxes(drawers[0])
    if not controls:
        return False

    options = [_option_label(drawers[0], control) for control in controls]
    question = _latest_question(driver, _QUESTION_WAIT)
    if not any(option.strip() for option in options):
        logger.error(
            "Checkbox question %r rendered %d control(s) with no readable labels",
            question,
            len(controls),
        )
        return None

    selections, _reason = answer_engine.resolve_many(question, options)
    if not selections:
        return None

    # Resolving takes seconds and Naukri re-renders the drawer in that window,
    # so every handle captured before the call is stale.
    drawers = _visible(driver.find_elements(By.CSS_SELECTOR, _DRAWER))
    if not drawers:
        logger.error("Chatbot drawer disappeared while the answer was resolved")
        return None
    controls = _selectable_checkboxes(drawers[0])
    if not controls:
        logger.error("Checkbox options disappeared while the answer was resolved")
        return None
    options = [_option_label(drawers[0], control) for control in controls]

    wanted = {_normalise(selection) for selection in selections}
    ticked = []
    for index, option in enumerate(options):
        if _normalise(option) not in wanted:
            continue
        try:
            if not controls[index].is_selected():
                _checkbox_target(drawers[0], controls[index]).click()
            if not controls[index].is_selected():
                logger.error("Checkbox option %r did not become selected", option)
                return False
            ticked.append(option)
        except (ElementClickInterceptedException, WebDriverException) as exc:
            logger.error("Could not tick %r (%s): %s", option, type(exc).__name__, exc)
            return False

    if not ticked:
        answer_engine.record_option_mismatch(question, ", ".join(selections), options)
        return None
    if len(ticked) != len(selections):
        logger.warning(
            "Ticked %d of %d selections for %r; missing %s",
            len(ticked),
            len(selections),
            question,
            [sel for sel in selections if _normalise(sel) not in {_normalise(t) for t in ticked}],
        )
    logger.info("Selected %s for %r", ticked, question)
    return click_send(driver)


def _handle_plain_text(driver: WebDriver, answer_engine: AnswerEngine) -> Optional[bool]:
    drawers = _visible(driver.find_elements(By.CSS_SELECTOR, _DRAWER))
    if not drawers:
        return False
    controls = [
        element
        for element in drawers[0].find_elements(By.CSS_SELECTOR, _PLAIN_INPUTS)
        if element.is_displayed() and element.is_enabled()
    ]
    if not controls:
        return False
    question = _latest_question(driver, _QUESTION_WAIT)
    resolution = answer_engine.resolve(question, options=None, field_type="text")
    if resolution.abstained or resolution.answer is None:
        return None
    # Resolving takes seconds - waiting for the question to paint, then an LLM
    # call - and Naukri re-renders the drawer in that window, so any handle
    # captured earlier is stale by now.
    drawers = _visible(driver.find_elements(By.CSS_SELECTOR, _DRAWER))
    if not drawers:
        logger.error("Chatbot drawer disappeared while the answer was resolved")
        return None
    controls = [
        element
        for element in drawers[0].find_elements(By.CSS_SELECTOR, _PLAIN_INPUTS)
        if element.is_displayed() and element.is_enabled()
    ]
    if not controls:
        logger.error("Chatbot input disappeared while the answer was resolved")
        return None
    control = controls[0]
    control.clear()
    human_type(control, resolution.answer.text)
    if _normalise(control.get_attribute("value") or "") != _normalise(resolution.answer.text):
        logger.error("Plain chatbot input write could not be verified")
        return None
    return click_send(driver)


def _dom_state(driver: WebDriver) -> Tuple[int, int, int, int, int, str]:
    bot_messages = driver.find_elements(By.CSS_SELECTOR, _BOT_MESSAGES)
    user_messages = driver.find_elements(By.CSS_SELECTOR, _USER_MESSAGES)
    return (
        len(bot_messages),
        len(user_messages),
        len(driver.find_elements(By.CSS_SELECTOR, _RADIOS)),
        len(driver.find_elements(By.CSS_SELECTOR, _CHECKBOXES)),
        len(driver.find_elements(By.CSS_SELECTOR, _TEXT_AREAS + ", " + _PLAIN_INPUTS)),
        _latest_question(driver),
    )


def _describe_drawer(driver: WebDriver, limit: int = 8) -> str:
    """Summarise what is in the chatbot drawer, for diagnosing a stall."""
    try:
        drawers = _visible(driver.find_elements(By.CSS_SELECTOR, _DRAWER))
        if not drawers:
            return "drawer not visible"
        drawer = drawers[0]
        counts = {
            "radios": len(_visible(drawer.find_elements(By.CSS_SELECTOR, _RADIOS))),
            "checkboxes": len(_visible(drawer.find_elements(By.CSS_SELECTOR, _CHECKBOXES))),
            "textareas": len(_visible(drawer.find_elements(By.CSS_SELECTOR, _TEXT_AREAS))),
            "inputs": len(_visible(drawer.find_elements(By.CSS_SELECTOR, _PLAIN_INPUTS))),
        }
        tags = []
        for element in drawer.find_elements(By.CSS_SELECTOR, "input, select, textarea, button")[:40]:
            try:
                if not element.is_displayed():
                    continue
                tag = element.tag_name
                kind = element.get_attribute("type") or ""
                label = "%s%s" % (tag, "[%s]" % kind if kind else "")
                if label not in tags:
                    tags.append(label)
            except WebDriverException:
                continue
            if len(tags) >= limit:
                break
        return "question=%r controls=%s visible=%s" % (
            _latest_question(driver)[:120],
            counts,
            tags or "none",
        )
    except WebDriverException as exc:
        return "could not inspect drawer: %s" % type(exc).__name__


def handle_chatbot(
    driver: WebDriver,
    profile: Profile,
    answer_engine: AnswerEngine,
    settings: Settings,
) -> ChatbotOutcome:
    """Process the drawer within a wall-clock budget and stop on any abstain."""
    del profile, settings
    try:
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, _DRAWER)))
    except TimeoutException as exc:
        logger.warning("Chatbot drawer did not appear: %s", exc)
        return ChatbotOutcome(False, 0, 0, "drawer_not_found")
    except WebDriverException as exc:
        logger.error("Could not inspect chatbot drawer (%s): %s", type(exc).__name__, exc)
        return ChatbotOutcome(False, 0, 0, "%s: %s" % (type(exc).__name__, exc))

    answered = 0
    deadline = time.monotonic() + _OVERALL_TIMEOUT
    try:
        state = _dom_state(driver)
    except (StaleElementReferenceException, WebDriverException) as exc:
        logger.error("Could not read initial chatbot state (%s): %s", type(exc).__name__, exc)
        return ChatbotOutcome(False, 0, 0, "%s: %s" % (type(exc).__name__, exc))
    changed_at = time.monotonic()
    acted_state: Optional[Tuple[int, int, int, int, int, str]] = None
    while time.monotonic() < deadline:
        try:
            if not is_drawer_open(driver):
                return ChatbotOutcome(True, answered, 0, "drawer_closed")
            current_state = _dom_state(driver)
            if current_state != state:
                state = current_state
                changed_at = time.monotonic()
                acted_state = None

            handled: Optional[bool] = False
            if acted_state != current_state:
                handled = handle_radio(driver, answer_engine)
                if handled is False:
                    handled = _handle_checkbox(driver, answer_engine)
                if handled is False:
                    handled = handle_text(driver, answer_engine)
                if handled is False:
                    handled = _handle_plain_text(driver, answer_engine)
            if handled is None:
                question = _latest_question(driver)
                logger.info("Abandoning application at unanswered question: %s", question)
                return ChatbotOutcome(False, answered, 1, question)
            if handled:
                answered += 1
                acted_state = current_state
                human_pause(0.45, 1.1)
                continue
            if acted_state != current_state and click_send(driver):
                acted_state = current_state
                human_pause(0.45, 1.1)
                continue

            if time.monotonic() - changed_at >= _STALL_TIMEOUT:
                # No handler recognised the drawer, so nothing happened until
                # this timeout. "stalled" alone cost a whole run to diagnose.
                return ChatbotOutcome(
                    False, answered, 0, "stalled; %s" % _describe_drawer(driver)
                )
            human_pause(0.3, 0.75)
        except (NoSuchElementException, StaleElementReferenceException) as exc:
            logger.debug("Chatbot DOM changed during dispatch (%s): %s", type(exc).__name__, exc)
            human_pause(0.2, 0.5)
        except (ElementClickInterceptedException, WebDriverException) as exc:
            logger.error("Chatbot dispatch failed (%s): %s", type(exc).__name__, exc)
            return ChatbotOutcome(False, answered, 0, "%s: %s" % (type(exc).__name__, exc))
    return ChatbotOutcome(False, answered, 0, "timeout")


__all__ = [
    "AnswerEngine",
    "click_send",
    "find_chat_text_area",
    "handle_chatbot",
    "handle_radio",
    "handle_text",
    "is_drawer_open",
    "write_contenteditable",
]
