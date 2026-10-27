"""Career-site accounts: get past "Sign in / Create account" so the form can open.

Workday, iCIMS, Taleo, SuccessFactors and many company portals put an account
wall in front of the application. The order tried is: the Google account already
signed in inside the bot's browser profile; then the email and password kept in
.env (COMPANY_SITE_EMAIL / COMPANY_SITE_PASSWORD); then creating an account with
them. The bot never types a Google password, never creates an account on a dry
run, and stops for a person when a site wants its email verified or shows a
captcha. user/inputs/accounts.md lists every site it signed in to or registered on.
"""

import logging
import re
import secrets
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple
from urllib.parse import urlparse

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from . import external as ext
from common.config import write_env_value
from common.models import Profile, Settings
from common import paths


logger = logging.getLogger(__name__)

SIGN_IN_WAIT_S = 20.0
FORM_WAIT_S = 10.0
# How long a visible window waits for a person to finish a Google sign-in before
# the email route is tried. scripts/google_login.sh makes this wait unnecessary.
GOOGLE_HUMAN_WAIT_S = 120.0
POLL_S = 0.5
PASSWORD_KEY = "COMPANY_SITE_PASSWORD"
_SYMBOLS = "!@#$%^&*"

_TO_EMAIL_FORM = re.compile(
    r"^((sign|log) ?in|continue|apply|register|sign ?up) (with|using) (your )?e-?mail( address)?$"
    r"|^(use|continue with) (your )?e-?mail( address)?$",
    re.I,
)
_SIGN_IN_LINK = re.compile(r"^((sign|log) ?in|login|already have an account\??.*)$", re.I)
_CREATE_LINK = re.compile(
    r"^(create( an| your| new)? account|sign ?up|register( now| here)?|new (user|candidate)\??.*"
    r"|join( now)?|don'?t have an account\??.*|start (your |an |a new )?application)$",
    re.I,
)
# Accenture's sign-up (Azure B2C) and others like it email a code before they
# let anyone in, and the bot cannot read that inbox.
_SEND_CODE = re.compile(r"^(send|get|e-?mail me)( a| the| my)?( verification)? code$|^verify( your)? e-?mail$", re.I)
_SIGN_IN_SUBMIT = re.compile(r"^((sign|log) ?in|login|continue|next|submit)$", re.I)
_CREATE_SUBMIT = re.compile(r"^(create( an| my)? account|sign ?up|register|submit|continue)$", re.I)
_EXISTS = re.compile(r"already (exists|registered|in use|taken)|already have an account|account (with|for) this e-?mail", re.I)
_VERIFY = re.compile(
    r"verify your e-?mail|verification (e-?mail|link)|check your (e-?mail|inbox)|activate your account"
    r"|confirm your e-?mail|we.ve sent (you )?an? (e-?mail|link)|sent (a|an) (verification|confirmation)",
    re.I,
)
_CAPTCHA = re.compile(r"captcha|i.m not a robot|verify (that )?you are (a )?human", re.I)
_EMAIL_LABEL = re.compile(r"e-?mail|user ?(name|id)|login id", re.I)
_AGREE = re.compile(r"\bi agree\b|\bi accept\b|\bterms\b|\bprivacy\b|\bconsent\b", re.I)
_ERRORS_CSS = "[aria-invalid='true'], [class*='error'], [role='alert']"
_FOLLOWS_SCRIPT = "return !!(arguments[0].compareDocumentPosition(arguments[1]) & 4)"


def account_email(settings: Settings) -> str:
    return settings.company_site_email or settings.google_email or settings.email


def generate_password(length: int = 16) -> str:
    """Upper, lower, digit and symbol: what Workday and most portals insist on."""
    alphabet = string.ascii_letters + string.digits + _SYMBOLS
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in _SYMBOLS for c in password)
        ):
            return password


def account_password(settings: Settings) -> str:
    """The saved career-site password, made and written to .env the first time one is needed."""
    if settings.company_site_password:
        return settings.company_site_password
    password = generate_password()
    write_env_value(settings.env_file, PASSWORD_KEY, password)
    settings.company_site_password = password
    logger.warning(
        "Made a password for career-site accounts and saved it in %s as %s.",
        settings.env_file,
        PASSWORD_KEY,
    )
    return password


def accounts_file(settings: Settings) -> Path:
    return Path(settings.data_dir or paths.user("inputs")) / "accounts.md"


def record_account(settings: Settings, host: str, email: str, what: str) -> Path:
    """One row per site and outcome in user/inputs/accounts.md; the password itself is never written."""
    path = accounts_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(
            "# Career-site accounts the bot signed in to or created\n\n"
            "Every account uses the email below and the password saved as "
            "COMPANY_SITE_PASSWORD in .env.\n\n"
            "| Date | Site | Email | What happened |\n"
            "|---|---|---|---|\n",
            encoding="utf-8",
        )
    existing = path.read_text(encoding="utf-8")
    if "| %s | %s | %s |" % (host, email, what) in existing:
        return path
    with path.open("a", encoding="utf-8") as handle:
        handle.write("| %s | %s | %s | %s |\n" % (datetime.now().strftime("%Y-%m-%d %H:%M"), host, email, what))
    return path


def has_account(settings: Settings, host: str) -> bool:
    """Whether user/inputs/accounts.md records an account the bot made or used on `host`."""
    try:
        rows = accounts_file(settings).read_text(encoding="utf-8")
    except OSError:
        return False
    return "| %s |" % host in rows


# ---------------------------------------------------------------------------
# Reading the page
# ---------------------------------------------------------------------------


def _host(driver: Any) -> str:
    return (urlparse(ext._current_url(driver)).netloc or "").lower()


def _fields(driver: Any) -> List[ext.Field]:
    return [item for item in ext.discover_fields(driver) if not ext.HONEYPOT.search(item.label)]


def _passwords(fields: List[ext.Field]) -> List[ext.Field]:
    return [item for item in fields if item.kind == "password"]


def _email_field(fields: List[ext.Field]) -> Optional[ext.Field]:
    for item in fields:
        hint = " ".join((item.label, item.name, item.ident, item.autocomplete))
        if item.kind == "email" or (item.kind == "text" and _EMAIL_LABEL.search(hint)):
            return item
    return None


def _control(driver: Any, pattern: "re.Pattern[str]", after: Any = None) -> Optional[Any]:
    """The first visible control whose text matches; with `after`, the first one after that element."""
    for control in ext._visible_controls(driver):
        if not pattern.match(ext._control_text(control)):
            continue
        if after is not None:
            try:
                if not driver.execute_script(_FOLLOWS_SCRIPT, after, control):
                    continue
            except WebDriverException:
                pass
        return control
    return None


def _errors(driver: Any) -> str:
    try:
        texts = [
            ext._clean(element.text)
            for element in driver.find_elements(By.CSS_SELECTOR, _ERRORS_CSS)
            if element.is_displayed() and ext._clean(element.text)
        ]
    except WebDriverException:
        texts = []
    return "; ".join(texts)[:300]


def _state(driver: Any) -> Tuple[str, str]:
    """Where a sign-in or sign-up stands: in, verify, captcha, error, or waiting."""
    text = ext._page_text(driver)
    if _CAPTCHA.search(text):
        return "captcha", ""
    if _VERIFY.search(text):
        return "verify", ""
    errors = _errors(driver)
    if errors:
        return "error", errors
    if not _passwords(_fields(driver)):
        return "in", ""
    return "waiting", ""


def _settle(driver: Any, timeout_s: float) -> Tuple[str, str]:
    deadline = time.monotonic() + timeout_s
    while True:
        state, detail = _state(driver)
        if state != "waiting" or time.monotonic() >= deadline:
            return state, detail
        time.sleep(POLL_S)


def _wait_for(predicate: Callable[[], bool], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)


# ---------------------------------------------------------------------------
# Signing in and signing up
# ---------------------------------------------------------------------------


def _submit_sign_in(
    driver: Any, email: str, password: str, fields: Optional[List[ext.Field]] = None
) -> Tuple[str, str]:
    fields = fields if fields is not None else _fields(driver)
    box = _email_field(fields)
    secret = _passwords(fields)
    if box is None or not secret:
        return "error", "the sign-in form has no email box"
    if not ext.set_text(driver, box.element, email) or not ext.set_text(driver, secret[0].element, password):
        return "error", "the sign-in form did not keep what was typed"
    button = _control(driver, _SIGN_IN_SUBMIT, after=secret[0].element)
    if button is None:
        return "error", "no Sign in button next to the password box"
    ext._click(driver, button)
    return _settle(driver, SIGN_IN_WAIT_S)


def _submit_create(driver: Any, email: str, password: str, profile: Profile) -> Tuple[str, str]:
    fields = _fields(driver)
    box = _email_field(fields)
    boxes = _passwords(fields)
    if box is None:
        return "error", "the sign-up form has no email box"
    values = ext.known_values(profile)
    ext.set_text(driver, box.element, email)
    for item in boxes:
        ext.set_text(driver, item.element, password)
    for item in fields:
        label = item.question or item.label
        if item.kind == "checkbox" and _AGREE.search(label) and not ext._OPTIONAL_NOISE.search(label):
            ext._set_checked(driver, item.element, True)
        elif item.kind == "text" and item is not box and not item.value:
            key = ext.classify_label(label)
            if key in ("first_name", "last_name", "full_name") and values.get(key):
                ext.set_text(driver, item.element, values[key])
    button = _control(driver, _CREATE_SUBMIT, after=boxes[-1].element if boxes else box.element)
    if button is None:
        return "error", "no Create account button on the sign-up form"
    ext._click(driver, button)
    return _settle(driver, SIGN_IN_WAIT_S)


def _google_button_shown(driver: Any) -> bool:
    try:
        return any(element.is_displayed() for element in driver.find_elements(By.XPATH, ext._GOOGLE_BUTTON_XPATH))
    except WebDriverException:
        return False


def sign_in(driver: Any, settings: Settings, profile: Profile, dry_run: bool) -> Tuple[bool, str]:
    """Get past the account wall on the current page; (signed in, how or why not)."""
    host = _host(driver)
    start = ext._current_url(driver)
    if settings.google_email and _google_button_shown(driver):
        ok, how = ext.google_sign_in(driver, settings, GOOGLE_HUMAN_WAIT_S)
        if ok:
            record_account(settings, host, settings.google_email, "signed in with Google")
            return True, "signed in with Google"
        logger.info("      company site: Google sign-in did not work (%s); trying email", how)
        # Workday sends the whole tab to Google rather than a popup.
        if ext._current_url(driver) != start:
            ext.safe_get(driver, start)
            _wait_for(lambda: bool(_control(driver, _TO_EMAIL_FORM) or _passwords(_fields(driver))), FORM_WAIT_S)

    email = account_email(settings)
    if not email:
        return False, "no email for career-site accounts (set COMPANY_SITE_EMAIL in .env)"

    if not _passwords(_fields(driver)):
        control = _control(driver, _TO_EMAIL_FORM) or _control(driver, _SIGN_IN_LINK)
        if control is not None:
            ext._click(driver, control)
            _wait_for(lambda: bool(_passwords(_fields(driver))), FORM_WAIT_S)
    sign_in_fields = None  # type: Optional[List[ext.Field]]
    known = bool(settings.company_site_password) and has_account(settings, host)
    # Workday opens on its sign-up form; where the bot already made an account,
    # the way in is the Sign In link. Its dialog is added on top of the sign-up
    # form, so the boxes to type in are the ones that were not there before.
    if known and len(_passwords(_fields(driver))) >= 2:
        control = _control(driver, _SIGN_IN_LINK)
        if control is not None:
            before = {item.element for item in _fields(driver)}
            ext._click(driver, control)

            def dialog() -> List[ext.Field]:
                return [item for item in _fields(driver) if item.element not in before]

            if _wait_for(lambda: len(_passwords(dialog())) == 1, FORM_WAIT_S):
                sign_in_fields = dialog()
    elif known and len(_passwords(_fields(driver))) == 1:
        sign_in_fields = _fields(driver)

    # The one shared password goes only to hosts accounts.md lists: typed into any
    # page with a password box, a lookalike or hostile career page would collect
    # the password for every account.
    if sign_in_fields is not None and known:
        state, detail = _submit_sign_in(driver, email, settings.company_site_password, sign_in_fields)
        if state == "in":
            record_account(settings, host, email, "signed in")
            return True, "signed in as %s" % email
        if state == "captcha":
            return False, "%s shows a captcha at sign-in" % host
        if state == "verify":
            return False, "%s wants the email %s verified first; click the link it sent, then apply again" % (host, email)
        return False, (
            "the account on %s for %s did not take the saved password (%s); sign in there once by hand"
            % (host, email, detail or state)
        )

    # One password box is a sign-in form; the sign-up form behind its link asks twice.
    if len(_passwords(_fields(driver))) < 2:
        control = _control(driver, _CREATE_LINK)
        if control is not None:
            ext._click(driver, control)
            _wait_for(
                lambda: len(_passwords(_fields(driver))) >= 2 or _control(driver, _SEND_CODE) is not None,
                FORM_WAIT_S,
            )
    if _control(driver, _SEND_CODE) is not None:
        return False, (
            "signing up on %s needs a code it emails to %s; sign up there once by hand with the "
            "password saved as COMPANY_SITE_PASSWORD in .env, then add a row for %s to %s so the bot "
            "signs in after that" % (host, email, host, accounts_file(settings))
        )
    if not _passwords(_fields(driver)):
        return False, "no sign-in or sign-up form found on %s" % host
    if dry_run:
        return False, "dry run: would create an account on %s for %s" % (host, email)

    state, detail = _submit_create(driver, email, account_password(settings), profile)
    if state == "in":
        record_account(settings, host, email, "account created")
        return True, "created an account on %s for %s" % (host, email)
    if state == "verify":
        record_account(settings, host, email, "account created, waiting for email verification")
        return False, "%s sent a verification email to %s; click the link in it, then apply again" % (host, email)
    if state == "captcha":
        return False, "%s shows a captcha at sign-up" % host
    if _EXISTS.search(detail):
        return False, (
            "an account for %s already exists on %s with another password; sign in there once by hand, "
            "or reset its password to COMPANY_SITE_PASSWORD from .env" % (email, host)
        )
    return False, "creating an account on %s did not work: %s" % (host, detail or state)


# ---------------------------------------------------------------------------
# The Google session itself
# ---------------------------------------------------------------------------

GOOGLE_HOME = "https://accounts.google.com/"
GOOGLE_ADD_ACCOUNT = "https://accounts.google.com/AddSession"
GOOGLE_EMAIL_CSS = "input[name='identifier'], input[type='email']"
GOOGLE_PASSWORD_CSS = "input[name='Passwd'], input[type='password'][autocomplete='current-password']"
_NEXT = re.compile(r"^next$", re.I)
_ANOTHER_WAY = re.compile(r"^try another way$", re.I)
_USE_PASSWORD = re.compile(r"^enter your password$", re.I)
_ANOTHER_ACCOUNT = re.compile(r"^use another account$", re.I)
_GOOGLE_REFUSED = re.compile(r"couldn.t sign you in|couldn.t verify this account", re.I)
_NOT_NOW = re.compile(r"^(not now|skip|cancel|remind me later|done|no thanks)$", re.I)


def google_signed_in(driver: Any, email: str = "") -> bool:
    """Signed in to Google; with `email`, signed in as that account and not some other one."""
    if "myaccount.google.com" not in ext._current_url(driver):
        return False
    return not email or email.casefold() in ext._page_text(driver).casefold()


def _shown(driver: Any, css: str) -> Optional[Any]:
    try:
        return next((element for element in driver.find_elements(By.CSS_SELECTOR, css) if element.is_displayed()), None)
    except WebDriverException:
        return None


def _press(driver: Any, pattern: "re.Pattern[str]") -> bool:
    control = _control(driver, pattern)
    if control is None:
        return False
    ext._click(driver, control)
    ext.human_pause(1.5, 3.0)
    return True


def _refusal_file(settings: Settings) -> Path:
    return Path(settings.report_dir or paths.user("reports")) / "google_refused.txt"


def google_refused_today(settings: Settings) -> bool:
    """Google turned this browser away today; asking again only makes it more suspicious."""
    try:
        return _refusal_file(settings).read_text(encoding="utf-8").strip() == datetime.now().strftime("%Y-%m-%d")
    except OSError:
        return False


def google_login(driver: Any, settings: Settings, timeout_s: float) -> Tuple[bool, str]:
    """Sign the bot's browser in to GOOGLE_EMAIL; a passkey, phone prompt or code waits for a person."""
    if not settings.google_email and not settings.session_only:
        return False, "GOOGLE_EMAIL is not set"
    if not ext.safe_get(driver, GOOGLE_HOME):
        return False, "Google's sign-in page did not load"
    _wait_for(lambda: google_signed_in(driver) or _shown(driver, GOOGLE_EMAIL_CSS) is not None, FORM_WAIT_S)
    if settings.session_only:
        from common.connections import PROVIDERS, verify
        result = verify(driver, PROVIDERS["google"], settings.google_email)
        if result["state"] == "connected":
            return True, "Saved Google sign-in verified"
        return False, "Saved Google sign-in could not be verified. Reconnect Google in Connections, then resume this workflow."
    if google_signed_in(driver, settings.google_email):
        return True, "already signed in to Google as %s" % settings.google_email
    if google_signed_in(driver):
        logger.warning("The bot's browser is signed in to a different Google account; adding %s", settings.google_email)
        ext.safe_get(driver, GOOGLE_ADD_ACCOUNT)
        _wait_for(lambda: _shown(driver, GOOGLE_EMAIL_CSS) is not None, FORM_WAIT_S)

    deadline = time.monotonic() + timeout_s
    typed_email = typed_password = asked_other_way = told = False
    while True:
        if google_signed_in(driver, settings.google_email):
            return True, "signed in to Google as %s" % settings.google_email
        email_box = _shown(driver, GOOGLE_EMAIL_CSS)
        if email_box is None and not typed_email and _press(driver, _ANOTHER_ACCOUNT):
            continue
        password_box = _shown(driver, GOOGLE_PASSWORD_CSS)
        if email_box is not None and not typed_email:
            typed_email = True
            if ext.set_text(driver, email_box, settings.google_email):
                _press(driver, _NEXT)
            continue
        if password_box is not None and settings.google_password and not typed_password:
            typed_password = True
            if ext.set_text(driver, password_box, settings.google_password):
                _press(driver, _NEXT)
            continue
        if settings.google_password and password_box is None and not typed_password:
            # Accounts set up with a passkey open on it; the password is one of the other ways.
            if _press(driver, _USE_PASSWORD):
                continue
            if not asked_other_way and _press(driver, _ANOTHER_WAY):
                asked_other_way = True
                continue
        if "speedbump" in ext._current_url(driver) and _press(driver, _NOT_NOW):
            continue
        if _GOOGLE_REFUSED.search(ext._page_text(driver)):
            path = _refusal_file(settings)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")
            return False, (
                "Google refused to sign this browser in to %s (\"couldn't verify this account belongs to you\"); "
                "no more tries today. Sign in once by hand with scripts/google_login.sh" % settings.google_email
            )
        if settings.headless:
            return False, (
                "Google wants a person to finish signing in. Open Google in Connections "
                "and choose Sign in, or set HEADLESS=false and BACKGROUND=false and omit "
                "--headless for a local run."
            )
        if not told:
            logger.warning(
                "Google needs you to finish signing in to %s (passkey, phone prompt or code) in the "
                "browser window; waiting up to %d minutes.",
                settings.google_email,
                max(1, int(timeout_s // 60)),
            )
            told = True
        if time.monotonic() >= deadline:
            minutes = max(1, int(timeout_s // 60))
            return False, "Google sign-in was not finished within %d minute%s" % (minutes, "" if minutes == 1 else "s")
        try:
            if not driver.window_handles:
                return False, "the browser window was closed"
        except WebDriverException:
            return False, "the browser window was closed"
        time.sleep(POLL_S)
