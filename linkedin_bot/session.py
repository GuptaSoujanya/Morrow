"""Read-only evidence of a LinkedIn browser session.

The feed composer is not available on every signed-in page. LinkedIn documents
its member navigation (My Network, Messaging, Notifications and Me) at
https://www.linkedin.com/help/linkedin/answer/a525089. Check that rendered
navigation together, rather than treating a destination URL as authentication.
No cookies, credentials, browser storage, or hidden application state are read.
"""

from urllib.parse import urljoin, urlsplit

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By


NAVIGATION = "header, nav, [role='banner'], [role='navigation']"
CONTROLS = "a[href], button, [role='button'], [role='menuitem']"
ACCOUNT_MENUS = "[role='menu'], [data-testid='account-menu']"
PASSWORD_FIELDS = "input[type='password'], input#password, input[name='session_password']"
SECURITY_FIELDS = "input[autocomplete='one-time-code']"
SECURITY_HEADINGS = (
    "h1:not(article h1):not([role='article'] h1), form h2, form [role='heading'], "
    "[role='dialog'] h2, [role='dialog'] [role='heading']"
)
FEED_COMPOSERS = (
    "button.share-box-feed-entry__trigger",
    "[data-control-name='share.open_share_box']",
    "button[aria-label*='Start a post']",
)

_HOSTS = frozenset(("linkedin.com", "www.linkedin.com"))
_PRIVATE_DESTINATIONS = frozenset(("mynetwork", "messaging", "notifications"))
_LOGIN_PATHS = (
    "/login", "/uas/login", "/authwall", "/signup", "/sign-up",
    "/start/join", "/reg/join", "/uas/request-password-reset",
)
_SECURITY_PATHS = ("/checkpoint", "/challenge", "/uas/consumer-email-challenge")
_LOGOUT_PATHS = frozenset(("/m/logout", "/uas/logout", "/logout"))
_ACCOUNT_LABELS = frozenset((
    "me", "open account menu", "open profile menu", "your profile",
    "view profile", "view my profile",
))
_LOGIN_LABELS = frozenset((
    "sign in", "log in", "login", "continue with google", "sign in with google",
    "join now",
))
_SECURITY_LABELS = frozenset((
    "enter the verification code", "enter your verification code",
    "let's do a quick security check", "let’s do a quick security check",
    "quick security check", "verify your identity", "confirm it's you", "confirm it’s you",
))


def _visible(root, selector):
    try:
        elements = root.find_elements(By.CSS_SELECTOR, selector)
    except WebDriverException:
        return []
    visible = []
    for element in elements:
        try:
            if element.is_displayed():
                visible.append(element)
        except WebDriverException:
            continue
    return visible


def _attribute(element, name):
    try:
        return element.get_attribute(name) or ""
    except WebDriverException:
        return ""


def _labels(element):
    try:
        text = element.text or ""
    except WebDriverException:
        text = ""
    values = [text, _attribute(element, "aria-label")]
    # LinkedIn can put the person's name and the Me label on separate lines.
    values.extend(text.splitlines())
    return {" ".join(value.split()).casefold() for value in values if value.strip()}


def _on_path(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def _application_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in _HOSTS


def _link_path(element, current_url):
    href = _attribute(element, "href")
    if not href:
        return ""
    resolved = urljoin(current_url, href)
    if not _application_url(resolved):
        return ""
    return urlsplit(resolved).path.rstrip("/")


def _is_logout(element, path):
    return path in _LOGOUT_PATHS or bool(_labels(element) & {"sign out", "log out", "logout"})


def _sign_in_controls(driver, current_url):
    # An email-first or Google sign-in screen may have no password input.
    # Inspect the site's navigation/forms, not links inside someone's post.
    for root in _visible(driver, NAVIGATION + ", form, [role='dialog']"):
        for control in _visible(root, CONTROLS):
            if not (_labels(control) & _LOGIN_LABELS):
                continue
            href = _attribute(control, "href")
            path = _link_path(control, current_url)
            if not href or any(_on_path(path, prefix) for prefix in _LOGIN_PATHS):
                return True
    return False


def _navigation_evidence(driver, current_url):
    for navigation in _visible(driver, NAVIGATION):
        destinations = set()
        account_control = False
        for control in _visible(navigation, CONTROLS):
            path = _link_path(control, current_url)
            destination = path.strip("/").split("/", 1)[0]
            if destination in _PRIVATE_DESTINATIONS:
                destinations.add(destination)
            if _labels(control) & _ACCOUNT_LABELS or _is_logout(control, path):
                account_control = True
        if len(destinations) == 3 or (account_control and len(destinations) >= 2):
            return True
    return False


def _account_menu_evidence(driver, current_url):
    for menu in _visible(driver, ACCOUNT_MENUS):
        logout = False
        account_destination = False
        for control in _visible(menu, CONTROLS):
            path = _link_path(control, current_url)
            logout |= _is_logout(control, path)
            account_destination |= _on_path(path, "/psettings") or _on_path(path, "/in")
        if logout and account_destination:
            return True
    return False


def _settings_evidence(driver, current_url):
    if not _on_path(urlsplit(current_url).path, "/psettings"):
        return False
    # Settings has a different layout from the feed. A rendered member profile
    # link together with its logout control provides independent account proof.
    logout = False
    profile = False
    for control in _visible(driver, CONTROLS):
        path = _link_path(control, current_url)
        logout |= _is_logout(control, path)
        profile |= path.startswith("/in/") and bool(path.removeprefix("/in/")) and bool(_labels(control))
    return logout and profile


def _composer_evidence(driver, current_url):
    if not _on_path(urlsplit(current_url).path, "/feed"):
        return False
    if any(_visible(driver, selector) for selector in FEED_COMPOSERS):
        return True
    # Current layouts need not carry the legacy share-box classes. Restrict the
    # fallback to a real control with this exact label in the feed's main area.
    for main in _visible(driver, "main, [role='main']"):
        if any("start a post" in _labels(control) for control in _visible(main, "button, [role='button']")):
            return True
    return False


def inspect_session(driver):
    """Return a fixed state/reason pair; never return page or account content."""
    try:
        current_url = driver.current_url or ""
    except WebDriverException:
        return {"state": "needs_attention", "reason": "loading"}
    if not _application_url(current_url):
        return {"state": "needs_sign_in", "reason": "login"}
    path = urlsplit(current_url).path.rstrip("/").lower()
    if (any(_on_path(path, prefix) for prefix in _SECURITY_PATHS)
            or _visible(driver, SECURITY_FIELDS)
            or any(_labels(heading) & _SECURITY_LABELS for heading in _visible(driver, SECURITY_HEADINGS))):
        return {"state": "needs_attention", "reason": "security_check"}
    if any(_on_path(path, prefix) for prefix in _LOGIN_PATHS) or _sign_in_controls(driver, current_url):
        return {"state": "needs_sign_in", "reason": "login"}
    if _visible(driver, PASSWORD_FIELDS):
        # Reauthentication/password screens can retain member navigation. The
        # person must finish them before this browser is ready for automation.
        return {"state": "needs_attention", "reason": "security_check"}
    if (_navigation_evidence(driver, current_url)
            or _account_menu_evidence(driver, current_url)
            or _settings_evidence(driver, current_url)
            or _composer_evidence(driver, current_url)):
        return {"state": "connected", "reason": ""}
    return {"state": "needs_attention", "reason": "loading"}
