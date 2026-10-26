"""The profile agent: an LLM browser agent with a profile-update skill, checked by the bot.

platforms.update_profile hands the signed-in browser to Claude with the Playwright MCP
server (vision on, so it can click by what it sees in a screenshot). Before the agent
starts, the bot reads the live profile itself and asks the LLM, with that board's
system prompt, for a section-by-section edit plan against the planned profile.

- system prompt: skills/profile-update/boards/<board>.md (the board's own agent: how it
  ranks profiles, its sections and quirks), then skills/profile-update/SKILL.md (audit,
  decide, edit one section at a time, read back, reload, report per section);
- task: the board task, the LLM-written profile plan with its ATS report
  (common.profile_plan), the edit plan for the live profile, and her facts.

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
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common.models import Profile, Settings

from . import browser_agent
from .board import Board

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent / "skills" / "profile-update"
SKILL_FILE = SKILL_DIR / "SKILL.md"
BOARD_PROMPTS = SKILL_DIR / "boards"
#: Live profile text and facts given to the edit planner.
_PAGE_CHARS = 10000
_FACTS_CHARS = 12000
EDIT_ACTIONS = ("update", "fill", "keep", "skip")
CHANGED = ("updated", "filled")
ALREADY_OK = "already_ok"
#: A section the edit plan asked for that the agent's report never mentions: it ran out of budget or
#: time before it got there. The repair pass finishes it.
PENDING = "pending"
#: The agent tried a section and says it could not save it.
FAILED = "failed"
#: Share of a changed section's phrases (or list items) that must be on the reloaded page to count as there.
WORD_MATCH = 0.7
#: Below this share of changed sections found on the page, the run is not counted as saved.
SECTIONS_FOUND = 0.5
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
#: How much of the page after a section's heading counts as that section, and how many
#: repeats of the heading to try (boards list a heading in their navigation as well).
_WINDOW_CHARS = 1200
_WINDOWS = 4
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

    @property
    def wanted(self) -> str:
        return self.after or self.evidence


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

    @property
    def changed(self) -> List[Section]:
        return [section for section in self.sections if section.action in CHANGED]

    @property
    def unverified(self) -> List[Section]:
        return [section for section in self.changed if section.on_page is False]

    @property
    def confirmed(self) -> List[Section]:
        return [section for section in self.changed if section.on_page is True]

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
    def needs_repair(self) -> List[Section]:
        if not self.page_read:
            return []
        return self.unverified + self.partial + self.undone

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
        if self.completeness:
            parts.append("completeness %s" % self.completeness)
        if self.unverified:
            parts.append("NOT on the page: %s" % ", ".join(section.name for section in self.unverified))
        if self.partial:
            parts.append("not seen: %s" % _cell(", ".join(item for section in self.partial
                                                          for item in section.missing), 80))
        if self.undone:
            parts.append("not done: %s" % ", ".join(section.name for section in self.undone))
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
        if edit.get("target") and edit["action"] in ("update", "fill"):
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
Below are: the board agent's own instructions, the planned profile (written from her resume, with its ATS
report), the text the bot just read from her LIVE profile page, and her facts.

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
Never invent an employer, title, number, skill, date or degree."""


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
        "--- Her live profile page, as text ---\n" + current[:_PAGE_CHARS],
        "--- Her facts ---\n" + facts[:_FACTS_CHARS],
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
        target = profile_plan._grounded_numbers(" ".join(str(item.get("target") or "").split()), known)
        if action not in EDIT_ACTIONS or (action in ("update", "fill") and not target):
            action = "skip"
        edits.append({"name": _text(item.get("name")), "action": action, "current": _text(item.get("current"))[:300],
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
document.querySelectorAll('a, button, span, div').forEach(function (el) {
  var text = (el.textContent || '').trim();
  if (/^(read|view|see|show)\\s+more(\\s*\\.\\.\\.)?$/i.test(text) && el.children.length === 0) {
    try { el.click(); n += 1; } catch (e) {}
  }
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
while ((node = walker.nextNode())) {
  if (node.nodeType === 1) {
    var kind = node.tagName, value = '';
    if (kind !== 'INPUT' && kind !== 'TEXTAREA' && kind !== 'SELECT') continue;
    if (!node.getClientRects().length) continue;
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
  var tag = parent.tagName;
  if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT' || tag === 'TEMPLATE') continue;
  if (!parent.getClientRects().length) continue;
  parts.push(text);
}
return parts.join(' ');
"""


def page_text(driver: Any) -> str:
    """The visible text of the page with a space between neighbouring elements, form values included.

    Selenium's body text runs inline chips together ("PythonJavascriptMongoDB"), so a skill list
    could never be matched chip by chip; it stays the fallback for a driver that cannot run scripts.
    What sits in a text box or a drop-down is part of the profile on a board that edits it as a
    form (Hirist's About and work preferences), and body text never shows it.
    """
    from .external import _page_text

    try:
        text = driver.execute_script(_TEXT_JS)
        if isinstance(text, str) and text.strip():
            return " ".join(text.split())
    except Exception:
        pass
    try:
        return _page_text(driver)
    except Exception:
        return ""


def _words(text: str) -> List[str]:
    return [token for token in _TOKEN.findall((text or "").casefold()) if token]


def _is_label(text: str) -> bool:
    words = text.split()
    one_token = len(words) == 1  # a URL is one item however long it is
    return 0 < len(words) <= _LIST_ITEM_WORDS and (len(text) <= _LIST_ITEM_CHARS or one_token)


def _items(text: str) -> List[str]:
    """The items of a list value (skills, roles) or the one label it is; [] when the value is prose.

    Every part has to read like a label, so "Python, Go." is still the two skills it is while
    "...systems on aws, with a focus on retrieval." is prose and gets matched as phrases instead
    of demanding each clause word for word.
    """
    parts = [part.strip(" .;") for part in str(text or "").split(",")]
    parts = [part for part in parts if part]
    if not parts or not all(_is_label(part) for part in parts):
        return []
    return parts


def _phrases(words: List[str], size: int) -> List[Tuple[str, ...]]:
    if len(words) <= size:
        return [tuple(words)] if words else []
    return [tuple(words[start:start + size]) for start in range(len(words) - size + 1)]


_YEARS = re.compile(r"^(\d+)(?:\.(\d))?\s*(?:years?|yrs?)$", re.IGNORECASE)


def _forms(item: str) -> List[str]:
    """The item and the ways a board renders it: "2.5 years" is shown as "2 Years 6 Months"."""
    match = _YEARS.match(item.strip())
    if not match:
        return [item]
    years, tenth = match.group(1), match.group(2)
    months = round(int(tenth) * 1.2) if tenth else 0
    return [item, "%s years %d months" % (years, months), "%s years" % years if not months else item]


def _plain(token: str) -> str:
    """A token as a board spells it: "Nextjs", "Next.js" and "next" are one skill, "React.js" is React."""
    return token[:-2] if token.endswith("js") and len(token) > 4 else token


def _run_of(words: List[str], haystack: List[str]) -> bool:
    """Whether the words appear consecutively in the haystack, so "Go" cannot match "Django".

    Spacing and a trailing "js" are the board's choice, not a difference: "Fast API" is FastAPI,
    "Nextjs" is Next.js and "React.js" is React, so a chip the board renamed on saving still counts.
    """
    wanted = _plain("".join(words))
    if not wanted:
        return False
    for start in range(len(haystack)):
        joined = ""
        for token in haystack[start:start + len(words) + 2]:
            joined += token
            if _plain(joined) == wanted:
                return True
            if len(_plain(joined)) >= len(wanted):
                break
    return False


def _compare(expected: str, page: str) -> Tuple[Optional[bool], List[str]]:
    have = _words(page)
    if not have:
        return None, []
    items = _items(expected)
    if items:
        missing = [item for item in items
                   if not any(_run_of(_words(form), have) for form in _forms(item))]
        return (len(items) - len(missing)) / len(items) >= WORD_MATCH, missing
    words = _words(expected)
    if not words:
        return None, []
    size = min(_PHRASE, len(words))
    wanted = _phrases(words, size)
    found = set(_phrases(have, size))
    share = sum(1 for phrase in wanted if phrase in found) / len(wanted)
    return share >= WORD_MATCH, []


def _windows(heading: str, page: str, lead: int = 0) -> List[str]:
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
    return [page[max(0, match.start() - lead):match.start() + _WINDOW_CHARS]
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
    if own and key in ("employment", "job profile"):
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
    best: Optional[Tuple[Optional[bool], List[str]]] = None
    for window in _windows(heading, page, lead):
        outcome = _compare(expected, window)
        if outcome[0] is True and not outcome[1]:
            return outcome
        if outcome[0] is not None and (best is None or _rank(outcome) > _rank(best)):
            best = outcome
    return best if best is not None else _compare(expected, page)


# Text between a pair of quotes that are not apostrophes inside a word ("Hirist's", "couldn't").
_QUOTED = re.compile(r"(?<![A-Za-z0-9])[\"'\u2018\u201c](.{3,400}?)[\"'\u2019\u201d](?![A-Za-z0-9])")


def _quoted(text: str) -> str:
    return ", ".join(part.strip() for part in _QUOTED.findall(text) if part.strip())


def claims(section: "Section") -> List[str]:
    """What the page should show for a section: the value typed, the text read back, and the quoted
    parts of either, for an agent that wrote a sentence around the value instead of the value."""
    found: List[str] = []
    for text in (section.after, section.evidence, _quoted(section.after), _quoted(section.evidence)):
        if text and text not in found:
            found.append(text)
    return found


def _claim_rank(outcome: Tuple[Optional[bool], List[str]]) -> Tuple[bool, int]:
    # A found claim with the fewest gaps wins; among claims not found, the one that names its gaps
    # (a list checked item by item) explains more than prose that only says "no".
    return outcome[0] is True, -len(outcome[1]) if outcome[0] is True else len(outcome[1])


def confirm(section: "Section", page: str) -> Tuple[Optional[bool], List[str]]:
    """verify() over every claim the section makes, best outcome first.

    "After reload, My Profile shows 'Software Engineer - Ethara AI'" is true of the page and wrong
    as a field value; the quoted part is what the page can be asked for.
    """
    heading, lead = _locate(section.name)
    best: Optional[Tuple[Optional[bool], List[str]]] = None
    for claim in claims(section):
        outcome = verify(claim, page, heading, lead)
        if outcome[0] is True and not outcome[1]:
            return outcome
        if outcome[0] is not None and (best is None or _claim_rank(outcome) > _claim_rank(best)):
            best = outcome
    return best if best is not None else (None, [])


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


def _same_section(left: str, right: str) -> bool:
    left = re.sub(r"[^a-z0-9]+", " ", left.casefold()).strip()
    right = re.sub(r"[^a-z0-9]+", " ", right.casefold()).strip()
    return bool(left and right) and (left == right or left in right or right in left)


def add_planned(result: ProfileCheck, edits: Optional[List[Dict[str, str]]], page: str) -> None:
    """Sections the edit plan asked for that the agent's report never mentions.

    An agent that ran out of budget, time or turns stops without a word about what it did not
    reach, and the repair pass only knows what it is told. The plan is the contract: a planned
    edit the page already shows is done; one it does not show is pending and gets redone.
    """
    for edit in edits or []:
        if edit.get("action") not in ("update", "fill") or not edit.get("target"):
            continue
        reported = [section for section in result.sections if _same_section(edit["name"], section.name)]
        for section in reported:
            if section.action == FAILED and not section.wanted:
                section.after = edit["target"]
        if reported:
            continue
        on_page, missing = verify(edit["target"], page, *_locate(edit["name"])) if page else (None, [])
        done = on_page is True and not missing
        result.sections.append(Section(
            name=edit["name"], action="already_ok" if done else PENDING, before=edit.get("current", ""),
            after=edit["target"], on_page=on_page, missing=missing,
            note="planned; the page shows it" if done else "planned, but the agent never reported it"))


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
    for url in board.profile_pages:
        try:
            extra = _read_page(driver, url)
        except Exception as exc:
            extra = ""
            logger.warning("%s: could not read %s: %s", board.label, url, exc)
        if extra:
            parts.append(extra)
        else:
            logger.warning("%s: %s could not be read; what it holds cannot be confirmed.", board.label, url)
    return "\n\n".join(parts)


def check(driver: Any, board: Board, settings: Settings, report: Dict[str, Any], plan: Any,
          workdir: Path, edits: Optional[List[Dict[str, str]]] = None) -> ProfileCheck:
    """Reload the profile and confirm on the page what the agent says it changed, and what the plan wanted."""
    result = ProfileCheck(
        saved=False, why="",
        sections=sections_from(report),
        completeness_before=_text(report.get("completeness_before")),
        completeness_after=_text(report.get("completeness_after")),
        confirmation=_text(report.get("board_confirmation")),
    )
    page = _read_profile(driver, board)
    if not page:
        logger.warning("%s: the profile page could not be read after the run; trying once more in %ds.",
                       board.label, _RETRY_READ_S)
        time.sleep(_RETRY_READ_S)
        page = _read_profile(driver, board)
    result.page_read = bool(page)
    if page:
        (workdir / "page-after.txt").write_text(page, encoding="utf-8")
    after = screenshot(driver, workdir / "after.png") if page else None
    if after:
        result.screenshots.append(str(after))
    # The LLM that looks at the page cannot decode a full-page capture of a long profile; the top of
    # the page, where the headline, designation and completeness sit, is what it is asked about.
    view = _viewport(driver, workdir / "after-view.png") if page else None
    for section in result.sections:
        # What the agent says it changed, and what it says was already there: both are claims about
        # the page, and a repair pass that finds a section "already_ok" must leave page evidence too.
        if page and section.wanted and (section.action in CHANGED or section.action == ALREADY_OK):
            section.on_page, section.missing = confirm(section, page)
    add_planned(result, edits, page)
    if page and plan is not None and plan.headline and not any("headline" in s.name.casefold()
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
    by_name = {section.name.casefold(): section for section in repaired.sections}
    for index, section in enumerate(result.sections):
        fresh = by_name.get(section.name.casefold())
        if fresh is None:
            continue
        result.sections[index] = replace(
            fresh,
            action=fresh.action if fresh.action in CHANGED or section.action in (PENDING, FAILED) else section.action,
            before=fresh.before or section.before,
            missing=list(fresh.missing),
            note=" ".join(part for part in (section.note, fresh.note) if part).strip(),
        )
    result.completeness_after = repaired.completeness_after or result.completeness_after
    result.confirmation = repaired.confirmation or result.confirmation
    result.vision = repaired.vision or result.vision
    for shot in repaired.screenshots:
        if shot not in result.screenshots:
            result.screenshots.append(shot)
    result.saved, result.why = _verdict(result)
    return result


def _verdict(result: ProfileCheck) -> Tuple[bool, str]:
    changed = result.changed
    undone = result.undone
    if not changed and not undone:
        return True, "nothing needed changing"
    if not result.page_read:
        return False, "the profile page could not be re-read after the run; unconfirmed: %s" % ", ".join(
            section.name for section in changed + undone)
    checked = [section for section in changed if section.on_page is not None]
    if not checked and not undone:
        return True, "the agent reports it saved; the bot could not re-read the page to confirm"
    found = [section for section in checked if section.on_page]
    if checked and len(found) < SECTIONS_FOUND * len(checked):
        return False, "only %d of %d checked sections are on the reloaded page" % (len(found), len(checked))
    if result.unverified:
        return False, "%s still not on the reloaded page" % ", ".join(s.name for s in result.unverified)
    if undone:
        return False, "not done: %s" % ", ".join(s.name for s in undone)
    if result.partial:
        return True, "confirmed on the reloaded page, except: %s" % ", ".join(
            item for section in result.partial for item in section.missing)
    return True, "confirmed on the reloaded page"


def repair(driver: Any, board: Board, settings: Settings, result: ProfileCheck, plan: Any, facts: str,
           email: str, files: Tuple[Path, ...], workdir: Path) -> ProfileCheck:
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
        result = _merge(result, check(driver, board, settings, agent.report, plan, folder))
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

    head = "%s - %s" % ("saved" if result.saved else "NOT confirmed", result.why)
    lines = ["# %s profile: %s" % (board.label, head), "", result.summary()]
    if plan is not None and plan.ats is not None:
        lines[-1] += "; resume ATS %d/100" % plan.ats.score
    lines += ["", "| Section | Action | On page | Value |", "|---|---|---|---|"]
    for section in result.sections:
        mark = "-" if section.on_page is None else ("yes" if section.on_page else "**NO**")
        value = _cell(section.after or section.before)
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
    result.saved = not absent and not partial
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
    _load_all(driver)
    current = page_text(driver)
    (workdir / "before.txt").write_text(current, encoding="utf-8")
    try:
        edits = edit_plan(settings, board, plan, facts, current)
    except Exception as exc:  # the agent still has the plan and audits the page itself
        logger.warning("%s: could not plan the edits for the live profile: %s", board.label, exc)
        edits = []
    if edits:
        (workdir / "edit-plan.json").write_text(json.dumps(edits, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
        logger.info("%s edit plan: %s", board.label, ", ".join("%s (%s)" % (e["name"], e["action"]) for e in edits))
    text = prompt(task, board.profile_url or board.home, facts, account_email(settings), files,
                  bool(settings.company_site_password), edits)
    agent = browser_agent.run_agent(driver, settings, text, workdir, files, system=system_prompt(board))
    report = agent.report or {}
    status = str(report.get("status", "")).strip().lower()
    reason = ""
    if agent.problem or status != "done":
        reason = agent.problem or _text(report.get("why")) or "the agent gave no reason"
        logger.error("%s profile agent stopped short: %s (run folder: %s)", board.label, reason, workdir)
        if not report and not edits:
            _finish(workdir, board, ProfileCheck(saved=False, why=reason), plan, settings)
            return False, reason
    result = check(driver, board, settings, report, plan, workdir, edits)
    if status == "needs_you":
        # A captcha, a code or a question only she can answer: a second pass would hit the same wall.
        result.saved, result.why = False, reason
        _finish(workdir, board, result, plan, settings)
        return False, reason
    result = repair(driver, board, settings, result, plan, facts, account_email(settings), files, workdir)
    if reason and not result.saved:
        result.why = "%s (the agent: %s)" % (result.why, reason)
    path = _finish(workdir, board, result, plan, settings)
    notes = "%s. %s. Report: %s" % (_text(report.get("notes") or report.get("why")), result.summary(), path)
    if plan is not None and plan.ats is not None:
        notes += " (resume ATS score %d/100)" % plan.ats.score
    for section in result.unverified:
        logger.warning("%s: %s is still not on the reloaded profile (wanted: %s%s)", board.label, section.name,
                       section.wanted[:120],
                       "; missing: %s" % ", ".join(section.missing) if section.missing else "")
    if not result.saved:
        logger.error("%s profile update not confirmed: %s. See %s", board.label, result.why, path)
        return False, notes
    logger.info("%s profile updated in %.0fs, $%s: %s", board.label, agent.seconds,
                "%.2f" % agent.cost_usd if agent.cost_usd is not None else "?", notes)
    return True, notes
