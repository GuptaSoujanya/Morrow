"""The day's study material in user/research/, written with the claude or kiro CLI.

- learning/weeks/week-NN.md: the 90-day plan, one file per week. A week file that
  is missing (or short of days) is written by the CLI when that week comes up.
- learning/today.md and learning/daily/<date>.md: today's day, cut from its week.
- user/memory/learning.json: shared durable progress (imports learning/progress.json once).
- resume-learning/NN-*.md: one study file per area of the resume; missing ones are written.
- daily/<date>/: the day's briefing, written by the agents in pipeline/briefing.py.
"""

import json
import hashlib
import logging
import os
import re
import fcntl
import tempfile
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from common import ai_cli
from common import interview_course
from common import persona as persona_module
from common.profile import ProfileError, extract_resume_text

from . import course, links
from common import paths

logger = logging.getLogger(__name__)

RESEARCH = paths.research_dir()
LEARNING = RESEARCH / "learning"
RESUME_LEARNING = RESEARCH / "resume-learning"
RESUME_TEX = paths.user_dir() / "resume" / "base.tex"
LAST_DAY = 90
_DAY = re.compile(r"^## Day (\d+)\b", re.M)
#: What the plan is for when the persona does not say.
DEFAULT_GOAL = "interview readiness in AI/ML, system design, full-stack development and DSA"
_generation_lock = threading.RLock()

Ask = Callable[[str], str]

#: A "{\bfseries Category:} items" line of the resume's Skills section: the fallback study areas.
_SKILL_LINE = re.compile(r"^\{\\bfseries (?P<category>[^}]+?):\}[ \t]*(?P<items>.*?)(?:\\par\\vspace\{\d+pt\})?[ \t]*$", re.M)


def resume_areas(resume_path: Optional[Path] = None) -> List[Tuple[str, str, str]]:
    """One study file per area of the resume: (number, slug, title).

    Current resume evidence wins over saved onboarding areas, which may belong
    to a previous upload. LaTeX categories and recognizable PDF/text skills work
    without another AI call; unknown stacks use the resume's projects directly.
    """
    resume = resume_text(resume_path)
    areas = []
    for match in _SKILL_LINE.finditer(resume):
        category, items = match.group("category").strip(), " ".join(match.group("items").split())
        if category and items:
            areas.append((persona_module.slugify(category), "%s: %s" % (category, _plain_tex(items))))
    if not areas and resume.strip():
        # Uploaded PDFs do not contain the old LaTeX skill macros. Derive areas
        # from the selected resume, never blindly reuse a previous persona.
        for category, vocabulary in (
            ("Languages", ("Python", "JavaScript", "TypeScript", "Java", "Go", "Rust", "C++", "SQL")),
            ("Full-stack engineering", ("React", "Next.js", "Vue", "Angular", "Node.js", "FastAPI", "Django", "Spring")),
            ("AI and machine learning", ("PyTorch", "TensorFlow", "LLM", "RAG", "LangChain", "Transformers", "machine learning", "AI agents")),
            ("Data and distributed systems", ("PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "Spark", "Elasticsearch")),
            ("Cloud and delivery", ("AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD")),
        ):
            found = [skill for skill in vocabulary if re.search(r"(?<![\w])" + re.escape(skill) + r"(?![\w])", resume, re.I)]
            if found:
                areas.append((persona_module.slugify(category), "%s: %s" % (category, ", ".join(found))))
        if not areas:
            areas = [("resume-projects", "Projects and experience evidenced by this resume")]
    if not resume.strip():
        areas = [(area.slug, area.title) for area in persona_module.load_persona().study_areas]
    return [("%02d" % number, slug, title) for number, (slug, title) in enumerate(areas[:99], start=1)]


def _plain_tex(text: str) -> str:
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z@]+", " ", text).replace("{", "").replace("}", "")
    return " ".join(text.replace("$", "").replace("\\", "").split())


def ask_cli(cli: Optional[str] = None) -> Ask:
    return lambda prompt: ai_cli.ask(prompt, cli)


def researchers(cli: Optional[str] = None) -> Dict[str, Ask]:
    """One ask per CLI in the team (claude and kiro by default); the first one also merges."""
    names = ai_cli.team(cli) or ["claude"]  # no CLI at all: asking fails later with a clear error
    return {name: ask_cli(name) for name in names}


# ---------------------------------------------------------------------------
# The 90-day plan
# ---------------------------------------------------------------------------


def week_of(day: int) -> int:
    return min((day - 1) // 7 + 1, 13)


def days_of(week: int) -> List[int]:
    first = (week - 1) * 7 + 1
    return list(range(first, min(first + 7, LAST_DAY + 1)))


def week_path(week: int, root: Path = LEARNING) -> Path:
    interview_course.week_spec(week)
    return content_root(root) / "weeks" / ("week-%02d.md" % week)


def content_root(root: Path = LEARNING) -> Path:
    """Keep generated shared-course lessons separate from the earlier resume plan."""
    return Path(root) / interview_course.COURSE_ID


def split_days(text: str) -> Dict[int, str]:
    """Each '## Day N:' section of a week file, heading included."""
    marks = list(_DAY.finditer(text))
    sections = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        sections[int(mark.group(1))] = text[mark.start():end].strip() + "\n"
    return sections


def syllabus_row(week: int, root: Path = LEARNING) -> str:
    """Canonical shared syllabus; private README files cannot change its topics."""
    spec = interview_course.week_spec(week)
    return '| %d | %d–%d | %s | %s |' % (week, spec['start_day'], spec['end_day'], spec['title'], spec['project'])


def _shared(root: Path) -> bool:
    """True for the user's own learning folder, whose progress lives in user/memory/learning.json."""
    resolved = root.resolve()
    if resolved == LEARNING.resolve():
        return True
    parts = resolved.parts[-3:]
    return len(parts) == 3 and parts == (paths.user_dir().name, "research", "learning")


def _repo(root: Path) -> Path:
    """The folder learning_memory resolves user/ against: three above user/research/learning."""
    return root.resolve().parent.parent.parent


def load_progress(root: Path = LEARNING) -> Dict:
    """Shared-course progress only; the earlier plan is never implicitly imported."""
    if _shared(root):
        from common import learning_memory
        data = learning_memory.transact(_repo(root))
        return {**interview_course.state_for(data), 'done': interview_course.completed_days(data)}
    path = content_root(root) / "progress.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return interview_course.state_for({})
    try:
        progress = json.loads(text)
    except ValueError as exc:
        raise ValueError("%s is not valid JSON (%s); fix or remove it" % (path, exc)) from exc
    return interview_course.state_for({'interview_course': progress})


def save_progress(progress: Dict, root: Path = LEARNING) -> None:
    if _shared(root):
        from common import learning_memory
        # Generation only establishes the start date. Completion belongs to locked
        # transactions, so a slow generator cannot overwrite a newer dashboard save.
        def update(data):
            saved = interview_course.ensure_course_state(data)
            for key, value in progress.items():
                if key not in ("done", "marked"):
                    saved.setdefault(key, value)
        learning_memory.transact(_repo(root), update)
        return
    value = {**interview_course.state_for({}), **progress}
    interview_course.state_for({'interview_course': value})
    _atomic_text(content_root(root) / "progress.json", json.dumps(value, indent=2) + '\n')


def current_day(progress: Dict) -> int:
    """The first day not marked done."""
    done = set(progress.get("done") or [])
    day = 1
    while day in done and day < LAST_DAY:
        day += 1
    return day


def mark_done(root: Path = LEARNING, today: Optional[date] = None) -> int:
    if _shared(root):
        from common import learning_memory
        result = []
        stamp = (today or date.today()).isoformat()
        def change(data):
            state = interview_course.ensure_course_state(data)
            if stamp in state.get('marked', {}):
                result.append(state['marked'][stamp])
                return
            day = interview_course.next_day(data)
            if day is not None:
                now = datetime.now().astimezone()
                at = datetime.combine(date.fromisoformat(stamp), now.timetz()).isoformat(timespec='microseconds')
                interview_course.record_completion(data, day, True, at=at)
            result.append(day or LAST_DAY)
        learning_memory.transact(_repo(root), change)
        return result[0]
    with _course_lock(root):
        progress = load_progress(root)
        stamp = (today or date.today()).isoformat()
        progress.setdefault("start", stamp)
        marked = progress.setdefault("marked", {})
        if stamp in marked:
            return int(marked[stamp])
        day = current_day(progress)
        progress["done"] = sorted(set(progress.get("done") or []) | {day})
        marked[stamp] = day
        save_progress(progress, root)
        return day


_LESSON_SHAPE = (
    "## Day N: <the canonical title>\n\n"
    "**ML / GenAI: <canonical AI/ML topic>**\n"
    "<use the detailed lesson structure below>\n\n"
    "**System Design: <canonical topic>**\n"
    "<use the detailed lesson structure below>\n\n"
    "**Full-stack: <canonical topic>**\n"
    "<use the detailed lesson structure below; explain each code line>\n\n"
    "**DSA: <canonical topic>**\n"
    "<use the detailed lesson structure below; trace a manageable input and explain scaling>\n\n"
    "**Recall**\n- 3 to 5 self-check questions with short answers after the questions\n\n"
    "**Go deeper**\n- 2 to 4 verified primary-source links (optional)\n\n"
    "Detailed lesson structure, repeated for each subject:\n"
    "### Words you need\n<plain meanings for the technical terms used in this lesson>\n"
    "### The idea\n<the concept, the engineering problem it solves and its limits>\n"
    "#### How it works\n<explain the technical mechanism, state or data changes, implementation details "
    "and boundary checks; connect each step to its purpose>\n"
    "#### System flow\n<explain the components or algorithm stages and how to read the flow>\n"
    "```mermaid\n<one valid flowchart or sequence diagram showing the actual mechanism>\n```\n"
    "<walk through the diagram with a concrete request, dataset or input>\n"
    "#### Trade-offs and failure cases\n<compare practical alternatives, explain when the approach fails "
    "and how to detect or handle those failures; include relevant boundary cases>\n"
    "### A small example\n<a worked engineering case with exact input, a trace or calculation, "
    "implementation details, checks and an exact result>\n"
    "### Your turn\n<a runnable task changing the case or a constraint; include the setup, "
    "expected output and boundary checks>\n"
    "### Check your answer\n<the actual answer and why it is correct; never just 'check your work'>\n"
    "### Interview practice\n<two interview questions specific to this day's topic, not generic study advice>\n"
    "#### Question 1\n<question>\n##### Show answer\n<reasoned answer with an example and limitation>\n"
    "##### Follow-up\n<a harder variation>\n###### Show follow-up answer\n<answer and reasoning>\n"
    "#### Question 2\n<a practical debugging or design case>\n##### Show answer\n<reasoned answer>\n"
    "##### Follow-up\n<a changed constraint>\n###### Show follow-up answer\n<answer and reasoning>\n"
    "#### Common mistake\n<a specific mistake and why it fails>\n"
    "#### Work on your own\n<a practical drill with clear checks>\n"
    "End each subject with a horizontal rule (---) before the next subject."
)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.lesson-', delete=False) as output:
            name = output.name
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


@contextmanager
def _course_lock(root):
    folder = content_root(root)
    folder.mkdir(parents=True, exist_ok=True)
    with _generation_lock, (folder / '.generation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _context_excerpt(section, day):
    """Keep each studied subject in context even when lessons become longer."""
    from markdown_it import MarkdownIt
    tokens, lines = MarkdownIt('commonmark').parse(section), section.splitlines(keepends=True)
    boundaries = []
    for index, token in enumerate(tokens[:-1]):
        if token.type not in ('heading_open', 'paragraph_open') or token.map is None:
            continue
        text = tokens[index + 1].content
        if ((token.type == 'heading_open' and re.match(r'^\d+\.\s', text))
                or (token.type == 'paragraph_open' and re.match(r'^\*\*(ML / GenAI|System Design|Full-stack|DSA):', text))):
            boundaries.append(token.map[0])
    if not boundaries:
        return section[:4200]
    spec = interview_course.day_spec(day)
    summary = f"Day {day}: {spec['title']}\n" + '\n'.join(item['title'] + ': ' + item['topic'] for item in spec['topics'])
    excerpts = []
    for index, start in enumerate(boundaries[:4]):
        stop = boundaries[index + 1] if index + 1 < len(boundaries) else len(lines)
        excerpts.append(''.join(lines[start:stop])[:900])
    return summary + '\n\n' + '\n\n'.join(excerpts)


def _prior_learning(day: int, root: Path) -> Tuple[str, List[int]]:
    """Only completed earlier lessons are evidence; unread files are excluded."""
    completed = sorted(number for number in load_progress(root).get('done', []) if number < day)
    parts = []
    # The last three actual readings keep prompts bounded. Earlier completed
    # topics are named, not represented as lessons the learner has mastered.
    for number in completed[-3:]:
        path = week_path(week_of(number), root)
        try:
            section = split_days(path.read_text(encoding='utf-8')).get(number, '')
        except OSError:
            section = ''
        metadata = _read_metadata(path)
        sources = metadata.get('day_sources', {})
        source = sources.get(str(number), {}) if isinstance(sources, dict) else {}
        if (not section or not interview_course.is_current(metadata) or not isinstance(source, dict)
                or source.get('teaching_version') != interview_course.TEACHING_VERSION):
            try:
                from common.interview_lessons import lesson
                public_root = course.COURSE if course.COURSE.is_absolute() else Path(__file__).resolve().parents[1] / course.COURSE
                section = lesson(number, public_root)['text']
            except (OSError, ValueError):
                # Isolated workspaces may omit the public reference chapters.
                # The canonical material is still evidence, never private files.
                spec = interview_course.day_spec(number)
                section = ('Day %d: %s\n%s\n%s\n' %
                           (number, spec['title'], spec['explanation'], spec['example']))
                section += '\n'.join(item['title'] + ': ' + item['topic'] for item in spec['topics'])
        parts.append(_context_excerpt(section, number))
    summary = ('Completed earlier course days: ' + ', '.join(map(str, completed))
               if completed else 'No earlier course days are marked complete. Start with the basics.')
    summary += '\nCompletion records show reading, not proof of mastery. Begin with a brief recall check.'
    return summary + ('\n\nPreviously completed material:\n' + '\n\n'.join(parts) if parts else ''), completed


def learning_context(day: int, root: Path = LEARNING) -> str:
    return _prior_learning(day, root)[0]


def _context_signature(day, root):
    text, completed = _prior_learning(day, root)
    return hashlib.sha256(text.encode('utf-8')).hexdigest(), completed


def _teaching_rules():
    return (
        "This is the same fixed course for everyone. Do not use a resume or change the syllabus. "
        "Use the learner's completed reading only to connect ideas and choose a short recap. Never assume "
        "an unread or future lesson has been studied. Teach in simple, clear English: define each new term "
        "before using it, avoid unexplained jargon, show every important step, and use small concrete examples. "
        "The learner has explicitly chosen VERY SIMPLE ENGLISH and is a working developer with about "
        "three years of experience. Keep the language accessible while teaching real interview and engineering depth. "
        "Use short, direct sentences and one connected idea per paragraph. Explain an abbreviation before using it. "
        "Do not replace one difficult word with another difficult word. Use realistic engineering examples, "
        "such as request handling, feature preparation or a study-tracker API, with traceable inputs and results. "
        "Do not paste a reference chapter, a wall of code, a list of tools, or a diagram without an explanation. "
        "Use as much runnable code as the mechanism needs, organize it into explained sections, "
        "and explain every line in everyday words. Do not truncate a working example to fit a line limit. "
        "Introduce a formula in words before showing symbols. Start with the smallest useful example, "
        "then show how the reasoning changes at a realistic scale or under a harder constraint. "
        "Aim for 800 to 1400 useful words per subject as a guideline, not a hard word-count rule. "
        "Use the space for mechanisms, implementation decisions, worked traces or calculations and boundary checks, "
        "not repeated definitions or filler. Inside each subject's 'The idea', include exactly these level-four "
        "headings: 'How it works', 'System flow', and 'Trade-offs and failure cases'. Give substantive explanatory "
        "prose under each. Under 'System flow', include a valid fenced mermaid flowchart or sequence diagram "
        "and explain its components, connections and one complete path. Use plain labels, an accTitle and "
        "accDescr when helpful, and no HTML, external assets, links or configuration directives in diagrams. "
        "Add a second worked real-world case, two specific interview questions, reasoned answers, harder follow-ups, "
        "a common mistake and a practical drill. Simple English must not mean shallow content. "
        "Every explanation must say what it is, why it matters, how it works and how to explain it in an interview. "
        "Give runnable exercises with expected output, hints and a way to check the answer. "
        "Plan a flexible 3 to 4 hours for reading, implementation, DSA and recall. Use the canonical session "
        "estimates as guidance, not a time cap; the learner may split the work across sessions. "
        "News, research papers and GitHub exploration are "
        "additional learning, never prerequisites for finishing this session. "
        "Search current official documentation and original papers; link only sources actually verified. "
        "Do not promise a job or claim the learner has mastered a topic merely by reading. "
        "Output Markdown only. Use exactly the requested Day headings and no other level-two headings. No emojis."
    )


def week_prompt(week: int, root: Path = LEARNING) -> str:
    spec = interview_course.week_spec(week)
    return '\n\n'.join([
        'Write week %d of the shared 90-day interview course: %s.' % (week, spec['title']),
        _teaching_rules(),
        'Fixed syllabus (do not reorder or substitute topics):\n' + json.dumps(spec, ensure_ascii=False),
        learning_context(spec['start_day'], root),
        "Start with '# Week %d: %s'. Then exactly %d sections, Day %d to Day %d. "
        "Each day follows this shape:\n\n%s" %
        (week, spec['title'], len(spec['days']), spec['start_day'], spec['end_day'], _LESSON_SHAPE),
        'The final day of this week is review, a practical deliverable and an interview rehearsal. '
        'The weekly deliverable is: ' + spec['project'],
    ])


def day_prompt(day: int, root: Path = LEARNING) -> str:
    spec = interview_course.day_spec(day)
    return '\n\n'.join([
        'Write only day %d of the shared 90-day interview course.' % day,
        _teaching_rules(),
        'Fixed lesson specification:\n' + json.dumps(spec, ensure_ascii=False),
        learning_context(day, root),
        'Output exactly one section starting with "## Day %d: %s". Follow this shape:\n\n%s' %
        (day, spec['title'], _LESSON_SHAPE),
    ])


def _checked_sections(text, wanted):
    numbers = [int(match[1]) for match in _DAY.finditer(text)]
    if set(numbers) != set(wanted) or len(numbers) != len(set(numbers)):
        raise ai_cli.AIError('the lesson output must contain exactly day(s) %s' % sorted(wanted))
    if re.search(r'^## (?!Day \d+\b)', text, re.M):
        raise ai_cli.AIError('the lesson output has an unexpected level-two heading')
    sections = split_days(text)
    for day, section in sections.items():
        required = ('**ML / GenAI:', '**System Design:', '**Full-stack:', '**DSA:', '**Recall**', '**Go deeper**')
        missing = [part.strip('*:') for part in required if part not in section]
        if missing:
            raise ai_cli.AIError('day %d is missing %s' % (day, ', '.join(missing)))
        _check_teaching_steps(day, section)
    return sections


def _check_teaching_steps(day, section):
    """Require four real lessons, excluding text that only appears in code."""
    from markdown_it import MarkdownIt
    tokens = MarkdownIt('commonmark').parse(section)

    def has_explanation(start, stop):
        # Heading text, fenced examples, image alt text and placeholders cannot
        # stand in for an explanation. This is a presence check, not a word-count
        # target or a claim to judge the technical quality of generated prose.
        for index in range(start, stop):
            token = tokens[index]
            if token.type != 'inline' or index == 0 or tokens[index - 1].type != 'paragraph_open':
                continue
            text = ' '.join(child.content for child in token.children or [] if child.type == 'text').strip()
            if (re.search(r'[^\W\d_]', text)
                    and not re.fullmatch(r'(?:todo|tbd|n/?a|coming soon|to be written|see above|placeholder)[.!\s]*', text, re.I)):
                return True
        return False

    def has_flow_diagram(start, stop):
        for token in tokens[start:stop]:
            if token.type != 'fence' or token.info.strip() != 'mermaid':
                continue
            source = '\n'.join(line for line in token.content.splitlines()
                               if not line.lstrip().startswith('%%')).strip()
            declaration = re.match(r'(?:(?:flowchart|graph)\s+(?:TB|TD|BT|LR|RL)\b|sequenceDiagram\b)', source)
            if declaration and re.search(r'\w', source[declaration.end():]):
                return True
        return False

    subjects = {'ML / GenAI', 'System Design', 'Full-stack', 'DSA'}
    boundaries = []
    for index, token in enumerate(tokens[:-1]):
        if token.type != 'paragraph_open' or tokens[index + 1].type != 'inline':
            continue
        line = tokens[index + 1].content
        possible = re.match(r'^\*\*(ML / GenAI|System Design|Full-stack|DSA):', line)
        if possible:
            if not re.match(r'^\*\*(ML / GenAI|System Design|Full-stack|DSA):[^\n*]+\*\*(?:\s|$)', line):
                raise ai_cli.AIError('day %d has a malformed subject label' % day)
            boundaries.append((possible[1], index))
        elif re.match(r'^\*\*(Recall|Go deeper)\*\*', line):
            boundaries.append(('', index))
    names = [name for name, _ in boundaries if name]
    if len(names) != 4 or set(names) != subjects:
        raise ai_cli.AIError('day %d must contain exactly four subject lessons' % day)
    needed = ['Words you need', 'The idea', 'A small example', 'Your turn', 'Check your answer', 'Interview practice']
    for position, (name, start) in enumerate(boundaries):
        if not name:
            continue
        end = boundaries[position + 1][1] if position + 1 < len(boundaries) else len(tokens)
        headings = [(tokens[i + 1].content.strip(), i) for i in range(start, end - 1)
                    if tokens[i].type == 'heading_open' and tokens[i].tag == 'h3']
        if [title for title, _ in headings if title in needed] != needed:
            raise ai_cli.AIError('day %d is missing or reorders the lesson steps: words, idea, example, task, answer and interview practice' % day)
        for i, (title, heading) in enumerate(headings):
            if title not in needed:
                continue
            stop = headings[i + 1][1] if i + 1 < len(headings) else end
            # Require explanatory text, not an empty heading or a bare code dump.
            if not any(t.type == 'inline' and re.search(r'\w', t.content)
                       for t in tokens[heading + 3:stop]):
                raise ai_cli.AIError('day %d has empty lesson steps: %s' % (day, title))
        idea_start = next(i for title, i in headings if title == 'The idea')
        idea_end = next(i for title, i in headings if i > idea_start)
        depth_titles = ['How it works', 'System flow', 'Trade-offs and failure cases']
        depth_heads = [(tokens[i + 1].content.strip(), i) for i in range(idea_start + 3, idea_end - 1)
                       if tokens[i].type == 'heading_open']
        required_depth = [(title, i) for title, i in depth_heads if title in depth_titles]
        if ([title for title, _ in required_depth] != depth_titles
                or any(tokens[i].tag != 'h4' for _, i in required_depth)):
            raise ai_cli.AIError('day %d needs level-four depth sections inside The idea for %s: %s' %
                                 (day, name, ', '.join(depth_titles)))
        for title, depth_start in required_depth:
            depth_end = next((i for _, i in depth_heads if i > depth_start and tokens[i].tag == 'h4'), idea_end)
            if not has_explanation(depth_start + 3, depth_end):
                raise ai_cli.AIError('day %d has an empty depth explanation for %s: %s' % (day, name, title))
            if title == 'System flow' and not has_flow_diagram(depth_start + 3, depth_end):
                raise ai_cli.AIError('day %d needs a nonempty fenced mermaid flowchart or sequence diagram in System flow for %s' %
                                     (day, name))
        interview_start = next(i for title, i in headings if title == 'Interview practice')
        # The renderer closes answer disclosures at sibling or higher headings.
        # A deeper Follow-up heading would hide its question inside Show answer.
        interview_levels = {'Question 1': 'h4', 'Question 2': 'h4',
                            'Show answer': 'h5', 'Follow-up': 'h5',
                            'Show follow-up answer': 'h6'}
        for heading in range(interview_start + 1, end - 1):
            if tokens[heading].type != 'heading_open':
                continue
            title = tokens[heading + 1].content.strip()
            expected_level = interview_levels.get(title)
            if expected_level and tokens[heading].tag != expected_level:
                raise ai_cli.AIError('day %d has an invalid interview heading level for %s: use %s' %
                                     (day, title, expected_level))
        question_heads = [i for i in range(interview_start, end - 1)
                          if tokens[i].type == 'heading_open' and tokens[i].tag == 'h4'
                          and tokens[i + 1].content.strip() in ('Question 1', 'Question 2')]
        if [tokens[i + 1].content.strip() for i in question_heads] != ['Question 1', 'Question 2']:
            raise ai_cli.AIError('day %d needs two interview questions per subject' % day)
        for position, start_question in enumerate(question_heads):
            stop = question_heads[position + 1] if position + 1 < len(question_heads) else end
            required_answers = ['Show answer', 'Follow-up', 'Show follow-up answer']
            all_heads = [i for i in range(start_question + 1, stop) if tokens[i].type == 'heading_open']
            answer_heads = [(tokens[i + 1].content.strip(), i) for i in range(start_question, stop - 1)
                            if tokens[i].type == 'heading_open' and tokens[i].tag in ('h5', 'h6')]
            first_answer = all_heads[0] if all_heads else stop
            if not any(t.type == 'inline' and re.search(r'\w', t.content)
                       for t in tokens[start_question + 3:first_answer]):
                raise ai_cli.AIError('day %d has an empty interview question' % day)
            if [title for title, _ in answer_heads if title in required_answers] != required_answers:
                raise ai_cli.AIError('day %d needs interview answers and follow-up reasoning' % day)
            for title, answer_start in answer_heads:
                if title not in required_answers:
                    continue
                answer_stop = next((i for i in all_heads if i > answer_start), stop)
                if not any(t.type == 'inline' and re.search(r'\w', t.content)
                           for t in tokens[answer_start + 3:answer_stop]):
                    raise ai_cli.AIError('day %d has an empty interview answer' % day)


def _source_valid(day, section, metadata, signature):
    sources = metadata.get('day_sources', {})
    source = sources.get(str(day), {}) if isinstance(sources, dict) else {}
    if not isinstance(source, dict):
        return False
    return (interview_course.is_current(metadata)
            and source.get('teaching_version') == interview_course.TEACHING_VERSION
            and source.get('context_sha256') == signature
            and source.get('content_sha256') == hashlib.sha256(section.encode('utf-8')).hexdigest())


def _selected_days_prompt(week, days, root):
    if len(days) == 1:
        return day_prompt(days[0], root)
    return '\n\n'.join([
        'Prepare only the unfinished days of week %d of the shared interview course.' % week,
        _teaching_rules(),
        'Fixed lesson specifications:\n' + json.dumps([interview_course.day_spec(day) for day in days], ensure_ascii=False),
        learning_context(min(days), root),
        "Start with '# Week %d: %s'. Output exactly these day sections: %s. "
        "Do not output completed days. Each section follows this shape:\n\n%s" %
        (week, interview_course.week_spec(week)['title'], ', '.join('Day %d' % day for day in days), _LESSON_SHAPE),
    ])


def _bundled_section(day):
    from common.interview_lessons import lesson
    public_root = course.COURSE if course.COURSE.is_absolute() else Path(__file__).resolve().parents[1] / course.COURSE
    # This changes only Markdown heading levels outside code fences, preserving
    # the exact reading the learner completed instead of asking AI to replace it.
    return course._demote(lesson(day, public_root)['text'], 2).strip() + '\n'


def _ensure_lessons(week, wanted, ask, root, prompt):
    path = week_path(week, root)
    metadata = _read_metadata(path)
    try:
        previous = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        previous = ''
    old_sections = split_days(previous)
    completed = set(load_progress(root).get('done', []))
    signatures = {day: _context_signature(day, root) for day in wanted}
    if all(day in old_sections and interview_course.is_current(metadata)
           and (day in completed or _source_valid(day, old_sections[day], metadata, signatures[day][0]))
           for day in wanted):
        return path
    required = [day for day in wanted if day not in completed
                and not (day in old_sections and _source_valid(day, old_sections[day], metadata, signatures[day][0]))]
    bundled = {day: _bundled_section(day) for day in wanted if day in completed
               and not (day in old_sections and interview_course.is_current(metadata))}
    sections = dict(bundled)
    if required:
        logger.info('Generating study content for %s with the AI CLI; not saved yet.', path)
        prefix = '# Week' if len(required) > 1 else '## Day'
        if required != list(wanted):
            prompt = _selected_days_prompt(week, required, root)
        text = links.linkify(ai_cli.markdown_from(ask(prompt), prefix))
        sections.update(_checked_sections(text, required))
    with _course_lock(root):
        latest_done = set(load_progress(root).get('done', []))
        if any(_context_signature(day, root) != signatures[day] for day in wanted):
            raise ai_cli.AIError('completed reading changed during lesson generation; retry to build on the latest progress')
        if any(day not in latest_done for day in bundled):
            raise ai_cli.AIError('a completed lesson was reopened during preparation; retry with the latest progress')
        metadata = _read_metadata(path)
        try:
            previous = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            previous = ''
        merged = split_days(previous) if interview_course.is_current(metadata) else {}
        saved_sources = metadata.get('day_sources', {})
        sources = dict(saved_sources) if interview_course.is_current(metadata) and isinstance(saved_sources, dict) else {}
        for day in sections:
            # Preserve a lesson completed or saved by another request while the
            # AI was running. Generation never writes completion state.
            if day in merged and (day in latest_done or _source_valid(day, merged[day], metadata, signatures[day][0])):
                continue
            if day in latest_done and day not in completed:
                raise ai_cli.AIError('this lesson was completed during generation; retry to prepare the next day')
            merged[day] = sections[day]
            sources[str(day)] = {'context_sha256': signatures[day][0], 'completed_days': signatures[day][1],
                                 'teaching_version': interview_course.TEACHING_VERSION,
                                 'source': 'bundled' if day in bundled else 'generated',
                                 'content_sha256': hashlib.sha256(sections[day].encode('utf-8')).hexdigest()}
        spec = interview_course.week_spec(week)
        saved = '# Week %d: %s\n\n%s\n\n' % (week, spec['title'], interview_course.COURSE_TITLE)
        saved += '\n'.join(merged[day] for day in sorted(merged))
        if previous and previous != saved:
            _archive(path, previous)
        _atomic_text(path, saved)
        _write_metadata(path, {'course_id': interview_course.COURSE_ID, 'course_version': interview_course.COURSE_VERSION,
                               'day_sources': sources})
    logger.info('Saved study content to %s.', path)
    return path


def ensure_week(week: int, ask: Ask, root: Path = LEARNING) -> Path:
    """Prepare a whole shared-syllabus week explicitly, keeping completed lessons."""
    return _ensure_lessons(week, days_of(week), ask, root, week_prompt(week, root))


def ensure_day(day: int, ask: Ask, root: Path = LEARNING) -> Path:
    """Prepare only the requested day using actual prior completed reading."""
    interview_course.day_spec(day)
    return _ensure_lessons(week_of(day), [day], ask, root, day_prompt(day, root))


def write_today(ask: Ask, root: Path = LEARNING, today: Optional[date] = None) -> Tuple[int, Path]:
    """Prepare the next unread course day; a missed date never skips a lesson."""
    today = today or date.today()
    with _course_lock(root):
        progress = load_progress(root)
        if 'start' not in progress:
            progress['start'] = today.isoformat()
            save_progress(progress, root)
    day = current_day(progress)
    complete = len(set(progress.get('done', []))) == LAST_DAY
    week = week_of(day)
    if complete:
        section = ('## Day 90: Course complete\n\nYou have completed all 90 course days. '
                   'Use your practice results to choose a review topic and continue mock interviews.\n')
        quoted, source = '', {}
        week_file = week_path(week, root)
    else:
        week_file = ensure_day(day, ask, root)
        section = split_days(week_file.read_text(encoding='utf-8'))[day]
        source = _read_metadata(week_file).get('day_sources', {}).get(str(day), {})
    course_info = interview_course.course_info()
    session = ', '.join('%s %d min' % (part['title'], part['minutes'])
                        for part in course_info['daily_session'])
    head = ('# %s: Day %d of %d (week %d)\n\n%s\n\n%s\n\n'
            'Suggested time by subject: %s.\n\n') % (
            today.isoformat(), day, LAST_DAY, week, interview_course.COURSE_TITLE,
            course_info['study_note'], session)
    tail = ("\nAdditional learning: today's research papers, tech news and GitHub discoveries. "
            'These do not change completion of your course lesson.\n')
    daily = content_root(root) / 'daily' / ('%s.md' % today.isoformat())
    for path in (daily, content_root(root) / 'today.md'):
        body = links.relink(section, week_file.parent, path.parent)
        quoted = ('## From the course\n\nRevisit the topics you found difficult.\n' if complete else
                  course.reading(day, section, week_file.parent, path.parent, content_root(root)))
        content = head + body + '\n' + quoted + tail
        with _course_lock(root):
            if current_day(load_progress(root)) != day:
                raise ai_cli.AIError('course progress changed before publishing today; retry to prepare the next day')
            if path == daily and path.exists():
                previous = path.read_text(encoding='utf-8')
                if previous != content:
                    _archive(path, previous)
            _atomic_text(path, content)
            _write_metadata(path, {'course_id': interview_course.COURSE_ID,
                                   'course_version': interview_course.COURSE_VERSION,
                                   'plan_day': day, 'week': week, 'source': source})
    return day, daily


# ---------------------------------------------------------------------------
# Resume study files
# ---------------------------------------------------------------------------


# Email, phone, address and profile links: any line holding one is dropped.
_CONTACT_LINE = re.compile(
    r"@|\+\d|\\href\{(?:mailto|tel)|\b(?i:phone|mobile|tel|address)\b"
    r"|\b\d{5}[ -]?\d{5}\b|\b\d{3}[ -]\d{3}[ -]\d{4}\b|\b[A-Z]{2},?\s+\d{6}\b"
    r"|(?i:linkedin\.com/in/|github\.com/)"
)


def selected_resume_path(path: Optional[Path] = None) -> Path:
    """Explicit callers win; the runner's selected input wins over legacy data."""
    if path is not None:
        return Path(path).expanduser()
    selected = os.getenv("RESUME_PATH", "").strip()
    return paths.resolve(selected, Path.cwd()) if selected else RESUME_TEX.expanduser()


def resume_fingerprint(path: Optional[Path] = None) -> str:
    """Public provenance contract: SHA256 of the selected resume's raw bytes."""
    try:
        return hashlib.sha256(selected_resume_path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _read_metadata(path: Path) -> Dict:
    try:
        data = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_metadata(path: Path, data: Dict) -> None:
    _atomic_text(path.with_suffix(".meta.json"), json.dumps({"schema_version": 1, **data}, indent=2) + "\n")


def _archive(path: Path, text: str) -> None:
    """A content-addressed copy keeps previous lessons and provenance reviewable."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    archived = path.parent / "archive" / path.stem / (digest + ".md")
    archived.parent.mkdir(parents=True, exist_ok=True)
    if not archived.exists():
        archived.write_text(links.relink(text, path.parent, archived.parent), encoding="utf-8")
        _write_metadata(archived, _read_metadata(path))


def resume_text(path: Optional[Path] = None) -> str:
    path = selected_resume_path(path)
    try:
        # Keep LaTeX lines intact: redaction and existing briefing skill
        # selectors depend on their original structure. PDFs need extraction.
        text = extract_resume_text(str(path)) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
    except ProfileError as exc:
        raise ai_cli.AIError(str(exc)) from exc
    except (OSError, UnicodeError) as exc:
        if os.getenv("RESUME_PATH") or path != RESUME_TEX:
            raise ai_cli.AIError("could not read the selected resume at %s" % path) from exc
        return ""
    # Contact lines stay out of the prompt.
    return "\n".join(line for line in text.splitlines() if not _CONTACT_LINE.search(line))


def missing_resume_areas(root: Path = RESUME_LEARNING, resume_path: Optional[Path] = None) -> List[Tuple[str, str, str]]:
    return [area for area in resume_areas(resume_path)
            if current_resume_area(area[0], area[1], root, resume_path) is None]


def current_resume_area(number: str, slug: str, root: Path = RESUME_LEARNING,
                        resume_path: Optional[Path] = None) -> Optional[Path]:
    fingerprint = resume_fingerprint(resume_path)
    for path in sorted(root.glob("%s-%s*.md" % (number, slug))):
        metadata = _read_metadata(path)
        if metadata.get("resume_sha256") == fingerprint and metadata.get("area_slug") == slug:
            return path
    return None


def _resume_area_path(root: Path, number: str, slug: str, fingerprint: str) -> Path:
    path = root / ("%s-%s.md" % (number, slug))
    if path.exists():
        # Preserve original paths: bookmarks and completion refer to them.
        path = root / ("%s-%s-%s.md" % (number, slug, fingerprint[:12]))
        revision = 2
        while path.exists():
            path = root / ("%s-%s-%s-%d.md" % (number, slug, fingerprint[:12], revision))
            revision += 1
    return path


def resume_prompt(area: str, resume: str) -> str:
    return "\n\n".join([
        "Write a study file for a software engineer preparing interviews on one area of their own "
        "resume: %s." % area,
        "Their resume:\n" + resume[:8000],
        "Search the web for accurate, current material and link real pages.",
        "Output markdown only. Start with '# <area title>', then these sections in order: "
        "## What it is, ## How you used it (only what the resume says, never invent numbers), "
        "## Core concepts, ## Interview questions and answers (8 to 12), ## Hands-on exercise, "
        "## Read next. No contact details, no emojis.",
    ])


def fill_resume_learning(ask: Ask, root: Path = RESUME_LEARNING, resume_path: Optional[Path] = None) -> List[Path]:
    """Write every missing resume study file, then the index; the files written."""
    resume_path = selected_resume_path(resume_path)
    fingerprint = resume_fingerprint(resume_path)
    resume = resume_text(resume_path)
    if not resume.strip():
        # Without the resume the model would invent "how you used it".
        raise ai_cli.AIError("could not read the resume at %s" % resume_path)
    written = []
    for number, slug, area in missing_resume_areas(root, resume_path):
        logger.info("Writing resume study file %s-%s with the AI CLI.", number, slug)
        text = links.linkify(ai_cli.markdown_from(ask(resume_prompt(area, resume)), "# "))
        if "## Interview questions" not in text:
            raise ai_cli.AIError("the %s file it wrote has no interview questions section" % slug)
        if resume_fingerprint(resume_path) != fingerprint:
            raise ai_cli.AIError("the selected resume changed during generation; retry with the current resume")
        path = _resume_area_path(root, number, slug, fingerprint)
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _write_metadata(path, {"resume_sha256": fingerprint, "area_slug": slug})
        written.append(path)
    write_resume_index(root, fingerprint)
    return written


def write_resume_index(root: Path = RESUME_LEARNING, fingerprint: str = "") -> Path:
    lines = ["# Resume learning", "", "One file per area of the resume: what it is, how you used it, "
             "core concepts, interview Q&A, a hands-on exercise, what to read next.", ""]
    for path in sorted(root.glob("[0-9][0-9]-*.md")):
        content = path.read_text(encoding="utf-8").splitlines()
        title = (content[0].lstrip("# ").strip() if content else "") or path.stem
        source = _read_metadata(path).get("resume_sha256", "")
        label = "" if source and source == fingerprint else " — previous resume" if source else " — source resume untracked"
        lines.append("- [%s](%s)%s" % (title, path.name, label))
    index = root / "README.md"
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index


def today_topics(root: Path = LEARNING) -> str:
    """Canonical topics for the next unread course day, including before fetch."""
    spec = interview_course.day_spec(current_day(load_progress(root)))
    return '; '.join(item['title'] + ': ' + item['topic'] for item in spec['topics'])
