"""Sign-in checks against synthetic DOMs: no browsers, logins or network calls.

Navigation targets mirror first-party public client bundles inspected 2026-10-24
(Hirist 24.0.1 and Cutshort candidate shell), plus Wellfound's documented editor
and Applied/Matches tabs. This verifies conservative rules, not a live guarantee.
"""
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pytest
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException

from common.connections import PROVIDERS, verify


def visible(node):
    return not any(parent.has_attr("hidden") or "display:none" in parent.get("style", "").replace(" ", "")
                   for parent in (node, *node.parents) if getattr(parent, "attrs", None) is not None)


class Element:
    def __init__(self, node, url):
        self.node, self.url = node, url

    def is_displayed(self):
        return visible(self.node)

    @property
    def text(self):
        return "\n".join(str(value).strip() for value in self.node.strings
                         if str(value).strip() and visible(value.parent))

    def get_attribute(self, name):
        assert self.node.get("type") != "password", "Password contents must never be inspected"
        value = self.node.get(name)
        return urljoin(self.url, value) if name == "href" and value else value

    def find_elements(self, by, selector):
        assert by == By.CSS_SELECTOR
        return [Element(node, self.url) for node in self.node.select(selector)]


class Page:
    def __init__(self, provider, html, path=None, host=None):
        self.current_url = urljoin(host or PROVIDERS[provider].check, path or "")
        self.dom = BeautifulSoup(html, "html.parser")

    def find_elements(self, by, selector):
        assert by == By.CSS_SELECTOR
        return [Element(node, self.current_url) for node in self.dom.select(selector)]

    def execute_script(self, script):
        assert script == "return document.body ? document.body.innerText.slice(0, 100000) : ''"
        return Element(self.dom, self.current_url).text

    def get(self, *_):
        pytest.fail("Verification must not navigate")

    def get_cookies(self):
        pytest.fail("Cookies are not authentication evidence")


HIRIST = '<nav><a href="/myprofile">My Profile</a><a href="/applied-jobs?ref=menu">Applied Jobs</a></nav>'
CUTSHORT = '<nav><a href="/profile/candidate-dashboard">Dashboard</a><a href="/profile/candidate-conversations">Conversations</a><a href="/profile/candidate-settings/profile">Settings</a></nav>'
WELLFOUND = '<nav><a href="/jobs/applications">Applied</a><a href="/jobs/matches">Matches</a></nav>'
INSTAHYRE = '<nav><a href="/candidate/profile/">Profile</a><a href="/candidate/opportunities/">Opportunities</a></nav>'
SIGNED_IN = [("hirist", HIRIST), ("cutshort", CUTSHORT), ("wellfound", WELLFOUND), ("instahyre", INSTAHYRE)]

# Structure observed in Hirist's /myprofile chunks 4232 and 6292. The account
# email is plain text in a span, not an email input or data-testid attribute.
HIRIST_OWN_PROFILE = '''
<main>
  <div class="profile-sidebar">
    <span><a href="/registration/addPersonalDetails"><img alt="user-icon"></a></span>
    <p>Example Candidate<span>candidate@example.test</span><span>1234567890</span></p>
  </div>
  <section>
    <p>Professional <span>Details</span><a href="registration/addWorkExperience"><img alt="edit"></a></p>
    <button>Add Professional Details</button>
    <p>Educational <span>Details</span><a href="registration/addEducationalDetails"><img alt="edit"></a></p>
    <button>Add Education Details</button>
  </section>
</main>
'''


@pytest.mark.parametrize("provider,html", SIGNED_IN)
def test_candidate_shell_is_positive_without_opening_avatar_menu(provider, html):
    result = verify(Page(provider, html), PROVIDERS[provider])
    assert result["state"] == "connected"
    assert result["identity_verified"] is False
    assert result["verified_account"] == ""
    assert result["last_verified_at"]


def test_wellfound_editor_navigation_is_positive_but_public_profile_is_not():
    html = '<a href="/profile/edit/overview">Overview</a><a href="/profile/edit/resume">Resume</a>'
    assert verify(Page("wellfound", html), PROVIDERS["wellfound"])["state"] == "connected"
    assert verify(Page("wellfound", html, "/u/someone"), PROVIDERS["wellfound"])["state"] == "needs_attention"


@pytest.mark.parametrize("provider,html,path", [
    ("hirist", '<button>My Profile</button><div role="menuitem">Applied Jobs</div>', "/jobfeed"),
    ("cutshort", '<button>Dashboard</button><button>Conversations</button><button>Settings</button>', "/profile/candidate-dashboard"),
    ("wellfound", '<button>Applied</button><button>Matches</button>', "/jobs"),
])
def test_private_navigation_can_use_buttons_without_anchor_hrefs(provider, html, path):
    assert verify(Page(provider, html, path), PROVIDERS[provider])["state"] == "connected"


def test_cutshort_generic_button_labels_need_candidate_context():
    html = '<button>Dashboard</button><button>Settings</button>'
    assert verify(Page("cutshort", html, "/company/example"), PROVIDERS["cutshort"])["state"] == "needs_attention"


@pytest.mark.parametrize("provider,html", SIGNED_IN)
def test_hidden_candidate_navigation_is_not_evidence(provider, html):
    result = verify(Page(provider, '<div hidden>' + html + '</div><h1>Welcome</h1>'), PROVIDERS[provider])
    assert result["state"] == "needs_attention"
    assert result["retryable"] is True
    assert "may already be signed in" in result["message"]


@pytest.mark.parametrize("provider", [row[0] for row in SIGNED_IN])
def test_private_url_alone_or_job_prose_does_not_prove_sign_in(provider):
    html = '<h1>Profile</h1><p>We build account menus with Log out buttons.</p><p>engineer@example.test</p>'
    result = verify(Page(provider, html), PROVIDERS[provider])
    assert result["state"] == "needs_attention"


@pytest.mark.parametrize("provider,html", [
    ("hirist", '<a href="/myprofile">View profile</a>'),
    ("cutshort", '<a href="/profile/all-jobs?jobid=123">Apply to this job</a>'),
    ("wellfound", '<a href="/profile/edit">Create a profile</a>'),
])
def test_single_public_job_call_to_action_does_not_prove_authentication(provider, html):
    result = verify(Page(provider, '<article>' + html + '</article>', '/jobs/example'), PROVIDERS[provider])
    assert result["state"] == "needs_attention"


@pytest.mark.parametrize("provider,html", SIGNED_IN)
def test_visible_login_controls_override_stale_authenticated_shell(provider, html):
    page = Page(provider, html + '<form><input type="password" value="never-read"><button>Sign in</button></form>')
    assert verify(page, PROVIDERS[provider])["state"] == "needs_sign_in"


@pytest.mark.parametrize("challenge", [
    '<h1>Enter the OTP</h1>',
    '<input autocomplete="one-time-code" aria-label="Verification code">',
    '<h1>Verify you are human</h1>',
    '<h1>Confirm it’s you</h1>',
])
def test_security_challenge_overrides_signed_in_navigation(challenge):
    result = verify(Page("hirist", HIRIST + challenge), PROVIDERS["hirist"])
    assert result["state"] == "needs_attention"
    assert "security check" in result["message"]
    assert "retryable" not in result


def test_login_route_cannot_pass_with_old_navigation():
    assert verify(Page("cutshort", CUTSHORT, "/login"), PROVIDERS["cutshort"])["state"] == "needs_sign_in"


def test_unrelated_and_help_hosts_cannot_supply_private_navigation():
    wrong = Page("hirist", HIRIST, host="https://hirist.tech.attacker.example/")
    assert verify(wrong, PROVIDERS["hirist"])["state"] == "needs_sign_in"
    help_page = Page("wellfound", WELLFOUND, host="https://help.wellfound.com/article/example")
    assert verify(help_page, PROVIDERS["wellfound"])["state"] == "needs_attention"


def test_account_menu_and_avatar_alone_are_not_positive():
    page = Page("hirist", '<button data-testid="account-menu"><img alt="Avatar"></button>')
    assert verify(page, PROVIDERS["hirist"])["state"] == "needs_attention"


def test_logout_must_be_a_visible_control_not_job_prose():
    provider = PROVIDERS["hirist"]
    assert verify(Page("hirist", '<p>Log out</p>'), provider)["state"] == "needs_attention"
    assert verify(Page("hirist", '<button>Log out</button>'), provider)["state"] == "connected"
    assert verify(Page("hirist", '<button style="display:none">Log out</button>'), provider)["state"] == "needs_attention"


def test_expected_account_match_is_case_insensitive_and_does_not_read_password():
    page = Page("hirist", HIRIST + '<input type="email" value="Person@Example.test"><input type="password" value="never-read">', '/update-profile')
    result = verify(page, PROVIDERS["hirist"], "person@example.test")
    assert result["state"] == "connected"
    assert result["verified_account"] == "Person@Example.test"
    assert result["identity_verified"] is True


def test_expected_email_mismatch_is_not_reported_as_signed_out():
    page = Page("cutshort", CUTSHORT + '<span data-testid="account-email">other@example.test</span>')
    result = verify(page, PROVIDERS["cutshort"], "expected@example.test")
    assert result["state"] == "needs_attention"
    assert "signed in" in result["message"] and "does not match" in result["message"]
    assert "retryable" not in result


def test_missing_email_has_different_guidance_from_an_actual_mismatch():
    result = verify(Page("wellfound", WELLFOUND), PROVIDERS["wellfound"], "expected@example.test")
    assert result["state"] == "needs_attention"
    assert "sign-in is detected" in result["message"]
    assert "optional email hint" in result["message"]
    assert "does not match" not in result["message"]


def test_job_email_and_arbitrary_email_field_cannot_verify_account_identity():
    page = Page("cutshort", CUTSHORT + '<article>Contact expected@example.test</article><input type="email" value="expected@example.test">', '/jobs/example')
    result = verify(page, PROVIDERS["cutshort"], "expected@example.test")
    assert result["state"] == "needs_attention"
    assert "clear matching account email" in result["message"]


def test_visible_account_menu_email_can_be_verified_without_special_email_selector():
    page = Page("cutshort", '<div role="menu"><p>person@example.test</p><button>Log out</button></div>')
    result = verify(page, PROVIDERS["cutshort"], "person@example.test")
    assert result["state"] == "connected" and result["identity_verified"]


def test_hidden_email_cannot_verify_expected_account():
    page = Page("hirist", HIRIST + '<span hidden data-testid="account-email">expected@example.test</span>')
    assert verify(page, PROVIDERS["hirist"], "expected@example.test")["state"] == "needs_attention"


def test_known_current_profile_targets_replace_obsolete_generic_routes():
    assert PROVIDERS["hirist"].check == "https://www.hirist.tech/myprofile"
    assert PROVIDERS["cutshort"].check == "https://cutshort.io/profile/candidate-dashboard"


def test_hydrating_stale_controls_do_not_destroy_other_positive_evidence():
    class Stale:
        def is_displayed(self):
            return True

        @property
        def text(self):
            raise StaleElementReferenceException("Element replaced")

        def get_attribute(self, _name):
            raise StaleElementReferenceException("Element replaced")

    class HydratingPage(Page):
        def find_elements(self, by, selector):
            result = super().find_elements(by, selector)
            return [Stale(), *result] if "a[href]" in selector else result

    assert verify(HydratingPage("hirist", HIRIST), PROVIDERS["hirist"])["state"] == "connected"


def test_hirist_loaded_own_profile_works_with_closed_navigation_menu():
    result = verify(Page("hirist", HIRIST_OWN_PROFILE), PROVIDERS["hirist"], "candidate@example.test")
    assert result["state"] == "connected"
    assert result["verified_account"] == "candidate@example.test"
    assert result["identity_verified"]


def test_hirist_own_profile_supports_icon_edit_links_without_text_buttons():
    html = HIRIST_OWN_PROFILE.replace('<button>Add Professional Details</button>', '').replace('<button>Add Education Details</button>', '')
    assert verify(Page("hirist", html), PROVIDERS["hirist"])["state"] == "connected"


def test_hirist_own_profile_supports_add_buttons_when_edit_links_are_not_rendered():
    html = HIRIST_OWN_PROFILE.replace('<a href="registration/addWorkExperience"><img alt="edit"></a>', '').replace('<a href="registration/addEducationalDetails"><img alt="edit"></a>', '')
    assert verify(Page("hirist", html), PROVIDERS["hirist"])["state"] == "connected"


@pytest.mark.parametrize("path", ["/", "/myprofile/other-person", "/j/public-job-123", "/company/example"])
def test_hirist_profile_content_is_not_private_identity_off_own_profile_route(path):
    result = verify(Page("hirist", HIRIST_OWN_PROFILE, path), PROVIDERS["hirist"])
    assert result["state"] == "needs_attention"


def test_hirist_unloaded_profile_skeleton_is_not_authentication_proof():
    html = HIRIST_OWN_PROFILE.replace('Example Candidate', '').replace('candidate@example.test', '').replace('1234567890', '')
    result = verify(Page("hirist", html), PROVIDERS["hirist"])
    assert result["state"] == "needs_attention" and result["retryable"]


@pytest.mark.parametrize("html", ['', '<h1>My Profile</h1>', '<p>Professional Details</p><p>Educational Details</p>'])
def test_hirist_own_profile_route_and_static_labels_alone_are_not_proof(html):
    assert verify(Page("hirist", html), PROVIDERS["hirist"])["state"] == "needs_attention"


def test_hirist_recommendation_email_cannot_replace_unloaded_account_identity():
    html = HIRIST_OWN_PROFILE.replace('candidate@example.test', '') + '<label>Request a recommendation from <input id="email" name="email" value="candidate@example.test"></label>'
    result = verify(Page("hirist", html), PROVIDERS["hirist"], "candidate@example.test")
    assert result["state"] == "needs_attention"


def test_hirist_hidden_identity_cannot_verify_static_profile_editor():
    html = HIRIST_OWN_PROFILE.replace('<p>Example Candidate', '<p hidden>Example Candidate')
    assert verify(Page("hirist", html), PROVIDERS["hirist"])["state"] == "needs_attention"


def test_hirist_hidden_profile_sections_give_profile_tab_guidance():
    html = HIRIST_OWN_PROFILE.replace('<section>', '<section style="display:none">')
    result = verify(Page("hirist", html), PROVIDERS["hirist"], "candidate@example.test")
    assert result["state"] == "needs_attention" and result["retryable"]
    assert "Select Profile on Hirist" in result["message"]
    assert "last_verified_at" not in result


def test_hirist_recommendations_view_uses_persistent_account_sidebars():
    html = HIRIST_OWN_PROFILE.replace('<section>', '<section style="display:none">')
    html += '<button>Profile</button><button>Recommendations</button><a href="/settings">Settings</a>'
    html += '<p>No Recommendation Yet</p><input name="email" type="email" value="recipient@example.test">'
    result = verify(Page("hirist", html), PROVIDERS["hirist"], "candidate@example.test")
    assert result["state"] == "connected"
    assert result["verified_account"] == "candidate@example.test"


def test_hirist_wrong_account_on_own_profile_reports_mismatch():
    result = verify(Page("hirist", HIRIST_OWN_PROFILE), PROVIDERS["hirist"], "another@example.test")
    assert result["state"] == "needs_attention"
    assert "does not match" in result["message"]
    assert "retryable" not in result


def test_hirist_recommendation_recipient_cannot_match_a_different_logged_in_email():
    page = Page("hirist", HIRIST_OWN_PROFILE + '<input id="email" name="email" type="email" value="another@example.test">')
    result = verify(page, PROVIDERS["hirist"], "another@example.test")
    assert result["state"] == "needs_attention"
    assert "does not match" in result["message"]


@pytest.mark.parametrize("heading", ["404", "Page not found", "Profile not found", "Something went wrong"])
def test_hirist_profile_load_error_does_not_accept_old_menu_or_profile(heading):
    result = verify(Page("hirist", HIRIST + HIRIST_OWN_PROFILE + '<h1>' + heading + '</h1>'), PROVIDERS["hirist"])
    assert result["state"] == "needs_attention"
    assert "could not load your profile" in result["message"]


def test_hirist_registration_redirect_requests_profile_completion_not_another_login():
    page = Page("hirist", '<h1>Personal Details</h1><label>Email<input type="email" value="candidate@example.test"></label><button>Next</button>', '/registration/addPersonalDetails')
    result = verify(page, PROVIDERS["hirist"])
    assert result["state"] == "needs_attention"
    assert "profile setup or editing" in result["message"]
    assert "do not need to change your login" in result["message"]


@pytest.mark.parametrize("path,extra,state", [
    ('/login', '<button>Login</button>', 'needs_sign_in'),
    ('/signup', '<button>Create account</button>', 'needs_sign_in'),
    ('/myprofile', '<input autocomplete="one-time-code">', 'needs_attention'),
])
def test_hirist_login_signup_and_otp_still_override_profile_markers(path, extra, state):
    assert verify(Page("hirist", HIRIST_OWN_PROFILE + extra, path), PROVIDERS["hirist"])["state"] == state


# Synthetic signed-in navigation: no dependence on a post composer existing on
# profile, jobs, messaging or settings pages.
LINKEDIN_NAV = '''
<nav id="global-nav" class="global-nav">
  <a href="/feed/">Home</a>
  <a href="/mynetwork/">My Network</a>
  <a href="/jobs/">Jobs</a>
  <a href="/messaging/">Messaging</a>
  <a href="/notifications/">Notifications</a>
  <button class="global-nav__primary-link-me-menu-trigger" aria-label="Me"><img alt="Me">Me</button>
</nav>
'''


@pytest.mark.parametrize("path", ["/feed/", "/in/example-member/", "/jobs/", "/messaging/", "/psettings/email"])
def test_linkedin_private_navigation_verifies_without_post_composer(path):
    from linkedin_bot.session import inspect_session
    from linkedin_bot.publisher import is_logged_in

    page = Page("linkedin", LINKEDIN_NAV, path)
    assert inspect_session(page) == {"state": "connected", "reason": ""}
    assert is_logged_in(page)  # Workflows reuse the same decision as Connections.
    result = verify(page, PROVIDERS["linkedin"])
    assert result["state"] == "connected"
    assert result["verified_account"] == "" and result["identity_verified"] is False
    assert result["last_verified_at"]


@pytest.mark.parametrize("composer", [
    '<button class="share-box-feed-entry__trigger"></button>',
    '<button data-control-name="share.open_share_box"></button>',
    '<button aria-label="Start a post"></button>',
    '<main><button><span>Start a post</span></button></main>',
])
def test_linkedin_legacy_and_modern_feed_composer_are_authentication_evidence(composer):
    assert verify(Page("linkedin", composer, "/feed/"), PROVIDERS["linkedin"])["state"] == "connected"


@pytest.mark.parametrize("html,path", [
    ('<p>Start a post</p>', "/feed/"),
    ('<main><button>Start a post</button></main>', "/blog/using-linkedin"),
    ('<div hidden>' + LINKEDIN_NAV + '</div>', "/in/example-member/"),
    ('<main><button style="display: none">Start a post</button></main>', "/feed/"),
    ('<p>Welcome back</p>', "/feed/"),
    ('<h1>Example Member</h1><p>Engineer</p>', "/in/example-member/"),
])
def test_linkedin_url_prose_hidden_controls_and_public_profiles_are_not_proof(html, path):
    from linkedin_bot.session import inspect_session

    page = Page("linkedin", html, path)
    assert inspect_session(page) == {"state": "needs_attention", "reason": "loading"}
    result = verify(page, PROVIDERS["linkedin"])
    assert result["state"] == "needs_attention" and result["retryable"]
    assert "last_verified_at" not in result


@pytest.mark.parametrize("path", ["/login?session_redirect=/feed/", "/uas/login?fromSignIn=true", "/authwall", "/signup"])
def test_linkedin_login_routes_override_stale_nav_and_composer_even_with_feed_in_query(path):
    from linkedin_bot.session import inspect_session

    page = Page("linkedin", LINKEDIN_NAV + '<button class="share-box-feed-entry__trigger">Start a post</button>', path)
    assert inspect_session(page) == {"state": "needs_sign_in", "reason": "login"}
    assert verify(page, PROVIDERS["linkedin"])["state"] == "needs_sign_in"


@pytest.mark.parametrize("path", ["/in/example-member/", "/pulse/public-article", "/feed/"])
def test_linkedin_sign_in_controls_override_stale_signed_in_markers(path):
    html = LINKEDIN_NAV + '<main><button>Start a post</button></main><header><a href="/login">Sign in</a></header>'
    assert verify(Page("linkedin", html, path), PROVIDERS["linkedin"])["state"] == "needs_sign_in"


@pytest.mark.parametrize("path,challenge", [
    ("/checkpoint/challenge/123", ""),
    ("/challenge/123", ""),
    ("/feed/", '<input autocomplete="one-time-code">'),
    ("/feed/", '<h1>Enter the verification code</h1>'),
])
def test_linkedin_security_checks_override_authenticated_navigation(path, challenge):
    result = verify(Page("linkedin", LINKEDIN_NAV + challenge, path), PROVIDERS["linkedin"])
    assert result["state"] == "needs_attention"
    assert "security check" in result["message"]
    assert "last_verified_at" not in result and "retryable" not in result


@pytest.mark.parametrize("host", ["https://linkedin.com.attacker.example/feed/", "https://help.linkedin.com/feed/", "http://www.linkedin.com/feed/"])
def test_linkedin_private_shell_on_wrong_or_insecure_host_cannot_pass(host):
    from linkedin_bot.session import inspect_session

    page = Page("linkedin", LINKEDIN_NAV, host=host)
    assert inspect_session(page)["state"] != "connected"
    assert verify(page, PROVIDERS["linkedin"])["state"] != "connected"


def test_linkedin_private_links_in_article_are_not_authenticated_navigation():
    html = LINKEDIN_NAV.replace('<nav id="global-nav" class="global-nav">', '<article>').replace('</nav>', '</article>')
    assert verify(Page("linkedin", html, "/pulse/example"), PROVIDERS["linkedin"])["state"] != "connected"


def test_linkedin_stale_controls_do_not_discard_other_visible_navigation():
    class Stale:
        def is_displayed(self):
            return True

        @property
        def text(self):
            raise StaleElementReferenceException("Synthetic replaced element")

        def get_attribute(self, _name):
            raise StaleElementReferenceException("Synthetic replaced element")

    class HydratingElement(Element):
        def find_elements(self, by, selector):
            return [Stale(), *super().find_elements(by, selector)]

    class HydratingPage(Page):
        def find_elements(self, by, selector):
            assert by == By.CSS_SELECTOR
            return [HydratingElement(node, self.current_url) for node in self.dom.select(selector)]

    assert verify(HydratingPage("linkedin", LINKEDIN_NAV, "/in/example-member/"), PROVIDERS["linkedin"])["state"] == "connected"


@pytest.mark.parametrize("path", ["/feed/", "/psettings/email"])
def test_linkedin_editable_email_field_and_profile_prose_do_not_verify_identity(path):
    html = LINKEDIN_NAV + '<article>Contact expected@example.test</article><input type="email" value="expected@example.test">'
    result = verify(Page("linkedin", html, path), PROVIDERS["linkedin"], "expected@example.test")
    assert result["state"] == "needs_attention"
    assert "optional email" in result["message"]
    assert "last_verified_at" not in result


def test_linkedin_missing_optional_email_has_provider_specific_account_guidance():
    result = verify(Page("linkedin", LINKEDIN_NAV), PROVIDERS["linkedin"], "expected@example.test")
    assert result["state"] == "needs_attention"
    assert "LinkedIn" in result["message"] and "optional email" in result["message"]
    assert "does not match" not in result["message"]


def test_linkedin_explicit_account_email_can_match_and_mismatch_without_reading_password():
    html = LINKEDIN_NAV + '<span data-testid="account-email">Person@Example.test</span><input hidden type="password" value="never-read">'
    matching = verify(Page("linkedin", html), PROVIDERS["linkedin"], "person@example.test")
    assert matching["state"] == "connected" and matching["identity_verified"]
    assert matching["verified_account"] == "Person@Example.test"
    mismatched = verify(Page("linkedin", html), PROVIDERS["linkedin"], "another@example.test")
    assert mismatched["state"] == "needs_attention" and "does not match" in mismatched["message"]


def test_linkedin_hidden_account_email_cannot_match_optional_identity():
    html = LINKEDIN_NAV + '<span hidden data-testid="account-email">expected@example.test</span>'
    result = verify(Page("linkedin", html), PROVIDERS["linkedin"], "expected@example.test")
    assert result["state"] == "needs_attention" and "does not match" not in result["message"]


def test_linkedin_feed_post_about_security_checks_is_not_an_account_challenge():
    html = LINKEDIN_NAV + '<article><p>Enter the OTP, verify you are human, and confirm it’s you are examples of security checks.</p></article>'
    assert verify(Page("linkedin", html), PROVIDERS["linkedin"])["state"] == "connected"


def test_linkedin_login_link_inside_feed_post_does_not_override_real_account_navigation():
    html = LINKEDIN_NAV + '<article><p>This article explains registration.</p><a href="/login">Sign in</a></article>'
    assert verify(Page("linkedin", html), PROVIDERS["linkedin"])["state"] == "connected"
