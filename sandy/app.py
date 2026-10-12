"""The Sandy screen: pick a task on the left, set its options, run it, watch it work."""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    MarkdownViewer,
    OptionList,
    RichLog,
    Select,
    Static,
    Switch,
    TextArea,
    Tree,
)
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from . import state
from .state import Command, Module

SECTIONS = [
    ("today", "⌂", "Today"),
    ("naukri", "▶", "Apply on Naukri"),
    ("sites", "◫", "Company sites"),
    ("profile", "↻", "Naukri profile"),
    ("linkedin", "✦", "LinkedIn post"),
    ("resume", "✎", "Tailor resume"),
    ("reports", "▤", "Reports"),
    ("study", "◉", "Study"),
    ("todo", "✓", "Your to-dos"),
    ("setup", "≡", "Setup"),
]

ANSWER_MODES = [
    ("As set in .env", ""),
    ("auto - submit answers grounded in your files", "auto"),
    ("propose - log the answers, submit none", "propose"),
    ("ask - skip LLM answers, leave them for you", "ask"),
]

LINKEDIN_CHOICES = [
    ("Draft a post (nothing saved)", "dry-run"),
    ("Save a draft, send it on Telegram", "propose"),
    ("Publish the draft on LinkedIn", "post"),
    ("Do today's scheduled step", "if-due"),
]


class Panel(VerticalScroll, can_focus=False):
    """One section's page; Tab goes straight to its first field."""


def field(label: str, widget: Widget) -> Horizontal:
    return Horizontal(Label(label, classes="field-label"), widget, classes="field")


def toggle(id: str, text: str, value: bool = False) -> Horizontal:
    return Horizontal(Switch(value=value, id=id), Label(text, classes="toggle-label"), classes="toggle")


def buttons(*items: Button) -> Horizontal:
    return Horizontal(*items, classes="buttons")


def heading(title: str, about: str) -> Tuple[Static, Static]:
    return Static(title, classes="title"), Static(about, classes="about")


def elapsed(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}:{seconds:02d}"


def bullet_list(items: List[str], empty: str, more: int = 0) -> Text:
    if not items:
        return Text(f"✓ {empty}", style="green")
    text = Text()
    for i, item in enumerate(items):
        text.append("• ", style="yellow")
        text.append(item)
        if i < len(items) - 1 or more:
            text.append("\n")
    if more:
        text.append(f"  … and {more} more", style="dim")
    return text


def progress(done: int, total: int, width: int = 28) -> Text:
    filled = round(width * done / total) if total else 0
    return Text.assemble(
        ("━" * filled, "bold green"), ("━" * (width - filled), "dim"), (f"  {done} of {total} read", "")
    )


class EditorScreen(Screen):
    """Edit one of your files right here; ctrl+s saves."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "close", "Close"),
    ]

    def __init__(self, path: Path, line: Optional[int] = None) -> None:
        super().__init__()
        self.path = path
        self.line = line
        self.saved = path.read_text(encoding="utf-8") if path.exists() else ""
        self.warned = False

    def compose(self) -> ComposeResult:
        name = str(self.path.relative_to(state.APPLY)) if state.APPLY in self.path.parents else str(self.path)
        yield Static(
            Text.assemble(("✎  ", "bold"), (name, "bold"), ("      ctrl+s save  ·  esc close", "dim")),
            id="editor-title",
        )
        yield TextArea(self.saved, id="editor", show_line_numbers=True, soft_wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        area = self.query_one(TextArea)
        area.focus()
        if self.line and self.line <= area.document.line_count:
            row = self.line - 1
            area.cursor_location = (row, len(area.document.get_line(row)))
            self.call_after_refresh(area.scroll_cursor_visible, center=True)

    def action_save(self) -> None:
        text = self.query_one(TextArea).text
        self.path.write_text(text, encoding="utf-8")
        self.saved = text
        self.warned = False
        self.notify(f"Saved {self.path.name}", title="Saved")

    def action_close(self) -> None:
        if self.query_one(TextArea).text != self.saved and not self.warned:
            self.warned = True
            self.notify("Unsaved changes. ctrl+s saves; esc again throws them away.", severity="warning")
            return
        self.dismiss(None)


class ReaderScreen(Screen):
    """Read a Markdown file (a report) full screen."""

    BINDINGS = [Binding("escape,q", "close", "Close")]

    def __init__(self, title: str, markdown: str) -> None:
        super().__init__()
        self.title_text = title
        self.markdown = markdown

    def compose(self) -> ComposeResult:
        yield Static(Text.assemble(("▤  ", "bold"), (self.title_text, "bold"), ("      esc close", "dim")), id="reader-title")
        yield MarkdownViewer(self.markdown, show_table_of_contents=True, id="reader")
        yield Footer()

    def action_close(self) -> None:
        self.dismiss(None)


class CourseViewer(MarkdownViewer):
    """A Markdown viewer that hands its links to the screen, so they stay inside the course."""

    class Follow(Message):
        def __init__(self, href: str) -> None:
            super().__init__()
            self.href = href

    async def _on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        message.prevent_default()
        message.stop()
        self.post_message(self.Follow(message.href))


class StudyScreen(Screen):
    """Read the course here, one module at a time."""

    BINDINGS = [
        Binding("escape,q", "close", "Close"),
        Binding("n", "turn(1)", "Next"),
        Binding("p", "turn(-1)", "Previous"),
        Binding("m", "mark", "Mark read"),
        Binding("t", "contents", "Contents"),
        Binding("w", "web", "On the site"),
        Binding("b", "back", "Back"),
    ]

    def __init__(self, modules: List[Module], index: int) -> None:
        super().__init__()
        self.modules = modules
        self.page = modules[index].file
        self.history: List[Path] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="study-title")
        yield CourseViewer(open_links=False, id="study-reader")
        yield Footer()

    def on_mount(self) -> None:
        self.go(self.page, remember=False)

    @property
    def module(self) -> Optional[Module]:
        return next((m for m in self.modules if m.file == self.page), None)

    def show_title(self, loading: bool = False) -> None:
        module = self.module
        text = Text("◉  ", style="bold")
        if module:
            read = module.path in state.studied()
            text.append(f"{module.track}  ›  ", style="dim")
            text.append(module.title, style="bold")
            text.append(f"    {self.modules.index(module) + 1} of {len(self.modules)}", style="dim")
            text.append("    ✓ read" if read else "    ○ not read yet", style="bold green" if read else "dim")
        else:
            text.append(self.page.name, style="bold")
        if loading:
            text.append("    loading…", style="italic dim")
        self.query_one("#study-title", Static).update(text)

    def go(self, path: Path, anchor: str = "", remember: bool = True) -> None:
        if remember:
            self.history.append(self.page)
        self.page = path
        self.show_title(loading=True)
        self.run_worker(self.load(path, anchor), exclusive=True, group="page")

    async def load(self, path: Path, anchor: str) -> None:
        viewer = self.query_one(CourseViewer)
        await viewer.document.load(path)
        viewer.scroll_home(animate=False)
        if anchor:
            viewer.document.goto_anchor(anchor)
        viewer.document.focus()
        self.show_title()

    @on(CourseViewer.Follow)
    def follow(self, event: CourseViewer.Follow) -> None:
        href = event.href
        if "://" in href or href.startswith("mailto:"):
            self.app.open_url(href)
            return
        target, _, anchor = href.partition("#")
        if not target:
            self.query_one(CourseViewer).document.goto_anchor(anchor)
            return
        path = (self.page.parent / target).resolve()
        if path.is_dir():
            path = path / "README.md"
        if state.COURSE not in path.parents or not path.is_file():
            self.notify(f"Can't find {target}", severity="warning")
        elif path.name in state.BROWSER_ONLY:
            self.app.open_on_site(path.relative_to(state.COURSE).with_suffix("").as_posix())
        elif path.suffix == ".md":
            self.go(path, anchor)
        else:
            self.notify(f"{target} can't be shown here", severity="warning")

    def action_turn(self, step: int) -> None:
        module = self.module
        index = self.modules.index(module) + step if module else 0
        if not 0 <= index < len(self.modules):
            self.notify("That was the last module." if step > 0 else "This is the first module.")
            return
        self.go(self.modules[index].file)

    def action_mark(self) -> None:
        module = self.module
        if module is None:
            self.notify("Only the modules in the course menu can be marked read.", severity="warning")
            return
        done = module.path not in state.studied()
        state.mark_studied(module.path, done)
        self.show_title()
        self.notify(f"{module.title}: {'marked read' if done else 'marked not read'}")

    def action_contents(self) -> None:
        viewer = self.query_one(CourseViewer)
        viewer.show_table_of_contents = not viewer.show_table_of_contents

    def action_web(self) -> None:
        self.app.open_on_site(self.page.relative_to(state.COURSE).with_suffix("").as_posix())

    def action_back(self) -> None:
        if not self.history:
            self.notify("Nothing to go back to.")
            return
        self.go(self.history.pop(), remember=False)

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str, yes: str) -> None:
        super().__init__()
        self.question = question
        self.yes = yes

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static(self.question, id="confirm-text")
            with Horizontal(id="confirm-buttons"):
                yield Button(self.yes, variant="error", id="confirm-yes")
                yield Button("Cancel", id="confirm-no")

    @on(Button.Pressed)
    def answer(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SandyApp(App):
    TITLE = "Sandy"
    SUB_TITLE = "job hunt + study, one screen"
    CSS_PATH = "sandy.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("x", "stop", "Stop run"),
        Binding("o", "toggle_output", "Big output"),
        Binding("l", "clear_log", "Clear output"),
        Binding("escape", "focus_nav", "Menu", show=False),
        *[
            Binding(str((i + 1) % 10), f"goto('{key}')", title, show=False)
            for i, (key, _, title) in enumerate(SECTIONS)
        ],
    ]

    def __init__(self) -> None:
        super().__init__()
        self.running: Optional[Command] = None
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.started = 0.0
        self.stopping = False
        self.quit_armed = False
        self.shown: Dict[str, object] = {}
        self.home: Optional[Screen] = None
        self.modules = state.course_modules()
        self.plan: Optional[state.PlanDay] = None
        self.plan_date: Optional[dt.date] = None
        self.track_nodes: Dict[str, TreeNode] = {}
        self.module_nodes: Dict[str, TreeNode] = {}
        self.read_shown: Optional[tuple] = None

    # --- layout -----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="pills"):
            for pill in ("pill-report", "pill-questions", "pill-site", "pill-run"):
                yield Static("", id=pill, classes="pill")
        with Horizontal(id="body"):
            yield OptionList(*[Option(f" {icon}  {title}", id=key) for key, icon, title in SECTIONS], id="nav")
            with Vertical(id="main"):
                with ContentSwitcher(initial="p-today", id="panels"):
                    yield from self.today_panel()
                    yield from self.naukri_panel()
                    yield from self.sites_panel()
                    yield from self.profile_panel()
                    yield from self.linkedin_panel()
                    yield from self.resume_panel()
                    yield from self.reports_panel()
                    yield from self.study_panel()
                    yield from self.todo_panel()
                    yield from self.setup_panel()
                with Vertical(id="output"):
                    yield RichLog(id="log", wrap=True, min_width=40)
        yield Footer()

    def today_panel(self) -> ComposeResult:
        with Panel(id="p-today", classes="panel"):
            yield Static("", id="today-summary", classes="card")
            yield Static("Quick start", classes="section")
            with Grid(id="quick"):
                yield Button("▶  Apply now", id="go-apply", variant="success")
                yield Button("◌  Practice run", id="go-practice", variant="primary")
                yield Button("▤  Today's report", id="go-report")
                yield Button("✎  Answer questions", id="go-answer", variant="warning")
                yield Button("◉  Study today's module", id="go-study")
                yield Button("✦  Draft LinkedIn post", id="go-linkedin")
            yield Static(
                "Apply now searches Naukri, applies to the best fresh matches and company sites, "
                "then writes today's report. Practice run does the same ranking but never clicks Apply.\n"
                "Keys: 1-9 and 0 jump between sections, x stops a run, o makes the output big, q quits.",
                classes="hint",
            )

    def naukri_panel(self) -> ComposeResult:
        with Panel(id="p-naukri", classes="panel"):
            yield from heading(
                "Apply on Naukri",
                "Finds fresh jobs that match your resume, ranks them, and applies to the best ones "
                "(Naukri allows 50 a day). Jobs that send you to a company site are tried there too. "
                "Writes today's report at the end.",
            )
            yield toggle("nk-dry", "Practice run: rank and report, never click Apply")
            yield toggle("nk-ea", "Also share interest on Early Access roles (uses no quota)")
            yield toggle("nk-ea-only", "Only Early Access: no search, no applying")
            yield toggle("nk-headless", "Hide the browser window (login is challenged more often)")
            yield field("Apply to at most", Input(placeholder="as many as today's quota allows", type="integer", id="nk-limit"))
            yield field("Screening answers", Select(ANSWER_MODES, value="", allow_blank=False, id="nk-mode"))
            yield field("Keywords", Input(placeholder="from your resume  (e.g. GenAI, LLM, Python)", id="nk-keywords"))
            yield field("Location", Input(placeholder="from .env", id="nk-location"))
            yield Static("", id="nk-preview", classes="preview")
            yield buttons(Button("▶  Run", id="run-naukri", variant="success"))

    def sites_panel(self) -> ComposeResult:
        with Panel(id="p-sites", classes="panel"):
            yield from heading(
                "Company sites",
                "Jobs whose Apply button leads to the company's own website. The bot fills what it "
                "can and lists the rest in data/company_sites.md.",
            )
            yield Static("Waiting for you", classes="section")
            yield Static("", id="sites-list", classes="card")
            yield toggle("cs-assist-dry", "Preview only: show what would be filled, change nothing")
            yield buttons(
                Button("▶  Fill waiting forms", id="run-assist", variant="success"),
                Button("✎  Open the list", id="edit-sites"),
            )
            yield Static("Apply on one page", classes="section")
            yield field("Application link", Input(placeholder="https://...", id="cs-url"))
            yield field("Job title", Input(placeholder="for the tailored resume", id="cs-title"))
            yield field("Company", Input(id="cs-company"))
            yield toggle("cs-dry", "Fill the form but do not press Submit")
            yield toggle("cs-no-tailor", "Send the base resume instead of a tailored one")
            yield toggle("cs-headless", "Hide the browser window")
            yield Static("", id="cs-preview", classes="preview")
            yield buttons(Button("▶  Apply on this page", id="run-external", variant="success"))

    def profile_panel(self) -> ComposeResult:
        with Panel(id="p-profile", classes="panel"):
            yield from heading(
                "Naukri profile",
                "Recruiters see recently updated profiles first. This toggles a dot on your resume "
                "headline so the profile counts as updated. Uses none of the apply quota.",
            )
            yield toggle("pf-dry", "Check only: open the headline editor, save nothing")
            yield toggle("pf-ifdue", "Only if a daily slot (09:00, 13:30, 18:30) is due")
            yield toggle("pf-headless", "Hide the browser window")
            yield Static("", id="pf-preview", classes="preview")
            yield buttons(
                Button("▶  Refresh now", id="run-profile", variant="success"),
                Button("Schedule status", id="profile-status"),
                Button("Turn on daily schedule", id="profile-install"),
            )

    def linkedin_panel(self) -> ComposeResult:
        with Panel(id="p-linkedin", classes="panel"):
            yield from heading(
                "LinkedIn post",
                "One post a day: a fresh article on your topics, a short reaction in your own words, "
                "and an image card. Drafts land in linkedin/drafts/.",
            )
            yield field("What to do", Select(LINKEDIN_CHOICES, value="dry-run", allow_blank=False, id="li-mode"))
            yield field("Draft to publish", Input(placeholder="today's saved draft", id="li-draft"))
            yield toggle("li-headless", "Hide the browser window")
            yield Static("", id="li-preview", classes="preview")
            yield buttons(
                Button("▶  Run", id="run-linkedin", variant="success"),
                Button("Schedule status", id="li-status"),
                Button("Turn on daily schedule", id="li-install"),
            )

    def resume_panel(self) -> ComposeResult:
        with Panel(id="p-resume", classes="panel"):
            yield from heading(
                "Tailor resume",
                "Rewrites your resume for one job, using only what is true about you, and builds "
                "the PDF in resume/out/tailored/.",
            )
            yield field("Job title", Input(id="rs-title"))
            yield field("Company", Input(id="rs-company"))
            yield Static("Paste the job description:", classes="field-label wide")
            yield TextArea(id="rs-jd-text", soft_wrap=True)
            yield field("…or a file with it", Input(placeholder="path/to/job.txt", id="rs-jd-file"))
            yield toggle("rs-headless", "Hide the browser window")
            yield Static("", id="rs-preview", classes="preview")
            yield buttons(
                Button("▶  Tailor", id="run-resume", variant="success"),
                Button("Open the resume folder", id="open-resumes"),
            )

    def reports_panel(self) -> ComposeResult:
        with Panel(id="p-reports", classes="panel"):
            yield from heading(
                "Reports",
                "One report a day: what was applied to, what is left for you, and the study module for today.",
            )
            yield field("Day", Input(placeholder=f"today ({dt.date.today().isoformat()})", id="rp-date"))
            yield Static("", id="report-days", classes="card")
            yield Static("", id="rp-preview", classes="preview")
            yield buttons(
                Button("▤  Read", id="read-report", variant="primary"),
                Button("↻  Build / rebuild", id="run-report"),
                Button("Open in an app", id="open-report"),
            )

    def study_panel(self) -> ComposeResult:
        with Panel(id="p-study", classes="panel"):
            yield from heading(
                "Study",
                "PrepForge, your interview course, right here. In a module: n and p turn the page, "
                "m marks it read, t hides its contents, w opens it on the study site, where the "
                "diagrams are drawn (here they show as text).",
            )
            yield Static("", id="study-today", classes="card")
            yield buttons(Button("▤  Read today's module", id="study-read-today", variant="primary"))
            yield Static("Every module  ·  enter opens one", classes="section")
            tree: Tree[Module] = Tree("Course", id="course-tree")
            tree.show_root = False
            yield tree
            yield Static("Study site in your browser", classes="section")
            yield Static(
                "Served on this computer only (your bot files are never served); it keeps running "
                "after you close Sandy.",
                classes="hint",
            )
            yield field("Port", Input(value=str(state.DEFAULT_PORT), type="integer", id="ss-port"))
            yield Static("", id="study-status", classes="card")
            yield buttons(
                Button("▶  Start", id="study-start", variant="success"),
                Button("Open in browser", id="study-open", variant="primary"),
                Button("■  Stop", id="study-stop", variant="error"),
            )

    def todo_panel(self) -> ComposeResult:
        with Panel(id="p-todo", classes="panel"):
            yield from heading(
                "Your to-dos",
                "Things only you can do. Whatever you fill in here is used on the next run.",
            )
            yield Static("Questions employers asked  ·  data/answers.txt", classes="section")
            yield Static("", id="todo-questions", classes="card")
            yield buttons(Button("✎  Answer them", id="edit-answers", variant="warning"))
            yield Static("Facts left blank  ·  data/profile.yaml", classes="section")
            yield Static("", id="todo-facts", classes="card")
            yield buttons(Button("✎  Fill them in", id="edit-profile", variant="warning"))
            yield Static("Company-site applications  ·  data/company_sites.md", classes="section")
            yield Static("", id="todo-sites", classes="card")
            yield buttons(
                Button("✎  Open the list", id="edit-sites-2"),
                Button("▶  Fill waiting forms", id="run-assist-2", variant="success"),
            )

    def setup_panel(self) -> ComposeResult:
        with Panel(id="p-setup", classes="panel"):
            yield from heading("Setup", "One-time things, and checks when something looks wrong.")
            yield Static(
                "Sign in to Google once in the bot's browser, so 'Sign in with Google' works on company sites. "
                "Quit that Chrome window (Cmd+Q) when you are done.",
                classes="hint",
            )
            yield buttons(Button("Sign in to Google", id="setup-google", variant="primary"))
            yield Static("Settings: logins, search, schedule times (.env, which git never commits).", classes="hint")
            yield buttons(Button("✎  Edit settings (.env)", id="edit-env"))
            yield Static("Install or update what the bots need, and check that everything still works.", classes="hint")
            yield buttons(
                Button("Install requirements", id="setup-install"),
                Button("Run the tests", id="setup-tests"),
            )

    # --- start-up -------------------------------------------------------------------

    def on_mount(self) -> None:
        self.home = self.screen
        if "tokyo-night" in self.available_themes:
            self.theme = "tokyo-night"
        self.query_one("#output").border_title = "Output"
        nav = self.query_one("#nav", OptionList)
        nav.highlighted = 0
        nav.focus()
        log = self.query_one("#log", RichLog)
        log.write(Text("Pick a task on the left (or press 1-9, 0), set its options and press Run.", style="bold"))
        log.write(Text("Its output streams here. Every command is the same one you could type in apply/.", style="dim"))
        self.build_course_tree()
        self.refresh_previews()
        self.refresh_status()
        self.set_interval(1.5, self.refresh_status)

    def find(self, selector: str, kind: type = Widget):
        """Query the main screen, even while the editor or a report is open."""
        return self.home.query_one(selector, kind)

    def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
        """Keep the output keys out of the footer while a reader or the editor is open."""
        if action in ("toggle_output", "clear_log") and self.home is not None and self.screen is not self.home:
            return False
        return True

    # --- reading the forms ---------------------------------------------------------------

    def is_on(self, id: str) -> bool:
        return self.find(f"#{id}", Switch).value

    def text(self, id: str) -> str:
        return self.find(f"#{id}", Input).value.strip()

    def choice(self, id: str) -> str:
        value = self.find(f"#{id}", Select).value
        return value if isinstance(value, str) else ""

    def naukri(self) -> Command:
        limit = self.text("nk-limit")
        return state.naukri_command(
            dry_run=self.is_on("nk-dry"),
            headless=self.is_on("nk-headless"),
            limit=int(limit) if limit else None,
            answer_mode=self.choice("nk-mode"),
            early_access=self.is_on("nk-ea"),
            early_access_only=self.is_on("nk-ea-only"),
            keywords=self.text("nk-keywords"),
            location=self.text("nk-location"),
        )

    def external(self) -> Command:
        return state.external_command(
            url=self.text("cs-url"),
            title=self.text("cs-title"),
            company=self.text("cs-company"),
            dry_run=self.is_on("cs-dry"),
            no_tailor=self.is_on("cs-no-tailor"),
            headless=self.is_on("cs-headless"),
        )

    def profile(self) -> Command:
        return state.profile_command(
            dry_run=self.is_on("pf-dry"), if_due=self.is_on("pf-ifdue"), headless=self.is_on("pf-headless")
        )

    def linkedin(self) -> Command:
        return state.linkedin_command(
            mode=self.choice("li-mode"), draft=self.text("li-draft"), headless=self.is_on("li-headless")
        )

    def resume(self, save: bool = False) -> Command:
        pasted = self.find("#rs-jd-text", TextArea).text
        if pasted.strip():
            jd_file = str(state.save_job_description(pasted)) if save else "logs/jd/<pasted text>.txt"
        else:
            jd_file = self.text("rs-jd-file")
        return state.resume_command(
            jd_file=jd_file,
            title=self.text("rs-title"),
            company=self.text("rs-company"),
            headless=self.is_on("rs-headless"),
            must_exist=save or not pasted.strip(),
        )

    def report(self) -> Command:
        return state.report_command(day=self.text("rp-date"))

    def port(self) -> int:
        try:
            port = int(self.text("ss-port"))
        except ValueError:
            return state.DEFAULT_PORT
        return port if 1024 <= port <= 65535 else state.DEFAULT_PORT

    # --- keeping the screen current ------------------------------------------------------

    @on(Input.Changed)
    @on(Switch.Changed)
    @on(Select.Changed)
    @on(TextArea.Changed, "#rs-jd-text")
    def form_changed(self) -> None:
        self.refresh_previews()

    def refresh_previews(self) -> None:
        builders: Dict[str, Callable[[], Command]] = {
            "nk-preview": self.naukri,
            "cs-preview": self.external,
            "pf-preview": self.profile,
            "li-preview": self.linkedin,
            "rs-preview": self.resume,
            "rp-preview": self.report,
        }
        for preview, build in builders.items():
            try:
                text = Text.assemble(("Will run  ", "bold"), ("$ " + build().shown, ""))
            except ValueError as exc:
                text = Text.assemble(("Needed  ", "bold yellow"), (str(exc), "yellow"))
            self.find(f"#{preview}", Static).update(text)

    def show(self, id: str, content, classes: Optional[str] = None) -> None:
        """Update a widget only when its content changed, so nothing flickers."""
        key = (str(content), classes)
        if self.shown.get(id) == key:
            return
        self.shown[id] = key
        widget = self.find(f"#{id}", Static)
        widget.update(content)
        if classes is not None:
            widget.set_classes(classes)

    def refresh_status(self) -> None:
        if self.plan_date != dt.date.today():
            self.refresh_study()
        port = self.port()
        report_ready = state.report_path().is_file()
        questions = state.unanswered_questions()
        facts = state.blank_facts()
        sites = state.waiting_company_sites()
        site_on = state.port_open(port)

        self.show("pill-report", "✓ Today's report ready" if report_ready else "○ No report yet today",
                  "pill ok" if report_ready else "pill off")
        count = len(questions)
        self.show("pill-questions",
                  f"! {count} question{'s' if count != 1 else ''} need you" if count else "✓ No questions waiting",
                  "pill warn" if count else "pill ok")
        self.show("pill-site", f"◉ Study site on :{port}" if site_on else "○ Study site off",
                  "pill ok" if site_on else "pill off")
        if self.running:
            self.show("pill-run", f"● {self.running.label}  {elapsed(time.monotonic() - self.started)}", "pill busy")
            self.find("#output").border_subtitle = "x to stop"
        else:
            self.show("pill-run", "Idle", "pill off")
            self.find("#output").border_subtitle = ""

        self.show("today-summary", self.summary(report_ready, questions, facts, sites, site_on, port))
        self.show("todo-questions", bullet_list(
            [state.tidy(qs[0] if qs else f"(line {line})") for line, qs in questions[:10]],
            "No questions are waiting for you.", max(0, count - 10)))
        self.show("todo-facts", bullet_list([key for _, key in facts], "Every fact is filled in."))
        self.show("todo-sites", bullet_list(
            [state.tidy(s) for s in sites[:10]], "No company-site applications are waiting.", max(0, len(sites) - 10)))
        self.show("sites-list", bullet_list(
            [state.tidy(s) for s in sites[:10]], "No company-site applications are waiting.", max(0, len(sites) - 10)))
        days = state.report_days()[:7]
        self.show("report-days", Text.assemble(("Reports on file  ", "bold"), ", ".join(days) or "none yet"))
        self.show("study-status", Text.assemble(
            ("◉ Running  ", "bold green"), (state.site_url(port), "underline")) if site_on
            else Text("○ Not running. Press Start.", style="dim"))

    def summary(self, report_ready, questions, facts, sites, site_on, port) -> Text:
        name = state.first_name()
        text = Text()
        text.append(f"{state.greeting()}{', ' + name if name else ''}.\n", style="bold")
        text.append(f"{dt.date.today():%A, %d %B %Y}\n\n", style="dim")
        rows = [
            (report_ready, "Today's report is ready: press Today's report to read it.",
             "No report yet today. Apply now writes one."),
            (not questions, "No questions are waiting for you.",
             f"{len(questions)} questions wait for your answer; jobs that ask them are skipped."),
            (not sites, "No company-site applications are waiting.",
             f"{len(sites)} company-site applications stopped short of submitting."),
            (not facts, "Your profile facts are all filled in.",
             f"{len(facts)} facts are blank in profile.yaml."),
            (site_on, f"The study site is running at {state.site_url(port)}.", "The study site is off."),
        ]
        for i, (good, yes, no) in enumerate(rows):
            if good:
                text.append("  ✓  ", style="bold green")
                text.append(yes)
            else:
                text.append("  !  " if i in (1, 2, 3) else "  ○  ", style="bold yellow" if i in (1, 2, 3) else "dim")
                text.append(no)
            if i < len(rows) - 1:
                text.append("\n")
        if self.plan:
            text.append("\n  ◉  ", style="bold cyan")
            text.append(f"Study today: {self.plan.module.title}")
            text.append(f"  (day {self.plan.number} of {self.plan.total})", style="dim")
        return text

    # --- the course ---------------------------------------------------------------------------

    def build_course_tree(self) -> None:
        tree = self.find("#course-tree", Tree)
        for module in self.modules:
            if module.track not in self.track_nodes:
                self.track_nodes[module.track] = tree.root.add(module.track)
            self.module_nodes[module.path] = self.track_nodes[module.track].add_leaf(module.title, data=module)

    def refresh_study(self) -> None:
        """Today's module, the progress bar and the ✓ marks in the module list."""
        self.plan_date = dt.date.today()
        self.plan = state.todays_module(self.modules)
        read = state.studied()
        today = self.plan.module if self.plan else None

        card = Text()
        if self.plan:
            card.append("Revise" if self.plan.revising else "Today", style="bold cyan")
            card.append(f"  ·  day {self.plan.number} of {self.plan.total} in the 8-week plan\n", style="dim")
            card.append(f"{self.plan.module.title}\n", style="bold")
            card.append(f"{self.plan.module.track}   ·   tomorrow: {self.plan.tomorrow.title}\n\n", style="dim")
        else:
            card.append("Pick any module below.\n\n", style="dim")
        card.append_text(progress(len(read & set(self.module_nodes)), len(self.modules)))
        self.show("study-today", card)

        key = (frozenset(read), today)
        if key == self.read_shown:
            return
        self.read_shown = key
        for track, node in self.track_nodes.items():
            paths = [m.path for m in self.modules if m.track == track]
            done = sum(p in read for p in paths)
            node.set_label(Text.assemble((track, "bold"), (f"   {done}/{len(paths)}", "green" if done == len(paths) else "dim")))
            if today and today.track == track:
                node.expand()
        for path, node in self.module_nodes.items():
            module = node.data
            node.set_label(Text.assemble(
                ("✓ ", "bold green") if path in read else ("○ ", "dim"),
                (module.title, ""),
                ("   ◉ today", "bold cyan") if module == today else ("", ""),
            ))

    def study(self, module: Module) -> None:
        self.push_screen(StudyScreen(self.modules, self.modules.index(module)), lambda _: self.refresh_study())

    @on(Tree.NodeSelected, "#course-tree")
    def module_chosen(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, Module):
            self.study(event.node.data)

    def open_on_site(self, route: str) -> None:
        self.site(start=True, then_open=True, route=route)

    # --- navigation -------------------------------------------------------------------------

    @on(OptionList.OptionHighlighted, "#nav")
    def nav_moved(self, event: OptionList.OptionHighlighted) -> None:
        self.find("#panels", ContentSwitcher).current = f"p-{event.option_id}"
        self.find("#main").set_class(event.option_id == "study", "reading")

    @on(OptionList.OptionSelected, "#nav")
    def nav_chosen(self) -> None:
        self.screen.focus_next()

    def action_goto(self, key: str) -> None:
        keys = [k for k, _, _ in SECTIONS]
        if self.screen is self.home and key in keys:
            nav = self.find("#nav", OptionList)
            nav.highlighted = keys.index(key)
            nav.focus()  # never leave focus on a button in the page just hidden

    def action_focus_nav(self) -> None:
        if self.screen is self.home:
            self.find("#nav", OptionList).focus()

    def action_toggle_output(self) -> None:
        self.find("#main").toggle_class("output-only")

    def action_clear_log(self) -> None:
        self.find("#log", RichLog).clear()

    # --- buttons -------------------------------------------------------------------------------

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        name = (event.button.id or "").removesuffix("-2").replace("-", "_")
        handler = getattr(self, f"do_{name}", None)
        if handler:
            handler()

    def attempt(self, build: Callable[[], Command], then: Optional[Callable[[], None]] = None) -> None:
        try:
            command = build()
        except ValueError as exc:
            self.notify(str(exc), title="Needed", severity="warning")
            return
        self.run_command(command, then)

    def do_go_apply(self) -> None:
        self.run_command(state.naukri_command())

    def do_go_practice(self) -> None:
        self.run_command(state.naukri_command(dry_run=True))

    def do_go_report(self) -> None:
        self.read_report(dt.date.today(), build_if_missing=True)

    def do_go_answer(self) -> None:
        self.do_edit_answers()

    def do_go_study(self) -> None:
        self.do_study_read_today()

    def do_study_read_today(self) -> None:
        if self.plan:
            self.study(self.plan.module)
        elif self.modules:
            self.study(self.modules[0])
        else:
            self.notify(f"No course found in {state.COURSE}.", severity="warning")

    def do_go_linkedin(self) -> None:
        self.run_command(state.linkedin_command(mode="dry-run"))

    def do_run_naukri(self) -> None:
        self.attempt(self.naukri)

    def do_run_assist(self) -> None:
        self.run_command(state.assist_command(dry_run=self.is_on("cs-assist-dry")))

    def do_run_external(self) -> None:
        self.attempt(self.external)

    def do_run_profile(self) -> None:
        self.attempt(self.profile)

    def do_profile_status(self) -> None:
        self.run_command(state.script("Profile schedule status", "profile_update_status.sh"))

    def do_profile_install(self) -> None:
        self.run_command(state.script("Turn on the profile schedule", "install_profile_updater.sh"))

    def do_run_linkedin(self) -> None:
        if self.choice("li-mode") != "post":
            self.attempt(self.linkedin)
            return
        command = self.linkedin()
        self.push_screen(
            ConfirmScreen("Publish the draft on LinkedIn now?\nEveryone in your network will see it.", "Publish"),
            lambda ok: self.run_command(command) if ok else None,
        )

    def do_li_status(self) -> None:
        self.run_command(state.script("LinkedIn schedule status", "linkedin_status.sh"))

    def do_li_install(self) -> None:
        self.run_command(state.script("Turn on the LinkedIn schedule", "install_linkedin_poster.sh"))

    def do_run_resume(self) -> None:
        self.attempt(lambda: self.resume(save=True))

    def do_open_resumes(self) -> None:
        folder = state.APPLY / "resume" / "out"
        self.open_path(folder if folder.exists() else state.APPLY / "resume")

    def do_read_report(self) -> None:
        try:
            day = state.parse_day(self.text("rp-date"))
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.read_report(day)

    def do_run_report(self) -> None:
        try:
            day = state.parse_day(self.text("rp-date"))
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self.run_command(state.report_command(day=day.isoformat()), then=lambda: self.read_report(day))

    def do_open_report(self) -> None:
        try:
            path = state.report_path(state.parse_day(self.text("rp-date")))
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        if path.is_file():
            self.open_path(path)
        else:
            self.notify("No report for that day yet. Build it first.", severity="warning")

    def do_study_start(self) -> None:
        self.site(start=True)

    def do_study_stop(self) -> None:
        self.site(start=False)

    def do_study_open(self) -> None:
        self.site(start=True, then_open=True)

    def do_edit_answers(self) -> None:
        waiting = state.unanswered_questions()
        self.edit(state.ANSWERS, waiting[0][0] if waiting else None)

    def do_edit_profile(self) -> None:
        blank = state.blank_facts()
        self.edit(state.PROFILE, blank[0][0] if blank else None)

    def do_edit_sites(self) -> None:
        self.edit(state.COMPANY_SITES)

    def do_edit_env(self) -> None:
        self.edit(state.APPLY / ".env")

    def do_setup_google(self) -> None:
        self.run_command(state.script("Sign in to Google", "google_login.sh"))

    def do_setup_install(self) -> None:
        self.run_command(state.py("Install requirements", "-m", "pip", "install", "-r", "requirements.txt"))

    def do_setup_tests(self) -> None:
        self.run_command(state.py("Run the tests", "-m", "pytest", "-q"))

    # --- screens and outside apps -------------------------------------------------------------

    def edit(self, path: Path, line: Optional[int] = None) -> None:
        if not path.exists():
            self.notify(f"{path.name} does not exist yet; the bot creates it on its first run.", severity="warning")
            return
        self.push_screen(EditorScreen(path, line), lambda _: self.refresh_status())

    def read_report(self, day: dt.date, build_if_missing: bool = False) -> None:
        path = state.report_path(day)
        if path.is_file():
            self.push_screen(ReaderScreen(f"Report for {day:%A, %d %B %Y}", path.read_text(encoding="utf-8")))
        elif build_if_missing:
            self.run_command(state.report_command(day=day.isoformat()), then=lambda: self.read_report(day))
        else:
            self.notify(f"No report for {day.isoformat()} yet. Press Build.", severity="warning")

    def open_path(self, target) -> None:
        subprocess.Popen(["open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @work(thread=True, exclusive=True, group="site")
    def site(self, start: bool, then_open: bool = False, route: str = "") -> None:
        port = self.port()
        ok, message = state.start_site(port) if start else state.stop_site(port)
        if ok and then_open:
            self.open_path(state.site_url(port) + (f"/#/{route}" if route else ""))
        self.call_from_thread(self.notify, message, severity="information" if ok else "warning")
        self.call_from_thread(self.refresh_status)

    # --- running a command -----------------------------------------------------------------------

    def run_command(self, command: Command, then: Optional[Callable[[], None]] = None) -> None:
        if self.running:
            self.notify(f"{self.running.label} is still running. Press x to stop it first.", severity="warning")
            return
        self.running = command
        self.started = time.monotonic()
        self.stopping = False
        self.refresh_status()
        self.run_worker(self.stream(command, then), group="runner", exit_on_error=False)

    async def stream(self, command: Command, then: Optional[Callable[[], None]]) -> None:
        log = self.find("#log", RichLog)
        log.write(Text.assemble(("\n▶ ", "bold cyan"), (command.label, "bold"), ("    $ " + command.shown, "dim")))
        code: Optional[int] = None
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *command.argv,
                cwd=str(state.APPLY),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
                limit=1 << 20,
            )
            assert self.proc.stdout is not None
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                log.write(Text.from_ansi(line.decode("utf-8", "replace").rstrip("\r\n")))
            code = await self.proc.wait()
        except OSError as exc:
            log.write(Text(f"✗ Could not start: {exc}", style="bold red"))
        finally:
            took = elapsed(time.monotonic() - self.started)
            if code == 0:
                log.write(Text(f"✓ {command.label}: done in {took}", style="bold green"))
            elif code is not None and self.stopping:
                log.write(Text(f"■ {command.label}: stopped after {took}", style="bold yellow"))
            elif code is not None:
                log.write(Text(f"✗ {command.label}: failed (exit {code}) after {took}", style="bold red"))
            self.proc = None
            self.running = None
            self.quit_armed = False
            self.refresh_status()
        if code == 0:
            self.notify(f"{command.label}: done", title="Finished")
            if then:
                then()
        elif code is not None and not self.stopping:
            self.notify(f"{command.label} failed. See the output.", title="Failed", severity="error")

    def signal_run(self, sig: int) -> None:
        if self.proc is not None and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, sig)
            except ProcessLookupError:
                pass

    def action_stop(self) -> None:
        if not self.running:
            self.notify("Nothing is running.")
            return
        if self.stopping:
            self.signal_run(signal.SIGKILL)
            self.notify("Forced to stop.", severity="warning")
            return
        self.stopping = True
        self.signal_run(signal.SIGINT)
        self.notify("Stopping, letting it close the browser cleanly. Press x again to force.")

    async def action_quit(self) -> None:
        if self.running and not self.quit_armed:
            self.quit_armed = True
            self.notify(f"{self.running.label} is still running. Press q again to stop it and quit.",
                        severity="warning")
            return
        self.signal_run(signal.SIGTERM)
        self.exit()


def main() -> int:
    SandyApp().run()
    return 0
