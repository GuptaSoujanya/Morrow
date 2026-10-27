"""The morning briefing: several AI agents, run in parallel, each writing one file of the day.

Every agent asks claude and kiro (the team, see ai_cli.team) the same brief at
once, each with web search; each draft is checked and the first CLI merges the
good drafts into one file with the best papers, news and companies of both. Each
agent writes its file into user/research/daily/<date>/ the moment it finishes, and the folder's
README.md (the index, with charts) is rewritten after every agent, so the briefing
fills in while the rest of the pipeline runs.

    01-goal.md            today's goal: what to learn, a concept map and a 2-hour plan
    02-system-design.md   a deep dive into today's design topic with architecture diagrams
    03-papers.md          two recent papers, prioritizing AI and resume relevance
    04-tech-news.md       the week's AI / GenAI / engineering news
    05-companies.md       companies to look at and why
    06-repositories.md    active GitHub repositories to explore and save

An answer is checked before it is written (headings, links, mermaid graphs), so a
bad answer leaves no file and the stage stays failed until `pipeline continue`.
"""

import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Union
from urllib.parse import urlsplit

from common import ai_cli
from common import persona as persona_module

from . import learning, links

logger = logging.getLogger(__name__)

DAILY = learning.RESEARCH / "daily"

_RULES = ("Output markdown only, nothing before or after it. Search the web; every source needs a real "
          "URL that you actually found, never an invented one. Graphs are mermaid code blocks "
          "(```mermaid) that render on GitHub: flowchart, sequenceDiagram, mindmap, timeline, pie, "
          "gantt or xychart-beta. No emojis.")


class Agent(NamedTuple):
    key: str
    filename: str
    heading: str
    graphs: int  # mermaid blocks the answer must have
    links: int  # URLs the answer must have
    brief: str
    recent: int = 0  # when set, every paper must be from this many years back or newer


AGENTS = (
    Agent("goal", "01-goal.md", "# Today's goal", 2, 3,
          "Write today's learning goal for this study day. Sections: ## Goal (one paragraph: what the "
          "learner can do by tonight), ## Concept map (a mermaid mindmap of today's ideas and how they "
          "connect), ## The 2 hours (a mermaid gantt chart of the 55 / 55 / 10 minute blocks, then a "
          "numbered step list), ## Key ideas (the 6 to 10 facts to remember, each one or two lines), "
          "## Check yourself (5 interview questions with short model answers), ## Where this leads "
          "(what tomorrow builds on, and how it shows up in real systems), ## Sources."),
    Agent("system-design", "02-system-design.md", "# System design:", 2, 4,
          "Write a deep dive into today's system design topic, at senior-interview level. Sections: "
          "## The problem, ## Architecture (a mermaid flowchart of the components), ## Request flow (a "
          "mermaid sequenceDiagram), ## Numbers (a back-of-envelope estimate as a markdown table: QPS, "
          "storage, bandwidth), ## Trade-offs (a table: option, gains, costs, when to pick it), ## How "
          "real companies do it (2 or 3 engineering-blog examples with links), ## Interview questions "
          "(5, with answers), ## Sources."),
    Agent("papers", "03-papers.md", "# Papers to read", 2, 2,
          "Pick exactly 2 distinct research papers, every one published in the years given below, that matter to the "
          "tech industry right now: work that companies are shipping, open-source projects are adopting "
          "or labs are building on (LLMs, agents, RAG, inference and serving, evaluation, ML systems, "
          "distributed systems for AI). Prioritize AI for both papers: one should directly fit the resume "
          "and today's learning topic; the other should introduce a new AI idea. Search the newest releases "
          "first, preferably the last 7 days, widening to 30 days only when necessary and stating the actual "
          "publication date as **Published**: YYYY-MM-DD in each paper section. Each paper must have been "
          "first published within the last 30 days, never in the future. Verify that date on its primary "
          "source; a new revision of an older paper does not make it newly published. Do not present an older paper as newly published. Avoid papers in the recent "
          "reading history below. Prefer arXiv or the venue "
          "page. For each: ## <paper title> (<year>) with the authors, the link, then **Problem**, "
          "**Idea**, **How it works**, **Results** (only numbers the paper states), **In industry** (who "
          "uses or builds on it: a company, product or open-source project, with a link), **Why it "
          "matters for you** (an engineer working on {focus}), and **Read** (which "
          "sections, in what order, about how long). Then ## Industry map, a mermaid mindmap of the "
          "papers grouped by area with the companies and projects using them, and ## Reading order, a "
          "mermaid flowchart of the order to read them in and how they depend on each other.",
          recent=2),
    Agent("tech-news", "04-tech-news.md", "# Tech news", 1, 6,
          "Write the news brief for the last 7 days: ## Models and labs, ## Tools and frameworks, "
          "## Research, ## Engineering and infrastructure, ## Jobs and industry (India and remote). 2 to 4 "
          "items each: a bold one-line headline, the date, two sentences on what happened and why it "
          "matters, the link. Then ## At a glance, a mermaid pie chart of the items per section, and "
          "## Try this week, one hands-on thing to try from the news."),
    Agent("companies", "05-companies.md", "# Companies to look at", 1, 5,
          "Find 6 to 8 companies currently hiring for roles that fit this resume ({focus}) in {location} "
          "or remote. For each: ## <company>, what they build, the stack, the kind of "
          "role that fits, a recent news item or engineering post, and the careers link. Then ## Where "
          "they sit, a mermaid mindmap grouping them (labs, infrastructure, product companies, services), and "
          "## Talking points, how the resume's work maps to each group."),
    Agent("repositories", "06-repositories.md", "# GitHub discoveries", 0, 3,
          "Search GitHub and the web for 3 to 5 active repositories gaining attention this week, prioritizing "
          "AI agents, useful new developer tools, and the resume's skills ({focus}). Verify each repository "
          "exists at its canonical https://github.com/owner/repository URL. Use exactly one ## owner/repository "
          "heading for each. Put the canonical link first, then **What it does**, **Why it fits your resume**, "
          "**Try it** (a small practical experiment), **Activity** (dated evidence with a source), and **License** "
          "(only when verified). Distinguish evidence of recent activity from evidence of trending; do not "
          "invent star counts, growth or popularity. No other level-two headings."),
)


def folder_for(day: date, root: Path = DAILY) -> Path:
    return root / day.isoformat()


def output_of(agent: Agent, day: date, root: Path = DAILY) -> Path:
    return folder_for(day, root) / agent.filename


def context(day: date, learning_root: Path = learning.LEARNING) -> str:
    """What every agent is told about today: the study day and the resume skills."""
    progress = learning.load_progress(learning_root)
    try:
        today = (learning_root / "today.md").read_text(encoding="utf-8")
    except OSError:
        today = ""
    resume = learning.resume_text()
    skills = re.findall(r"\\textbf\{([^}]*)\}", resume)[:40]
    who = persona_module.load_persona()
    return "\n\n".join(part for part in [
        "Today is %s. The learner is %s%s on day %d of a 90-day plan to reach %s, studying 2 hours a day."
        % (day.isoformat(), "the engineer described by the current resume" if resume.strip() else who.learner_line(), " in " + who.location if who.location else "",
           learning.current_day(progress), who.goal or learning.DEFAULT_GOAL),
        "Today's topics: %s." % (learning.today_topics(learning_root) or "system design and LLMs"),
        "Today's study notes (for reference):\n" + today[:6000] if today else "",
        "Resume highlights: " + ", ".join(skills) if skills else "",
        "Resume evidence (contact details removed; authoritative for experience):\n" + resume[:6000],
        "Saved goals/location are preferences, not evidence of experience. Study notes may predate the selected resume; use the resume for personal relevance.",
        "Recent paper reading history (avoid repeating these):\n" + recent_papers(day, learning_root.parent / 'daily'),
    ] if part)


def recent_papers(day: date, root: Path = DAILY) -> str:
    """Bounded prior history helps the daily researchers avoid repeated papers."""
    lines = []
    for path in sorted(root.glob('????-??-??/03-papers.md'), reverse=True):
        try:
            previous = date.fromisoformat(path.parent.name)
            if not 0 < (day - previous).days <= 30:
                continue
            text = path.read_text(encoding='utf-8')
        except (ValueError, OSError):
            continue
        lines.extend(line for line in text.splitlines() if line.startswith('## ') or 'arxiv.org/' in line)
    return '\n'.join(lines)[:5000] or 'No previous papers saved.'


def first_year(agent: Agent, day: date) -> int:
    return day.year - agent.recent


def brief_for(agent: Agent) -> str:
    """The agent's brief with {focus} and {location} filled from the persona."""
    who = persona_module.load_persona()
    return (agent.brief.replace("{focus}", "the skills and projects evidenced by the current resume")
            .replace("{location}", who.location or "their country"))


def prompt_for(agent: Agent, ctx: str, day: Optional[date] = None) -> str:
    start = agent.heading + " <topic>" if agent.heading.endswith(":") else agent.heading
    years = ""
    if agent.recent and day:
        years = ("Only papers published from %d to %d; nothing older, not even classics. Put the year in "
                 "each paper's heading." % (first_year(agent, day), day.year))
    return "\n\n".join(part for part in [ctx, brief_for(agent), years, "Start with '%s'." % start, _RULES] if part)


_YEAR = re.compile(r"\b(19|20)\d\d\b")
_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d\d)(\d\d)\.\d{4,5}")


def paper_sources(text):
    """One primary URL per paper; normalize arXiv versions for deduplication."""
    papers = [part for part in re.split(r'^## ', text, flags=re.M)[1:] if _YEAR.search(part.split('\n')[0])]
    sources = []
    for paper in papers:
        urls = re.findall(r'https?://[^\s)>\]]+', paper)
        def priority(url):
            try:
                return urlsplit(url).hostname not in ('arxiv.org', 'www.arxiv.org', 'openreview.net', 'aclanthology.org', 'proceedings.mlr.press')
            except ValueError:
                return True
        urls.sort(key=priority)
        url = urls[0].rstrip('.,;') if urls else ''
        try:
            parsed = urlsplit(url)
            arxiv = re.match(r'/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$', parsed.path) if parsed.hostname in ('arxiv.org', 'www.arxiv.org') else None
        except ValueError:
            arxiv = None
        sources.append('https://arxiv.org/abs/' + arxiv[1] if arxiv else url)
    return sources


def old_papers(text: str, since: int) -> List[str]:
    """Paper headings (## ... with a year) or arXiv links from before `since`."""
    old = []
    for line in text.splitlines():
        if line.startswith("## "):
            years = [int(m.group(0)) for m in _YEAR.finditer(line)]
            if years and max(years) < since:
                old.append(line[3:].strip())
    old += ["arXiv %s%s" % (yy, mm) for yy, mm in _ARXIV.findall(text) if 2000 + int(yy) < since]
    return old


def check(agent: Agent, text: str, day: Optional[date] = None) -> None:
    """AIError when the answer is missing the agent's graphs or links, or cites papers too old."""
    graphs = text.count("```mermaid")
    links = len(set(re.findall(r"https?://[^\s)>\]]+", text)))
    if graphs < agent.graphs:
        raise ai_cli.AIError("%s: %d mermaid graph(s), wanted %d" % (agent.key, graphs, agent.graphs))
    if links < agent.links:
        raise ai_cli.AIError("%s: %d link(s), wanted %d" % (agent.key, links, agent.links))
    if agent.recent and day:
        old = old_papers(text, first_year(agent, day))
        if old:
            raise ai_cli.AIError("%s: papers from before %d: %s" % (agent.key, first_year(agent, day), "; ".join(old)))
    if agent.key == 'papers':
        sections = re.split(r'^## ', text, flags=re.M)[1:]
        papers = [section for section in sections if _YEAR.search(section.split('\n')[0])]
        if len(papers) != 2:
            raise ai_cli.AIError('papers: expected exactly 2 paper sections with publication years')
        sources = paper_sources(text)
        if any(not url for url in sources) or len(set(sources)) != 2:
            raise ai_cli.AIError('papers: each paper needs its own original source link')
        if day and any(int(match.group()) > day.year for paper in papers for match in _YEAR.finditer(paper.split('\n')[0])):
            raise ai_cli.AIError('papers: publication years cannot be in the future')
        for paper in papers:
            published = re.search(r'^\*\*Published\*\*:\s*(\d{4}-\d{2}-\d{2})\s*$', paper, re.M)
            try:
                stamp = date.fromisoformat(published[1]) if published else None
            except ValueError:
                stamp = None
            if stamp is None:
                raise ai_cli.AIError('papers: each paper needs a verified **Published**: YYYY-MM-DD date')
            if day and not 0 <= (day - stamp).days <= 30:
                raise ai_cli.AIError('papers: first publication must be within the last 30 days')
            if str(stamp.year) not in paper.split('\n')[0]:
                raise ai_cli.AIError('papers: heading year must match the publication date')
            source = paper_sources('## ' + paper)[0]
            arxiv = _ARXIV.search(source)
            if arxiv and (2000 + int(arxiv[1]), int(arxiv[2])) != (stamp.year, stamp.month):
                raise ai_cli.AIError('papers: arXiv submission month must match first publication')
    if agent.key == 'repositories':
        sections = re.split(r'^## ', text, flags=re.M)[1:]
        names = [section.split('\n')[0].strip() for section in sections]
        if not 3 <= len(names) <= 5 or len({name.casefold() for name in names}) != len(names):
            raise ai_cli.AIError('repositories: expected 3 to 5 distinct repository sections')
        for name, section in zip(names, sections):
            if not re.fullmatch(r'[\w.-]+/[\w.-]+', name, re.ASCII):
                raise ai_cli.AIError('repositories: use owner/repository headings')
            urls = re.findall(r'https?://[^\s)>\]]+', section)
            canonical = 'https://github.com/' + name
            if not urls or urls[0].rstrip('.,;/') != canonical:
                raise ai_cli.AIError('repositories: put the matching canonical GitHub URL first')


def merge_prompt(agent: Agent, ctx: str, day: date, drafts: Dict[str, str]) -> str:
    """Ask for one file made of the best of every researcher's draft."""
    parts = [ctx, "%d researchers (%s) each searched the web and wrote a draft of the same file. Their brief "
             "was:\n\n%s" % (len(drafts), ", ".join(drafts), agent.brief),
             "Write the final file from the best of the drafts: keep the strongest, newest and most "
             "industry-relevant items (papers, news, companies), drop duplicates and anything you cannot "
             "confirm at its link, and keep the brief's exact sections and format. Check links with the web "
             "if unsure. Do not mention the drafts or the researchers."]
    parts += ["--- Draft by %s ---\n%s" % (name, text) for name, text in drafts.items()]
    return prompt_for(agent, "\n\n".join(parts), day)


def _draft(agent: Agent, ask: learning.Ask, prompt: str, day: date) -> str:
    text = links.linkify(ai_cli.markdown_from(ask(prompt), agent.heading.split(":")[0]))
    check(agent, text, day)
    return text


def research(agent: Agent, team: Dict[str, learning.Ask], day: date, ctx: str) -> str:
    """The agent's checked text: every CLI in the team researches at once, then the first merges.

    With one good draft that draft is the answer; when the merge fails its check the
    first good draft is kept, so a second CLI can only make the file better.
    """
    prompt = prompt_for(agent, ctx, day)
    drafts: Dict[str, str] = {}
    errors = []
    with ThreadPoolExecutor(max_workers=len(team)) as pool:
        futures = {name: pool.submit(_draft, agent, ask, prompt, day) for name, ask in team.items()}
        for name, future in futures.items():
            try:
                drafts[name] = future.result()
                logger.info("[agent %s] %s's draft passed the check", agent.key, name)
            except ai_cli.AIError as exc:
                errors.append("%s: %s" % (name, exc))
                logger.warning("[agent %s] %s's draft failed: %s", agent.key, name, exc)
    if not drafts:
        raise ai_cli.AIError("; ".join(errors))
    if len(drafts) == 1:
        return next(iter(drafts.values()))
    judge = next(iter(team))
    logger.info("[agent %s] %s merges the %d drafts...", agent.key, judge, len(drafts))
    try:
        text = _draft(agent, team[judge], merge_prompt(agent, ctx, day, drafts), day)
    except ai_cli.AIError as exc:
        logger.warning("[agent %s] the merge failed (%s); keeping %s's draft", agent.key, exc, next(iter(drafts)))
        return next(iter(drafts.values()))
    return text + "\n*Researched by %s; merged by %s.*\n" % (" and ".join(drafts), judge)


def run_agent(agent: Agent, ask: Union[learning.Ask, Dict[str, learning.Ask]], day: date, ctx: str,
              root: Path = DAILY) -> Path:
    """Research, check and write one agent's file; its path. `ask` is one CLI or a team of them."""
    logger.info("[agent %s] working...", agent.key)
    text = research(agent, ask if isinstance(ask, dict) else {"cli": ask}, day, ctx)
    if agent.key == 'papers':
        previous_sources = set()
        for previous in root.glob('????-??-??/03-papers.md'):
            try:
                age = (day - date.fromisoformat(previous.parent.name)).days
            except ValueError:
                continue
            if 0 < age <= 30:
                previous_sources.update(paper_sources(previous.read_text(encoding='utf-8')))
        if previous_sources.intersection(paper_sources(text)):
            raise ai_cli.AIError('papers: this selection repeats a paper from the last 30 days; retry for fresh research')
    path = output_of(agent, day, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.info("[agent %s] wrote %s", agent.key, path)
    return path


# ---------------------------------------------------------------------------
# The day's index, with charts
# ---------------------------------------------------------------------------


def _label(text: str) -> str:
    return text.replace('"', "'")


def progress_pie(done_days: int) -> str:
    return "\n".join(["```mermaid", "pie title 90-day plan", '    "Done" : %d' % done_days,
                      '    "Left" : %d' % (learning.LAST_DAY - done_days), "```"])


def applied_chart(history: List[tuple]) -> str:
    """A bar chart of verified applications per day, from (date, count) pairs."""
    if not history:
        return "_No applications recorded yet._"
    history = history[-14:]
    top = max(max(count for _, count in history), 1)
    return "\n".join([
        "```mermaid", "xychart-beta", '    title "Applications per day"',
        "    x-axis [%s]" % ", ".join('"%s"' % day[5:] for day, _ in history),
        '    y-axis "Applied" 0 --> %d' % top,
        "    bar [%s]" % ", ".join(str(count) for _, count in history), "```"])


def stages_chart(stages: Dict[str, Dict]) -> str:
    counts = {}  # type: Dict[str, int]
    for entry in stages.values():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    if not counts:
        return ""
    return "\n".join(["```mermaid", "pie title Today's stages"]
                     + ['    "%s" : %d' % (_label(status), n) for status, n in sorted(counts.items())] + ["```"])


def _publish_text(path: Path, text: str) -> None:
    """Readers see the previous complete index or the new complete index."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".%s-" % path.name, suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_index(day: date, stages: Dict[str, Dict], history: List[tuple], applied: List[Dict],
                root: Path = DAILY, learning_root: Path = learning.LEARNING) -> Path:
    """user/research/daily/<date>/README.md: every agent's file and status, and the day in charts."""
    folder = folder_for(day, root)
    progress = learning.load_progress(learning_root)
    lines = ["# Briefing %s" % day.isoformat(), "",
             "Day %d of %d. Topics: %s." % (learning.current_day(progress), learning.LAST_DAY,
                                            learning.today_topics(learning_root) or "-"), "",
             "Study notes: [today.md](../../learning/today.md). Mark the day finished with "
             "`python3 -m pipeline learn --done`.", "",
             "## Agents", "", "| Agent | Status | File |", "| --- | --- | --- |"]
    for agent in AGENTS:
        entry = stages.get("brief:%s" % agent.key) or {"status": "not run"}
        exists = (folder / agent.filename).exists()
        lines.append("| %s | %s | %s |" % (agent.key, entry["status"],
                                           "[%s](%s)" % (agent.filename, agent.filename) if exists else "-"))
    lines += ["", "## Progress", "", progress_pie(len(progress.get("done") or [])), "",
              stages_chart(stages), "", "## Applications", "", applied_chart(history), ""]
    if applied:
        lines += ["Today (%d): %s" % (len(applied), ", ".join(sorted({row["company"] or "?" for row in applied}))), ""]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "README.md"
    _publish_text(path, "\n".join(lines))
    _publish_text(root.parent / "TODAY.md",
        "# Today\n\nThe briefing for %s: [daily/%s/README.md](daily/%s/README.md)\n"
        % (day.isoformat(), day.isoformat(), day.isoformat()))
    return path


def by_key(key: str) -> Optional[Agent]:
    return next((agent for agent in AGENTS if agent.key == key), None)
