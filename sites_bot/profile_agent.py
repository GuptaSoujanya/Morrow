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
passed for free. Sections the page does not show are sent back to the agent as their own
small task (PROFILE_REPAIR_PASSES, default 1) and checked again. It takes a full-page
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
_LIST_ITEM_CHARS = 40
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
    def completeness(self) -> str:
        if not (self.completeness_before or self.completeness_after):
            return ""
        return "%s -> %s" % (self.completeness_before or "?", self.completeness_after or "?")

    def summary(self) -> str:
        parts = ["%d/%d changed sections confirmed" % (len(self.confirmed), len(self.changed))]
        if self.completeness:
            parts.append("completeness %s" % self.completeness)
        if self.unverified:
            parts.append("NOT on the page: %s" % ", ".join(section.name for section in self.unverified))
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
- name: the section as the board labels it;
- current: its value on the live page now, copied briefly ("" if empty or not shown);
- target: the exact text or values to enter, taken only from the planned profile and the facts
  (for skills: the comma-separated skills to ADD; for dropdowns: the option to pick);
- action: "update" (present but different in meaning or missing target keywords), "fill" (empty and the
  facts answer it), "keep" (already matches), or "skip" (the facts do not answer it, or it must not change);
- why: one short reason, naming any ATS keyword it adds.
Also give the completeness percentage shown on the page ("" if none) and gaps: board prompts for missing
details that the facts cannot answer. Never invent an employer, title, number, skill, date or degree."""


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


def _load_all(driver: Any) -> None:
    """Scroll to the bottom a few times so lazily loaded sections render."""
    for _ in range(4):
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            return
        time.sleep(0.7)
    try:
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass


def page_text(driver: Any) -> str:
    from .external import _page_text

    try:
        return _page_text(driver)
    except Exception:
        return ""


def _words(text: str) -> List[str]:
    return [token for token in _TOKEN.findall((text or "").casefold()) if token]


def _is_label(text: str) -> bool:
    return 0 < len(text) <= _LIST_ITEM_CHARS and len(text.split()) <= 2


def _items(text: str) -> List[str]:
    """The items of a list value (skills, roles) or the one label it is; [] when the value is prose."""
    parts = [part.strip(" .;") for part in str(text or "").split(",")]
    parts = [part for part in parts if part]
    if not parts:
        return []
    if len(parts) == 1:
        return parts if _is_label(parts[0]) else []
    if any(len(part) > _LIST_ITEM_CHARS or part.endswith(".") for part in parts):
        return []
    return parts


def _phrases(words: List[str], size: int) -> List[Tuple[str, ...]]:
    if len(words) <= size:
        return [tuple(words)] if words else []
    return [tuple(words[start:start + size]) for start in range(len(words) - size + 1)]


def _run_of(words: List[str], haystack: List[str]) -> bool:
    """Whether the words appear consecutively in the haystack, so "Go" cannot match "Django"."""
    if not words:
        return False
    return any(haystack[start:start + len(words)] == words
               for start in range(len(haystack) - len(words) + 1))


def _compare(expected: str, page: str) -> Tuple[Optional[bool], List[str]]:
    have = _words(page)
    if not have:
        return None, []
    items = _items(expected)
    if items:
        missing = [item for item in items if not _run_of(_words(item), have)]
        return (len(items) - len(missing)) / len(items) >= WORD_MATCH, missing
    words = _words(expected)
    if not words:
        return None, []
    size = min(_PHRASE, len(words))
    wanted = _phrases(words, size)
    found = set(_phrases(have, size))
    share = sum(1 for phrase in wanted if phrase in found) / len(wanted)
    return share >= WORD_MATCH, []


def _windows(heading: str, page: str) -> List[str]:
    """The page text after each place the section's own heading appears.

    Looking for a value only where its section is keeps a skill that is also in the headline, or a
    sentence repeated in a sidebar, from confirming a section it never reached. Every occurrence is
    returned because boards repeat a heading in their navigation before the section itself.
    """
    words = _words(heading)
    if not words or not page:
        return []
    pattern = r"\W+".join(re.escape(word) for word in words)
    return [page[match.start():match.start() + _WINDOW_CHARS]
            for match in re.finditer(pattern, page, re.IGNORECASE)][:_WINDOWS]


def verify(expected: str, page: str, heading: str = "") -> Tuple[Optional[bool], List[str]]:
    """Whether the expected text is on the page, and the parts that are not.

    A list value (skills, roles) is checked item by item, so a report names the skills that did
    not land. Prose is checked as overlapping phrases, so word order has to match while the
    board's own line breaks and truncation are still tolerated. With a heading, only that
    section's part of the page counts. Returns (None, []) when there is nothing to compare -- an
    empty value, or a page the bot could not read -- never a bare True.
    """
    best: Optional[Tuple[Optional[bool], List[str]]] = None
    for window in _windows(heading, page):
        outcome = _compare(expected, window)
        if outcome[0] is True:
            return outcome
        if outcome[0] is False and (best is None or len(outcome[1]) < len(best[1])):
            best = outcome
    return best if best is not None else _compare(expected, page)


def shown(expected: str, page: str, heading: str = "") -> bool:
    return verify(expected, page, heading)[0] is True


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


def check(driver: Any, board: Board, settings: Settings, report: Dict[str, Any], plan: Any,
          workdir: Path) -> ProfileCheck:
    """Reload the profile and confirm on the page what the agent says it changed."""
    from common.browser import safe_get

    result = ProfileCheck(
        saved=False, why="",
        sections=sections_from(report),
        completeness_before=_text(report.get("completeness_before")),
        completeness_after=_text(report.get("completeness_after")),
        confirmation=_text(report.get("board_confirmation")),
    )
    page = ""
    try:
        if safe_get(driver, board.profile_url):
            time.sleep(_SETTLE_S)
            _load_all(driver)
            page = page_text(driver)
    except Exception as exc:
        logger.warning("%s: could not reload the profile to check it: %s", board.label, exc)
    after = screenshot(driver, workdir / "after.png") if page else None
    if after:
        result.screenshots.append(str(after))
    for section in result.changed:
        if page:
            section.on_page, section.missing = verify(section.wanted, page, section.name)
    if page and plan is not None and plan.headline and not any("headline" in s.name.casefold()
                                                               for s in result.sections):
        on_page, missing = verify(plan.headline, page)
        result.sections.append(Section(name="Headline (planned)", action="checked", after=plan.headline,
                                       on_page=on_page, missing=missing))
    try:
        result.vision = _vision_check(settings, after, plan)
    except Exception as exc:  # advisory only
        logger.warning("%s: the screenshot check failed: %s", board.label, exc)
    if result.vision.get("completeness") and not result.completeness_after:
        result.completeness_after = _text(result.vision["completeness"])

    result.saved, result.why = _verdict(result)
    return result


def repair_text(sections: List[Section]) -> str:
    """The task for a repair pass: only the sections the reloaded page did not show."""
    lines = ["You already worked on this profile and reported these sections as saved and verified. The bot then "
             "reloaded the page itself and could NOT find this text on it, so the save did not take effect.",
             "", "Fix ONLY these sections. Leave every other section alone."]
    for number, section in enumerate(sections, 1):
        lines.append("%d. %s" % (number, section.name))
        lines.append("   write: %s" % section.wanted)
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
        if fresh.action not in CHANGED:
            fresh = replace(fresh, action=section.action)
        fresh.before = fresh.before or section.before
        fresh.note = " ".join(part for part in (section.note, fresh.note) if part).strip()
        result.sections[index] = fresh
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
    found = [section for section in changed if section.on_page]
    if not changed:
        return True, "nothing needed changing"
    if all(section.on_page is None for section in changed):
        return True, "the agent reports it saved; the bot could not re-read the page to confirm"
    if len(found) < SECTIONS_FOUND * len(changed):
        return False, "only %d of %d changed sections are on the reloaded page" % (len(found), len(changed))
    if result.unverified:
        return False, "%s still not on the reloaded page" % ", ".join(s.name for s in result.unverified)
    return True, "confirmed on the reloaded page"


def repair(driver: Any, board: Board, settings: Settings, result: ProfileCheck, plan: Any, facts: str,
           email: str, files: Tuple[Path, ...], workdir: Path) -> ProfileCheck:
    """Send the agent back for the sections the page did not show, then check the page again."""
    passes = max(0, int(getattr(settings, "profile_repair_passes", 0) or 0))
    for attempt in range(1, passes + 1):
        broken = result.unverified
        if not broken:
            break
        logger.warning("%s: %s not on the reloaded profile; repair pass %d of %d.", board.label,
                       ", ".join(section.name for section in broken), attempt, passes)
        folder = workdir / ("repair-%d" % attempt)
        folder.mkdir(parents=True, exist_ok=True)
        text = prompt(repair_text(broken), board.profile_url or board.home, facts, email, files,
                      bool(settings.company_site_password))
        try:
            agent = browser_agent.run_agent(driver, settings, text, folder, files, system=system_prompt(board))
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


def write_report(workdir: Path, board: Board, result: ProfileCheck, plan: Any) -> Path:
    """profile-report.md and .json in the run folder: the verdict first, then a line per section."""
    from common import profile_record

    path = workdir / "profile-report.md"
    record = profile_record.digest(board.name, board.label, result, plan, report=path, run=workdir)
    if plan is not None:
        record["plan_source"] = plan.source
        record["ats"] = asdict(plan.ats) if plan.ats is not None else None
    (workdir / "profile-report.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
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


def _finish(workdir: Path, board: Board, result: ProfileCheck, plan: Any,
            settings: Optional[Settings] = None) -> Path:
    """Write the run's report, then record its digest in the index every board shares."""
    from common import profile_record

    path = write_report(workdir, board, result, plan)
    try:
        profile_record.save(profile_record.digest(board.name, board.label, result, plan, report=path, run=workdir),
                            profile_record.index_dir(settings))
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
    if agent.problem or status != "done":
        reason = agent.problem or _text(report.get("why")) or "the agent gave no reason"
        logger.error("%s profile not updated: %s (run folder: %s)", board.label, reason, workdir)
        if report:
            _finish(workdir, board, ProfileCheck(saved=False, why=reason, sections=sections_from(report)),
                    plan, settings)
        return False, reason
    result = check(driver, board, settings, report, plan, workdir)
    result = repair(driver, board, settings, result, plan, facts, account_email(settings), files, workdir)
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
