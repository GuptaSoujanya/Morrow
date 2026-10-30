"""Apply on an employer's own site when Naukri's button leaves Naukri.

"Apply on company site" opens the employer's career page, nearly always an
applicant tracking system (Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
Workday, ...). This module follows that link in a new tab, fills the form from
the facts file, user/inputs/answers.txt and the resume, attaches the PDF, and submits
only when every required field has an answer and the site then confirms the
submission. Anything short of that is written to user/inputs/company_sites.md for a
person to finish, and the open questions wait in user/inputs/answers.txt.
"""

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchWindowException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from . import browser_agent
from common.answers import _NOT_FOR_JUDGEMENT, match_option
from common.browser import human_pause, human_type, safe_get
from common.models import AnswerMode, ApplyResult, ApplyStatus, JobPosting, Profile, Settings
from common.shared_files import atomic_write_text, locked_file
from common import paths
from common.llm import out_of_quota


logger = logging.getLogger(__name__)

OPEN_WAIT_S = 20.0
FORM_WAIT_S = 12.0
FILE_WAIT_S = 15.0
CONFIRM_WAIT_S = 30.0
GOOGLE_WAIT_S = 30.0
MANUAL_LOGIN_TIMEOUT_S = 300
POLL_S = 0.5
OPTION_WAIT_S = 3.0
# How long a page that has drawn its buttons but no form gets to draw the form.
SETTLE_S = 2.0
# How long a form's field count must hold still before it counts as drawn.
STEADY_S = 1.5

DRY_RUN = "dry_run"
# The posting was removed: nothing for you to finish, so it never reaches your list.
GONE = "gone"

ATS_HOSTS = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("workable.com", "workable"),
    ("smartrecruiters.com", "smartrecruiters"),
    ("myworkdayjobs.com", "workday"),
    ("workday.com", "workday"),
    ("icims.com", "icims"),
    ("bamboohr.com", "bamboohr"),
    ("jobvite.com", "jobvite"),
    ("taleo.net", "taleo"),
    ("successfactors", "successfactors"),
    ("oraclecloud.com", "oracle"),
    ("linkedin.com", "linkedin"),
    ("indeed.com", "indeed"),
    ("naukri.com", "naukri"),
)
#: Sites that insist on a per-employer account before showing any form.
# Applying there needs that network's own session, not a career-site account.
NOT_A_CAREER_SITE = ("linkedin", "indeed")
MAX_PAGES = 8
# An employer runs one careers system for all its postings, so a second identical
# stop means the rest of its entries get the same reason without another visit.
SAME_SITE_FAILURES = 2
# A posting applied to through the board itself still waits in the company-site
# list. Its page says so, and reading that is cheaper than an agent task that
# ends up reporting a submit it never made.
_ALREADY_APPLIED = re.compile(
    r"already applied|application sent|you have applied|applied to this job|"
    r"applied for this (?:job|position|role)", re.I)


def already_applied(driver: Any) -> str:
    """The page's own words saying this application is in, or "" when it does not."""
    found = _ALREADY_APPLIED.search(_page_text(driver))
    return found.group(0) if found else ""

_FIELD_RULES = (
    (re.compile(r"\bfirst\s*name\b|\bgiven\s*name\b|\bforename\b", re.I), "first_name"),
    (re.compile(r"\blast\s*name\b|\bsurname\b|\bfamily\s*name\b", re.I), "last_name"),
    (re.compile(r"\bfull\s*name\b|\blegal\s*name\b|\byour\s*name\b|^\W*name\W*$", re.I), "full_name"),
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"country\s*(/\s*region\s*)?(phone\s*)?code|dial(l?ing)?\s*code|\bisd\s*code\b"
                r"|\bphone\s*code\b|\bcode\s*\(country\)", re.I), "country_code"),
    (re.compile(r"^(?!.*\b(extension|ext|country( phone)? code|device type)\b).*"
                r"(\bphone|\bmobile|\bcontact\s*(number|no)|\btelephone|\bcell\b)", re.I), "phone"),
    (re.compile(r"linkedin", re.I), "linkedin_url"),
    (re.compile(r"github", re.I), "github_url"),
    (re.compile(r"portfolio|personal\s*(web)?site|\bwebsite\b|\bblog\b", re.I), "portfolio_url"),
    (re.compile(r"\bcurrent\s*(company|employer|organi[sz]ation)\b|\bcompany\s*name\b|\bemployer\b", re.I), "current_company"),
    (re.compile(r"\bcurrent\s*(job\s*)?(title|designation|role|position)\b|\bjob\s*title\b", re.I), "current_designation"),
    (re.compile(r"\blocation\b|\bcity\b|where\s+are\s+you\s+(based|located)|\bcurrent\s*address\b", re.I), "current_location"),
    (re.compile(r"\bcountry\b", re.I), "country"),
)
_YES_NO_QUESTION = re.compile(
    r"^\W*(are|do|does|did|will|would|have|has|had|is|was|were|can|could|should|may|shall)\b", re.I
)
_PLACE = re.compile(r"\blocation\b|\bcity\b|\btown\b", re.I)
_TEXT_KINDS = ("text", "email", "tel", "url", "number", "search", "textarea")
_CONSENTING = re.compile(r"^\W*(yes\b|i (consent|agree|accept|acknowledge)\b)", re.I)
_EEO = re.compile(
    r"\bgender\b|\brace\b|\bethnicit|\bveteran\b|\bdisabilit|\bpronoun|sexual\s*orientation|\bhispanic|\blatino",
    re.I,
)
_DECLINE = re.compile(r"decline|prefer not|don't wish|do not wish|not to (answer|say|disclose)|rather not|not specified", re.I)
_RESUME = re.compile(r"\bresume\b|\bcv\b|curriculum", re.I)
_COVER = re.compile(r"cover[\s_-]*letter", re.I)
_CONSENT = re.compile(r"\bagree\b|\bconsent\b|\backnowledge\b|\bprivacy\b|\bterms\b|\bgdpr\b", re.I)
_ACCOUNT = re.compile(r"password|captcha|verification\s*code|\botp\b", re.I)
# Checked before _ACCOUNT, which also matches these: a code the site emailed can
# be read from their Gmail, while a password on the same form cannot.
_ONE_TIME_CODE = re.compile(
    r"one[- ]?time (code|password|pin)|\botp\b|verification\s*code|security code|confirmation code"
    r"|code (we|that was|just)? ?(e-?mailed|sent)|e-?mailed code|enter the code",
    re.I,
)
# Workday's forms carry a box labelled "This input is for robots only, do not
# enter"; filling it marks the applicant as a bot.
# Captchas and "type the text in the image" checks are for a person; a form
# showing one is never submitted.
_CHALLENGE = re.compile(
    r"captcha|image text|text (in|from|shown in) the image|characters (you see|shown)|security code"
    r"|i.m not a robot|verify (that )?you are (a )?human",
    re.I,
)
_CHALLENGE_CSS = (
    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
    ".g-recaptcha, .h-captcha, .cf-turnstile"
)
HONEYPOT = re.compile(r"robots? only|do not (enter|fill)|leave (this )?(field )?(blank|empty)|if you are (a )?human", re.I)
_OPTIONAL_NOISE = re.compile(r"subscribe|newsletter|job\s*alert|keep me (updated|informed)|marketing", re.I)
_PLACEHOLDER_OPTION = re.compile(r"^(select|choose|please|pick|--|-|\.\.\.|none)\b|^\W*$", re.I)
_REVEAL_TEXT = re.compile(
    r"^(apply( now| for this job| to this job| for this position| to position| here| today| manually)?"
    r"|i'?m interested|start (your )?application|apply for this role)$",
    re.I,
)
_SUBMIT_TEXT = re.compile(
    r"^(submit( application| your application| my application)?|apply( now| for this job)?"
    r"|send( application| my application)?|finish|complete application|review and submit)$",
    re.I,
)
_FACT_QUESTION = re.compile(
    r"\b(ctc|salary|compensation|notice|years?|yrs|experience|location|located|living|live|reside\w*|residing|"
    r"based|staying|join|relocat\w*|passport|authori[sz]\w*|visa|shift|remote|hybrid|on-?site|"
    r"how (many|soon|long))\b", re.I)
_NEXT_TEXT = re.compile(
    r"^(next|continue|save (and|&) continue|save and next|proceed|next step|continue to next step)$", re.I
)
_SEARCH_WIDGET = re.compile(
    r"search|keyword|job (number|id|title|code)|requisition|location|city|country"
    r"|category|department|sort|filter|distance|radius",
    re.I,
)
_APPLICANT_FIELD = re.compile(r"name|e-?mail|phone|mobile|resume|\bcv\b|linkedin", re.I)
_SIGN_IN = re.compile(r"\bsign in\b|\blog in\b|\blogin\b|\bcreate (an )?account\b|\bregister\b", re.I)
_CONFIRMED = (
    "thank you for applying",
    "thanks for applying",
    "application has been submitted",
    "application submitted",
    "application was submitted",
    "we have received your application",
    "we've received your application",
    "application received",
    "successfully submitted",
    "your application has been received",
    "application complete",
    "thank you for your application",
    "thanks for your interest",
    "you have applied",
)
_CONFIRM_URL_WORDS = ("confirmation", "thank", "success", "submitted", "applied")


def _confirmation_url(url: str) -> bool:
    """A path part that is itself a confirmation word, such as /thank-you or /applied.

    A word inside a longer part does not count: /customer-success-engineer/apply
    is a job page, not a confirmation.
    """
    path = re.split(r"[?#]", url, 1)[0]
    for part in path.split("/")[3:]:
        part = part.strip().lower()
        if part in _CONFIRM_URL_WORDS or part.startswith(("thank", "confirmation")):
            return True
        if part.replace("_", "-") in ("application-submitted", "application-sent", "success-page"):
            return True
    return False

_LOWER = "translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
_CLICKABLE_XPATH = "//*[self::button or self::a or @role='button' or @type='submit']"
_GOOGLE_BUTTON_XPATH = "%s[contains(%s,'google')]" % (_CLICKABLE_XPATH, _LOWER)

# One round trip returns every usable control with the text a person would read
# as its label, so the Python side never has to walk the DOM element by element.
_FIELDS_SCRIPT = r"""
// Workday's dropdowns are buttons that open a listbox; they are questions too.
const controls = Array.from(document.querySelectorAll('input, select, textarea, button[aria-haspopup="listbox"]'));
const PLACEHOLDER = /^(select one|select\.*|choose\.*|please select\.*|none selected)$/i;
function visible(el) {
  const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
  return s.display !== 'none' && s.visibility !== 'hidden' && (r.width > 0 || r.height > 0);
}
function text(el) { return el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
function tickLabel(el) {
  // A styled Yes/No keeps its own box hidden and shows the label instead
  // (Hirist's screening questions, Wellfound's location choice).
  if (el.labels && el.labels[0]) return el.labels[0];
  const own = el.closest('label');
  if (own) return own;
  try { return el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null; } catch (e) { return null; }
}
const GENERIC = /^(attach|upload|browse|choose( a)? files?|select( a)? files?|enter manually|or|add|drop (your )?files? here.*|(type|enter|write) (your )?(response|answer)( here)?|type here|your (answer|response)|answer here|start typing.*|select\.*)$/i;
function textBefore(el, levels) {
  // The nearest text before the element, a few containers up: where a label sits.
  let node = el;
  for (let i = 0; i < levels && node.parentElement; i++) {
    node = node.parentElement;
    const candidates = Array.from(node.querySelectorAll('label, legend, span, div, p, h1, h2, h3, h4, h5, strong, b'));
    for (let k = candidates.length - 1; k >= 0; k--) {
      const c = candidates[k];
      if (c.contains(el) || c.querySelector('input, select, textarea, button')) continue;
      if (!(c.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) continue;
      const ct = text(c);
      if (ct && ct.length < 300 && /[a-z]/i.test(ct) && !GENERIC.test(ct)) return ct;
    }
  }
  return '';
}
function labelFor(el) {
  let t = '';
  if (el.id) { try { t = text(document.querySelector('label[for="' + CSS.escape(el.id) + '"]')); } catch (e) {} }
  const by = el.getAttribute('aria-labelledby');
  if (!t && by) { t = by.split(/\s+/).map(id => text(document.getElementById(id))).filter(Boolean).join(' '); }
  if (!t) t = (el.getAttribute('aria-label') || '').trim();
  if (!t) { const l = el.closest('label'); if (l) t = text(l); }
  // "Attach" or "Upload" says what the button does, not what the field is for.
  if (GENERIC.test(t)) t = '';
  if (!t) { t = (el.getAttribute('placeholder') || '').trim(); if (GENERIC.test(t)) t = ''; }
  if (!t) t = textBefore(el, 6);
  if (!t) t = (el.name || '').replace(/[\[\]_\-.]+/g, ' ').trim();
  return t;
}
function scopeOf(el) {
  // Where the control sits. A page's own header search box is not a question, and
  // typing in one closes an application modal, which left the bot clicking the
  // page's Apply button again and believing it had sent the form (Wellfound).
  if (el.closest('[role="dialog"], dialog, [aria-modal="true"]')) return 'dialog';
  if (el.closest('header, nav, [role="banner"], [role="navigation"], footer, [role="contentinfo"]')) return 'furniture';
  return 'page';
}
function pillOf(el) {
  // Workday shows a chosen item ("India (+91)") as a chip beside an empty search box.
  const box = el.closest('[data-automation-id^="formField"]');
  const pill = box && box.querySelector('[data-automation-id="selectedItem"]');
  return pill ? text(pill) : '';
}
function requiredOf(el, label) {
  if (el.required || el.getAttribute('aria-required') === 'true') return true;
  if (/^\*|\*\s*$/.test(label)) return true;
  let node = el;
  for (let i = 0; i < 3 && node.parentElement; i++) {
    node = node.parentElement;
    if (/\brequired\b/i.test(node.className || '')) return true;
  }
  return false;
}
function groupOf(el) {
  const fs = el.closest('fieldset');
  if (fs) { const lg = fs.querySelector('legend'); if (lg) return text(lg); }
  const g = el.closest('[role="group"],[role="radiogroup"]');
  if (g) {
    const by = g.getAttribute('aria-labelledby');
    const t = g.getAttribute('aria-label') || (by ? text(document.getElementById(by)) : '');
    if (t) return t.trim();
  }
  // No fieldset: the question is the text before the box that holds every option.
  const type = (el.type || '').toLowerCase();
  if ((type === 'radio' || type === 'checkbox') && el.name) {
    const siblings = document.querySelectorAll('input[name="' + CSS.escape(el.name) + '"]').length;
    let box = el;
    for (let i = 0; i < 6 && box.parentElement; i++) {
      box = box.parentElement;
      if (box.querySelectorAll('input[name="' + CSS.escape(el.name) + '"]').length >= siblings) break;
    }
    if (siblings > 1) return textBefore(box, 3);
  }
  return '';
}
return controls.filter(el => {
  if (el.tagName === 'BUTTON') return !el.disabled && visible(el);
  const type = (el.type || '').toLowerCase();
  if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type) || el.disabled) return false;
  if (type === 'file') return true;
  if (el.getAttribute('aria-hidden') === 'true') return false;
  if ((type === 'radio' || type === 'checkbox') && !visible(el)) return visible(tickLabel(el) || el);
  // Custom dropdowns keep an invisible required twin while empty; it is not a question.
  return visible(el);
}).map(el => {
  const tag = el.tagName.toLowerCase();
  const listbox = tag === 'button';
  const kind = listbox ? 'text' : tag === 'input' ? (el.type || 'text').toLowerCase() : tag;
  const label = labelFor(el);
  const shown = listbox ? text(el) : '';
  return {
    el: el, kind: kind, name: el.name || '', label: label, required: requiredOf(el, label),
    group: groupOf(el),
    value: listbox ? (PLACEHOLDER.test(shown) ? '' : shown) : tag === 'select' ? '' : (el.value || pillOf(el)),
    options: tag === 'select' ? Array.from(el.options).map(o => o.text.trim()) : [],
    role: listbox ? 'listbox' : (el.getAttribute('role') || ''), autocomplete: el.getAttribute('aria-autocomplete') || '',
    checked: !!el.checked, accept: el.getAttribute('accept') || '', ident: el.id || '', scope: scopeOf(el)
  };
});
"""
_SET_VALUE_SCRIPT = (
    "const el = arguments[0], value = arguments[1];"
    "const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
    "const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;"
    "setter.call(el, value);"
    "el.dispatchEvent(new Event('input', {bubbles: true}));"
    "el.dispatchEvent(new Event('change', {bubbles: true}));"
)
_SELECT_SCRIPT = (
    "const el = arguments[0], wanted = arguments[1];"
    "const opt = Array.from(el.options).find(o => o.text.trim() === wanted);"
    "if (!opt) return '';"
    "el.value = opt.value;"
    "el.dispatchEvent(new Event('input', {bubbles: true}));"
    "el.dispatchEvent(new Event('change', {bubbles: true}));"
    "return el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '';"
)
_UNHIDE_SCRIPT = (
    "const el = arguments[0];"
    "el.style.display = 'block'; el.style.visibility = 'visible'; el.style.opacity = '1';"
    "el.style.width = '1px'; el.style.height = '1px'; el.style.position = 'static';"
)
_SCROLL_SCRIPT = "arguments[0].scrollIntoView({block: 'center'})"
_CLICK_SCRIPT = "arguments[0].click()"
_BLUR_SCRIPT = "arguments[0].blur()"
# A hidden radio or checkbox is ticked the way a person does it: through its label.
_CLICK_TICK_SCRIPT = (
    "const el = arguments[0];"
    "let box = (el.labels && el.labels[0]) || el.closest('label');"
    "if (!box && el.id) { try { box = document.querySelector('label[for=\"' + CSS.escape(el.id) + '\"]'); } catch (e) {} }"
    "(box || el).click();"
)
# The options of whichever dropdown menu is open, as [element, text] pairs.
_OPTIONS_SCRIPT = r"""
const out = [];
for (const o of document.querySelectorAll("[role='option'], [id*='-option-'], .dropdown-location")) {
  const r = o.getBoundingClientRect(); const s = getComputedStyle(o);
  if (s.display === 'none' || s.visibility === 'hidden' || (r.width === 0 && r.height === 0)) continue;
  const t = (o.innerText || o.textContent || '').replace(/\s+/g, ' ').trim();
  if (t) out.push([o, t]);
}
return out;
"""
# What a custom dropdown displays: its control box, a few levels above the search input.
_CONTROL_TEXT_SCRIPT = (
    "let node = arguments[0];"
    "for (let i = 0; i < 3 && node.parentElement; i++) node = node.parentElement;"
    "return (node.innerText || '').replace(/\\s+/g, ' ').trim();"
)


class ExternalError(RuntimeError):
    """The company site could not be worked with at all."""


@dataclass
class Field:
    element: Any
    kind: str
    label: str
    required: bool
    group: str = ""
    name: str = ""
    options: List[str] = field(default_factory=list)
    value: str = ""
    role: str = ""
    autocomplete: str = ""
    checked: bool = False
    accept: str = ""
    ident: str = ""
    scope: str = "page"

    @property
    def question(self) -> str:
        if self.kind in ("radio", "checkbox") and self.group:
            return self.group
        return self.label

    @property
    def is_combobox(self) -> bool:
        return self.kind == "text" and (self.role in ("combobox", "listbox") or bool(self.autocomplete))


@dataclass
class FormOutcome:
    filled: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    resume_attached: bool = False

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass
class ExternalResult:
    status: str
    url: str = ""
    ats: str = ""
    detail: str = ""
    filled: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    resume: str = ""

    def to_apply_result(self, job: JobPosting) -> ApplyResult:
        if self.status in (
            ApplyStatus.APPLIED_EXTERNAL,
            ApplyStatus.EXTERNAL_MANUAL,
            ApplyStatus.EXTERNAL_SKIPPED,
            ApplyStatus.ALREADY_APPLIED,
        ):
            status = self.status
        elif self.status == DRY_RUN:
            status = ApplyStatus.EXTERNAL_SKIPPED
        elif self.status == GONE:
            status = ApplyStatus.NO_APPLY_BUTTON
        else:
            status = ApplyStatus.ERROR
        detail = "%s | %s" % (self.url or self.ats or "company site", self.detail)
        return ApplyResult(
            job_id=job.job_id,
            url=job.url,
            status=status,
            detail=detail[:500],
            quota_consumed=False,
            questions_answered=len(self.filled),
            questions_abstained=len(self.missing),
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def detect_ats(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    for needle, name in ATS_HOSTS:
        if needle in host:
            return name
    return "website"


def known_values(profile: Profile) -> Dict[str, str]:
    """Identity, contact and link fields that need no judgement to fill."""
    extra = profile.extra_facts or {}
    full_name = _clean(profile.full_name)
    first = _clean(profile.first_name) or (full_name.split()[0] if full_name else "")
    last = _clean(profile.last_name) or (" ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else "")
    values = {
        "first_name": first,
        "last_name": last,
        "full_name": full_name or " ".join(part for part in (first, last) if part),
        "email": _clean(profile.email),
        "phone": _clean(profile.phone),
        "linkedin_url": _clean(extra.get("linkedin_url")),
        "github_url": _clean(extra.get("github_url")),
        "portfolio_url": _clean(extra.get("portfolio_url") or extra.get("website_url") or extra.get("website")),
        "current_company": _clean(extra.get("current_company")),
        "current_designation": _clean(extra.get("current_designation")),
        "current_location": _clean(profile.current_location),
        "country": _clean(extra.get("country")),
        "country_code": dial_code(profile.phone) or _clean(extra.get("country")),
    }
    return {key: value for key, value in values.items() if value}


def dial_code(phone: str) -> str:
    """The country code a phone number carries: '+91 88789 50951' -> '+91'; "" when it has none.

    Forms that keep the country in a list of its own left the phone short a code: the phone
    rule skips those boxes on purpose, so that the whole number is not typed into one, and
    nothing else answered them. Taken from the number itself rather than a country table.
    """
    found = re.match(r"\+\s*(\d{1,3})", _clean(phone))
    return "+" + found.group(1) if found else ""


def classify_label(question: str) -> Optional[str]:
    """Which known value a label asks for, or None when it needs judgement."""
    text = _clean(question)
    if not text or _YES_NO_QUESTION.match(text):
        # "Will you need sponsorship to stay in your current location?" names a
        # location but wants Yes or No.
        return None
    for pattern, key in _FIELD_RULES:
        if pattern.search(text):
            if key == "portfolio_url" and re.search(r"linkedin|github", text, re.I):
                continue
            if key == "current_location" and re.search(r"preferred|relocat|willing", text, re.I):
                return None
            return key
    return None


def pick_place(value: str, options: List[str], country: str = "") -> Optional[str]:
    """The suggestion for a city typed by name: 'Indore' -> 'Indore, Madhya Pradesh, IND', not 'Indore, WV, USA'."""
    exact = match_option(value, options)
    if exact is not None:
        return exact
    wanted = _norm(value)
    starts = [option for option in options if wanted and _norm(option).startswith(wanted)]
    if len(starts) <= 1:
        return starts[0] if starts else None
    codes = {_norm(country)} if country else set()
    if _norm(country) == "india":
        codes |= {"ind", "in"}
    local = [option for option in starts if codes & set(re.findall(r"[a-z]+", _norm(option)))]
    return min(local or starts, key=len)


def real_options(options: List[str]) -> List[str]:
    return [option for option in options if option and not _PLACEHOLDER_OPTION.match(option)]


def decline_option(options: List[str]) -> Optional[str]:
    for option in options:
        if _DECLINE.search(option):
            return option
    return None


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------


def discover_fields(driver: Any) -> List[Field]:
    try:
        raw = driver.execute_script(_FIELDS_SCRIPT) or []
    except TimeoutException:
        # One careers page hung the renderer: every later read spent the same minute
        # and came back empty, so the page kept being treated as "no form yet" and a
        # single entry held a whole run. A minute of silence is answer enough.
        logger.warning("The page stopped answering; giving this one up.")
        raise
    except WebDriverException as exc:
        logger.warning("Could not read the form (%s): %s", type(exc).__name__, exc)
        return []
    fields = []  # type: List[Field]
    for item in raw:
        if not isinstance(item, dict) or item.get("el") is None:
            continue
        fields.append(
            Field(
                element=item["el"],
                kind=str(item.get("kind") or "text"),
                label=_clean(item.get("label")),
                required=bool(item.get("required")),
                group=_clean(item.get("group")),
                name=str(item.get("name") or ""),
                options=[_clean(option) for option in (item.get("options") or []) if _clean(option)],
                value=str(item.get("value") or ""),
                role=str(item.get("role") or ""),
                autocomplete=str(item.get("autocomplete") or ""),
                checked=bool(item.get("checked")),
                accept=str(item.get("accept") or ""),
                ident=str(item.get("ident") or ""),
                scope=str(item.get("scope") or "page"),
            )
        )
    return fields


def _page_text(driver: Any) -> str:
    try:
        return _clean(driver.find_element(By.TAG_NAME, "body").text)
    except TimeoutException:
        raise
    except WebDriverException:
        return ""


def _current_url(driver: Any) -> str:
    try:
        return driver.current_url or ""
    except WebDriverException:
        return ""


def _visible_controls(driver: Any) -> List[Any]:
    try:
        return [
            element
            for element in driver.find_elements(By.XPATH, _CLICKABLE_XPATH)
            if element.is_displayed() and element.is_enabled()
        ]
    except WebDriverException:
        return []


def _control_text(element: Any) -> str:
    try:
        return _clean(element.text or element.get_attribute("value") or element.get_attribute("aria-label") or "")
    except WebDriverException:
        return ""


def _click(driver: Any, element: Any) -> None:
    try:
        driver.execute_script(_SCROLL_SCRIPT, element)
    except WebDriverException:
        pass
    try:
        element.click()
    except (ElementClickInterceptedException, WebDriverException) as exc:
        logger.debug("Click fell back to the DOM (%s)", type(exc).__name__)
        driver.execute_script(_CLICK_SCRIPT, element)


def _clear(element: Any) -> None:
    for modifier in (Keys.COMMAND, Keys.CONTROL):
        try:
            element.send_keys(modifier + "a")
            element.send_keys(Keys.DELETE)
        except WebDriverException:
            continue


_NUMBER_IN_TEXT = re.compile(r"-?\d+(?:\.\d+)?")


def number_only(value: str) -> str:
    """'3 years' -> '3', '16 LPA' -> '16': a number box keeps nothing else, so it stayed empty."""
    found = _NUMBER_IN_TEXT.search((value or "").replace(",", ""))
    return found.group(0) if found else ""


def set_text(driver: Any, element: Any, value: str) -> bool:
    """Type `value` into a text control and confirm the control holds it."""
    try:
        _click(driver, element)
        _clear(element)
        if len(value) <= 120:
            human_type(element, value)
        else:
            driver.execute_script(_SET_VALUE_SCRIPT, element, value)
        if _norm(element.get_attribute("value") or "") == _norm(value):
            return True
        driver.execute_script(_SET_VALUE_SCRIPT, element, value)
        return _norm(element.get_attribute("value") or "") == _norm(value)
    except WebDriverException as exc:
        logger.debug("Could not write %r (%s): %s", value, type(exc).__name__, exc)
        return False


def select_option(driver: Any, element: Any, wanted: str) -> bool:
    try:
        chosen = driver.execute_script(_SELECT_SCRIPT, element, wanted)
    except WebDriverException as exc:
        logger.debug("Could not select %r (%s): %s", wanted, type(exc).__name__, exc)
        return False
    return _norm(str(chosen or "")) == _norm(wanted)


def _shown_options(driver: Any, timeout_s: float) -> List[Tuple[Any, str]]:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            shown = [(pair[0], _clean(pair[1])) for pair in (driver.execute_script(_OPTIONS_SCRIPT) or []) if len(pair) == 2]
        except WebDriverException:
            shown = []
        if shown or time.monotonic() >= deadline:
            return shown
        time.sleep(POLL_S)


def _word_in(needle: str, haystack: str) -> bool:
    return bool(needle) and bool(re.search(r"(?<!\w)%s(?!\w)" % re.escape(needle), haystack))


def _control_shows(driver: Any, element: Any) -> str:
    try:
        return _norm(str(driver.execute_script(_CONTROL_TEXT_SCRIPT, element) or ""))
    except WebDriverException:
        return ""


def _combobox_shows(driver: Any, element: Any, wanted: str, before: Optional[str] = None) -> bool:
    """True when the dropdown, closed again, displays `wanted` as its value.

    Some pickers display only part of a clicked option ("+91" for "India +91");
    pass the display from `before` the click and that counts once it changed.
    """
    target = _norm(wanted)
    if not target:
        return False
    try:
        typed = _norm(element.get_attribute("value") or "")
    except WebDriverException:
        return False
    shown = _control_shows(driver, element)
    if typed == target or _word_in(target, shown):
        return True
    return before is not None and shown != before and _word_in(shown, target)


def combobox_options(driver: Any, element: Any) -> List[str]:
    """Open a custom dropdown, read what it offers, close it again; [] for type-to-search ones."""
    try:
        _click(driver, element)
        shown = _shown_options(driver, OPTION_WAIT_S / 3)
        if not shown:
            element.send_keys(Keys.ARROW_DOWN)
            shown = _shown_options(driver, OPTION_WAIT_S / 3)
        element.send_keys(Keys.ESCAPE)
        driver.execute_script(_BLUR_SCRIPT, element)
    except WebDriverException as exc:
        logger.debug("Could not open a dropdown (%s): %s", type(exc).__name__, exc)
        return []
    return [text for _, text in shown]


def pick_from_combobox(driver: Any, element: Any, value: str, typed: bool = True) -> bool:
    """Type into a custom dropdown, click the option that names `value`, and confirm it shows.

    The search box keeps whatever was typed until focus leaves, so its text is
    no evidence of a choice; only the closed control displaying the option is.
    """
    before = _control_shows(driver, element)
    try:
        _click(driver, element)
        if typed:
            _clear(element)
            human_type(element, value)
        shown = _shown_options(driver, OPTION_WAIT_S)
        texts = [text for _, text in shown]
        chosen = match_option(value, texts) if texts else None
        if chosen is not None:
            _click(driver, shown[texts.index(chosen)][0])
        elif texts:
            # Leaving with the menu open would let Tab pick whichever option is highlighted.
            element.send_keys(Keys.ESCAPE)
        human_pause(0.3, 0.8)
        driver.execute_script(_BLUR_SCRIPT, element)
        human_pause(0.2, 0.5)
        if chosen is None:
            return _combobox_shows(driver, element, value)
        return _combobox_shows(driver, element, chosen, before)
    except WebDriverException as exc:
        logger.debug("Combobox %r failed (%s): %s", value, type(exc).__name__, exc)
        return False


def attach_file(driver: Any, element: Any, path: Path) -> bool:
    path = paths.readable_upload(path)
    try:
        if not element.is_displayed():
            driver.execute_script(_UNHIDE_SCRIPT, element)
        element.send_keys(str(Path(path).resolve()))
    except WebDriverException as exc:
        logger.warning("Could not attach %s (%s): %s", path.name, type(exc).__name__, exc)
        return False
    deadline = time.monotonic() + FILE_WAIT_S
    while True:
        try:
            if path.name.lower() in (element.get_attribute("value") or "").lower():
                return True
        except WebDriverException:
            pass
        if path.name.lower() in _page_text(driver).lower():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL_S)


def _set_checked(driver: Any, element: Any, checked: bool) -> bool:
    try:
        if bool(element.is_selected()) != checked:
            if element.is_displayed():
                _click(driver, element)
            else:
                driver.execute_script(_CLICK_TICK_SCRIPT, element)
        return bool(element.is_selected()) == checked
    except WebDriverException:
        return False


# ---------------------------------------------------------------------------
# Getting to the form
# ---------------------------------------------------------------------------


def open_company_site(driver: Any, button: Any) -> str:
    """Click Naukri's company-site button and land on the employer's page, in whatever tab it opens."""
    before = set(driver.window_handles)
    start = _current_url(driver)
    _click(driver, button)
    deadline = time.monotonic() + OPEN_WAIT_S
    while True:
        new = [handle for handle in driver.window_handles if handle not in before]
        if new:
            driver.switch_to.window(new[-1])
        url = _current_url(driver)
        if url and url != start and "naukri.com" not in (urlparse(url).netloc or "").lower():
            if "about:blank" not in url:
                return url
        if time.monotonic() >= deadline:
            return ""
        time.sleep(POLL_S)


def return_to(driver: Any, handle: str, keep: List[str]) -> None:
    """Close the tabs this job opened and go back to `handle`.

    Never the last tab: chromedriver quits Chrome with it. When a site or the
    browser agent had closed the tab we started in, the run lost its browser here.
    """
    left: List[str] = []
    try:
        handles = list(driver.window_handles)
        extra = [other for other in handles if other not in keep]
        if len(extra) == len(handles):
            extra = extra[1:]
        for other in extra:
            driver.switch_to.window(other)
            driver.close()
        left = [other for other in handles if other not in extra]
        if left:
            driver.switch_to.window(handle if handle in left else left[0])
    except WebDriverException as exc:
        logger.warning("Could not get back to the Naukri tab (%s): %s", type(exc).__name__, exc)
        return
    if not left:
        raise NoSuchWindowException("The browser has no window left: it was closed or it crashed.")


def settled_fields(driver: Any, settle_s: Optional[float] = None) -> List[Field]:
    """discover_fields, once the page has drawn something.

    Workday builds its page with script after the address changes. Looking the
    moment the tab opened found no fields and no buttons, and the Fidelity
    posting went to you as "no application form found (controls: none)".
    """
    settle_s = SETTLE_S if settle_s is None else settle_s
    deadline = time.monotonic() + FORM_WAIT_S
    drawn_at: Optional[float] = None
    counted, steady_since = -1, 0.0
    while True:
        fields = discover_fields(driver)
        now = time.monotonic()
        if len(fields) != counted:
            counted, steady_since = len(fields), now
        # Workday draws a form in stages; the phone box came after the address.
        if (len(fields) >= 2 and now - steady_since >= STEADY_S) or now >= deadline:
            return fields
        if drawn_at is None and _visible_controls(driver):
            drawn_at = now
        if drawn_at is not None and now - drawn_at >= settle_s:
            return fields
        time.sleep(POLL_S)


def reveal_form(driver: Any, settle_s: Optional[float] = None) -> List[Field]:
    """The form's fields, clicking through an 'Apply' button or two when the page starts with the posting."""
    fields = settled_fields(driver, settle_s)
    if len(fields) >= 2:
        return fields
    for _ in range(2):
        before = set(driver.window_handles)
        candidates = []
        for control in _visible_controls(driver):
            text = _control_text(control)
            if _REVEAL_TEXT.match(text) and not re.search(r"linkedin|indeed|autofill|with", text, re.I):
                # Workday's "Apply" opens a choice; "Apply Manually" is the way on.
                candidates.append((0 if re.search(r"manual", text, re.I) else 1, len(candidates), control))
        if not candidates:
            break
        _click(driver, min(candidates)[2])
        deadline = time.monotonic() + FORM_WAIT_S
        while time.monotonic() < deadline:
            new = [handle for handle in driver.window_handles if handle not in before]
            if new:
                driver.switch_to.window(new[-1])
            fields = discover_fields(driver)
            if len(fields) >= 2:
                return fields
            time.sleep(POLL_S)
    return discover_fields(driver)


def application_fields(fields: List[Field]) -> List[Field]:
    """The form's own fields, or [] when they are only a job-search box: a keyword and a city are not an application.

    A control in the page's header or footer never belongs to the application, and
    while a modal is open the page behind it does not either.
    """
    fields = [item for item in fields if item.scope != "furniture"]
    inside = [item for item in fields if item.scope == "dialog"]
    fields = inside or fields
    for item in fields:
        label = item.question or item.name or ""
        if item.kind in ("file", "textarea", "email", "tel") or _APPLICANT_FIELD.search(label):
            return fields
        if not _SEARCH_WIDGET.search(label):
            return fields
    return []


def find_form_with_help(
    driver: Any, job: JobPosting, settings: Settings, answer_engine: Any
) -> Tuple[List[Field], str]:
    """(fields, why there are none) for a page that shows no form.

    A removed posting is named from its text, a human check is screenshotted
    and left to you, and otherwise the page brain may click one control at a
    time, up to page_brain.MAX_STEPS.
    """
    from . import page_brain

    client = getattr(answer_engine, "client", None)
    for _ in range(page_brain.MAX_STEPS):
        text = _page_text(driver)
        gone = page_brain.dead_reason(text)
        if gone:
            return [], "the posting is gone: %s" % gone
        if challenge_shown(driver) or page_brain.human_check(text):
            shot = page_brain.save_screenshot(driver, settings, "check")
            return [], "the site shows a check only a person may answer (screenshot: %s)" % shot
        if out_of_quota():
            return [], "waiting for the model: %s" % out_of_quota()
        if not settings.judge_answers or client is None or not client.available():
            return [], ""
        controls = [(control, _control_text(control)) for control in _visible_controls(driver)]
        controls = [(control, label) for control, label in controls if label]
        if not controls:
            return [], ""
        shot = page_brain.save_screenshot(driver, settings, "stuck")
        step = page_brain.next_step(client, shot, _current_url(driver), text, [label for _, label in controls], job)
        if step is None:
            return [], "the page brain gave no usable answer (screenshot: %s)" % shot
        if step.action == "dead":
            return [], "the posting is gone: %s" % step.reason
        if step.action == "stop":
            return [], "no way to the form: %s (screenshot: %s)" % (step.reason, shot)
        element, label = controls[step.control - 1]
        if re.search(r"linkedin|indeed", label, re.I):
            return [], "the only way in is %r, which needs you (screenshot: %s)" % (label, shot)
        logger.info("      page brain: clicking %r (%s)", label, step.reason)
        before = set(driver.window_handles)
        _click(driver, element)
        human_pause(2.0, 4.0)
        new = [handle for handle in driver.window_handles if handle not in before]
        if new:
            driver.switch_to.window(new[-1])
        fields = application_fields(reveal_form(driver))
        if len(fields) >= 2 or wants_account(driver, fields):
            return fields, ""
    return [], "the page brain clicked %d time(s) and still found no form on %s" % (page_brain.MAX_STEPS, _current_url(driver))


def wants_account(driver: Any, fields: List[Field]) -> bool:
    """A sign-in wall: no form but a sign-in control, or a password box with nowhere to attach a resume."""
    if any(item.kind == "password" for item in fields):
        return not any(item.kind == "file" for item in fields)
    if len(fields) >= 2:
        return False
    texts = " | ".join(_control_text(control) for control in _visible_controls(driver))
    return bool(_SIGN_IN.search(texts))


def google_sign_in(driver: Any, settings: Settings, timeout_s: float = MANUAL_LOGIN_TIMEOUT_S) -> Tuple[bool, str]:
    """Use the Google session already in the browser profile; never type a Google password."""
    buttons = [element for element in driver.find_elements(By.XPATH, _GOOGLE_BUTTON_XPATH) if element.is_displayed()]
    if not buttons:
        return False, "no Google sign-in button"
    if not settings.google_email:
        return False, "GOOGLE_EMAIL is not set, so the account to pick is unknown"
    main = driver.current_window_handle
    before = set(driver.window_handles)
    _click(driver, buttons[0])

    deadline = time.monotonic() + GOOGLE_WAIT_S
    popup = None  # type: Optional[str]
    while time.monotonic() < deadline:
        new = [handle for handle in driver.window_handles if handle not in before]
        if new:
            popup = new[-1]
            driver.switch_to.window(popup)
        if "accounts.google.com" in _current_url(driver) or (popup is None and _current_url(driver) != ""):
            break
        time.sleep(POLL_S)

    wanted = settings.google_email.casefold()
    chooser_deadline = time.monotonic() + GOOGLE_WAIT_S
    asked_person = False
    while True:
        url = _current_url(driver)
        if "accounts.google.com" not in url:
            break
        try:
            accounts = [
                element
                for element in driver.find_elements(By.XPATH, "//*[@data-identifier or @data-email or contains(%s,'%s')]" % (_LOWER, wanted))
                if element.is_displayed()
            ]
        except WebDriverException:
            accounts = []
        match = next(
            (
                element
                for element in accounts
                if wanted in _norm((element.get_attribute("data-identifier") or element.get_attribute("data-email") or element.text or ""))
            ),
            None,
        )
        if match is not None:
            _click(driver, match)
            human_pause(1.0, 2.0)
            chooser_deadline = time.monotonic() + GOOGLE_WAIT_S
            continue
        try:
            needs_typing = any(element.is_displayed() for element in driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[type='password']"))
        except WebDriverException:
            needs_typing = False
        if needs_typing:
            if settings.headless:
                _leave_popup(driver, popup, main)
                return False, (
                    "Google wants a fresh sign-in. Open Google in Connections and choose "
                    "Sign in, or set HEADLESS=false and BACKGROUND=false and omit "
                    "--headless for a local run, then finish signing in by hand."
                )
            if not asked_person:
                logger.warning(
                    "Google is asking for the account sign-in. Finish it in the browser window; waiting up to %d minutes.",
                    int(timeout_s // 60),
                )
                asked_person = True
                chooser_deadline = time.monotonic() + timeout_s
        if time.monotonic() >= chooser_deadline:
            _leave_popup(driver, popup, main)
            return False, "Google sign-in did not finish in time"
        time.sleep(1.0)

    _leave_popup(driver, popup, main)
    return True, "google"


def _leave_popup(driver: Any, popup: Optional[str], main: str) -> None:
    try:
        if popup is not None and popup in driver.window_handles and popup != main:
            driver.switch_to.window(popup)
            driver.close()
        driver.switch_to.window(main)
    except WebDriverException as exc:
        logger.debug("Could not tidy the sign-in window (%s): %s", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# Filling
# ---------------------------------------------------------------------------


def _resolve(answer_engine: Any, question: str, options: Optional[List[str]]) -> Optional[str]:
    resolution = answer_engine.resolve(question, options=options, field_type="text" if options is None else "select")
    if resolution.abstained or resolution.answer is None or not resolution.answer.text:
        return None
    return resolution.answer.text


def _choose(driver: Any, item: Field, option: str) -> bool:
    if not item.is_combobox:
        return select_option(driver, item.element, option)
    # A Greenhouse dropdown once dropped a "No" that the same page took on every
    # later try; one more attempt costs seconds, a missed one costs the application.
    typed = item.role != "listbox"
    return pick_from_combobox(driver, item.element, option, typed) or pick_from_combobox(driver, item.element, option, typed)


def _note_mismatch(answer_engine: Any, question: str, value: str, options: List[str]) -> None:
    """An answer that fits none of the options goes to answers.txt like an unanswered question."""
    note = getattr(answer_engine, "record_option_mismatch", None)
    if callable(note):
        note(question, value, options)


Writer = Callable[[str], Optional[str]]


def _own_words(answer_engine: Any, question: str, required: bool, writer: Optional[Writer] = None) -> Optional[str]:
    """A long answer: yours from answers.txt first, else (when required or marked per job) one written for this job.

    A required one that neither gives is added to the file for you to write.
    """
    book = getattr(answer_engine, "book", None)
    answer = book.answer_for(question) if book is not None else None
    per_job = book is not None and book.per_job(question)
    if answer is None and (required or per_job) and writer is not None:
        answer = writer(question)
    if answer is None and required and book is not None:
        book.add_blank(question, "long answers are yours to write", None, getattr(answer_engine, "job_context", None))
    return answer


def long_answer_writer(settings: Settings, answer_engine: Any, job: JobPosting) -> Optional[Writer]:
    """Writes a form's long answer from the resume and posting; each one is kept in the job's resume folder."""
    client = getattr(answer_engine, "client", None)
    if not settings.judge_answers or settings.answer_mode != AnswerMode.AUTO:
        return None
    if client is None or not client.available():
        return None
    from common import assist
    from common import resume as resume_module

    try:
        base = resume_module.load_source(settings.resume_path)
    except resume_module.ResumeError as exc:
        logger.info("      long answers stay yours: %s", exc)
        return None

    def write(question: str) -> Optional[str]:
        if _NOT_FOR_JUDGEMENT.search(question):
            return None
        answer = resume_module.write_long_answer(client, base, job, question)
        if answer is None:
            return None
        folder = resume_module.tailored_dir(settings, job)
        kept = folder / "answers.md"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with kept.open("a", encoding="utf-8") as handle:
                handle.write("## %s\n\n%s\n\n" % (" ".join(question.split()), answer))
            assist.record_change(settings, assist.Change(
                file=str(kept), item=" ".join(question.split()), value=answer,
                source="resume and posting", evidence="", kind="written"))
        except OSError as exc:
            logger.warning("Could not keep the long answer in %s: %s", kept, exc)
        logger.info("      wrote a long answer for %r (kept in %s)", question, kept)
        return answer

    return write


def _fill_choice(
    driver: Any, item: Field, value: str, options: List[str], answer_engine: Any, outcome: FormOutcome
) -> None:
    label = item.question or item.name
    chosen = match_option(value, options)
    if chosen is None:
        _note_mismatch(answer_engine, label, value, options)
    if chosen is not None and _choose(driver, item, chosen):
        outcome.filled.append(label)
    elif item.required:
        outcome.missing.append(label)
    else:
        outcome.skipped.append(label)


def type_place(driver: Any, element: Any, value: str, country: str) -> bool:
    """Type a city and click the matching suggestion; free text stands only where no list appears."""
    try:
        _click(driver, element)
        _clear(element)
        human_type(element, value)
        shown = _shown_options(driver, OPTION_WAIT_S)
        texts = [text for _, text in shown]
        chosen = pick_place(value, texts, country) if texts else None
        if chosen is not None:
            _click(driver, shown[texts.index(chosen)][0])
        elif texts:
            element.send_keys(Keys.ESCAPE)
        human_pause(0.3, 0.8)
        driver.execute_script(_BLUR_SCRIPT, element)
        human_pause(0.2, 0.5)
        return _combobox_shows(driver, element, chosen or value)
    except WebDriverException as exc:
        logger.debug("Place %r failed (%s): %s", value, type(exc).__name__, exc)
        return False


def _fresh(driver: Any, item: Field) -> Optional[Any]:
    """The field as the page has it now: Workday redraws a box once something is typed in it."""
    for by, key in ((By.ID, item.ident), (By.NAME, item.name)):
        if not key:
            continue
        try:
            found = driver.find_elements(by, key)
        except WebDriverException:
            continue
        if len(found) == 1:
            return found[0]
    return None


def _kept(driver: Any, item: Field, value: str) -> bool:
    element = _fresh(driver, item)
    try:
        return element is not None and _norm(element.get_attribute("value") or "") == _norm(value)
    except WebDriverException:
        return False


def _fill_place(driver: Any, item: Field, value: str, country: str, outcome: FormOutcome) -> None:
    label = item.question or item.name
    if type_place(driver, item.element, value, country) or _kept(driver, item, value):
        outcome.filled.append(label)
    elif item.required:
        outcome.missing.append(label)
    else:
        outcome.skipped.append(label)


def _recheck(driver: Any, fields: List[Field], outcome: FormOutcome) -> None:
    """Some sites clear a field once focus moves on; a value that vanished was never filled."""
    for item in fields:
        label = item.question or item.name
        if item.kind not in _TEXT_KINDS or item.is_combobox or label not in outcome.filled:
            continue
        try:
            value = item.element.get_attribute("value") or ""
        except WebDriverException:
            element = _fresh(driver, item)
            if element is None:
                continue
            try:
                value = element.get_attribute("value") or ""
            except WebDriverException:
                continue
        if not value.strip():
            outcome.filled.remove(label)
            (outcome.missing if item.required else outcome.skipped).append(label)


def _fill_text(driver: Any, item: Field, value: str, outcome: FormOutcome) -> None:
    label = item.question or item.name
    if item.kind == "number":
        value = number_only(value) or value
    done = (
        pick_from_combobox(driver, item.element, value, item.role != "listbox")
        if item.is_combobox
        else set_text(driver, item.element, value)
    )
    if not done and not item.is_combobox:
        done = _kept(driver, item, value)
    if done:
        outcome.filled.append(label)
    elif item.required:
        outcome.missing.append(label)
    else:
        outcome.skipped.append(label)


def _fill_radio_group(driver: Any, group: List[Field], answer_engine: Any, outcome: FormOutcome) -> None:
    question = group[0].group or _clean(group[0].name.replace("_", " ").replace("-", " "))
    options = [item.label for item in group if item.label]
    required = any(item.required for item in group)
    if any(item.checked for item in group):
        outcome.skipped.append(question)
        return
    chosen = None  # type: Optional[str]
    if _EEO.search(question) or any(_EEO.search(option) for option in options):
        chosen = decline_option(options)
    elif _CONSENT.search(question) or any(_CONSENT.search(option) for option in options):
        chosen = next(
            (option for option in options if _CONSENTING.match(option) and not re.search(r"\bnot\b|\bdon'?t\b", option, re.I)),
            None,
        )
    if chosen is None and options:
        chosen = _resolve(answer_engine, question, options)
    if chosen is not None:
        target = next((item for item in group if item.label == chosen), None)
        if target is None:
            fitted = match_option(chosen, options)
            target = next((item for item in group if item.label == fitted), None)
            if target is None:
                _note_mismatch(answer_engine, question, chosen, options)
        if target is not None and _set_checked(driver, target.element, True):
            outcome.filled.append(question)
            return
    (outcome.missing if required else outcome.skipped).append(question)


def _fill_checkbox_group(driver: Any, group: List[Field], answer_engine: Any, outcome: FormOutcome) -> None:
    question = group[0].group or _clean(group[0].name.replace("_", " ").replace("-", " "))
    options = [item.label for item in group if item.label]
    required = any(item.required for item in group)
    selections, _ = answer_engine.resolve_many(question, options)
    if selections:
        ok = all(
            _set_checked(driver, item.element, item.label in selections)
            for item in group
            if item.label
        )
        if ok:
            outcome.filled.append(question)
            return
    (outcome.missing if required else outcome.skipped).append(question)


def _fill_single_checkbox(driver: Any, item: Field, answer_engine: Any, outcome: FormOutcome) -> None:
    label = item.question or item.name
    if _CONSENT.search(label):
        if _set_checked(driver, item.element, True):
            outcome.filled.append(label)
        elif item.required:
            outcome.missing.append(label)
        return
    # "Remember me", "Show password", job alerts: an optional box never blocks a submit.
    if not item.required:
        outcome.skipped.append(label)
        return
    answer = _resolve(answer_engine, label, ["Yes", "No"])
    if answer is not None and _set_checked(driver, item.element, answer == "Yes"):
        outcome.filled.append(label)
    elif item.required:
        outcome.missing.append(label)
    else:
        outcome.skipped.append(label)


def _emailed_code(driver: Any, settings: Optional[Settings]) -> str:
    """The code the site just emailed, read out of their Gmail; "" when it cannot be had."""
    if settings is None:
        return ""
    from .inbox import verification

    found = verification(settings, driver, domain=urlparse(_current_url(driver)).netloc)
    if found.code:
        logger.info("      read the code Gmail got (%s)", found.subject or "no subject")
        return found.code
    logger.info("      no emailed code to use: %s", found.why or "nothing recent in the inbox")
    return ""


def fill_form(
    driver: Any,
    fields: List[Field],
    profile: Profile,
    answer_engine: Any,
    resume_pdf: Optional[Path],
    writer: Optional[Writer] = None,
    settings: Optional[Settings] = None,
    insist: bool = False,
) -> FormOutcome:
    """Fill every control the bot can answer for; name the required ones it cannot.

    Without `settings` a code the site emailed cannot be read, and that field is
    reported as one for a person. With `insist` every box counts as required: forms
    that mark their questions optional and still refuse to move on get a second pass
    where an unanswered one is reported rather than passed over.
    """
    outcome = FormOutcome()
    values = known_values(profile)
    emailed = {}  # type: Dict[str, Optional[str]]
    radios = {}  # type: Dict[str, List[Field]]
    checkboxes = {}  # type: Dict[str, List[Field]]
    for item in fields:
        if item.kind == "radio":
            radios.setdefault(item.name or item.group or item.label, []).append(item)
        elif item.kind == "checkbox":
            checkboxes.setdefault(item.name or item.group or item.label, []).append(item)

    if settings is not None and any(_ONE_TIME_CODE.search(item.question or item.name) for item in fields):
        # This page will email a code, and the only inbox the bot can read is the one
        # signed in to this browser: an address it cannot open leaves the form stuck.
        from .accounts import account_email

        values["email"] = account_email(settings) or values.get("email", "")

    for item in fields:
        label = item.question or item.name
        if item.kind in ("radio", "checkbox"):
            continue
        if item.kind == "file":
            # The id often says what a generic "Attach" label does not (resume, cover_letter).
            hint = " ".join((label, item.name, item.ident))
            for_resume = bool(_RESUME.search(label)) or (not _COVER.search(label) and bool(_RESUME.search(hint)))
            if _COVER.search(hint) and not for_resume:
                (outcome.missing if item.required else outcome.skipped).append(label or "Cover letter")
            elif resume_pdf is not None and resume_pdf.is_file() and (for_resume or not label or "pdf" in item.accept.lower()):
                if attach_file(driver, item.element, resume_pdf):
                    outcome.filled.append(label or "Resume")
                    outcome.resume_attached = True
                else:
                    outcome.missing.append(label or "Resume")
            else:
                (outcome.missing if item.required else outcome.skipped).append(label or "File")
            continue
        if HONEYPOT.search(label):
            continue
        if _CHALLENGE.search(label):
            outcome.missing.append("%s (a check only a person may answer)" % label)
            continue
        if _ONE_TIME_CODE.search(label) and item.kind != "password":
            # Oracle Cloud's gate has four boxes the inbox could fill; waiting a minute
            # for each one costs four minutes to learn the same thing once would.
            if "code" not in emailed:
                emailed["code"] = _emailed_code(driver, settings)
            code = emailed["code"]
            if code:
                _fill_text(driver, item, code, outcome)
            else:
                outcome.missing.append("%s (the code the site emailed)" % label)
            continue
        if _ACCOUNT.search(label) or item.kind == "password":
            outcome.missing.append(label or item.kind)
            continue
        if item.value and item.kind != "select":
            outcome.skipped.append(label)
            continue
        if _COVER.search(label) and item.kind != "textarea":
            (outcome.missing if item.required else outcome.skipped).append(label)
            continue
        options = real_options(combobox_options(driver, item.element) if item.is_combobox else item.options)
        if _EEO.search(label):
            chosen = decline_option(options) if options else None
            if chosen is not None and _choose(driver, item, chosen):
                outcome.filled.append(label)
                continue
            # This form has no "prefer not to say", so the answer you wrote yourself
            # is better than a required box left empty; falls through to the usual path.
        key = classify_label(label)
        value = values.get(key or "", "")
        wanted = item.required or insist
        if not value and item.kind == "textarea":
            # Hirist asks for CTC, notice and years in a textarea: a fact first, prose only when no fact answers.
            if _FACT_QUESTION.search(label):
                value = _resolve(answer_engine, label, options or None) or ""
            value = value or _own_words(answer_engine, label, wanted, writer) or ""
        elif not value and (wanted or _FACT_QUESTION.search(label)):
            # Hirist marks every screening question optional and still keeps Next disabled
            # until each one is answered, so a fact is worth looking up either way.
            value = _resolve(answer_engine, label, options or None) or ""
            if not value and insist:
                value = _own_words(answer_engine, label, True, writer) or ""
        elif not value:
            # Other optional boxes (social links, "Street", search widgets) take only your own
            # answers: asking the model filled answers.txt with "Loading" and "Facebook".
            own = getattr(answer_engine, "own_answer", None)
            value = (own(label, options or None) if callable(own) else None) or ""
        if not value:
            (outcome.missing if wanted else outcome.skipped).append(label)
            continue
        if item.kind == "select" or (item.is_combobox and options):
            _fill_choice(driver, item, value, options, answer_engine, outcome)
        elif item.kind in _TEXT_KINDS and item.kind != "textarea" and _PLACE.search(" ".join((label, item.name))):
            _fill_place(driver, item, value, values.get("country", ""), outcome)
        else:
            _fill_text(driver, item, value, outcome)

    _recheck(driver, fields, outcome)
    for group in radios.values():
        _fill_radio_group(driver, group, answer_engine, outcome)
    for group in checkboxes.values():
        if len(group) == 1:
            _fill_single_checkbox(driver, group[0], answer_engine, outcome)
        else:
            _fill_checkbox_group(driver, group, answer_engine, outcome)
    return outcome


# ---------------------------------------------------------------------------
# Submitting
# ---------------------------------------------------------------------------


def challenge_shown(driver: Any) -> bool:
    """A reCAPTCHA, hCaptcha or Turnstile widget on the page."""
    try:
        return any(element.is_displayed() for element in driver.find_elements(By.CSS_SELECTOR, _CHALLENGE_CSS))
    except WebDriverException:
        return False


def find_submit(driver: Any) -> Optional[Any]:
    """The form's submit control; a page-top 'Apply' link only when nothing better exists."""
    best = None  # type: Optional[Any]
    best_rank = 3
    for control in _visible_controls(driver):
        text = _control_text(control)
        if re.search(r"linkedin|indeed|autofill|google|with ", text, re.I):
            continue
        try:
            is_submit = (control.get_attribute("type") or "").lower() == "submit"
        except WebDriverException:
            is_submit = False
        if not (_SUBMIT_TEXT.match(text) or (is_submit and re.search(r"submit|apply|send", text, re.I))):
            continue
        rank = (0 if is_submit else 1) + (1 if text.lower().startswith("apply") else 0)
        if rank < best_rank:
            best, best_rank = control, rank
    return best


_MAILTO_SCRIPT = """
return Array.from(document.querySelectorAll('a[href^="mailto:"], a[href^="MAILTO:"]'))
  .filter(function (a) { var r = a.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
  .map(function (a) {
    return {
      href: a.getAttribute('href') || '',
      text: ((a.innerText || '') + ' ' + (a.getAttribute('aria-label') || '') + ' ' + (a.getAttribute('title') || '')).trim(),
      around: ((a.parentElement && a.parentElement.innerText) || '').slice(0, 200)
    };
  });
"""

_APPLY_BY_MAIL = re.compile(r"appl|resume|\bcv\b|candidat|hiring|recruit|\bjobs?\b|careers?|\bhr\b", re.I)


def apply_by_email(driver: Any) -> str:
    """The address to send an application to, when a mail link is the posting's only apply route."""
    try:
        links = driver.execute_script(_MAILTO_SCRIPT) or []
    except TimeoutException:
        raise
    except WebDriverException:
        return ""
    for link in links:
        href = str(link.get("href") or "")
        address = href.split(":", 1)[-1].split("?", 1)[0].strip()
        if "@" not in address:
            continue
        said = " ".join([str(link.get("text") or ""), str(link.get("around") or ""), href])
        if _APPLY_BY_MAIL.search(said):
            return address
    return ""


def disabled_step(driver: Any) -> str:
    """The text of a Next or Submit button the page shows but keeps disabled; "" when there is none."""
    try:
        for element in driver.find_elements(By.XPATH, _CLICKABLE_XPATH):
            text = _control_text(element)
            if (_NEXT_TEXT.match(text) or _SUBMIT_TEXT.match(text)) and element.is_displayed() and not element.is_enabled():
                return text
    except WebDriverException:
        pass
    return ""


def find_next(driver: Any) -> Optional[Any]:
    """A multi-page form's Next / Save and Continue button, if this page has one."""
    for control in _visible_controls(driver):
        text = _control_text(control)
        if _NEXT_TEXT.match(text) and not re.search(r"with ", text, re.I):
            return control
    return None


def _form_signature(driver: Any) -> Tuple[str, Tuple[str, ...]]:
    return _current_url(driver), tuple(sorted(item.question or item.name for item in discover_fields(driver)))


def next_page(driver: Any, step: Any) -> Tuple[bool, str]:
    """Click Next and wait for a different set of fields; (moved, what the site said if not)."""
    before = _form_signature(driver)
    _click(driver, step)
    deadline = time.monotonic() + FORM_WAIT_S
    while True:
        try:
            errors = [
                _clean(element.text)
                for element in driver.find_elements(By.CSS_SELECTOR, "[aria-invalid='true'], [class*='error'], [role='alert']")
                if element.is_displayed() and _clean(element.text)
            ]
        except WebDriverException:
            errors = []
        if errors:
            return False, "the site reported: %s" % "; ".join(errors)[:300]
        if _form_signature(driver) != before:
            human_pause(0.8, 1.6)
            return True, ""
        if time.monotonic() >= deadline:
            return False, "nothing changed within %d seconds of clicking %s" % (int(FORM_WAIT_S), _control_text(step) or "Next")
        time.sleep(POLL_S)


def confirmation_words(text: str) -> str:
    """The confirmation phrase a page or a quote of one holds, or "" when it holds none."""
    lowered = _clean(text).lower()
    return next((marker for marker in _CONFIRMED if marker in lowered), "")


def wait_for_confirmation(driver: Any, timeout_s: float = CONFIRM_WAIT_S) -> Tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    while True:
        marker = confirmation_words(_page_text(driver))
        if marker:
            return True, "the site says: %s" % marker
        try:
            errors = [
                _clean(element.text)
                for element in driver.find_elements(By.CSS_SELECTOR, "[aria-invalid='true'], [class*='error'], [role='alert']")
                if element.is_displayed() and _clean(element.text)
            ]
        except WebDriverException:
            errors = []
        if errors:
            return False, "the site reported: %s" % "; ".join(errors)[:300]
        url = _current_url(driver).lower()
        if _confirmation_url(url) and not discover_fields(driver):
            return True, "confirmation page %s" % url
        if time.monotonic() >= deadline:
            return False, "no confirmation within %d seconds" % int(timeout_s)
        time.sleep(POLL_S)


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------


def apply_here(
    driver: Any,
    job: JobPosting,
    profile: Profile,
    answer_engine: Any,
    settings: Settings,
    resume_pdf: Optional[Path],
    dry_run: bool,
) -> ExternalResult:
    """Apply on the page the browser is showing; never submit a half-filled form."""
    from .accounts import sign_in

    from .cold_email import harvest_contacts

    url = _current_url(driver)
    ats = detect_ats(url)
    result = ExternalResult(status=ApplyStatus.EXTERNAL_MANUAL, url=url, ats=ats, resume=str(resume_pdf or ""))
    if ats in NOT_A_CAREER_SITE:
        result.detail = "%s applications need a %s session; finish this one by hand" % (ats, ats)
        return result
    harvest_contacts(driver, job, settings, "career page %s" % (urlparse(url).netloc or ats or "the employer"))
    said = already_applied(driver)
    if said:
        result.status = ApplyStatus.ALREADY_APPLIED
        result.detail = "this one is already in; the page says: %s" % said
        return result
    waiting = site_already_waiting(settings, url, settings.browser_agent)
    if waiting:
        result.status = ApplyStatus.EXTERNAL_SKIPPED
        result.detail = "%s: %s" % (SAME_SITE_WAITING, waiting)
        return result

    from .page_brain import dead_reason

    fields = application_fields(reveal_form(driver))
    stuck = ""
    if len(fields) < 2:
        gone = dead_reason(_page_text(driver))
        if gone:
            result.status, result.detail = GONE, "the posting is gone: %s" % gone
            return result
        if not wants_account(driver, fields):
            # No form and no Apply control, but a hiring mailbox: reading the page with the model
            # or handing it to the agent cannot help, because there is nothing here to fill in.
            address = apply_by_email(driver) if find_submit(driver) is None else ""
            if address:
                result.detail = "this employer takes applications by email only: %s" % address
                return result
            fields, stuck = find_form_with_help(driver, job, settings, answer_engine)
            if stuck.startswith("the posting is gone"):
                result.status, result.detail = GONE, stuck
                return result
    # Workday asks for a new account's password once more right after creating it.
    for _ in range(2):
        if not wants_account(driver, fields):
            break
        ok, how = sign_in(driver, settings, profile, dry_run)
        if not ok:
            result.detail = "the site asks for an account: %s" % how
            return result
        logger.info("      company site: %s", how)
        human_pause(1.5, 3.0)
        # After a sign-in Workday draws its header at once and the form seconds later.
        fields = application_fields(reveal_form(driver, settle_s=FORM_WAIT_S))
    if len(fields) < 2 and stuck:
        result.detail = stuck
        return result
    if len(fields) < 2:
        labels = [_control_text(control) for control in _visible_controls(driver)]
        result.detail = "no application form found on %s (controls: %s)" % (
            url,
            ", ".join([label for label in labels if label][:8]) or "none",
        )
        return result

    writer = long_answer_writer(settings, answer_engine, job)
    saw_file_input = False
    for page in range(1, MAX_PAGES + 1):
        outcome = fill_form(driver, fields, profile, answer_engine, resume_pdf, writer, settings)
        result.filled += outcome.filled
        result.missing = outcome.missing
        saw_file_input = saw_file_input or any(item.kind == "file" for item in fields)
        if outcome.resume_attached:
            resume_pdf = None
        held = disabled_step(driver) if outcome.skipped and not outcome.missing else ""
        if held:
            # The page will not move until every box is answered, whatever it marks as
            # optional, so the ones passed over get a second pass that insists.
            logger.info(
                "      company site: '%s' is disabled; answering the %d optional question(s) too",
                held,
                len(outcome.skipped),
            )
            fields = application_fields(settled_fields(driver))
            outcome = fill_form(driver, fields, profile, answer_engine, None, writer, settings, insist=True)
            result.filled += outcome.filled
            result.missing = outcome.missing
        if challenge_shown(driver):
            result.missing.append("captcha (a check only a person may answer)")
        if result.missing:
            result.detail = "needs you for: %s" % "; ".join(result.missing)
            return result

        step = find_next(driver)
        if step is None:
            break
        if dry_run:
            result.status = DRY_RUN
            result.detail = "dry run: page %d filled (%d fields), the next page was not opened" % (page, len(result.filled))
            return result
        moved, problem = next_page(driver, step)
        if not moved:
            result.detail = "page %d did not move on: %s" % (page, problem)
            return result
        fields = discover_fields(driver)
    else:
        result.detail = "the form still had more pages after %d; finish it by hand" % MAX_PAGES
        return result

    if resume_pdf is not None and not saw_file_input:
        result.missing.append("Resume (the form has no file upload)")
        result.detail = "needs you for: %s" % "; ".join(result.missing)
        return result
    submit = find_submit(driver)
    if submit is None:
        held = disabled_step(driver)
        result.detail = (
            "every field is filled but the '%s' button stays disabled" % held
            if held
            else "every field is filled but no Submit button was found"
        )
        return result
    if dry_run:
        result.status = DRY_RUN
        result.detail = "dry run: %d fields filled, Submit found, nothing sent" % len(result.filled)
        return result

    try:
        _click(driver, submit)
    except WebDriverException as exc:
        # The click may have gone through before the error, so this is held back like
        # any other unconfirmed submit rather than retried as a plain error.
        result.status = ApplyStatus.ERROR
        result.detail = "Submit was clicked but the browser then failed: %s" % type(exc).__name__
        return result
    confirmed, detail = wait_for_confirmation(driver, CONFIRM_WAIT_S)
    if not confirmed and not detail.startswith("the site reported"):
        quote = _confirmed_by_brain(driver, job, settings, answer_engine)
        if quote:
            confirmed, detail = True, "the site says (read by the page brain): %s" % quote
    if confirmed:
        result.status = ApplyStatus.APPLIED_EXTERNAL
        result.detail = detail
        return result
    refused = _submit_refused(driver, detail)
    if refused:
        result.detail = "the site turned the Submit click down: %s" % refused
        return result
    result.status = ApplyStatus.ERROR
    result.detail = "Submit was clicked but %s" % detail
    return result


def _submit_refused(driver: Any, said: str) -> str:
    """Why a clicked Submit sent nothing, or "" when a quiet success cannot be ruled out.

    Both gates that decide what to try again refuse anything whose reason says the Submit
    was clicked, because applying twice is worse than not applying. A site that answered
    the click with an error of its own, or that is still showing the form with required
    boxes empty, plainly has nothing on file, so those two are told apart here and left
    open instead of being retired.
    """
    if said.startswith("the site reported"):
        return said
    blank = [
        item.question or item.name
        for item in application_fields(settled_fields(driver))
        if item.required and not item.value
    ]
    if not blank:
        return ""
    return "the form is still on screen, unanswered: %s" % ", ".join(blank[:6])


def _confirmed_by_brain(driver: Any, job: JobPosting, settings: Settings, answer_engine: Any) -> str:
    """After a Submit with no confirmation it knows, let the page brain read the page; "" when it cannot tell."""
    from . import page_brain

    client = getattr(answer_engine, "client", None)
    if not settings.judge_answers or client is None or not client.available():
        return ""
    text = _page_text(driver)
    if challenge_shown(driver) or page_brain.human_check(text):
        return ""
    shot = page_brain.save_screenshot(driver, settings, "submitted")
    quote = page_brain.confirmation(client, shot, _current_url(driver), text, job)
    logger.info("      page brain on the submitted page: %s", quote or "no confirmation it can quote")
    return quote


def apply_on_company_site(
    driver: Any,
    job: JobPosting,
    profile: Profile,
    answer_engine: Any,
    settings: Settings,
    resume_pdf: Optional[Path] = None,
) -> ExternalResult:
    """From the Naukri job page: follow 'Apply on company site', apply there, come back."""
    from naukri_bot.apply import classify_apply_button

    naukri_handle = driver.current_window_handle
    keep = list(driver.window_handles)
    set_context = getattr(answer_engine, "set_job_context", None)
    if callable(set_context):
        set_context(job)
    try:
        button, kind = classify_apply_button(driver)
        if button is None or kind != "external":
            return ExternalResult(status=ApplyStatus.ERROR, url=job.url, detail="no company-site button on the job page")
        site = open_company_site(driver, button)
        if not site:
            return ExternalResult(status=ApplyStatus.ERROR, url=job.url, detail="the company-site link did not leave Naukri")
        logger.info("      company site: %s (%s)", site, detect_ats(site))
        result = apply_here(driver, job, profile, answer_engine, settings, resume_pdf, settings.dry_run)
        result = browser_agent.take_over(driver, job, profile, settings, resume_pdf, settings.dry_run, result)
    except (StaleElementReferenceException, WebDriverException) as exc:
        result = ExternalResult(status=ApplyStatus.ERROR, url=_current_url(driver), detail="%s: %s" % (type(exc).__name__, exc))
    finally:
        return_to(driver, naukri_handle, keep)
    if result.status in (ApplyStatus.APPLIED_EXTERNAL, ApplyStatus.ALREADY_APPLIED, GONE):
        forget_company_site(settings, job)
    elif result.status != DRY_RUN and not (result.detail or "").startswith(SAME_SITE_WAITING):
        record_company_site(settings, job, result)
    return result


SAME_SITE_WAITING = "another posting on this site is already waiting"


def site_already_waiting(settings: Settings, url: str, agent: bool = False) -> str:
    """Why this employer's site stopped before, when no posting on it is worth trying again."""
    host = (urlparse(url).netloc or "").casefold()
    if not host:
        return ""
    waiting = [
        entry
        for entry in pending_company_sites(settings)
        if (urlparse(str(entry.get("site") or "")).netloc or "").casefold() == host
    ]
    if not waiting or any(retryable(entry, agent=agent) for entry in waiting):
        return ""
    return str(waiting[-1].get("why") or "something only you can finish")


def record_company_site(settings: Settings, job: JobPosting, result: ExternalResult) -> Path:
    """Append the half-done application to user/inputs/company_sites.md for a person."""
    path = Path(settings.data_dir or paths.user("inputs")) / "company_sites.md"
    header = (
        "# Applications on company websites that need you\n\n"
        "The bot opened these from Naukri's \"Apply on company site\" button, filled\n"
        "what it could and stopped short of submitting. Finish each one by hand, or\n"
        "answer the open questions in answers.txt and run\n"
        "`python3 -m sites_bot.external --url <site link> --title \"...\" --company \"...\"`.\n"
        "Delete an entry once you have applied; the bot drops it itself when it\n"
        "finishes one, and replaces it when it tries the same job again.\n"
    )
    entry = [
        "",
        "## %s | %s | %s" % (datetime.now().strftime("%Y-%m-%d %H:%M"), job.company or "Unknown company", job.title or "Role"),
        "- Status: %s" % ("needs you" if result.status == ApplyStatus.EXTERNAL_MANUAL else result.status),
        "- Why: %s" % (result.detail or "-"),
        "- Site: %s" % (result.url or "-"),
        "- Naukri: %s" % (job.url or "-"),
    ]
    if result.resume:
        entry.append("- Resume to send: %s" % result.resume)
    if result.filled:
        entry.append("- Already filled: %s" % ", ".join(result.filled))
    if result.missing:
        entry.append("- Left for you: %s" % "; ".join(result.missing))
    try:
        with locked_file(path) as target:
            head, blocks = _read_company_sites(target)
            blocks = [block for block in blocks if not _same_job(block, job)]
            blocks.append("\n".join(entry[1:]) + "\n")
            _write_company_sites(target, head or header, blocks)
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)
    return path


def forget_company_site(settings: Settings, job: JobPosting) -> None:
    """Drop the job's entry once the bot has finished that application itself."""
    path = Path(settings.data_dir or paths.user("inputs")) / "company_sites.md"
    try:
        with locked_file(path) as target:
            head, blocks = _read_company_sites(target)
            kept = [block for block in blocks if not _same_job(block, job)]
            if len(kept) != len(blocks):
                _write_company_sites(target, head, kept)
    except OSError as exc:
        logger.warning("Could not update %s: %s", path, exc)


def _read_company_sites(path: Path) -> Tuple[str, List[str]]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    parts = re.split(r"\n(?=## )", text)
    head = parts[0] if parts and not parts[0].startswith("## ") else ""
    blocks = [part.strip("\n") + "\n" for part in parts if part.startswith("## ")]
    return head, blocks


def _write_company_sites(path: Path, head: str, blocks: List[str]) -> None:
    body = head.rstrip("\n") + "\n" + "".join("\n" + block for block in blocks)
    atomic_write_text(path, body)


def _same_job(block: str, job: JobPosting) -> bool:
    return bool(job.url) and ("\n- Naukri: %s\n" % job.url) in block + "\n"


def pending_company_sites(settings: Settings) -> List[Dict[str, str]]:
    """Entries still listed in user/inputs/company_sites.md, newest last."""
    path = Path(settings.data_dir or paths.user("inputs")) / "company_sites.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries = []  # type: List[Dict[str, str]]
    for block in re.split(r"\n(?=## )", text):
        if not block.startswith("## "):
            continue
        lines = block.splitlines()
        head = [part.strip() for part in lines[0][3:].split("|")]
        entry = {
            "when": head[0] if head else "",
            "company": head[1] if len(head) > 1 else "",
            "title": head[2] if len(head) > 2 else "",
        }
        for line in lines[1:]:
            if line.startswith("- ") and ":" in line:
                key, value = line[2:].split(":", 1)
                entry[key.strip().lower()] = value.strip()
        entries.append(entry)
    return entries


# Entries waiting on something only you can give: your answers, a code from your
# inbox, a password you set by hand. Trying them again changes nothing. One where
# Submit was already clicked may have gone through, and a retry would apply twice.
_WAITS_ON_YOU = re.compile(
    r"^needs you for(?!: password\*?$)|^submit was clicked|needs a code it emails|already exists on|verified first"
    r"|sent a verification email"
    r"|did not take the saved password|captcha|a check only a person|browser agent did not report",
    re.I,
)


# Walls the scripted filler cannot get through but the browser agent can read its
# way past. A question only they can answer is not here: retrying that costs an
# agent task and ends in the same place.
_FOR_THE_AGENT = re.compile(
    r"still blank: none the bot can see|opened nothing the bot recognised|no Submit button on the form"
    r"|needs a code it emails|sent a verification email|verified first|no way to the form"
    r"|no application form found|stays disabled"
    r"|upload (your |the )?(cv|resume)|resume \(the form has no file upload\)|resume/cv"
    r"|drop your resume|file size|autofill option|attach (your |the )?(cv|resume)",
    re.I,
)
# Trying these again either applies twice or repeats a failure the agent already had.
_NEVER_AGAIN = re.compile(
    r"^submit was clicked|already exists on|did not take the saved password|captcha"
    r"|a check only a person|browser agent did not report|^the browser agent stopped"
    r"|by email only",
    re.I,
)


# Walls that have since been taken down, so the stop they caused says nothing about what
# another try would do. They are worth one on their own, ahead of every other rule here,
# including the ones that otherwise retire a posting for good:
#   - a form marking its questions optional while keeping Next disabled: the second,
#     insisting pass answers those now;
#   - an upload the browser itself refused (ERR_ACCESS_DENIED), which the employer's form
#     reported as "Failed to fetch": the resume is now handed over from a folder this
#     Chrome may read, so those forms can finish.
_NOW_HANDLED = re.compile(r"stays disabled until every question is answered|ERR_ACCESS_DENIED", re.I)


def retryable(entry: Dict[str, str], agent: bool = False) -> bool:
    """Whether another try can get further: the bot stopped on its own side, or the agent can clear the wall."""
    why = entry.get("why", "")
    if not entry.get("site"):
        return False
    if _NOW_HANDLED.search(why):
        return True
    if _NEVER_AGAIN.search(why):
        return False
    return not _WAITS_ON_YOU.search(why) or bool(agent and _FOR_THE_AGENT.search(why))


def job_from_entry(entry: Dict[str, str]) -> JobPosting:
    naukri = entry.get("naukri", "")
    number = re.search(r"(\d{9,})/?$", naukri)
    return JobPosting(
        job_id=number.group(1) if number else naukri or entry.get("site", ""),
        url=naukri or entry.get("site", ""),
        title=entry.get("title", ""),
        company=entry.get("company", ""),
    )


def browser_answers(driver: Any) -> bool:
    try:
        driver.window_handles
        return True
    except Exception:
        return False


def retry_pending(
    driver: Any, settings: Settings, profile: Profile, answer_engine: Any, ledger: Any,
    base_pdf: Optional[Path], dry_run: bool, reopen: Optional[Any] = None,
) -> Dict[str, int]:
    """Work through user/inputs/company_sites.md again; counts of what became of each entry tried.

    `reopen` returns a fresh browser: one careers page hung Chrome's renderer until
    chromedriver died, and the rest of the list then waited on a browser that was
    never going to answer. With it the list carries on in a new window.
    """
    counts = {"tried": 0, "applied": 0, "gone": 0, "still waiting": 0}
    walls = {}  # type: Dict[str, ExternalResult]
    failures = {}  # type: Dict[str, int]
    home = driver.current_window_handle
    for entry in [entry for entry in pending_company_sites(settings) if retryable(entry, settings.browser_agent)]:
        company = (entry.get("company") or "").casefold()
        job = job_from_entry(entry)
        if company in walls:
            # Same company, same wall: the entry gets today's reason without another visit.
            record_company_site(settings, job, replace(walls[company], url=entry["site"]))
            continue
        sent = Path(entry.get("resume to send", ""))
        resume_pdf = sent if entry.get("resume to send") and sent.is_file() else base_pdf
        logger.info("[retry %d] %s @ %s: %s", counts["tried"] + 1, job.title, job.company, entry["site"])
        counts["tried"] += 1
        set_context = getattr(answer_engine, "set_job_context", None)
        if callable(set_context):
            set_context(job)
        result = None  # type: Optional[ExternalResult]
        try:
            if safe_get(driver, entry["site"]):
                human_pause(1.5, 3.0)
                result = apply_here(driver, job, profile, answer_engine, settings, resume_pdf, dry_run)
                result = browser_agent.take_over(driver, job, profile, settings, resume_pdf, dry_run, result)
            else:
                logger.info("      -> could not open the site")
        except WebDriverException as exc:
            logger.warning("      -> browser error: %s", " ".join(str(exc).split())[:200])
        # safe_get reports a dead browser as a page it could not open, so every
        # remaining entry would quietly retry against it; the list is only worth
        # going on with in a browser that still answers.
        if browser_answers(driver):
            return_to(driver, home, [home])
        elif reopen is None:
            logger.error("The browser stopped answering; the rest of the list waits for the next run.")
            break
        else:
            logger.warning("The browser stopped answering; opening a new one to carry on.")
            try:
                driver = reopen()
                home = driver.current_window_handle
            except Exception as problem:
                logger.error("Could not open another browser (%s); the rest waits for the next run.", problem)
                break
        if result is None:
            continue
        logger.info("      -> %s (%s)", result.status, result.detail[:300])
        if result.status == ApplyStatus.APPLIED_EXTERNAL:
            counts["applied"] += 1
            forget_company_site(settings, job)
            ledger.record_attempt(result.to_apply_result(job), title=job.title, company=job.company)
        elif result.status in (GONE, ApplyStatus.ALREADY_APPLIED):
            counts["gone"] += 1
            forget_company_site(settings, job)
        elif result.status in (ApplyStatus.EXTERNAL_MANUAL, ApplyStatus.ERROR):
            counts["still waiting"] += 1
            record_company_site(settings, job, result)
            failures[company] = failures.get(company, 0) + 1
            if "the site asks for an account" in result.detail or failures[company] >= SAME_SITE_FAILURES:
                walls[company] = result
    return counts


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def resume_to_attach(settings: Settings, client: Any, job: JobPosting, no_tailor: bool = False) -> Optional[Path]:
    """The PDF to upload: tailored when tailoring is on and possible, otherwise the one they uploaded.

    A resume that cannot be tailored is still worth attaching unchanged: every
    career form wants a file, and attaching none stops the whole application.
    """
    from common import resume as resume_module

    if not no_tailor and job.title and settings.tailor_resume:
        try:
            tailored, notes = resume_module.build_tailored_pdf(settings, client, job)
            for note in notes:
                logger.info("  resume: %s", note)
            return tailored
        except resume_module.ResumeError as exc:
            logger.warning("Could not tailor the resume (%s); attaching the one you uploaded", exc)
    try:
        return resume_module.build_base_pdf(settings)
    except resume_module.ResumeError as exc:
        logger.warning("No resume PDF to attach (%s)", exc)
        return None


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m sites_bot.external",
        description=(
            "Apply on an employer's own career page: fill the form from your facts and "
            "answers, attach the resume, submit only when complete and confirmed."
        ),
    )
    parser.add_argument("--url", help="the application page to work on (a company_sites.md Site link)")
    parser.add_argument(
        "--retry-pending",
        action="store_true",
        help="try user/inputs/company_sites.md again, skipping entries that wait on your answers or a code from your inbox",
    )
    parser.add_argument("--title", default="", help="job title, for the tailored resume and the records")
    parser.add_argument("--company", default="", help="company name, for the tailored resume and the records")
    parser.add_argument("--dry-run", action="store_true", help="fill the form and find Submit, but never click it")
    parser.add_argument("--no-tailor", action="store_true", help="attach the base resume instead of a tailored one")
    parser.add_argument(
        "--google-login",
        action="store_true",
        help="sign the bot's browser in to GOOGLE_EMAIL (types GOOGLE_PASSWORD when set; waits 10 minutes "
        "for a passkey, phone prompt or code); nothing else happens",
    )
    parser.add_argument("--headless", action="store_true", help="run the browser without a window")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, configure_logging, keep_log
    from common import browser, config, ledger as ledger_module, llm, profile as profile_module, resume as resume_module
    from common.answers import AnswerEngine

    args = parse_args(argv)
    configure_logging(args.verbose)
    overrides = {"dry_run": True} if args.dry_run else {}  # type: Dict[str, Any]
    if args.headless:
        overrides["headless"] = True
    try:
        settings = config.load_settings(args.env, overrides)
    except Exception as exc:
        logger.error("Could not load settings: %s", exc)
        return EXIT_CONFIG
    if not args.url and not args.google_login and not args.retry_pending:
        logger.error("Give --url (an application page), --retry-pending or --google-login.")
        return EXIT_CONFIG
    keep_log(settings, "company-site")

    if args.google_login:
        from .accounts import google_login

        driver = browser.create_driver(settings)
        try:
            ok, how = google_login(driver, settings, timeout_s=600.0)
            (logger.info if ok else logger.error)("Google: %s", how)
            return EXIT_OK if ok else EXIT_FAILED
        finally:
            driver.quit()

    try:
        profile = profile_module.load_profile(settings)
    except profile_module.ProfileError as exc:
        logger.error("Could not load your profile: %s", exc)
        return EXIT_CONFIG
    if args.retry_pending:
        from common import report

        ledger = ledger_module.open_ledger(settings)
        engine = AnswerEngine(ledger, llm.build_client(settings), profile, settings)
        try:
            base_pdf = resume_module.build_base_pdf(settings)  # type: Optional[Path]
        except resume_module.ResumeError as exc:
            logger.warning("No resume PDF to attach (%s)", exc)
            base_pdf = None
        opened = [browser.create_driver(settings)]

        def reopen() -> Any:
            for old in opened:
                try:
                    old.quit()
                except Exception:
                    pass
            opened.append(browser.create_driver(settings))
            return opened[-1]

        try:
            counts = retry_pending(opened[0], settings, profile, engine, ledger, base_pdf,
                                   args.dry_run, reopen)
        finally:
            try:
                opened[-1].quit()
            except Exception:
                pass
            ledger.close()
        logger.info("Company sites tried again: %s", ", ".join("%s %d" % item for item in counts.items()))
        if not args.dry_run:
            report.update_quietly(settings)
        return EXIT_OK
    job = JobPosting(
        job_id="manual-%s" % datetime.now().strftime("%Y%m%d-%H%M%S"),
        url=args.url,
        title=args.title,
        company=args.company,
    )
    ledger = ledger_module.open_ledger(settings)
    client = llm.build_client(settings)
    engine = AnswerEngine(ledger, client, profile, settings)
    engine.set_job_context(job)
    resume_pdf = resume_to_attach(settings, client, job, args.no_tailor)

    driver = browser.create_driver(settings)
    try:
        if not safe_get(driver, args.url):
            logger.error("Could not open %s", args.url)
            return EXIT_FAILED
        human_pause(1.5, 3.0)
        result = apply_here(driver, job, profile, engine, settings, resume_pdf, args.dry_run)
        result = browser_agent.take_over(driver, job, profile, settings, resume_pdf, args.dry_run, result)
    finally:
        driver.quit()
        ledger.close()

    logger.info("Site: %s (%s)", result.url, result.ats)
    logger.info("Filled: %s", ", ".join(result.filled) or "nothing")
    if result.missing:
        logger.info("Left for you: %s", "; ".join(result.missing))
    logger.info("Outcome: %s - %s", result.status, result.detail)
    if result.status == ApplyStatus.EXTERNAL_MANUAL:
        path = record_company_site(settings, job, result)
        logger.info("Recorded in %s", path)
        return EXIT_FAILED
    if result.status == GONE:
        forget_company_site(settings, job)
        return EXIT_FAILED
    if result.status == ApplyStatus.ERROR:
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
