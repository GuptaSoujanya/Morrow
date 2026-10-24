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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


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
        Provider("hirist", "Hirist", "https://www.hirist.tech/", "https://www.hirist.tech/profile", ("hirist.tech", "hirist.com")),
        Provider("instahyre", "Instahyre", "https://www.instahyre.com/login/", "https://www.instahyre.com/candidate/profile/", ("instahyre.com",)),
        Provider("cutshort", "Cutshort", "https://cutshort.io/login", "https://cutshort.io/profile", ("cutshort.io",)),
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


def profile_locked(base: Path) -> bool:
    return any((base / "chrome" / name).exists() or (base / "chrome" / name).is_symlink()
               for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"))


def chrome_binary() -> str:
    configured = os.getenv("CHROME_BINARY", "")
    candidates = [configured, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")]
    return next((str(path) for path in candidates if path and Path(path).is_file()), "")


def create_driver(settings):
    """Chrome only, one persistent profile, no fallback to an anonymous session."""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
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
    service = Service(executable_path=os.environ["CHROMEDRIVER"]) if os.getenv("CHROMEDRIVER") else Service()
    driver = webdriver.Chrome(service=service, options=options)
    try:
        return browser._position_visible_window(browser._configure_driver(driver), settings)
    except Exception:
        driver.quit()
        raise


def allowed_host(url: str, provider: Provider) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return urlsplit(url).scheme == "https" and any(host == domain or host.endswith("." + domain) for domain in provider.domains)


def verify(driver, provider: Provider, expected: str = "") -> dict:
    """Inspect positive authentication evidence; a missing login form is not proof."""
    from selenium.webdriver.common.by import By

    if not allowed_host(driver.current_url, provider):
        return {"state": "needs_sign_in", "message": "Finish signing in on the provider's own page, then check again."}
    text = str(driver.execute_script("return document.body ? document.body.innerText.slice(0, 100000) : ''") or "")
    lower = text.lower()
    if any(term in lower for term in ("couldn’t sign you in", "couldn't sign you in", "this browser or app may not be secure")):
        return {"state": "needs_attention", "message": "Google could not verify this automation browser. Complete its offered verification or try again later."}
    if any(term in lower for term in ("enter the verification code", "enter the otp", "verify you are human", "confirm it’s you")):
        return {"state": "needs_attention", "message": "Complete the security check in the automation browser, then check again."}
    if provider.id == "naukri":
        from naukri_bot.auth import is_logged_in
        positive = is_logged_in(driver, trust_url=False)
    elif provider.id == "linkedin":
        from linkedin_bot.publisher import is_logged_in
        positive = is_logged_in(driver) or any(item.is_displayed() for item in
            driver.find_elements(By.CSS_SELECTOR, "a[href*='/m/logout'], a[href*='/uas/logout']"))
    elif provider.id == "google":
        # Account management is authenticated; the chooser/login page is not.
        controls = driver.find_elements(By.CSS_SELECTOR, "a[href*='SignOut'], a[href*='Logout'], [aria-label*='Google Account'], [data-email]")
        positive = urlsplit(driver.current_url).hostname == "myaccount.google.com" and any(
            item.is_displayed() and (item.get_attribute("data-email")
                or "@" in (item.get_attribute("aria-label") or "")
                or re.search(r"SignOut|Logout", item.get_attribute("href") or ""))
            for item in controls)
    else:
        controls = driver.find_elements(By.CSS_SELECTOR, "a[href*='logout'], a[href*='signout'], button[data-testid*='logout'], [data-testid='account-menu']")
        positive = any(item.is_displayed() for item in controls)
        if not positive:
            positive = bool(re.search(r"(?im)^\s*(?:log\s*out|sign\s*out)\s*$", text))
    if not positive:
        return {"state": "needs_sign_in", "message": "A signed-in account could not be verified. Finish sign-in and open the account menu, then check again."}
    # Read only visible account identifiers, never password fields or cookies.
    identifiers = []
    for item in driver.find_elements(By.CSS_SELECTOR, "[data-email], [aria-label*='Google Account'], input[type='email'], [data-testid='account-email'], [data-testid='profile-email'], .email-verified"):
        if item.is_displayed():
            value = item.get_attribute("data-email") or item.get_attribute("aria-label") or item.get_attribute("value") or item.text or ""
            identifiers += re.findall(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I)
    matched = next((value for value in identifiers if value.casefold() == expected.casefold()), "") if expected else ""
    if expected and not matched:
        return {"state": "needs_attention", "message": "You are signed in, but the selected email could not be verified. Open your account details or correct the email hint, then check again."}
    unique = {value.casefold(): value for value in identifiers}
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
