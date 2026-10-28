"""Private automation profiles and read-only sign-in verification.

No cookie values or page content leave this module. Connecting never types a
password, submits a form, applies for a job, or opens the person's Chrome profile.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit


MARKER = ".morrow-managed.json"
METADATA = ".morrow-connections.json"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    login: str
    check: str
    domains: tuple[str, ...]


PROVIDERS = {
    p.id: p for p in (
        Provider("google", "Google", "https://accounts.google.com/", "https://myaccount.google.com/", ("google.com",)),
        Provider("naukri", "Naukri", "https://www.naukri.com/nlogin/login", "https://www.naukri.com/mnjuser/profile", ("naukri.com",)),
        Provider("linkedin", "LinkedIn", "https://www.linkedin.com/login", "https://www.linkedin.com/feed/", ("linkedin.com",)),
        Provider("hirist", "Hirist", "https://www.hirist.tech/", "https://www.hirist.tech/myprofile", ("hirist.tech", "hirist.com")),
        Provider("instahyre", "Instahyre", "https://www.instahyre.com/login/", "https://www.instahyre.com/candidate/profile/", ("instahyre.com",)),
        Provider("cutshort", "Cutshort", "https://cutshort.io/login", "https://cutshort.io/profile/candidate-dashboard", ("cutshort.io",)),
        Provider("wellfound", "Wellfound", "https://wellfound.com/login", "https://wellfound.com/profile/edit", ("wellfound.com",)),
    )
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def account_hint(value) -> str:
    if not isinstance(value, str) or len(value) > 254:
        raise ValueError("Enter an email address of at most 254 characters.")
    value = value.strip()
    if value and not re.fullmatch(r"[^\s<>\"'@]+@[^\s<>\"'@]+\.[^\s<>\"'@]+", value):
        raise ValueError("Enter a valid email address, or leave the account hint empty.")
    return value


def private_dir(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Automation profiles cannot be symbolic links.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def read_metadata(base: Path) -> dict:
    path = base / METADATA
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_metadata(base: Path, value: dict) -> None:
    private_dir(base)
    descriptor, name = tempfile.mkstemp(prefix=".connection-", dir=base)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream)
        os.chmod(name, 0o600)
        os.replace(name, base / METADATA)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def mark_managed(base: Path) -> None:
    private_dir(base)
    marker = base / MARKER
    if marker.is_symlink():
        raise ValueError("The managed profile marker cannot be a symbolic link.")
    descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"version": 1, "session_only": True}, stream)
    marker.chmod(0o600)


def managed_profile(base: str) -> bool:
    if not base:
        return False
    marker = Path(base) / MARKER
    try:
        return (not marker.is_symlink() and marker.stat().st_size < 1024
                and json.loads(marker.read_text()).get("session_only") is True)
    except (OSError, ValueError, AttributeError):
        return False


def local_hostnames() -> set:
    """Every name this machine writes into a Chrome SingletonLock, case-folded.

    Chrome records the Bonjour name ("Soujanya-Mac.local") while gethostname() can answer
    with the computer name ("MacBookPro") once the network changes, so a lock left by a
    killed Chrome on this very machine looked like a live browser on another host and
    blocked every run until the file was deleted by hand.
    """
    names = {socket.gethostname()}
    for key in ("LocalHostName", "ComputerName", "HostName"):
        try:
            value = subprocess.run(["scutil", "--get", key], capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if value and not value.endswith("not set"):
            names.update((value, value + ".local"))
    return {name.casefold() for name in names if name} | {name.casefold().removesuffix(".local") for name in names if name}


def profile_locked(base: Path) -> bool:
    """Block live or uncertain owners, but let Chrome recover a dead local lock.

    Chromium's POSIX SingletonLock is a symlink to ``hostname-pid``. Its socket
    and cookie can survive a crash, so their existence alone does not prove a
    browser is running. Never remove these files ourselves: Chrome performs its
    own singleton checks and recovery when it starts.
    """
    profile = base / "chrome"
    present = False
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (profile / name).lstat()  # Include dangling links without following them.
            present = True
        except FileNotFoundError:
            continue
        except OSError:
            return True  # Inaccessible state is not evidence that it is unused.
    if not present:
        return False
    lock = profile / "SingletonLock"
    try:
        target = os.readlink(lock)
        owner = re.fullmatch(r"(.+)-([1-9][0-9]{0,9})", target)
        if not owner or owner[1].casefold() not in local_hostnames():
            return True
        pid = int(owner[2])
        if pid > 2**31 - 1:
            return True
        try:
            os.kill(pid, 0)  # Probe only; no signal is sent.
        except ProcessLookupError:
            # A different browser may have claimed the profile during the probe.
            # Leave unknown/changed ownership blocked until a later check.
            return os.readlink(lock) != target
        return True
    except (OSError, ValueError):
        return True  # Includes live inaccessible PIDs, foreign hosts and old locks.


def chrome_binary() -> str:
    configured = os.getenv("CHROME_BINARY", "")
    candidates = [configured, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")]
    return next((str(path) for path in candidates if path and Path(path).is_file()), "")


def create_driver(settings):
    """Chrome only, one persistent profile, no fallback to an anonymous session."""
    from selenium import webdriver
    from common import browser

    base = Path(settings.browser_profile_dir)
    if not settings.browser_profile_dir:
        raise ValueError("A private automation profile is required.")
    if profile_locked(base):
        raise ValueError("This automation browser is already open. Close it before starting a run.")
    private_dir(base)
    private_dir(base / "chrome")
    options = browser._chrome_options(settings, str(base / "chrome"))
    binary = chrome_binary()
    if binary:
        options.binary_location = binary
    driver = webdriver.Chrome(service=browser.chromedriver_service(options), options=options)
    try:
        return browser._position_visible_window(browser._configure_driver(driver), settings)
    except Exception:
        driver.quit()
        raise


def allowed_host(url: str, provider: Provider) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return urlsplit(url).scheme == "https" and any(host == domain or host.endswith("." + domain) for domain in provider.domains)


_BOARD_IDS = frozenset(("hirist", "instahyre", "cutshort", "wellfound"))
_CONTROLS = "a[href], button, [role='button'], [role='menuitem'], input[type='submit']"
_LOGIN_CONTROL = re.compile(r"^(?:log\s?in|sign\s?in|candidate login|login\s*/\s*register|(?:sign in|log in|continue) with google)$", re.I)
_LOGOUT_CONTROL = re.compile(r"^(?:log\s?out|sign\s?out)$", re.I)
_EMAIL = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
# Observed in Hirist's first-party /myprofile sidebar chunk 4232 (24.0.1):
# the avatar's edit link is followed by the loaded account-name/email paragraph.
# No generated MUI class names, cookies or app-store state are used as evidence.
_HIRIST_PROFILE_IDENTITY = "span:has(> a[href$='/registration/addPersonalDetails'] img[alt='user-icon']) + p"


def _visible(driver, selector):
    """Ignore a node replaced during hydration, not the entire verification."""
    from selenium.common.exceptions import StaleElementReferenceException
    from selenium.webdriver.common.by import By

    result = []
    for item in driver.find_elements(By.CSS_SELECTOR, selector):
        try:
            if item.is_displayed():
                result.append(item)
        except StaleElementReferenceException:
            continue
    return result


def _label(item):
    from selenium.common.exceptions import StaleElementReferenceException
    try:
        return " ".join((item.text or item.get_attribute("aria-label") or item.get_attribute("value") or "").split())
    except StaleElementReferenceException:
        return ""


def _attribute(item, name):
    from selenium.common.exceptions import StaleElementReferenceException
    try:
        return item.get_attribute(name) or ""
    except StaleElementReferenceException:
        return ""


def _app_host(url, provider):
    # Help articles and public company subdomains can link to account pages;
    # they are not the candidate application whose session we are checking.
    return allowed_host(url, provider) and (urlsplit(url).hostname or "").removeprefix("www.") in provider.domains


def _hirist_profile_email(driver):
    if urlsplit(driver.current_url).path.rstrip("/") != "/myprofile" or not _app_host(driver.current_url, PROVIDERS["hirist"]):
        return []
    result = []
    for identity in _visible(driver, _HIRIST_PROFILE_IDENTITY):
        emails = _EMAIL.findall(_label(identity))
        # A recommendation recipient, footer contact, or job description is not
        # the candidate identity displayed next to the private profile avatar.
        if len({email.casefold() for email in emails}) == 1:
            result.append(emails[0])
    return result


def _board_evidence(driver, provider, controls):
    """Recognize rendered candidate navigation, never URL/cookies alone.

    Hirist's anonymous public 24.0.1 app bundle and Cutshort's public candidate
    route bundle were inspected on 2026-10-24. Their private navigation targets
    below are observed routes, not assumed class names. Wellfound documents its
    editor, resume and Applied/Matches tabs in its official support articles.
    Requiring distinct account destinations avoids a public job's single CTA.
    """
    if not _app_host(driver.current_url, provider):
        return False
    links, labels = set(), {_label(item).casefold() for item in controls}
    path = urlsplit(driver.current_url).path.rstrip("/")
    for item in controls:
        href = _attribute(item, "href")
        if href:
            target = urljoin(driver.current_url, href.strip())
            if _app_host(target, provider):
                links.add(urlsplit(target).path.rstrip("/") or "/")
    # Logout must be an actual visible control, not a phrase in page prose.
    if any(_LOGOUT_CONTROL.fullmatch(_label(item)) for item in controls):
        return True
    if links & {"/logout", "/signout", "/sign-out", "/users/sign_out"}:
        return True
    if provider.id == "hirist":
        own = links & {"/myprofile", "/registration/addPersonalDetails", "/update-profile"}
        private = links & {"/applied-jobs", "/saved-jobs", "/chats", "/recruiterview", "/settings"}
        # MUI navigation may use buttons/menuitems instead of anchors. These
        # labels are from the same observed candidate menu, not page prose.
        menu = "my profile" in labels and bool(labels & {"applied jobs", "my chat", "recruiter view"})
        # /myprofile can render its static editor skeleton before authentication
        # and profile requests complete. Require the loaded private sidebar
        # identity as well as independent work/education editing controls.
        editor = ({"/registration/addWorkExperience", "/registration/addEducationalDetails"} <= links
                  or {"add professional details", "add education details"} <= labels)
        own_profile = path == "/myprofile" and editor and bool(_hirist_profile_email(driver))
        return bool(own and private) or len(private) >= 3 or menu or own_profile
    if provider.id == "cutshort":
        own = links & {"/profile/candidate-dashboard", "/profile/candidate-settings/profile", "/profile/candidate-conversations"}
        private = links & {"/profile/candidate-dashboard", "/profile/candidate-settings/profile", "/profile/candidate-conversations",
                           "/profile/all-jobs", "/profile/recommended-jobs", "/profile/saved-jobs"}
        menu = path.startswith("/profile/") and bool(labels & {"dashboard", "conversations"}) and len(labels & {"dashboard", "conversations", "settings", "view jobs"}) >= 2
        return (bool(own) and len(private) >= 2) or menu
    if provider.id == "wellfound":
        editor = {path for path in links if path == "/profile/edit" or path.startswith("/profile/edit/")}
        private = links & {"/jobs/applications", "/jobs/applied", "/jobs/matches", "/jobs/saved"}
        # Applied and Matches are separate private tabs; a public profile, or
        # a public job listing with an Apply button, does not supply this shell.
        menu = (path == "/jobs" or path.startswith("/jobs/") or path.startswith("/profile/edit")) and {"applied", "matches"} <= labels
        return bool(editor and private) or len(private) >= 2 or menu or (
            path.startswith("/profile/edit") and len(editor) >= 2)
    if provider.id == "instahyre":
        return "/candidate/profile" in links and "/candidate/opportunities" in links
    return False


def _account_identifiers(driver, provider):
    """Only visible account fields; emails in job descriptions are not identity."""
    selector = "[data-email], [aria-label*='Google Account'], [data-testid='account-email'], [data-testid='profile-email'], .email-verified"
    if provider.id == "linkedin":
        selector = "[data-testid='account-email'], [data-testid='profile-email']"
    path = urlsplit(driver.current_url).path.rstrip("/")
    own_editor = {
        # /myprofile's email input is a recommendation RECIPIENT, not the
        # signed-in candidate. Its account email comes from the sidebar below.
        "hirist": path in ("/registration/addPersonalDetails", "/update-profile"),
        "cutshort": path.startswith("/profile/candidate-settings/profile"),
        "wellfound": path.startswith("/profile/edit") or path.startswith("/settings"),
        "instahyre": path.startswith("/candidate/profile"),
        # LinkedIn's feeds, jobs and settings can contain editable recipient or
        # add-email fields. Their values do not identify the signed-in account.
        "linkedin": False,
    }.get(provider.id, True)
    if own_editor:
        selector += ", input[type='email'], input[name*='email' i]"
    identifiers = []
    for item in _visible(driver, selector):
        value = _attribute(item, "data-email") or _attribute(item, "aria-label") or _attribute(item, "value") or _label(item)
        identifiers.extend(_EMAIL.findall(value))
    if provider.id == "hirist":
        identifiers.extend(_hirist_profile_email(driver))
    # Account popovers often render the email as plain text. Require an actual
    # menu with a logout control, not all body text or a generic job dialog.
    for menu in _visible(driver, "[role='menu'], [data-testid='account-menu']"):
        from selenium.common.exceptions import StaleElementReferenceException
        try:
            menu_text = menu.text
        except StaleElementReferenceException:
            continue
        if any(_LOGOUT_CONTROL.fullmatch(line.strip()) for line in menu_text.splitlines()):
            identifiers.extend(_EMAIL.findall(menu_text))
    return identifiers


def verify(driver, provider: Provider, expected: str = "") -> dict:
    """Inspect positive authentication evidence; a missing login form is not proof."""
    from selenium.webdriver.common.by import By

    if not allowed_host(driver.current_url, provider):
        return {"state": "needs_sign_in", "message": "Finish signing in on the provider's own page, then check again."}
    if provider.id == "linkedin":
        from linkedin_bot.session import inspect_session
        session = inspect_session(driver)
        if session["state"] != "connected":
            messages = {
                "login": "LinkedIn is showing its sign-in screen. Finish signing in in this browser, then check again.",
                "security_check": "LinkedIn is asking for a security check. Complete it in this browser, then check again.",
                "loading": "LinkedIn has not finished showing its signed-in account controls. Wait for the page to load, or open Home, then check again. Your browser will stay open.",
            }
            result = {"state": session["state"], "message": messages[session["reason"]]}
            if session["reason"] == "loading":
                result["retryable"] = True
            return result
        # Feed posts can discuss sign-in and verification; their prose is not
        # evidence of an account challenge. The shared detector checks controls.
        text = ""
    else:
        text = str(driver.execute_script("return document.body ? document.body.innerText.slice(0, 100000) : ''") or "")
    lower = text.lower()
    if any(term in lower for term in ("couldn’t sign you in", "couldn't sign you in", "this browser or app may not be secure")):
        return {"state": "needs_attention", "message": "The sign-in provider could not verify this automation browser. Complete its offered verification or try again later."}
    if any(term in lower for term in ("enter the verification code", "enter your verification code", "enter the otp", "enter otp", "verify you are human", "confirm it’s you", "confirm it's you")) or _visible(driver, "input[autocomplete='one-time-code']"):
        return {"state": "needs_attention", "message": "Complete the security check in the automation browser, then check again."}
    if provider.id in _BOARD_IDS:
        controls = _visible(driver, _CONTROLS)
        if re.search(r"/(?:login|signin|sign-in|signup|sign-up|register)(?:/|$)", urlsplit(driver.current_url).path, re.I) or any(_LOGIN_CONTROL.fullmatch(_label(item)) for item in controls):
            return {"state": "needs_sign_in", "message": provider.label + " is showing its sign-in screen. Finish signing in in this browser, then check again."}
        if provider.id == "hirist":
            if re.match(r"^/registration(?:/|$)", urlsplit(driver.current_url).path):
                return {"state": "needs_attention", "message": "Hirist is showing profile setup or editing. Finish or save the required details, then check again so Morrow can open your completed profile. You do not need to change your login."}
            if any(line.strip().casefold() in {"404", "page not found", "profile not found", "something went wrong"} for line in text.splitlines()):
                return {"state": "needs_attention", "retryable": True,
                        "message": "Hirist could not load your profile. Retry the check after the page is available; this does not mean you are signed out."}
        positive = _board_evidence(driver, provider, controls)
    elif provider.id == "naukri":
        from naukri_bot.auth import is_logged_in
        positive = is_logged_in(driver, trust_url=False)
    elif provider.id == "linkedin":
        positive = True  # The shared detector already confirmed account controls.
    elif provider.id == "google":
        # Account management is authenticated; the chooser/login page is not.
        controls = driver.find_elements(By.CSS_SELECTOR, "a[href*='SignOut'], a[href*='Logout'], [aria-label*='Google Account'], [data-email]")
        positive = urlsplit(driver.current_url).hostname == "myaccount.google.com" and any(
            item.is_displayed() and (item.get_attribute("data-email")
                or "@" in (item.get_attribute("aria-label") or "")
                or re.search(r"SignOut|Logout", item.get_attribute("href") or ""))
            for item in controls)
    else:
        positive = False
    if not positive:
        if provider.id == "hirist" and _hirist_profile_email(driver):
            return {"state": "needs_attention", "retryable": True,
                    "message": "Your Hirist account details are visible, but the profile sections are hidden or still loading. Select Profile on Hirist, wait for the details to appear, then check again."}
        if provider.id in _BOARD_IDS:
            return {"state": "needs_attention", "retryable": True,
                    "message": "This tab does not yet show enough account details to confirm sign-in. You may already be signed in. Open your own " + provider.label + " profile or dashboard, wait for it to load, then check again."}
        return {"state": "needs_sign_in", "message": "A signed-in account could not be verified. Finish sign-in and open the account menu, then check again."}
    # Read only visible account identifiers, never password fields or cookies.
    identifiers = _account_identifiers(driver, provider)
    matched = next((value for value in identifiers if value.casefold() == expected.casefold()), "") if expected else ""
    unique = {value.casefold(): value for value in identifiers}
    if expected and not matched:
        if provider.id == "linkedin" and not unique:
            return {"state": "needs_attention", "message": "Your LinkedIn sign-in is detected, but a matching saved account email is not visible. Open Me, then Settings & Privacy, Sign in & security, and Email addresses to show your account details, or clear the optional email to check the saved sign-in without matching an address."}
        return {"state": "needs_attention", "message": (
            "You are signed in, but the visible account email does not match the email you selected. Change the account or correct the optional email hint, then check again."
            if len(unique) == 1 else
            "Your sign-in is detected, but this page does not show a clear matching account email. Open your account details to verify it, or clear the optional email hint, then check again.")}
    actual = matched if expected else next(iter(unique.values())) if len(unique) == 1 else ""
    return {"state": "connected", "message": "Saved sign-in verified. Close this browser before running a workflow.",
            "verified_account": actual, "identity_verified": bool(actual), "last_verified_at": now()}


def clear_provider(driver, provider: Provider) -> None:
    """Remove this provider's saved login only; cookie values never leave memory."""
    cookies = driver.execute_cdp_cmd("Network.getAllCookies", {}).get("cookies", [])
    for cookie in cookies:
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        if any(domain == owned or domain.endswith("." + owned) for owned in provider.domains):
            driver.execute_cdp_cmd("Network.deleteCookies", {"name": cookie["name"], "domain": cookie["domain"], "path": cookie.get("path", "/")})
    # Clear known origin stores, keeping other providers in the shared profile.
    origins = {f"https://{domain}" for domain in provider.domains}
    origins.update(f"https://www.{domain}" for domain in provider.domains)
    origins.update(f"https://{urlsplit(url).hostname}" for url in (provider.login, provider.check))
    for origin in origins:
        driver.execute_cdp_cmd("Storage.clearDataForOrigin", {"origin": origin, "storageTypes": "local_storage,indexeddb,service_workers,cache_storage"})
    driver.get(provider.login)
