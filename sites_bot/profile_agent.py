"""The profile agent: an LLM browser agent with a profile-update skill, checked by the bot.

platforms.update_profile hands the signed-in browser to Claude with the Playwright MCP
server (vision on, so it can click by what it sees in a screenshot). Before the agent
starts, the bot reads the live profile itself and asks the LLM, with that board's
system prompt, for a section-by-section edit plan against the planned profile.

- system prompt: skills/profile-update/boards/<board>.md (the board's own agent: how it
  ranks profiles, its sections and quirks), then skills/profile-update/SKILL.md (audit,
  decide, edit one section at a time, read back, reload, report per section);
- task: the board task, the LLM-written profile plan with its ATS report
  (common.profile_plan), the edit plan for the live profile, and their facts.

The agent's word is not the end of it. Afterwards the bot reloads the profile itself and
looks for each changed section's new text where that section is on the page, not anywhere
on it: a skill that is only in the headline does not confirm the skills section, and a
value too short for a keyword search ("Go", "R", "C#") is still checked rather than
passed for free. Whatever the page does not show -- a whole section, or one skill of
several that did not land -- is sent back to the agent as its own small task
(PROFILE_REPAIR_PASSES, default 1) and checked again. It takes a full-page
screenshot before and after, and when the LLM can read images it asks it to look at the
final screenshot too. Everything lands in the run folder:

    system.md, task.md                     the agent's system prompt and its task
    before.txt, edit-plan.json             the live profile as fetched, and the LLM's edits for it
    steps.txt, transcript.jsonl            what the agent did
    before.png, after.png                  the profile as it was and as it was left
    repair-1/                              a second pass over the sections the page did not show
    profile-report.md                      the verdict, then a line per section
    profile-report.json                    the same as one flat record

The run folder holds hundreds of files once the MCP server has written its snapshots, so
every run also appends its flat record to one index shared by all the boards
(common.profile_record), and the whole state of every profile is a single file read:

    python3 -m common.profile_record             # board, when, saved, sections, ATS
    python3 -m common.profile_record --board naukri
"""

import base64
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from common.models import Profile, Settings

from . import browser_agent, profile_contract
from .board import Board

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent / "skills" / "profile-update"
SKILL_FILE = SKILL_DIR / "SKILL.md"
BOARD_PROMPTS = SKILL_DIR / "boards"
#: Live profile text and facts given to the edit planner.
_PAGE_CHARS = 40000
_FACTS_CHARS = 24000
EDIT_ACTIONS = ("update", "fill", "keep", "skip")
CHANGED = ("updated", "filled")
#: The one reported issue the bot may not settle: which of two live entries the user wants to keep.
_USER_ISSUE = re.compile(r"Duplicate needs review\b", re.IGNORECASE)
ALREADY_OK = "already_ok"
#: A section the edit plan asked for that the agent's report never mentions: it ran out of budget or
#: time before it got there. The repair pass finishes it.
PENDING = "pending"
#: The agent tried a section and says it could not save it.
FAILED = "failed"
NEEDS_INPUT = "needs_input"
UNSUPPORTED = "unsupported"
EXCLUDED = "excluded"
NEEDS_REVIEW = "needs_review"
#: Every phrase must be present; a partial match is not a saved field.
WORD_MATCH = 1.0
#: Words per phrase compared against the page. Long enough that word order matters, short
#: enough to survive the board's own line breaks and "...see more" truncation.
_PHRASE = 4
#: Every word, including one- and two-letter skills ("Go", "R", "C#", "C++") that a longer
#: pattern would drop and so count as found when they are not on the page at all.
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#]*")
#: What a list item looks like next to prose: long enough for "Natural Language Processing",
#: short enough that a clause of a sentence is not mistaken for one and checked word for word.
_LIST_ITEM_CHARS = 40
_LIST_ITEM_WORDS = 4
#: A value the agent wrote with semicolons is a list by its own say-so; its parts may be longer
#: ("15 Days or less notice period", "inference-latency-profiler Jun 2026 to Sep 2026").
_SEMICOLON_ITEM_CHARS = 64
#: How many tokens after an entry's name still belong to its own row: Naukri writes a skill as
#: "Python - 2026 3 Years 0 Month" and a project as "Morrow Self (Offsite) Aug 2026 to Oct 2026".
_ROW_TOKENS = 12
#: Words a field name the agent writes before a value may take ("Date of birth 05 Apr 2003").
_LABEL_WORDS = 3
#: How much of the page after a section's heading counts as that section, and how many
#: repeats of the heading to try (boards list a heading in their navigation as well).
_WINDOW_CHARS = 1200
_WINDOWS = 4
#: A job entry's window: Naukri lists "Top 5 key skills" after a job profile of up to 4,000 characters.
_ENTRY_CHARS = 4500
#: One listed entry's room on the page. A row naming six projects is 120 characters, while the
#: page gives each its own description, so sizing the window from the value alone cut the list off.
_LIST_ENTRY_SPAN = 320
_SETTLE_S = 3

_REPORT = ("When you finish or stop, reply with the ONE JSON object described under \"Your report\" in "
           "the skill above, and nothing else.")


@dataclass
class Section:
    name: str
    action: str
    before: str = ""
    after: str = ""
    evidence: str = ""
    agent_verified: bool = False
    #: None when the bot could not read the page; else whether the new text is on it after a reload.
    on_page: Optional[bool] = None
    #: The list items (or the whole value) that were not on the reloaded page.
    missing: List[str] = field(default_factory=list)
    note: str = ""
    # The approved edit target survives agent reports and repair passes.
    target: str = ""
    fact_key: str = ""
    project_dates: Dict[str, str] = field(default_factory=dict)

    @property
    def wanted(self) -> str:
        return self.target or self.after or self.evidence or (self.before if self.action == ALREADY_OK else "")


@dataclass
class ProfileCheck:
    saved: bool
    why: str
    sections: List[Section] = field(default_factory=list)
    completeness_before: str = ""
    completeness_after: str = ""
    confirmation: str = ""
    vision: Dict[str, Any] = field(default_factory=dict)
    screenshots: List[str] = field(default_factory=list)
    #: False when the profile page could not be re-read after the run (network gone, browser dead).
    page_read: bool = True
    issues: List[str] = field(default_factory=list)
    facts_digest: str = ""

    @property
    def required(self) -> List[Section]:
        return [s for s in self.sections if s.action not in (UNSUPPORTED, EXCLUDED)]

    @property
    def verified(self) -> List[Section]:
        return [s for s in self.required if s.on_page is True and not s.missing
                and s.action in (*CHANGED, ALREADY_OK, "checked")]

    @property
    def coverage(self) -> Dict[str, Any]:
        total, verified = len(self.required), len(self.verified) if self.page_read else 0
        complete = bool(total and verified == total and not self.issues and self.page_read)
        percent = int(100 * verified / total) if total else 0
        return {"verified": verified, "total": total, "percent": percent if complete else min(99, percent),
                "complete": complete, "blocked": [s.name for s in self.required if s not in self.verified],
                "excluded": [{"name": s.name, "reason": s.note} for s in self.sections
                             if s.action in (UNSUPPORTED, EXCLUDED)], "issues": list(self.issues)}

    @property
    def changed(self) -> List[Section]:
        return [section for section in self.sections if section.action in CHANGED]

    @property
    def unverified(self) -> List[Section]:
        return [section for section in self.changed if section.on_page is False]

    @property
    def confirmed(self) -> List[Section]:
        return [section for section in self.changed if section.on_page is True and not section.missing]

    @property
    def partial(self) -> List[Section]:
        return [section for section in self.changed if section.on_page is True and section.missing]

    @property
    def pending(self) -> List[Section]:
        return [section for section in self.sections if section.action == PENDING and section.on_page is not True]

    @property
    def failed(self) -> List[Section]:
        return [section for section in self.sections if section.action == FAILED]

    @property
    def undone(self) -> List[Section]:
        return self.pending + self.failed

    @property
    def needs_input(self) -> List[Section]:
        return [section for section in self.sections if section.action == NEEDS_INPUT]

    @property
    def waiting_on_facts(self) -> bool:
        """The profile is intact and confirmed except for sections whose facts only the user can give."""
        if not self.page_read or self.issues or self.undone or self.unverified or not self.needs_input:
            return False
        return all(section in self.verified or section.action == NEEDS_INPUT for section in self.required)

    @property
    def waiting_on_you(self) -> bool:
        """The profile is intact and what is left is the user's to give or to choose.

        A missing fact, a value the board will not take and two entries only the user may choose
        between are not failures the bot can work off: the next run with the same facts reports the
        same thing. Anything else outstanding -- an unapplied edit, a changed section the page does
        not show, a conflict or an ambiguous match -- still fails the run.
        """
        if not self.page_read or self.undone or self.unverified:
            return False
        if any(not _USER_ISSUE.match(issue) for issue in self.issues):
            return False
        outstanding = [section for section in self.required if section not in self.verified]
        if not outstanding and not self.issues:
            return False
        return all(section.action in (NEEDS_INPUT, NEEDS_REVIEW) for section in outstanding)

    @property
    def needs_repair(self) -> List[Section]:
        if not self.page_read:
            return []
        return [s for s in self.required if s.action not in (NEEDS_INPUT, NEEDS_REVIEW, "skipped")
                and s.wanted and (s.on_page is not True or s.missing or s.action in (FAILED, PENDING))]

    @property
    def completeness(self) -> str:
        if not (self.completeness_before or self.completeness_after):
            return ""
        return "%s -> %s" % (self.completeness_before or "?", self.completeness_after or "?")

    def summary(self) -> str:
        if not self.page_read:
            # Nothing on the page could be confirmed or denied, so "not done" would be a guess.
            return "the page could not be re-read; unconfirmed: %s" % ", ".join(
                section.name for section in self.changed + self.undone)
        parts = ["%d/%d changed sections confirmed" % (len(self.confirmed), len(self.changed))]
        coverage = self.coverage
        parts.append("%d/%d required sections verified (%d%%)" % (
            coverage["verified"], coverage["total"], coverage["percent"]))
        if self.issues:
            parts.append("needs review: %s" % "; ".join(self.issues))
        if self.completeness:
            parts.append("completeness %s" % self.completeness)
        if self.unverified:
            parts.append("NOT on the page: %s" % ", ".join(section.name for section in self.unverified))
        if self.partial:
            parts.append("not seen: %s" % _cell(", ".join(item for section in self.partial
                                                          for item in section.missing), 80))
        if self.undone:
            parts.append("not done: %s" % ", ".join(section.name for section in self.undone))
        if self.needs_input:
            parts.append("needs your input: %s" % ", ".join(section.name for section in self.needs_input))
        if self.vision.get("problems"):
            parts.append("screenshot: %s" % "; ".join(self.vision["problems"][:2]))
        return "; ".join(parts)


def skill_text() -> str:
    try:
        return SKILL_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError("the profile skill is missing at %s: %s" % (SKILL_FILE, exc)) from exc


def agent_settings(settings: Settings) -> Settings:
    """Settings for a profile run: vision tools, a saved MCP session, and more time and budget."""
    mcp = settings.browser_agent_mcp
    if "--caps" not in mcp:
        mcp += " --caps vision"
    if "--save-session" not in mcp:
        mcp += " --save-session"
    return replace(settings, browser_agent_mcp=mcp,
                   browser_agent_timeout_s=max(settings.browser_agent_timeout_s, settings.profile_agent_timeout_s),
                   browser_agent_budget_usd=max(settings.browser_agent_budget_usd, settings.profile_agent_budget_usd))


def board_prompt(board: Board) -> str:
    """The board's own agent prompt (boards/<name>.md), else the generic one."""
    for name in (board.name, "default"):
        path = BOARD_PROMPTS / ("%s.md" % name)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise RuntimeError("no board prompt in %s" % BOARD_PROMPTS)


def system_prompt(board: Board) -> str:
    """Who the agent is on this board, then the skill it must follow."""
    return "%s\n\n---\n\nFollow this skill exactly.\n\n%s" % (board_prompt(board).strip(), skill_text())


def edits_text(edits: List[Dict[str, str]]) -> str:
    """The edit plan as the agent reads it."""
    if not edits:
        return ""
    lines = ["Edit plan for the live profile (the bot read the profile just before you started and the LLM "
             "compared it with the planned profile). Confirm each 'now' in your audit; where the page differs, "
             "trust the page and still aim for the target:"]
    for number, edit in enumerate(edits, 1):
        line = "%d. %s - %s" % (number, edit["name"], edit["action"])
        if edit.get("current"):
            line += "\n   now: %s" % edit["current"]
        if edit.get("target"):
            line += "\n   write: %s" % edit["target"]
        if edit.get("why"):
            line += "\n   why: %s" % edit["why"]
        lines.append(line)
    return "\n".join(lines)


def prompt(task: str, url: str, facts: str, email: str, files: Tuple[Path, ...], has_password: bool,
           edits: Optional[List[Dict[str, str]]] = None) -> str:
    """The agent's task: the board task and plan, the edit plan, the facts. The skill is in its system prompt."""
    instruction = task + ("\n\n" + edits_text(edits) if edits else "")
    return browser_agent.task_prompt(instruction, url, facts, email, files, has_password=has_password,
                                     report=_REPORT)


# ---------------------------------------------------------------------------
# The edit plan: the LLM compares the live profile with the planned one
# ---------------------------------------------------------------------------

_EDIT_SCHEMA = ('{"completeness": "", "sections": [{"name": "...", "current": "...", "target": "...", '
                '"action": "update | fill | keep | skip", "why": "..."}], "gaps": ["..."]}')

_EDIT_INSTRUCTIONS = """You plan the edits a browser agent will make to a candidate's profile on %(board)s.
Below are: the board agent's own instructions, the planned profile (written from their resume, with its ATS
report), the text the bot just read from their LIVE profile page, and their facts.

For EVERY section that board's instructions list (and any other section the live page shows), give:
- name: the section as the board labels it; one entry per employment, project and IT skill when the board
  lists them one by one ("Employment: Ethara AI", "Project: EvalAgentFlow", "IT skill: LangChain");
- current: its value on the live page now, copied briefly ("" if empty or not shown);
- target: the exact text or values to enter, copied word for word from the planned profile (headline,
  summary, About, a role's job profile and skills used, a project's description, an IT skill's years) or
  from the facts (for skills: the comma-separated skills to ADD; for dropdowns: the option to pick);
- action: "update" (present but different in meaning, thinner than the planned text, or missing target
  keywords), "fill" (empty and the plan or the facts answer it), "keep" (already matches), or "skip" (the
  plan and facts do not answer it, or it must not change);
- why: one short reason, naming any ATS keyword it adds.
Also give the completeness percentage shown on the page ("" if none) and gaps: board prompts for missing
details that the facts cannot answer (a mandatory field like a salary breakdown the facts never give).
Never invent an employer, title, number, skill, date or degree.
The shared profile plan is not a list of fields this board supports. Skip fields the board does not
provide. Missing text on the overview does not mean a missing field: inspect the board's instructions.
Do not plan per-role descriptions, expected salary or projects on boards without those editors.
Keep the exact section names throughout the report and repair, including the same employer name."""


def unsupported_section(board: Board, name: str) -> bool:
    """Known absent editors, confirmed in saved board audits. Never fabricate a target for them."""
    name = name.casefold()
    if board.name == 'instahyre':
        return bool(re.search(r'expected (?:ctc|salary)|willing to relocate|summary|about|headline|'
                              r'preferred / desired roles|preferred roles|target roles|work mode|job type|projects?|'
                              r'it skills|certifications?|job profile|description|\bdates\b|'
                              r'^employment:|'
                              r'work experience: (?!total|current (?:job title|company)|years|role type|industry|previous companies)', name))
    if board.name == 'hirist' and 'headline' in name:
        return True
    if board.name == 'hirist' and re.search(r'employment|work experience', name):
        return bool(re.search(r'description|job profile|skills used', name))
    if board.name in ('cutshort', 'wellfound') and re.match(r'^(?:projects?|certifications?)(?:\b|:)', name):
        # These fields were inspected in the saved board audits. The shared
        # resume plan must not manufacture editors that these boards lack.
        return True
    if board.name == 'cutshort':
        return bool(re.fullmatch(r'current role(?: / designation)?|designation|desired roles|target roles|desired job titles|it skill years|total experience', name)
                    or re.fullmatch(r'education\s*\(degree,\s*branch,\s*years\)', name)
                    or (re.match(r'^(?:employment|work experience):', name)
                        and re.search(r'description|job profile|skills used|dates|designation', name)))
    if board.name == 'wellfound':
        return bool(re.search(r'\bcurrent (?:salary|ctc|compensation)\b|\bnotice period\b', name)
                    or re.fullmatch(r'(?:preferences:\s*)?availability', name))
    return False


def edit_plan(settings: Settings, board: Board, plan: Any, facts: str, current: str,
              client: Any = None) -> List[Dict[str, str]]:
    """The LLM's section-by-section edits for the live profile; [] when none could be made."""
    from common import profile_plan
    from common.llm import build_client

    if plan is None or not current.strip():
        return []
    if client is None:
        client = build_client(replace(settings, llm_timeout_s=max(settings.llm_timeout_s, 300)))
    if not client.available():
        return []
    text = "\n\n".join([
        _EDIT_INSTRUCTIONS % {"board": board.label},
        "--- The board agent's instructions ---\n" + board_prompt(board),
        "--- The planned profile ---\n" + profile_plan.agent_brief(plan),
        "--- Their live profile page, as text ---\n" + current[:_PAGE_CHARS],
        "--- Their facts ---\n" + facts[:_FACTS_CHARS],
    ])
    raw = client.complete_json(text, _EDIT_SCHEMA)
    sections = raw.get("sections") if isinstance(raw, dict) else None
    if not isinstance(sections, list):
        logger.warning("%s: the LLM gave no edit plan for the live profile; the agent plans in its audit.",
                       board.label)
        return []
    known = facts + "\n" + profile_plan.agent_brief(plan)
    edits = []
    for item in sections:
        if not isinstance(item, dict) or not _text(item.get("name")):
            continue
        action = _text(item.get("action")).casefold()
        if unsupported_section(board, _text(item.get('name'))):
            action = 'skip'
            item['why'] = 'This board does not provide this editor. Leave it unchanged.'
        target = profile_plan._grounded_numbers(" ".join(str(item.get("target") or "").split()), known)
        if action not in EDIT_ACTIONS or (action in ("update", "fill") and not target):
            action = "skip"
        edits.append({"name": _text(item.get("name")), "action": action, "current": _text(item.get("current")),
                      "target": target, "why": _text(item.get("why"))})
    return edits


# ---------------------------------------------------------------------------
# Seeing the page from the bot's side
# ---------------------------------------------------------------------------


def screenshot(driver: Any, path: Path) -> Optional[Path]:
    """A full-page PNG through Chrome DevTools, else the viewport; None when neither works."""
    try:
        metrics = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
        shot = driver.execute_cdp_cmd("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": size.get("width", 1280),
                     "height": min(size.get("height", 2000), 12000), "scale": 1},
        })
        path.write_bytes(base64.b64decode(shot["data"]))
        return path
    except Exception as exc:  # not Chrome, or DevTools refused: fall back to the viewport
        logger.debug("Full-page screenshot failed (%s); taking the viewport.", exc)
    try:
        return path if driver.save_screenshot(str(path)) else None
    except Exception as exc:
        logger.warning("Could not take a screenshot of the profile: %s", exc)
        return None


#: Clicks every "Read More" / "View more" style link so a summary or job profile the board folds
#: behind one is in the page text the bot reads back (Naukri cuts both to a few lines otherwise).
_EXPAND_JS = """
var n = 0;
var clicked = new Set();
document.querySelectorAll('a, button, [role="button"], span, div').forEach(function (node) {
  var text = (node.textContent || '').replace(/\\s+/g, ' ').trim();
  if (!/^(?:\\.\\.\\.|…)?\\s*(read|view|see|show)\\s+more(?:\\s*(?:\\.\\.\\.|…))?$/i.test(text)) return;
  if (!node.getClientRects().length) return;
  var el = node.closest('button, [role="button"], a');
  if (!el) {
    // A noninteractive wrapper and its child can have identical text. Click
    // only the leaf so a container's bubbling handler does not fire twice.
    if (node.children.length) return;
    el = node;
  }
  if (el !== node && !/^(?:\\.\\.\\.|…)?\\s*(read|view|see|show)\\s+more(?:\\s*(?:\\.\\.\\.|…))?$/i.test((el.textContent || '').trim())) return;
  if (clicked.has(el)) return;
  clicked.add(el);
  try { el.click(); n += 1; } catch (e) {}
});
return n;
"""


_SCROLL_JS = ("window.scrollBy(0, window.innerHeight * 0.8); "
              "return window.scrollY + window.innerHeight >= document.body.scrollHeight - 2;")
_SCROLL_STEPS = 15
_SCROLL_PAUSE_S = 0.6


def _load_all(driver: Any) -> None:
    """Scroll a screen at a time so sections that render on sight do, then unfold "Read More" text.

    Naukri draws its IT skills, projects, summary and accomplishments only once they scroll into
    view; a jump straight to the bottom left the middle of the page out of the text.
    """
    try:
        for _ in range(_SCROLL_STEPS):
            at_bottom = driver.execute_script(_SCROLL_JS)
            time.sleep(_SCROLL_PAUSE_S)
            if at_bottom:
                break
        time.sleep(_SCROLL_PAUSE_S)
        if driver.execute_script(_EXPAND_JS):
            time.sleep(0.7)
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass


_TEXT_JS = """
var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT),
    parts = [], node, blind = ['hidden', 'password', 'checkbox', 'radio', 'submit', 'button', 'file'];
function visible(el) {
  if (!el.getClientRects().length || el.closest('[hidden], [aria-hidden="true"]')) return false;
  var visibility = window.getComputedStyle(el).visibility;
  return visibility !== 'hidden' && visibility !== 'collapse';
}
while ((node = walker.nextNode())) {
  if (node.nodeType === 1) {
    var kind = node.tagName, value = '';
    if (kind === 'A' && visible(node)) {
      // Icon-only profile links have no text node. Keep their public destination
      // next to the section so the verifier can check saved portfolio URLs.
      try {
        var link = new URL(node.href);
        if (link.protocol === 'https:' && !link.search && !link.hash) parts.push(link.href);
      } catch (e) {}
    }
    if (kind !== 'INPUT' && kind !== 'TEXTAREA' && kind !== 'SELECT') continue;
    if (!visible(node)) continue;
    if (kind === 'SELECT') {
      var chosen = node.options[node.selectedIndex];
      value = chosen ? chosen.text : '';
    } else if (kind !== 'INPUT' || blind.indexOf((node.type || '').toLowerCase()) < 0) {
      value = node.value || '';
    }
    value = String(value).replace(/\\s+/g, ' ').trim();
    if (value) parts.push(value);
    continue;
  }
  var text = node.nodeValue.replace(/\\s+/g, ' ').trim(), parent = node.parentElement;
  if (!text || !parent) continue;
  // A select's other options are not saved values. Its selected text was read
  // above; including all options can falsely verify an unsaved preference.
  // Textarea child text is its initial/default value, not necessarily the
  // current saved .value already read above.
  if (parent.closest('select, textarea')) continue;
  var option = parent.closest('[role="option"]');
  if (option && option.getAttribute('aria-selected') !== 'true') continue;
  var label = parent.closest('label'), control = label && label.control;
  if (control && /^(checkbox|radio)$/i.test(control.type) && !control.checked) continue;
  var choice = parent.closest('[role="checkbox"], [role="radio"]');
  if (choice && choice.getAttribute('aria-checked') !== 'true') continue;
  var tag = parent.tagName;
  if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEMPLATE') continue;
  if (!visible(parent)) continue;
  parts.push(text);
}
return parts.join(' ');
"""


def page_text(driver: Any) -> str:
    """The visible text of the page with a space between neighbouring elements, form values included.

    Selenium's body text runs inline chips together ("PythonJavascriptMongoDB") and includes
    unselected dropdown options. It cannot substitute for a selected-value read.
    What sits in a text box or a drop-down is part of the profile on a board that edits it as a
    form (Hirist's About and work preferences), and body text never shows it.
    """
    try:
        text = driver.execute_script(_TEXT_JS)
        if isinstance(text, str):
            return " ".join(text.split())
    except Exception:
        pass
    return ""


def _words(text: str) -> List[str]:
    # Naukri exposes its edit icon as text between every row. These are controls,
    # not part of the value; leaving them in broke otherwise identical IT tables.
    text = re.sub(r'\b(?:editOneTheme|deleteOneTheme|downloadOneTheme)\b', ' ', text or '', flags=re.I)
    return [token for token in _TOKEN.findall(text.casefold()) if token]


def _is_label(text: str, loose: bool = False) -> bool:
    words = text.split()
    one_token = len(words) == 1  # a URL is one item however long it is
    if loose and 0 < len(words) and len(text) <= _SEMICOLON_ITEM_CHARS:
        return True
    aside = _ASIDE.match(text)
    if _ROW_FIELD.match(aside.group(1) if aside else text):
        return True  # "Feb 2021 - Apr 2021 (3 months)" is one item, however many words it takes
    # A bracketed note does not make a name prose: Hirist prints the employer as "Ethara AI
    # (formerly Green Rider Technology)". The name itself still has to read like one, so a clause
    # that merely ends in brackets stays prose and keeps being matched as phrases.
    core = _BRACKETED.sub("", text).strip()
    # A lone "-" or "&" is punctuation, not a word: Naukri's own industry and functional-area
    # names ("Engineering - Software & QA") are labels that would otherwise read as prose.
    named = [word for word in core.split() if any(character.isalnum() for character in word)]
    return 0 < len(named) <= _LIST_ITEM_WORDS and (len(core) <= _LIST_ITEM_CHARS or one_token)


def _items(text: str) -> List[str]:
    """The items of a list value (skills, roles) or the one label it is; [] when the value is prose.

    Every part has to read like a label, so "Python, Go." is still the two skills it is while
    "...systems on aws, with a focus on retrieval." is prose and gets matched as phrases instead
    of demanding each clause word for word. Semicolons separate items too -- the agent writes
    "Gurugram, INDIA; 2 Years 11 Months; ₹ 16,00,000" -- and those parts may be a little longer.
    """
    text = str(text or "")
    loose = ";" in text
    parts = [part.strip(" .;") for part in _split(text)]
    parts = [part for part in parts if part]
    if not parts or not all(_is_label(part, loose) for part in parts):
        return []
    return parts


def _split(text: str) -> List[str]:
    """The value's parts, keeping a bracketed note whole.

    Hirist's languages read "English Expert (Read, Write, Speak); Hindi Expert (Read, Write,
    Speak)": splitting on every comma tore each note into parts no page has.
    """
    parts, part, depth = [], "", 0
    for character in text:
        if character in "([":
            depth += 1
        elif character in ")]" and depth:
            depth -= 1
        if character in ",;" and not depth:
            parts.append(part)
            part = ""
            continue
        part += character
    return parts + [part]


def _phrases(words: List[str], size: int) -> List[Tuple[str, ...]]:
    if len(words) <= size:
        return [tuple(words)] if words else []
    return [tuple(words[start:start + size]) for start in range(len(words) - size + 1)]


_YEARS = re.compile(r"^(\d+)(?:\.(\d))?\s*(?:years?|yrs?)$", re.IGNORECASE)
_YEARS_MONTHS = re.compile(r"^(\d+)\s*(?:years?|yrs?)\s+(\d+)\s*(?:months?|mos?)$", re.IGNORECASE)
_LAST_USED = re.compile(r"^last used\s*:?\s*((?:19|20)\d{2})$", re.IGNORECASE)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}"
_DATES = re.compile(r"^(%s)\s*(?:to|-|–|—)\s*((?:%s)|present|till date|current)$" % (_MONTH, _MONTH), re.IGNORECASE)
#: "Skills used: Python" -- a field name the agent put in front of the value; the page shows the
#: value under the board's own label ("Top 5 key skills: Python").
_LABELLED = re.compile(r"^[A-Za-z][A-Za-z0-9 /&()-]{1,30}:\s*([^/\s].*)$")
#: An entry's name followed by its dates, as the agent lists projects and jobs: the board puts its
#: own words between them ("llm-eval-harness editOneTheme Self (Offsite) Sep 2026 to Sep 2026").
_NAME_DATES = re.compile(r"^(.+?)[\s,]+(%s\s*(?:to|-|–|—)\s*(?:%s|present|till date|current))$" % (_MONTH, _MONTH), re.IGNORECASE)
#: A row field next to an entry's name: its years, the year it was last used, or its dates.
_ROW_FIELD = re.compile(r"^(?:last used\s*:?\s*)?(?:19|20)\d{2}$|^\d+(?:\.\d)?\s*(?:years?|yrs?)(?:\s+\d+\s*(?:months?|mos?))?$"
                        r"|^%s\s*(?:to|-|–|—)\s*(?:%s|present|till date|current)$" % (_MONTH, _MONTH), re.IGNORECASE)
#: "16 LPA", "16 lakhs", "₹16L": Naukri shows the salary as "₹ 16,00,000".
_LAKHS = re.compile(r"^(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?(?:\s*(?:per\s*annum|p\.?a\.?))?|l)$", re.IGNORECASE)
#: "Mar 2024 - Present (current)", "Feb 2021 - Apr 2021 (3 months)": the agent's aside in brackets
#: after a value is its own remark, not something the page shows beside the value.
_ASIDE = re.compile(r"^(.*\S)\s*\((?:current|present|ongoing|till date|\d+\s*(?:years?|yrs?|months?|mos?)"
                    r"(?:\s+\d+\s*(?:months?|mos?))?)\)$", re.IGNORECASE)
#: A bracketed note at the end of a value: "Ethara AI (formerly Green Rider Technology)".
_BRACKETED = re.compile(r"\s*\([^()]*\)\s*$")
#: A name and its bracketed note apart: boards print both but put their own words between them
#: ("Medi-Caps University Bachelor of Technology (B.Tech), Computer Science and Engineering 2020 - 2024").
_NAME_NOTE = re.compile(r"^(.+?)\s*\(([^()]+)\)$")
#: One question of a form and its answer, as the agent lists several in one value ("Requires
#: sponsorship: Yes; Legally authorized to work in the US: No"). Questions run longer than a label.
_ANSWERED_ITEM = re.compile(r"^(.{3,120}?)\s*:\s*(yes|no)$", re.IGNORECASE)
#: The agent's own joining words before a value ("also open to Contractor"), which no board prints
#: that way: Wellfound's own wording is "Also open to the following job types: Contractor".
_CONNECTIVE = re.compile(r"^(?:and|or|also|plus|including|open to)\s+", re.IGNORECASE)
#: Where an agent abbreviated a long text it quotes; each part it did quote must still be on the page.
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")
#: A value the board itself refused to keep, which only the user can settle with the board.
_REFUSED = re.compile(r"\b(?:save request did not include|did not save|would not save|not accepted|"
                      r"does not (?:accept|allow)|re(?:fused|jected) the save|no option for)\b", re.IGNORECASE)
#: "Full-Stack Developer Intern": Naukri shows the role from its own list and "Internship" as the type.
_INTERN = re.compile(r"^(.+?)\s+intern$", re.IGNORECASE)
#: An uploaded file: the stem and the extension boards keep when they re-store it under their own name.
_FILENAME = re.compile(r"^([\w .()\-]+?)(\.(?:pdf|docx?|rtf|odt|txt|png|jpe?g))$", re.IGNORECASE)
#: How many tokens of the board's own tag may sit between the sent stem and the extension.
_FILE_TAG_TOKENS = 2
#: How far after a section's heading, and after its "last updated" label, its date may sit.
_UPLOAD_CHARS = 120
#: A tick, toggle or switch state, which a page shows as a control rather than as text.
_STATE = re.compile(r"(?:checked|unchecked|ticked|unticked|selected|enabled|disabled|on|off|set|unset|true|false)",
                    re.IGNORECASE)
#: The half word and ellipsis a report leaves where it cut a long text short.
_CUT = re.compile(r"\s*\S*\.\.\.\s*$")
#: Cities boards still call by their former name.
_CITIES = (("gurugram", "gurgaon"), ("bengaluru", "bangalore"), ("mumbai", "bombay"),
           ("kolkata", "calcutta"), ("chennai", "madras"), ("pune", "poona"))
#: An already_ok row whose `after` names what the board had no room for ("CI/CD") instead of the
#: field's value: the note explains the limit, and only the user can decide what to drop for it.
_BOARD_LIMIT = re.compile(r"\b(?:is full|box full|did not fit|no room|maxlength|character limit|limit of \d+|"
                          r"capped at|table (?:is )?full|full at \d+|left out|no deletions?)\b", re.IGNORECASE)
#: A planned skip that leaves a field as it is ("No resume file was given, so the upload must not be
#: touched") asks nothing of the user, unlike a skip for a fact the facts file lacks.
_LEFT_ALONE = re.compile(r"\b(?:no (?:\w+ )?file was given|must not be touched|left (?:as is|alone|unchanged)|"
                         r"nothing to upload)\b", re.IGNORECASE)


def _indian(amount: int) -> str:
    """1600000 the way Naukri writes it: 16,00,000."""
    text = str(amount)
    if len(text) <= 3:
        return text
    head, tail = text[:-3], text[-3:]
    groups: List[str] = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(groups + [tail])


def _forms(item: str) -> List[str]:
    """The item and the ways a board renders it: "2.5 years" is shown as "2 Years 6 Months".

    Naukri writes "3 Years 0 Month" and "1 Year 0 Month" in the singular, lists the year a skill was
    last used in its own column with no "last used" beside it, and separates dates with "to".
    """
    item = item.strip()
    match = _ASIDE.match(item)
    if match:
        return _forms(match.group(1)) + [item]
    match = _LAKHS.match(item)
    if match:
        rupees = int(round(float(match.group(1)) * 100000))
        return [item, _indian(rupees), str(rupees)]
    match = _YEARS.match(item)
    if match:
        years, tenth = match.group(1), match.group(2)
        months = round(int(tenth) * 1.2) if tenth else 0
        forms = [item, "%s years %d months" % (years, months), "%s years" % years if not months else item]
        if months in (0, 1):
            forms.append("%s years %d month" % (years, months))
        return forms
    match = _YEARS_MONTHS.match(item)
    if match:
        years, months = match.group(1), match.group(2)
        return [item] + ["%s %s %s %s" % (years, year_word, months, month_word)
                         for year_word in ("years", "year") for month_word in ("months", "month")]
    match = _LAST_USED.match(item)
    if match:
        return [item, match.group(1)]
    match = _DATES.match(item)
    if match:
        return [item, "%s to %s" % (match.group(1), match.group(2)), "%s - %s" % (match.group(1), match.group(2))]
    if _ANSWERED_ITEM.match(item):
        # A bare "No" elsewhere under the heading is no answer to this question; only the answer
        # printed directly after it counts, which _confirmed_answer checks against the page.
        return [item]
    match = _LABELLED.match(item)
    if match:
        if _STATE.fullmatch(_BRACKETED.sub("", match.group(1)).strip()):
            # "Work remotely: selected" is a tick the page draws as a control and never spells out;
            # the label printed beside the box is the only text the page can be asked for.
            return [item, item.split(":", 1)[0].strip()]
        return [item, match.group(1)]
    plain = item
    while _CONNECTIVE.match(plain):
        plain = _CONNECTIVE.sub("", plain, count=1)
    return [item] + ([plain] if plain != item else []) + _renamed(item) + _unlabelled(item)


def _renamed(item: str) -> List[str]:
    """The same place under the name the board uses: Instahyre says Gurgaon for Gurugram."""
    forms = []
    for names in _CITIES:
        for name in names:
            if re.search(r"\b%s\b" % name, item, re.IGNORECASE):
                forms += [re.sub(r"\b%s\b" % name, other, item, flags=re.IGNORECASE)
                          for other in names if other != name]
    return forms


def _unlabelled(item: str) -> List[str]:
    """The value without a field name the agent put in front of it, when the name is told apart.

    "DOB 05 Apr 2003" is the date under Naukri's "Date of birth"; "Preferred roles Machine Learning
    Engineer" is the role under "Preferred job role". A label is an all-capitals word ("DOB") or a
    capitalised word followed by lower-case ones ("Preferred roles", "Date of birth"); the value
    starts with a capital or a digit and keeps at least two words, so "Senior Software Engineer"
    never shrinks to "Software Engineer". A read/write/speak tally ("R/W/S") is no value either.
    """
    words = [word for word in item.split() if not re.fullmatch(r"[A-Z](?:/[A-Z])+", word)]
    forms = [" ".join(words)] if len(words) < len(item.split()) else []
    for count in range(1, min(_LABEL_WORDS, len(words) - 2) + 1):
        label, value = words[:count], words[count:]
        if not (value[0][0].isupper() or value[0][0].isdigit()):
            continue
        if (count == 1 and len(label[0]) > 1 and label[0].isupper()) or (count > 1 and all(w.islower() for w in label[1:])):
            forms.append(" ".join(value))
    return forms


def _plain(token: str) -> str:
    """A token as a board spells it: "Nextjs", "Next.js" and "next" are one skill, "React.js" is React."""
    return token[:-2] if token.endswith("js") and len(token) > 4 else token


def _run_of(words: List[str], haystack: List[str]) -> bool:
    """Whether the words appear consecutively in the haystack, so "Go" cannot match "Django".

    Spacing and a trailing "js" are the board's choice, not a difference: "Fast API" is FastAPI,
    "Nextjs" is Next.js and "React.js" is React, so a chip the board renamed on saving still counts.
    """
    return bool(_starts(words, haystack))


def _starts(words: List[str], haystack: List[str]) -> List[int]:
    """Where in the haystack the words appear consecutively (see _run_of); [] when they do not."""
    wanted = _plain("".join(words))
    if not wanted:
        return []
    starts = []
    for start in range(len(haystack)):
        joined = ""
        for token in haystack[start:start + len(words) + 2]:
            joined += token
            if _plain(joined) == wanted:
                starts.append(start)
                break
            if len(_plain(joined)) >= len(wanted):
                break
    return starts


def _in_row(name: str, fields: List[str], have: List[str]) -> Tuple[bool, List[str]]:
    """Whether an entry's name is on the page with its fields in its own row: (name found, fields not in the row).

    "Python, 3 years 0 months, last used 2026" is one IT-skills row, which Naukri shows as
    "Python - 2026 3 Years 0 Month": the fields come in the board's order and words, so each is
    looked for in any form just after the name, never in another skill's row.
    """
    name_words = _words(name)
    starts = _starts(name_words, have)
    if not starts:
        return False, list(fields)
    best: Optional[List[str]] = None
    for start in starts:
        row = have[start + len(name_words):start + len(name_words) + _ROW_TOKENS]
        missing = [field for field in fields if not any(_run_of(_words(form), row) for form in _forms(field))]
        if not missing:
            return True, []
        if best is None or len(missing) < len(best):
            best = missing
    return True, best or []


def _found(item: str, have: List[str]) -> bool:
    """Whether a list item is on the page in some form, or as an entry name followed by its dates."""
    if any(_run_of(_words(form), have) for form in _forms(item)):
        return True
    match = _NAME_DATES.match(item)
    if match and _words(match.group(1)):
        found, missing = _in_row(match.group(1), [match.group(2)], have)
        return found and not missing
    match = _INTERN.match(item)
    if match and "internship" in have and _found(match.group(1), have):
        return True
    match = _NAME_NOTE.match(item)
    if match:
        found, missing = _in_row(match.group(1), [match.group(2)], have)
        if found and not missing:
            return True
    parts = [part for part in _ELLIPSIS.split(item) if _words(part)]
    if len(parts) > 1 and all(_run_of(_words(part), have) for part in parts):
        return True
    return _file_named(item, have)


def _file_named(item: str, have: List[str]) -> bool:
    """Whether an upload is on the page under the name the board gave it.

    Cutshort stores "Soujanya_Gupta_Resume.pdf" as "Soujanya_Gupta_Resume_Xwcy.pdf", so the name it
    shows keeps the sent stem and extension with its own tag between them. Without this, a resume
    that uploaded correctly is reported missing from the page on every run.
    """
    match = _FILENAME.match(item)
    if not match:
        return False
    stem, extension = _words(match.group(1)), _words(match.group(2))
    if not stem or not extension:
        return False
    return any(extension[0] in have[start + len(stem):start + len(stem) + _FILE_TAG_TOKENS + 1]
               for start in _starts(stem, have))


def _compare(expected: str, page: str) -> Tuple[Optional[bool], List[str]]:
    have = _words(page)
    if not have:
        return None, []
    # A report shortens a long value to 300 characters and marks the cut with an ellipsis, which
    # leaves half a word ("Lite" of LiteLLM) that is on no page. Drop it, item list or prose alike.
    expected = _CUT.sub("", expected) or expected
    rows = [row.strip() for row in re.split(r'[|;]', expected) if row.strip()]
    if len(rows) > 1 and all(re.fullmatch(r'.+?\s+(?:-\s*)?(?:20\d{2}\s+)?\d+(?:\.\d+)?\s+Years?\s+\d+\s+Months?', row, re.I)
                             for row in rows):
        # An IT skills table is not prose: every claimed row must match. A 70%
        # phrase threshold could otherwise approve the wrong years in one row.
        missing = [row for row in rows if not _run_of(_words(row), have)]
        return not missing, missing
    items = _items(expected)
    if len(items) > 1 and ";" not in expected and all(_ROW_FIELD.match(item) for item in items[1:]):
        # One entry and its row fields ("Python, 3 years 0 months, last used 2026"): the fields
        # count only in that entry's own row, so another skill's year cannot stand in.
        found, missing = _in_row(items[0], items[1:], have)
        if found:
            return not missing, missing
    asked_whole = None if ';' in expected else _ANSWERED_ITEM.match(expected.strip())
    if asked_whole:
        outcome = _answered(asked_whole.group(1), asked_whole.group(2), page)
        return (None, []) if outcome is None else (outcome, [] if outcome else [expected.strip()])
    halves = [half.strip() for half in expected.split(';') if half.strip()]
    if not items and len(halves) > 1 and any(_items(half) for half in halves):
        # An entry written as its fields and then its description ("Software Engineer, Ethara AI,
        # Mar 2024 - Present; Expanded the WildClawBench fork...") is two kinds of value at once:
        # the fields are checked item by item and the description as prose, each on its own.
        missing = []
        for half in halves:
            outcome = _compare(half, page)
            if outcome[0] is False:
                missing.extend(outcome[1] or [half[:60]])
        return not missing, missing
    if items:
        asked = [_ANSWERED_ITEM.match(item) for item in items]
        if all(asked) and all(_answered(m.group(1), m.group(2), page) is None for m in asked):
            # The page prints no answer under any of these questions, so it contradicts none of
            # them either: that is no evidence, not a value the board dropped.
            return None, []
        missing = [item for item in items
                   if not _found(item, have) and not _confirmed_answer(item, page)]
        return not missing, missing
    # A single value carries the agent's own framing too: Cutshort's choice reads "Work remotely:
    # Within 3-4 hrs of my timezone", where the page prints only what follows the label.
    for form in [expected] + (_forms(expected)[1:] if len(_items(expected)) <= 1 else []):
        # An agent that quotes the opening and the close of a long text marks the gap it left out
        # with an ellipsis. Every part it did quote still has to be on the page, word for word.
        parts = [part for part in _ELLIPSIS.split(form) if _words(part)]
        if parts and all(_phrase_share(part, have) >= WORD_MATCH for part in parts):
            return True, []
    # An entry the agent writes as one line puts its fields and its description in one sentence
    # ("Full-Stack Developer Intern, Feb 2021 - Apr 2021, Shipped Indore Carbonic, a carbon portal"),
    # which the board prints as separate fields. Each part still has to be on the page, in its own
    # right, so nothing is accepted that the page does not hold.
    pieces = [piece.strip() for piece in _split(expected) if piece.strip()]
    if len(pieces) > 1 and all(_compare(piece, page)[0] is True for piece in pieces):
        return True, []
    return (False, []) if _words(expected) else (None, [])


def _answered(label: str, answer: str, page: str) -> Optional[bool]:
    """Whether the question's own label is followed by this answer; None when the page says neither.

    An unrelated Yes elsewhere on a long form cannot prove this choice, so only the answer directly
    after this question counts, and a board printing both options ("Yes No") has named none of them.
    """
    # A section's name carries its group before the question ("US work authorization: legally
    # authorized to work in the US"). The question is what the board prints an answer under; the
    # group heading is followed by the first question of the form, whose answer is another one's.
    labels = [label.split(':', 1)[1], label] if ':' in label else [label]
    for text in labels:
        words = _words(text)
        if not words:
            continue
        # The agent writes the question in its own words ("work in the US" for the board's "work in
        # the United States"), so the longest opening of its wording that the page does print is
        # used, down to half of it, and never fewer than two words.
        for size in range(len(words), max(2, (len(words) + 1) // 2) - 1, -1):
            answers = _answers_after(words[:size], page)
            if answers:
                return all(found == answer.strip().casefold() for found in answers)
    return None


def _answers_after(words: List[str], page: str) -> List[str]:
    # A word matches in the singular or the plural, as a section heading does ("Requires
    # sponsorship" for "require sponsorship").
    pattern = r'\b' + r'\W+'.join(re.escape(word.rstrip('s') or word) + 's?' for word in words) + r'\b'
    answers = []
    for match in re.finditer(pattern, page, re.I):
        # The wording can sit inside a longer question ("...will you require sponsorship for a US
        # employment visa (e.g. H-1B)? Yes"), so the answer may follow the question's end rather
        # than the words themselves; nothing but the rest of that one question may come between.
        found = re.match(r'(?:[^?]{0,180}\?)?\s*[:*?\-]*\s*(yes|no)\b(?!\s+(?:yes|no)\b)',
                         page[match.end():], re.I)
        if found:
            answers.append(found.group(1).casefold())
    return answers


def _confirmed_answer(item: str, page: str) -> bool:
    match = _ANSWERED_ITEM.match(item)
    return bool(match) and _answered(match.group(1), match.group(2), page) is True


def _phrase_share(text: str, have: List[str]) -> float:
    words = _words(text)
    size = min(_PHRASE, len(words))
    wanted = _phrases(words, size)
    found = set(_phrases(have, size))
    return sum(1 for phrase in wanted if phrase in found) / len(wanted) if wanted else 0.0


#: An "Add"/"Edit" affordance directly before a heading, so the heading labels the entries above it.
_ACTION = re.compile(r"\b(?:add|edit|update|manage)\s+$", re.IGNORECASE)


def _windows(heading: str, page: str, lead: int = 0, size: int = _WINDOW_CHARS) -> List[str]:
    """The page text after each place the section's own heading appears (and `lead` characters before).

    Looking for a value only where its section is keeps a skill that is also in the headline, or a
    sentence repeated in a sidebar, from confirming a section it never reached. Every occurrence is
    returned because boards repeat a heading in their navigation before the section itself. A heading
    matches in the singular or the plural: Naukri's "Online profile" is the plan's "Online profiles".
    """
    words = _words(heading)
    if not words or not page:
        return []
    pattern = r"\b" + r"\W+".join(re.escape(word.rstrip("s") or word) + "s?" for word in words) + r"\b"
    # Hirist names a section only by the "Add Education Details" button printed under its entries, so
    # a window starting at that heading begins past them. Look behind for an action affordance alone:
    # a plain heading preceded by a value (AWS Bedrock in the headline, above "Key skills") must not
    # reach back and confirm a section that never got it.
    return [page[max(0, match.start() - (_LIST_ENTRY_SPAN if _ACTION.search(page[:match.start()]) else lead)):
                 match.start() + size]
            for match in re.finditer(pattern, page, re.IGNORECASE)][:_WINDOWS]


_LEAD_CHARS = 160


def _locate(name: str) -> Tuple[str, int]:
    """Where on the page a section's value is looked for: (heading, characters of lead-in before it).

    "IT skill: Python" sits under the board's "IT skills" heading. A job or a project is headed by its
    own company or name; a job's title comes just before the company, hence the lead-in. Any other
    section is headed by its name.
    """
    kind, _, own = name.partition(":")
    key, own = kind.strip().casefold(), own.strip()
    if own and key in ("employment", "experience", "work experience", "job profile"):
        own = re.split(r'\s+(?:—|–|-)\s+(?:job profile|description|skills used|title|dates)', own, flags=re.I)[0]
        return own, _LEAD_CHARS
    if own and key == "project":
        return own, 0
    if key == "it skill":
        return "IT skills", 0
    return name, 0


def _rank(outcome: Tuple[Optional[bool], List[str]]) -> Tuple[bool, int]:
    return outcome[0] is True, -len(outcome[1])


def verify(expected: str, page: str, heading: str = "", lead: int = 0) -> Tuple[Optional[bool], List[str]]:
    """Whether the expected text is on the page, and the parts that are not.

    A list value (skills, roles) is checked item by item, so a report names the skills that did
    not land. Prose is checked as overlapping phrases, so word order has to match while the
    board's own line breaks and truncation are still tolerated. With a heading, only that
    section's part of the page counts, and of those the best-matching one does, so a heading
    that also sits in the navigation cannot report items the section itself has. Returns
    (None, []) when there is nothing to compare -- an empty value, or a page the bot could not
    read -- never a bare True.
    """
    if expected.strip().casefold() in ('yes', 'no'):
        outcome = _answered(heading, expected, page)
        return (None, []) if outcome is None else (outcome, [] if outcome else [expected])
    best: Optional[Tuple[Optional[bool], List[str]]] = None
    # About can be 2,600 characters and job descriptions 4,000. A fixed 1,200
    # character window could never verify 70% of a complete long section. A job or project is
    # headed by its own name (a lead-in marks a job); its skills and dates follow a description
    # that can run to 4,000 characters, so the window of such an entry reaches past that.
    listed = len(_items(expected))
    window_size = max(_WINDOW_CHARS, min(10000, len(expected) * 2 + len(heading) + lead),
                      _ENTRY_CHARS if lead else 0,
                      min(_ENTRY_CHARS, listed * _LIST_ENTRY_SPAN) if listed > 1 else 0)
    for window in _windows(heading, page, lead, window_size):
        outcome = _compare(expected, window)
        if outcome[0] is True and not outcome[1]:
            return outcome
        if outcome[0] is not None and (best is None or _rank(outcome) > _rank(best)):
            best = outcome
    if best is None:
        return _compare(expected, page)
    if best[0] is not True or best[1]:
        # The heading is on the page but the value sits under the board's own label for it: Hirist
        # lists "Resume Attached" in its status card and shows the file under "Attach Resume" on a
        # form page. One value too specific to be mistaken for anything else -- three words or
        # more, never a list whose items could each come from a different section -- counts
        # wherever the page shows it, whole.
        if len(_items(expected)) <= 1 and len(_words(expected)) >= 3:
            whole = _compare(expected, page)
            if whole[0] is True and not whole[1]:
                return whole
    return best


# Text between a pair of quotes that are not apostrophes inside a word ("Hirist's", "couldn't").
_QUOTED = re.compile(r"(?<![A-Za-z0-9])[\"'\u2018\u201c](.{3,400}?)[\"'\u2019\u201d](?![A-Za-z0-9])")


def _quoted(text: str) -> str:
    return ", ".join(part.strip() for part in _QUOTED.findall(text) if part.strip())


def claims(section: "Section") -> List[str]:
    """Evidence cannot weaken the approved target or a claimed saved value."""
    wanted = section.wanted
    if not wanted:
        return []
    return [wanted]


def _claim_rank(outcome: Tuple[Optional[bool], List[str]]) -> Tuple[bool, int]:
    # A found claim with the fewest gaps wins; among claims not found, the one that names its gaps
    # (a list checked item by item) explains more than prose that only says "no".
    return outcome[0] is True, -len(outcome[1]) if outcome[0] is True else len(outcome[1])


def confirm(section: "Section", page: str) -> Tuple[Optional[bool], List[str]]:
    """Verify the approved target; the report's shorter evidence cannot replace it."""
    if section.project_dates:
        return profile_contract.verify_project_dates(section.project_dates, page)
    if section.fact_key:
        return profile_contract.verify_fact(section.fact_key, section.wanted, page)
    heading, lead = _locate(section.name)
    if section.wanted.strip().casefold() in ('yes', 'no'):
        category, _, question = section.name.partition(':')
        if question and category.casefold() in ('additional information', 'professional details', 'preferences', 'personal details'):
            heading = question.strip()
    best: Optional[Tuple[Optional[bool], List[str]]] = None
    for claim in claims(section):
        outcome = verify(claim, page, heading, lead)
        if outcome[0] is True and not outcome[1]:
            return outcome
        if outcome[0] is not None and (best is None or _claim_rank(outcome) > _claim_rank(best)):
            best = outcome
    return best if best is not None else (None, [])


def _uploaded_today(heading: str, page: str) -> bool:
    """Whether the board says this section was updated today, where it shows no file name at all.

    Instahyre prints "Resume Last updated: Nov 12, 2026" and never the name that was sent, so the
    only evidence a board can give is its own date. Yesterday's date is no evidence for this run.
    """
    today = date.today()
    stamps = [today.strftime(form).replace(" 0", " ") for form in ("%b %d, %Y", "%d %b %Y", "%b %d %Y", "%Y-%m-%d")]
    for window in _windows(heading, page, size=_UPLOAD_CHARS) or [page]:
        for marker in re.finditer(r"\b(?:last )?(?:updated|uploaded|modified)\b[^A-Za-z0-9]{0,4}", window, re.I):
            tail = window[marker.end():marker.end() + _UPLOAD_CHARS]
            if any(tail.lower().startswith(stamp.lower()) for stamp in stamps):
                return True
    return False


def _confirm_saved(section: "Section", page: str, board: Board,
                   workdir: Path) -> Tuple[Optional[bool], List[str]]:
    """Check the page, with upload evidence when Hirist renames the supplied resume."""
    outcome = confirm(section, page)
    if outcome != (True, []) and _FILENAME.match(section.wanted.strip()) and _uploaded_today(section.name, page):
        section.note = (section.note + ' ' if section.note else '') + (
            'The board shows no file name, only that it was updated today.')
        return True, []
    if (board.name != 'hirist' or outcome == (True, [])
            or not re.fullmatch(r'(?:attach |uploaded )?resume(?: attached)?', section.name, re.I)):
        return outcome
    from .resume_evidence import verify_hirist_resume

    folders = [workdir]
    repair = re.fullmatch(r'repair-(\d+)', workdir.name)
    if repair:
        # An unrelated repair must not discard the first pass's upload proof.
        # Each candidate still has to match the current reloaded attachment's
        # timestamp and size; a later different upload cannot reuse old proof.
        prior = [path for path in workdir.parent.glob('repair-*')
                 if path.is_dir() and re.fullmatch(r'repair-\d+', path.name)
                 and int(path.name.split('-')[1]) < int(repair.group(1))]
        folders.extend(sorted(prior, key=lambda path: int(path.name.split('-')[1]), reverse=True))
        folders.append(workdir.parent)
    for folder in folders:
        before = folder / 'before.txt'
        if not before.is_file() and re.fullmatch(r'repair-\d+', folder.name):
            before = folder.parent / 'page-after.txt'
        try:
            previous = before.read_text(encoding='utf-8')
        except OSError:
            continue
        if verify_hirist_resume(folder, section.wanted, previous, page):
            evidence = 'Saved attachment verified from the supplied file upload, changed upload time and matching size.'
            if evidence not in section.note:
                section.note = (section.note + ' ' + evidence).strip()
            return True, []
    return outcome


# ---------------------------------------------------------------------------
# Reading the agent's report and checking it
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return " ".join(str(value or "").split())


def sections_from(report: Dict[str, Any]) -> List[Section]:
    sections = []
    for item in report.get("sections") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        sections.append(Section(
            name=_text(item.get("name")), action=_text(item.get("action")).casefold() or "unknown",
            before=_text(item.get("before")), after=_text(item.get("after")),
            evidence=_text(item.get("evidence")), agent_verified=item.get("verified") is True,
            note=_text(item.get("note")),
        ))
    return sections


def _viewport(driver: Any, path: Path) -> Optional[Path]:
    try:
        return path if driver.save_screenshot(str(path)) else None
    except Exception as exc:
        logger.debug("Viewport screenshot failed: %s", exc)
        return None


def _vision_check(settings: Settings, image: Optional[Path], plan: Any) -> Dict[str, Any]:
    """Ask the LLM to look at the final screenshot; {} when it cannot read images."""
    if image is None or plan is None:
        return {}
    from common.llm import build_client

    client = build_client(replace(settings, llm_timeout_s=max(settings.llm_timeout_s, 300)))
    if not hasattr(client, "complete_json_with_image") or not client.available():
        return {}
    expected = {"headline": plan.headline, "designation": plan.designation,
                "key_skills": plan.key_skills, "summary_starts": plan.summary[:160]}
    result = client.complete_json_with_image(
        "This is a screenshot of a candidate's own job-board profile after an automated update. Compare "
        "what is visible with the expected values below. Report which expected values you can see, the "
        "profile completeness percentage if one is shown, and any error message, warning, or "
        "'missing details' prompt on the page. Only report what is actually visible.\n\nExpected:\n%s"
        % json.dumps(expected, ensure_ascii=False),
        '{"headline_visible": true, "designation_visible": true, "skills_visible": ["..."], '
        '"summary_visible": true, "completeness": "", "problems": ["..."]}',
        image,
    )
    return result if isinstance(result, dict) else {}


def _section_key(name: str) -> str:
    fact = profile_contract.fact_key(name)
    if fact:
        return 'fact ' + fact
    if profile_contract._summary_section(name):
        return 'profile summary'
    name = re.sub(r'^(?:employment|work experience|job profile)\s*:', 'experience:', name, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()


def _same_section(left: str, right: str) -> bool:
    left, right = _section_key(left), _section_key(right)
    return bool(left and right) and (left == right or left in right or right in left)


def add_planned(result: ProfileCheck, edits: Optional[List[Dict[str, str]]], page: str) -> None:
    """Sections the edit plan asked for that the agent's report never mentions.

    An agent that ran out of budget, time or turns stops without a word about what it did not
    reach, and the repair pass only knows what it is told. The plan is the contract: a planned
    edit the page already shows is done; one it does not show is pending and gets redone.
    """
    for edit in edits or []:
        if profile_contract.protected(edit.get('name', '')):
            continue
        target = edit.get('target') or (edit.get('current', '') if edit.get('action') == 'keep' else '')
        if edit.get('action') == 'skip':
            if 'needs review' in edit.get('why', ''):
                action = NEEDS_REVIEW
            elif _LEFT_ALONE.search(edit.get('why', '')):
                action = EXCLUDED
            else:
                action = NEEDS_INPUT
        else:
            action = PENDING
        reported = [section for section in result.sections if _section_key(edit['name']) == _section_key(section.name)]
        if not reported:
            reported = [section for section in result.sections if _same_section(edit["name"], section.name)]
        if len(reported) > 1 and ':' in edit["name"]:
            # A planned name is "parent: child" ("Personal details: Languages"), so it loosely matches
            # the parent section as well. The child names the field the edit is about.
            child = [section for section in reported
                     if _same_section(edit["name"].rsplit(':', 1)[1], section.name)]
            if len(child) == 1:
                reported = child
        if len(reported) > 1:
            # Never apply one job/project target to multiple existing entries. A skipped edit has
            # nothing to apply: "Resume" beside the agent's "Resume headline" is no conflict.
            if target and edit.get('action') != 'skip':
                result.issues.append('Ambiguous section match: ' + edit['name'])
            continue
        for section in reported:
            if edit.get('action') == 'keep' and not edit.get('target') and section.action == ALREADY_OK and section.after:
                # The planner's `current` is its own paraphrase of the page before the run; the agent's
                # `after` is the value read back from the reloaded page, in the board's words.
                target = section.target
            elif (edit.get('action') == 'update' and section.action == ALREADY_OK and target
                    and len(_items(target)) in (1, 2) and target.casefold() in section.note.casefold()
                    and _BOARD_LIMIT.search(section.note)):
                # The board had no room for the planned value; the user decides what to drop for it.
                section.action = NEEDS_INPUT
                section.on_page, section.missing = None, []
            section.target = target or section.target
            section.fact_key = edit.get('fact_key', '')
            section.project_dates = edit.get('project_dates', {})
            if edit.get('action') == 'skip':
                # Missing facts and conflicts are authoritative. An agent's
                # already_ok claim cannot turn an old website value into a fact.
                section.action = action
                section.on_page, section.missing = None, []
                section.note = edit.get('why') or section.note
            elif section.action in (UNSUPPORTED, EXCLUDED, 'skipped'):
                section.action = action
        if reported:
            continue
        section = Section(name=edit['name'], action=action, target=target, fact_key=edit.get('fact_key', ''),
                          project_dates=edit.get('project_dates', {}))
        on_page, missing = confirm(section, page) if action == PENDING and page and target else (None, [])
        done = action == PENDING and on_page is True and not missing
        result.sections.append(Section(
            name=edit["name"], action=ALREADY_OK if done else action, before=edit.get("current", ""),
            target=target, fact_key=edit.get('fact_key', ''), on_page=on_page, missing=missing,
            project_dates=edit.get('project_dates', {}),
            note="planned; the page shows it" if done else edit.get('why') or "planned, but the agent never reported it"))


_PROFILE_WAIT_S = 20
_STABLE_READS = 3
_RETRY_READ_S = 30


def _read_page(driver: Any, url: str) -> str:
    """Open one page and read it once its text has held still for three reads; "" when it cannot be opened.

    Boards draw the header first and fetch the sections afterwards, so the text right after the
    navigation is only the menu, and on Hirist that menu alone is longer than a short profile.
    """
    from common.browser import safe_get

    if not safe_get(driver, url):
        return ""
    time.sleep(_SETTLE_S)
    deadline = time.monotonic() + _PROFILE_WAIT_S
    text, same = page_text(driver), 1
    while same < _STABLE_READS and time.monotonic() < deadline:
        time.sleep(1)
        fresh = page_text(driver)
        same = same + 1 if fresh == text else 1
        text = fresh
    _load_all(driver)
    return page_text(driver)


def _read_profile(driver: Any, board: Board) -> str:
    """The profile as text: its page, then the form pages the board spreads it over; "" when the page is unreadable."""
    try:
        text = _read_page(driver, board.profile_url)
    except Exception as exc:
        logger.warning("%s: could not read the profile page: %s", board.label, exc)
        return ""
    if not text:
        return ""
    parts = [text]
    entries = profile_contract.read_entries(driver)
    pages = list(board.profile_pages)
    if board.name == 'cutshort':
        # /profile is a collapsed dashboard. Follow only its own unique talent
        # card link, never a job/recruiter's card or an ID saved from another user.
        cards = set(re.findall(r'https://cutshort\.io/profile/edit-signal/([a-f0-9]{24})(?=\s|$)', text))
        if len(cards) == 1:
            card = cards.pop()
            pages.extend(['https://cutshort.io/profile/edit-signal/' + card,
                          'https://cutshort.io/profile/matches/c/' + card + '?view=survey'])
        elif len(cards) > 1:
            logger.warning('Cutshort: several talent cards are visible; no editor was selected for verification.')
    if board.name == 'linkedin':
        # LinkedIn's overview only shows two skills, and draws its Experience, Education and
        # Projects cards late or not at all, so a run that changed a position/project had nothing to be
        # checked against. The candidate's own detail pages are at fixed paths under the profile
        # the overview redirected to: read those, never somebody else's profile or an editor.
        current = urlsplit(str(getattr(driver, 'current_url', '')))
        own = re.match(r'^/in/[^/]+/', current.path + '/')
        if own and current.scheme == 'https' and current.hostname in ('linkedin.com', 'www.linkedin.com'):
            base = 'https://%s%s' % (current.netloc, own.group())
            for detail in ('details/skills/', 'details/experience/', 'details/projects/',
                           'details/certifications/', 'details/education/'):
                if base + detail not in pages:
                    pages.append(base + detail)
    for url in pages:
        try:
            extra = _read_page(driver, url)
        except Exception as exc:
            extra = ""
            logger.warning("%s: could not read %s: %s", board.label, url, exc)
        if extra:
            parts.append(extra)
            entries.extend(profile_contract.read_entries(driver))
        else:
            logger.warning("%s: %s could not be read; what it holds cannot be confirmed.", board.label, url)
    if board.name in ('linkedin', 'hirist', 'wellfound', 'cutshort') and pages:
        # The following screenshot check expects the overview's headline and
        # completeness, not whichever detail page we inspected last.
        try:
            _read_page(driver, board.profile_url)
        except Exception as exc:
            logger.warning('%s: could not return to the profile overview: %s', board.label, exc)
    driver._profile_entries = entries
    return "\n\n".join(parts)


def check(driver: Any, board: Board, settings: Settings, report: Dict[str, Any], plan: Any,
          workdir: Path, edits: Optional[List[Dict[str, str]]] = None,
          profile: Optional[Profile] = None) -> ProfileCheck:
    """Reload the profile and confirm on the page what the agent says it changed, and what the plan wanted."""
    result = ProfileCheck(
        saved=False, why="",
        sections=sections_from(report),
        completeness_before=_text(report.get("completeness_before")),
        completeness_after=_text(report.get("completeness_after")),
        confirmation=_text(report.get("board_confirmation")),
        issues=profile_contract.report_issues(report),
    )
    for section in result.sections:
        if unsupported_section(board, section.name):
            section.action = UNSUPPORTED
        elif section.action in ('skipped', UNSUPPORTED, EXCLUDED, NEEDS_INPUT, ALREADY_OK) and profile_contract.protected(section.name):
            section.action = EXCLUDED
        elif section.action in ('skipped', UNSUPPORTED, EXCLUDED):
            section.action = NEEDS_INPUT
        if section.action == FAILED and (re.search(r'needs? (?:salary breakdown|client|start date|course dates|institute)|missing (?:facts|dates)', section.note, re.I)
                                         or _REFUSED.search(section.note) or _BOARD_LIMIT.search(section.note)):
            # A value the board drops on save (Hirist keeps no 0% variable pay) is not work the bot
            # can finish: the next run types the same digit and the board drops it again.
            section.action = NEEDS_INPUT
        if (section.action == ALREADY_OK and section.after and len(_items(section.after)) in (1, 2)
                and section.after.casefold() in section.note.casefold() and _BOARD_LIMIT.search(section.note)):
            # The agent wrote what did not fit where the field's value belongs; the board's limit,
            # not the page, keeps it out, and the user chooses what to drop for it.
            section.action = NEEDS_INPUT
        key = profile_contract.fact_key(section.name)
        if board.name == 'cutshort' and key in ('full_time_experience_years', 'internship_experience_months'):
            if (getattr(profile, 'extra_facts', {}) or {}).get(key) in (None, ''):
                section.action = NEEDS_INPUT
                section.note = 'The saved facts do not include %s; unchanged website values are not proof.' % key
                section.on_page, section.missing = None, []
    page = _read_profile(driver, board)
    if not page:
        logger.warning("%s: the profile page could not be read after the run; trying once more in %ds.",
                       board.label, _RETRY_READ_S)
        time.sleep(_RETRY_READ_S)
        page = _read_profile(driver, board)
    result.page_read = bool(page)
    result.issues.extend(profile_contract.duplicates(getattr(driver, '_profile_entries', [])))
    if page:
        (workdir / "page-after.txt").write_text(page, encoding="utf-8")
    after = screenshot(driver, workdir / "after.png") if page else None
    if after:
        result.screenshots.append(str(after))
    # The LLM that looks at the page cannot decode a full-page capture of a long profile; the top of
    # the page, where the headline, designation and completeness sit, is what it is asked about.
    view = _viewport(driver, workdir / "after-view.png") if page else None
    add_planned(result, [edit for edit in edits or [] if not unsupported_section(board, edit.get('name', ''))
                        and not profile_contract.exclusion_reason(profile, edit.get('name', ''))], page)
    for section in result.sections:
        if board.name == 'cutshort' and section.action == NEEDS_INPUT and section.target:
            kind, _, company = section.name.partition(':')
            company = re.sub(r'\s*\(formerly[^)]*\)', '', company, flags=re.I).strip()
            if kind.casefold() in ('employment', 'work experience') and profile_contract.key(section.target) == profile_contract.key(company):
                windows = _windows('Your current company', page) + _windows('Past companies', page)
                if any(_compare(section.target, window)[0] is True for window in windows):
                    section.action = ALREADY_OK
                    section.note = 'The approved company chip is on the reloaded page; role descriptions and dates are unsupported.'
        excluded = profile_contract.exclusion_reason(profile, section.name)
        if excluded:
            section.action = EXCLUDED
            section.note = excluded
            section.on_page, section.missing = None, []
            continue
        # What the agent says it changed, and what it says was already there: both are claims about
        # the page, and a repair pass that finds a section "already_ok" must leave page evidence too.
        if page and section.wanted and section.action in (*CHANGED, ALREADY_OK, 'checked', PENDING):
            section.on_page, section.missing = _confirm_saved(section, page, board, workdir)
            if (section.on_page is not True and not _windows(section.name, page)
                    and (section.on_page is None or _STATE.fullmatch(section.wanted.strip()))):
                # A ticked box is not text, and Hirist keeps its work-preference questions on a
                # registration step the profile page never prints. Where the page shows neither
                # this field's own name nor its state, it holds no evidence either way and the
                # agent's confirmation in the form is all there can be.
                section.action = EXCLUDED
                section.note = (section.note + ' ' if section.note else '') + (
                    'The board does not print this field or its state; the agent confirmed it in the form.')
                section.on_page, section.missing = None, []
                continue
            if section.action == PENDING and section.on_page is True and not section.missing:
                section.action = ALREADY_OK
    if page and plan is not None and plan.headline and not unsupported_section(board, 'Headline') and not any("headline" in s.name.casefold()
                                                               for s in result.sections):
        on_page, missing = verify(plan.headline, page)
        result.sections.append(Section(name="Headline (planned)", action="checked", after=plan.headline,
                                       on_page=on_page, missing=missing))
    try:
        result.vision = _vision_check(settings, view or after, plan)
    except Exception as exc:  # advisory only
        logger.warning("%s: the screenshot check failed: %s", board.label, exc)
    if result.vision.get("completeness") and not result.completeness_after:
        result.completeness_after = _text(result.vision["completeness"])
    # A board meter is a separate observation, not the verifier's coverage.
    observed = completeness_on(page)
    if observed:
        result.completeness_after = observed
    preferences = (getattr(profile, 'extra_facts', {}) or {}).get('profile_update_preferences', {})
    user_limited_scope = isinstance(preferences, dict) and any(
        preferences.get(k) is True for k in ('skip_profile_photo', 'skip_school_education'))
    if not user_limited_scope and result.completeness_after and re.fullmatch(r'\d+%', result.completeness_after):
        if int(result.completeness_after[:-1]) < 100:
            result.issues.append('Website completeness is %s; review its missing-details prompts' % result.completeness_after)

    result.saved, result.why = _verdict(result)
    return result


def repair_text(sections: List[Section]) -> str:
    """The task for a repair pass: only the sections the reloaded page did not show or the plan still wants."""
    lines = ["An agent already worked on this profile. The bot then reloaded the page itself and these sections "
             "are still not right: either the agent reported them saved and the text is NOT on the page (the save "
             "did not take effect), or the plan asked for them and the agent never got to them.",
             "", "Fix ONLY these sections. Leave every other section alone."]
    for number, section in enumerate(sections, 1):
        lines.append("%d. %s" % (number, section.name))
        lines.append("   write: %s" % section.wanted)
        if section.action == PENDING:
            lines.append("   status: not done yet; the page does not show it")
        elif section.action == FAILED:
            lines.append("   status: the previous pass could not save it%s"
                         % (": %s" % section.note if section.note else ""))
        if section.missing:
            lines.append("   not on the page: %s" % ", ".join(section.missing))
    lines += ["", "For each one: open its editor, check whether your text is actually in the field, correct it, and "
              "save. A save that shows no success toast, or an editor that reopens empty, means it did not save -- "
              "look for a validation error, a required field you left blank, or a character limit, and say so in "
              "your report. After saving, RELOAD the profile page and read the section back from the reloaded page "
              "before you call it verified.",
              "", "Report only these sections, in the same JSON format."]
    return "\n".join(lines)


def _merge(result: ProfileCheck, repaired: ProfileCheck) -> ProfileCheck:
    """Take the repair pass's verdict for the sections it revisited; keep the first pass for the rest."""
    for index, section in enumerate(result.sections):
        candidates = [item for item in repaired.sections if _section_key(section.name) == _section_key(item.name)]
        if not candidates:
            candidates = [item for item in repaired.sections if _same_section(section.name, item.name)]
        fresh = candidates[0] if len(candidates) == 1 else None
        if fresh is None:
            continue
        result.sections[index] = replace(
            fresh,
            action=fresh.action if fresh.action in (*CHANGED, NEEDS_INPUT, UNSUPPORTED, EXCLUDED, NEEDS_REVIEW) or section.action in (PENDING, FAILED) else section.action,
            before=fresh.before or section.before,
            missing=list(fresh.missing),
            target=section.target or fresh.target,
            fact_key=section.fact_key or fresh.fact_key,
            project_dates=section.project_dates or fresh.project_dates,
            note=" ".join(part for part in (section.note, fresh.note) if part).strip(),
        )
    result.completeness_after = repaired.completeness_after or result.completeness_after
    result.confirmation = repaired.confirmation or result.confirmation
    result.vision = repaired.vision or result.vision
    result.page_read = repaired.page_read
    result.issues = list(dict.fromkeys([i for i in result.issues if not i.startswith('Website completeness')]
                                    + repaired.issues))
    for shot in repaired.screenshots:
        if shot not in result.screenshots:
            result.screenshots.append(shot)
    result.saved, result.why = _verdict(result)
    return result


def _verdict(result: ProfileCheck) -> Tuple[bool, str]:
    """Completion requires positive evidence for every applicable section."""
    if not result.page_read:
        return False, "the profile page could not be re-read after the run; unconfirmed: %s" % ", ".join(
            section.name for section in result.required)
    if not result.required:
        return False, "no applicable profile sections were verified"
    if result.issues:
        return False, "needs review: " + "; ".join(result.issues)
    if result.undone:
        return False, "not done: %s" % ", ".join(s.name for s in result.undone)
    if result.needs_input:
        return False, "needs your input: %s" % ", ".join(s.name for s in result.needs_input)
    if result.unverified:
        return False, "%s still not on the reloaded page" % ", ".join(s.name for s in result.unverified)
    gaps = [s for s in result.required if s not in result.verified]
    if gaps:
        return False, "unconfirmed: %s" % ", ".join(s.name for s in gaps)
    return True, "all applicable sections confirmed on the reloaded page"


def repair(driver: Any, board: Board, settings: Settings, result: ProfileCheck, plan: Any, facts: str,
           email: str, files: Tuple[Path, ...], workdir: Path, profile: Optional[Profile] = None) -> ProfileCheck:
    """Send the agent back for the sections the page did not show, then check the page again."""
    passes = max(0, int(getattr(settings, "profile_repair_passes", 0) or 0))
    for attempt in range(1, passes + 1):
        broken = result.needs_repair
        if not broken:
            break
        logger.warning("%s: %s not on the reloaded profile; repair pass %d of %d.", board.label,
                       ", ".join(section.name for section in broken), attempt, passes)
        folder = workdir / ("repair-%d" % attempt)
        folder.mkdir(parents=True, exist_ok=True)
        staged = browser_agent.stage_files(folder, files)
        text = prompt(repair_text(broken), board.profile_url or board.home, facts, email, staged,
                      bool(settings.company_site_password))
        try:
            agent = browser_agent.run_agent(driver, settings, text, folder, staged, system=system_prompt(board))
        except Exception as exc:
            logger.warning("%s: the repair pass could not run: %s", board.label, exc)
            break
        if agent.problem or not agent.report:
            logger.warning("%s: repair pass %d gave nothing back: %s", board.label, attempt,
                           agent.problem or "no report")
            break
        # The approved target must be verified again in a repair. Otherwise a
        # short new 'already_ok' report could erase an earlier failed target.
        repair_edits = [dict(name=s.name, action='update', target=s.wanted,
                            current=s.before, fact_key=s.fact_key, project_dates=s.project_dates) for s in broken]
        repaired = check(driver, board, settings, agent.report, None, folder, repair_edits, profile=profile)
        result = _merge(result, repaired)
        page_path = folder / 'page-after.txt'
        if result.page_read and page_path.exists():
            fresh_page = page_path.read_text(encoding='utf-8')
            for section in result.required:
                if section.wanted and section.action in (*CHANGED, ALREADY_OK, 'checked'):
                    section.on_page, section.missing = _confirm_saved(section, fresh_page, board, folder)
            result.saved, result.why = _verdict(result)
    return result


def _cell(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split()).replace("|", "/")
    return text if len(text) <= limit else text[:limit - 3] + "..."


def write_report(path: Path, board: Board, result: ProfileCheck, plan: Any,
                 record: Dict[str, Any]) -> Path:
    """profile-report.md and .json in the run folder: the verdict first, then a line per section."""
    workdir = path.parent
    full = dict(record)
    if plan is not None:
        full["plan_source"] = plan.source
        full["ats"] = asdict(plan.ats) if plan.ats is not None else None
    (workdir / "profile-report.json").write_text(json.dumps(full, indent=2, ensure_ascii=False) + "\n",
                                                 encoding="utf-8")

    head = "%s - %s" % ("complete" if result.saved else "INCOMPLETE", result.why)
    lines = ["# %s profile: %s" % (board.label, head), "", result.summary()]
    if plan is not None and plan.ats is not None:
        lines[-1] += "; local resume heuristic %d/100" % plan.ats.score
    lines += ["", "| Section | Action | On page | Value |", "|---|---|---|---|"]
    for section in result.sections:
        mark = "-" if section.on_page is None else ("yes" if section.on_page else "**NO**")
        value = _cell(section.wanted or section.before)
        if section.missing:
            value = "%s<br>missing: %s" % (value, _cell(", ".join(section.missing), 60))
        lines.append("| %s | %s | %s | %s |" % (_cell(section.name, 40), section.action, mark, value))
    extras = []
    if result.confirmation:
        extras.append("Board said: \"%s\"" % _cell(result.confirmation, 200))
    if result.vision.get("problems"):
        extras.append("Screenshot check: %s" % _cell("; ".join(result.vision["problems"]), 200))
    if result.screenshots:
        extras.append("Screenshots: before.png, after.png.")
    if extras:
        lines += [""] + extras
    lines += ["", "Full record: profile-report.json. Every board: python3 -m common.profile_record"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_PERCENT = re.compile(r"\b(\d{1,3})\s*%(?!\s*off\b)", re.IGNORECASE)  # "Flat 25% off" is a promotion
SCORED = "checked"


def completeness_on(page: str) -> str:
    """The completeness figure a board shows at the top of the profile ("85%"), "" when there is none."""
    match = _PERCENT.search(page or "")
    return match.group(1) + "%" if match else ""


_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def _short_name(name: str) -> str:
    """"Ethara AI (formerly Green Rider Technology)" as a board shows it: "Ethara AI"."""
    return _PARENTHETICAL.sub("", name).strip() or name


def planned_sections(plan: Any) -> List[Section]:
    """Every value the plan (made from the resume) wants on the profile, as sections to check a page against.

    The names are the board's headings where the plan has one, so verify() looks in the right part of the
    page; a job, a project or an IT skill is one section each, so the score names exactly what is missing.
    """
    sections = []  # type: List[Section]

    def add(name: str, value: Any) -> None:
        text = _text(value)
        if text:
            sections.append(Section(name=name, action=SCORED, after=text))

    add("Resume headline", getattr(plan, "headline", ""))
    add("Key skills", getattr(plan, "key_skills", []))
    add("Profile summary", getattr(plan, "summary", ""))
    for role in getattr(plan, "experience", []) or []:
        company = _short_name(_text(role.get("company")) or _text(role.get("title")))
        add("Employment: %s" % company, "%s, %s" % (role.get("title", ""), company))
        add("Job profile: %s" % company, role.get("description", ""))
    for project in getattr(plan, "projects", []) or []:
        add("Project: %s" % _text(project.get("name")), project.get("description") or project.get("name"))
    for skill in getattr(plan, "it_skills", []) or []:
        parts = [skill.get("name", "")]
        if skill.get("years"):
            parts.append("%s years" % skill["years"])
        if skill.get("last_used"):
            parts.append(str(skill["last_used"]))
        add("IT skill: %s" % _text(skill.get("name")), ", ".join(part for part in parts if part))
    add("Certifications", getattr(plan, "certifications", []))
    add("Online profiles", getattr(plan, "links", []))
    return sections


def score(driver: Any, board: Board, plan: Any, workdir: Path) -> ProfileCheck:
    """Read the live profile and check every planned value against it; nothing is changed.

    The verdict says how many planned sections the page shows and names the rest, so a person can see
    at once how far the profile is from the resume. The board's own completeness figure is read too.
    """
    result = ProfileCheck(saved=False, why="", sections=planned_sections(plan))
    page = _read_profile(driver, board)
    if not page:
        result.why = "could not read the profile page"
        return result
    (workdir / "page.txt").write_text(page, encoding="utf-8")
    shot = screenshot(driver, workdir / "profile.png")
    if shot:
        result.screenshots.append(str(shot))
    result.completeness_after = completeness_on(page)
    for section in result.sections:
        section.on_page, section.missing = verify(section.wanted, page, *_locate(section.name))
    shown = [section for section in result.sections if section.on_page is True]
    absent = [section for section in result.sections if section.on_page is False]
    partial = [section for section in shown if section.missing]
    result.saved = bool(result.sections) and len(shown) == len(result.sections) and not partial
    result.why = "%d of %d planned sections are on the profile" % (len(shown), len(result.sections))
    if absent:
        result.why += "; not on it: %s" % ", ".join(section.name for section in absent)
    if partial:
        result.why += "; partly: %s" % "; ".join(
            "%s (%s)" % (section.name, ", ".join(section.missing)) for section in partial)
    return result


def score_text(board: Board, result: ProfileCheck, plan: Any) -> str:
    """The score as a person reads it: the figures first, then one line per planned section."""
    lines = ["%s profile score" % board.label]
    if result.completeness_after:
        lines.append("  Completeness shown by %s: %s" % (board.label, result.completeness_after))
    ats = getattr(plan, "ats", None)
    if ats is not None:
        lines.append("  Resume ATS: %d/100 (keywords %d, structure %d)"
                     % (ats.score, ats.keyword_score, ats.structure_score))
    lines.append("  Resume on the profile: %s" % result.why)
    lines.append("")
    for section in result.sections:
        mark = {True: "ok ", False: "NO ", None: "?  "}.get(section.on_page, "?  ")
        lines.append("  %s %-40s %s" % (mark, _cell(section.name, 40), _cell(section.wanted, 70)))
        if section.missing:
            lines.append("      not on the page: %s" % ", ".join(section.missing))
    return "\n".join(lines)


def keep_score(workdir: Path, board: Board, result: ProfileCheck, plan: Any,
               settings: Optional[Settings] = None) -> Path:
    """Write the score's report and record it in the shared index, like a run."""
    from common import profile_record

    return _finish(workdir, board, result, plan, settings, kind=profile_record.SCORE)


def _finish(workdir: Path, board: Board, result: ProfileCheck, plan: Any,
            settings: Optional[Settings] = None, kind: str = "run") -> Path:
    """Write the run's report, then record its digest in the index every board shares.

    One digest serves both, so the run folder and the index never disagree about a run.
    """
    from common import profile_record

    path = workdir / "profile-report.md"
    record = profile_record.digest(board.name, board.label, result, plan, report=path, run=workdir, kind=kind)
    write_report(path, board, result, plan, record)
    try:
        profile_record.save(record, profile_record.index_dir(settings))
    except OSError as exc:
        logger.warning("%s: could not record the profile update in the index: %s", board.label, exc)
    return path


def _same_blocked_target(previous: str, target: str) -> bool:
    """An old missing-input result cannot block a changed board-specific task.

    The record shortens long targets to 300 characters. Compare that prefix,
    not merely the section name (Cutshort company chips used to request prose).
    """
    return previous == target or (previous.endswith('...') and target.startswith(previous[:-3]))


#: Prefix put on an edit the record says is still waiting on the user's facts.
_STILL_BLOCKED = 'needs input (facts unchanged; do not reopen this form): '


def _blocked_why(notes: List[str]) -> str:
    """The skip reason for a still-blocked edit, built from the recorded notes.

    The note recorded last time is this prefix plus the agent's note, so strip
    the prefix first; otherwise every run wraps the note once more.
    """
    reasons = []
    for note in notes:
        while note.startswith(_STILL_BLOCKED):
            note = note[len(_STILL_BLOCKED):]
        if note and note not in reasons:
            reasons.append(note)
    return _STILL_BLOCKED + '; '.join(reasons)


def run(driver: Any, board: Board, settings: Settings, profile: Optional[Profile], task: str,
        files: Tuple[Path, ...], plan: Any, label: str) -> Tuple[bool, str]:
    """One profile-agent run, checked; (saved, notes for memory and the log)."""
    from .accounts import account_email

    settings = agent_settings(settings)
    workdir = browser_agent.workdir_for(settings, "%s %s" % (board.label, label))
    workdir.mkdir(parents=True, exist_ok=True)
    files = browser_agent.stage_files(workdir, files)
    screenshot(driver, workdir / "before.png")
    facts = browser_agent.facts_text(profile, settings)
    facts_digest = hashlib.sha256(facts.encode('utf-8')).hexdigest()
    current = _read_profile(driver, board)
    (workdir / "before.txt").write_text(current, encoding="utf-8")
    if not current:
        result = ProfileCheck(False, 'Could not read the profile before editing', page_read=False)
        _finish(workdir, board, result, plan, settings)
        return False, result.why
    try:
        edits = edit_plan(settings, board, plan, facts, current)
    except Exception as exc:  # the agent still has the plan and audits the page itself
        logger.warning("%s: could not plan the edits for the live profile: %s", board.label, exc)
        edits = []
    if profile is not None:
        edits = profile_contract.reconcile(edits, profile, board.name, plan)
        edits = [e for e in edits if not unsupported_section(board, e['name'])]
        from common import profile_record
        previous = profile_record.load(profile_record.index_dir(settings)).get(board.name, {})
        if previous.get('facts_digest') == facts_digest:
            blocked = [s for s in previous.get('sections', []) if s.get('action') == NEEDS_INPUT]
            for edit in edits:
                matches = [s for s in blocked if _same_section(s.get('name', ''), edit['name'])
                           and _same_blocked_target(s.get('after', ''), edit.get('target', ''))]
                if matches:
                    edit.update(action='skip', why=_blocked_why([s.get('note', '') for s in matches]))
    if files:
        # Upload eligibility comes from the selected file, not the LLM's guess
        # about whether a filename such as onboarding.pdf sounds like a resume.
        resumes = [e for e in edits if re.fullmatch(r'(?:attach |uploaded )?resume(?: attached)?', e['name'], re.I)]
        if not resumes:
            resumes = [dict(name='Resume', current='')]
            edits.extend(resumes)
        for edit in resumes:
            edit.update(action='update', target=Path(files[0]).name,
                        why='The supplied file is the resume selected by the user. Upload it and verify the saved attachment.')
    before_entries = getattr(driver, '_profile_entries', [])
    duplicate_issues = profile_contract.duplicates(before_entries)
    journal = [{"operation_id": profile_contract.operation_id(board.name, e), **e, "state": "planned"}
               for e in edits]
    (workdir / 'operations.json').write_text(json.dumps(journal, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (workdir / 'entries-before.json').write_text(json.dumps(before_entries, indent=2) + '\n', encoding='utf-8')
    if edits:
        (workdir / "edit-plan.json").write_text(json.dumps(edits, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
        logger.info("%s edit plan: %s", board.label, ", ".join("%s (%s)" % (e["name"], e["action"]) for e in edits))
    text = prompt(task, board.profile_url or board.home, facts, account_email(settings), files,
                  bool(settings.company_site_password), edits)
    text += ('\n\nAccuracy contract: atomic values from profile.yaml in the edit plan override any conflicting '
             'old profile or generated prose. Re-read existing entries before each Add, and after any interrupted '
             'Save. Edit a uniquely matching entry in place. If multiple matches exist, report needs_review; '
             'do not add or delete. Every keep field also requires evidence after reload. Unknown mandatory '
             'facts are needs_input, never guessed. A skipped field does not count as verified.\n'
             'Existing entry identities: ' + json.dumps(before_entries, ensure_ascii=False))
    preferences = (getattr(profile, 'extra_facts', {}) or {}).get('profile_update_preferences', {})
    if preferences:
        text += ('\nUser-selected scope takes priority: ' + json.dumps(preferences) +
                 '\nSkip school education (Class X/XII) and the profile photo when requested above. '
                 'Do not open or save those editors, ask for their details, or treat them as missing. '
                 'College education remains in scope. Report the website meter honestly even if these '
                 'exclusions keep it below 100%.')
    if duplicate_issues:
        text += '\nExisting duplicate groups: ' + '; '.join(duplicate_issues)
    agent = browser_agent.run_agent(driver, settings, text, workdir, files, system=system_prompt(board))
    report = agent.report or {}
    status = str(report.get("status", "")).strip().lower()
    reason = ""
    if agent.problem or status not in ("done", "partial", NEEDS_INPUT):
        reason = agent.problem or _text(report.get("why")) or "the agent gave no reason"
        logger.error("%s profile agent stopped short: %s (run folder: %s)", board.label, reason, workdir)
        if not report and not edits:
            _finish(workdir, board, ProfileCheck(saved=False, why=reason), plan, settings)
            return False, reason
    elif status != "done":
        # `partial` is the skill's own word for "a field is outstanding", and facts the agent could
        # not find are the user's to add: neither fails the run by itself. The verifier decides,
        # section by section, from the reloaded page.
        logger.warning("%s profile agent left fields outstanding: %s (run folder: %s)", board.label,
                       _text(report.get("why")) or "the agent gave no reason", workdir)
    aside = reason or (_text(report.get("why")) if status != "done" else "")
    result = check(driver, board, settings, report, plan, workdir, edits, profile=profile)
    result.facts_digest = facts_digest
    if status == "needs_you":
        # A captcha, a code or a question only they can answer: a second pass would hit the same wall.
        result.saved, result.why = False, reason
        _finish(workdir, board, result, plan, settings)
        return False, reason
    result = repair(driver, board, settings, result, plan, facts, account_email(settings), files, workdir, profile=profile)
    result.issues = list(dict.fromkeys(result.issues + duplicate_issues))
    result.saved, result.why = _verdict(result)
    if aside and not result.saved:
        result.why = "%s (the agent: %s)" % (result.why, aside)
    path = _finish(workdir, board, result, plan, settings)
    for operation in journal:
        matches = [s for s in result.sections if _same_section(s.name, operation['name'])]
        operation['state'] = 'verified' if matches and all(s in result.verified for s in matches) else 'unresolved'
    (workdir / 'operations.json').write_text(json.dumps(journal, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if result.needs_input:
        logger.warning("%s asks for facts the facts file does not have; add them to profile.yaml and the next "
                       "run fills them in: %s", board.label,
                       "; ".join("%s (%s)" % (section.name, _cell(section.note, 160)) if section.note else section.name
                                 for section in result.needs_input))
    notes = "%s. %s. Report: %s" % (_text(report.get("notes") or report.get("why")), result.summary(), path)
    if plan is not None and plan.ats is not None:
        notes += " (local resume heuristic %d/100)" % plan.ats.score
    for section in result.unverified:
        logger.warning("%s: could not verify all requested fields for %s after reload (wanted: %s%s)", board.label, section.name,
                       section.wanted[:120],
                       "; missing: %s" % ", ".join(section.missing) if section.missing else "")
    if not result.saved and not reason and result.waiting_on_you:
        # Every section the bot can settle is on the page; the rest wait for profile.yaml, for a
        # value the board refuses, or for the user to choose between two live entries. Retrying
        # tomorrow with the same facts would ask the same, so the run counts as done.
        logger.warning("%s profile is intact and confirmed except for %s; it is not a failure. See %s",
                       board.label, result.why, path)
        return True, notes
    if not result.saved:
        logger.error("%s profile update not confirmed: %s. See %s", board.label, result.why, path)
        return False, notes
    logger.info("%s profile updated in %.0fs, $%s: %s", board.label, agent.seconds,
                "%.2f" % agent.cost_usd if agent.cost_usd is not None else "?", notes)
    return True, notes
