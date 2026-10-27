"""The morning pipeline: one command that does the whole day, and continues where it stopped.

    python3 -m pipeline              # run (or continue) today
    python3 -m pipeline continue     # the same thing
    python3 -m pipeline status       # today's checkpoint
    python3 -m pipeline learn [--done]
    python3 -m pipeline onboard      # the first run: your resume and facts into user/ (common/onboard.py)

A run that finds no user/inputs/profile.yaml starts with onboarding when a person
is at the terminal, and stops with a pointer to it otherwise.

Stages, in order. Each is recorded in user/memory/ the moment it ends; a second run
the same day skips the done ones and retries the rest.

1. profile:naukri       the Naukri headline toggle, then the Playwright agent reviews the whole
                        profile (naukri_bot.update_profile --review)
2. profile:linkedin     the LinkedIn profile via the Playwright agent (linkedin_bot.update_profile)
3. profile:<board>      each board's profile via its own bot (<board>_bot.update_profile, Playwright agent);
                        creates the account and profile first when the board has none
4. apply:naukri         the Naukri apply run (naukri_bot.cli)
5. apply:<board>        each board's apply run via its own bot (<board>_bot.cli)
6. research:resume      any missing user/research/resume-learning file, written by the AI CLI
7. brief:<agent>        the briefing agents (goal, system-design, papers, tech-news, companies)

Every site runs at the same time, each site's profile then apply stage in its own
process and Chrome profile (pipeline/lanes.py). --bots N (or PIPELINE_BOTS=N) caps
that at N sites at once; --bots 1 runs the browser stages one after another in this
process. A site never runs twice at once: its stages share one account and one login.
With --containers (or PIPELINE_CONTAINERS=1) every site runs in its own Docker
container (docker-compose.yml), and a page showing all their screens opens
(user/docker/watch.html).

The browser stages start right away. `learn` (today's study day from the 90-day
plan) runs next to them, and the briefing agents wait for it because they are told
today's topics. The agents then run in parallel with each other and with the browser
stages (--agents N at a time, default one worker per agent), each writing its file to
user/research/daily/<date>/ as soon as it is done; see pipeline/briefing.py.

A stage counts as done only when its tool exits 0 and the files it wrote are still
there. When every stage is done the day is marked done in user/memory/ and another run
that day only prints the checkpoint (--fresh starts over). Boards come from PLATFORMS
in .env. The briefing agents ask claude and kiro-cli together and merge their answers;
the other writing stages use claude (--cli claude|kiro or PIPELINE_AI_CLI picks one).
"""

import argparse
import fcntl
import importlib
import logging
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

from common import memory as memory_module
from common.pipeline_diagnostics import StageDiagnostics, sanitize_detail
from common.run import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, configure_logging

from . import briefing, content, lanes as lanes_module, learning
from common import paths

logger = logging.getLogger(__name__)

MEMORY_DIR = memory_module.MEMORY_DIR
WATCH_PAGE = paths.user_dir() / "docker" / "watch.html"
AGENTS_AT_ONCE = 6  # research:resume and the five briefing agents, all in one wave


class Stage(NamedTuple):
    name: str
    work: Callable[[], int]
    parallel: bool = False  # an AI agent: runs in the pool, next to the browser stages
    outputs: Sequence[Path] = ()  # files the stage writes; a done stage whose file is gone runs again
    command: Sequence[str] = ()  # the same work as `python3 -m <command>`, for --bots N (pipeline/lanes.py)


def _bot(name: str, module: str, flags: List[str], work: Callable[[], int]) -> Stage:
    return Stage(name, work, command=(module, *flags))


def _naukri_profile(flags: List[str]) -> int:
    from naukri_bot import update_profile

    return update_profile.main(flags)


def _linkedin_profile(flags: List[str]) -> int:
    from linkedin_bot import update_profile

    return update_profile.main(flags)


def _naukri_apply(flags: List[str]) -> int:
    from naukri_bot import cli

    return cli.main(flags)


def _board_bot(name: str, tool: str, flags: List[str]) -> int:
    """Run one board's own bot: <name>_bot.cli (apply) or <name>_bot.update_profile."""
    return importlib.import_module("%s_bot.%s" % (name, tool)).main(flags)


def base_profile(env: Optional[str] = None) -> str:
    from common import config

    return config.load_settings(env).browser_profile_dir


def isolated_lanes(args: argparse.Namespace, browser: List[Stage]) -> List[List[Stage]]:
    """The browser stages as one lane per site, each stage run in its own process (see lanes.py)."""
    containers = bool(getattr(args, "containers", False))
    # In a container each site already has its own profile (docker-compose.yml).
    base = "" if containers else base_profile(args.env)
    lanes = []
    for names in lanes_module.group([s.name for s in browser]):
        lane = lanes_module.lane_of(names[0])
        env = {} if containers else lanes_module.prepare(lane, base)
        stages = []
        for stage in (s for s in browser if s.name in names):
            if stage.command:
                stage = stage._replace(work=lambda lane=lane, command=stage.command, env=env:
                                       lanes_module.run_isolated(lane, command, env, containers))
            stages.append(stage)
        lanes.append(stages)
    return lanes


def board_names(env: Optional[str] = None) -> List[str]:
    from common import config
    from sites_bot import platforms

    # Raises on a bad .env: returning [] here planned a day without the boards
    # and then marked it done.
    settings = config.load_settings(env)
    return [board.name for board in platforms.chosen_boards(None, settings)]


def _ai_stage(work: Callable[[], object]) -> int:
    from common.ai_cli import AIError

    try:
        work()
    except AIError as exc:
        logger.error("AI CLI: %s", exc)
        return EXIT_FAILED
    return EXIT_OK


def build_stages(args: argparse.Namespace, boards: List[str]) -> List[Stage]:
    common = (["--env", args.env] if args.env else []) + (["-v"] if args.verbose else [])
    dry = ["--dry-run"] if args.dry_run else []
    team = learning.researchers(args.cli)
    ask = next(iter(team.values()))
    day = args.today or date.today()
    stages = [Stage("learn", lambda: _ai_stage(lambda: learning.write_today(ask, today=day)), False,
                    (learning.LEARNING / "daily" / ("%s.md" % day.isoformat()),))]
    naukri_flags = dry + common + ["--review"]
    stages.append(_bot("profile:naukri", "naukri_bot.update_profile", naukri_flags,
                       lambda: _naukri_profile(naukri_flags)))
    stages.append(_bot("profile:linkedin", "linkedin_bot.update_profile", dry + common,
                       lambda: _linkedin_profile(dry + common)))
    board_flags = dry + common + ["--create-profile"]
    for name in boards:
        stages.append(_bot("profile:%s" % name, "%s_bot.update_profile" % name, board_flags,
                           lambda name=name: _board_bot(name, "update_profile", board_flags)))
    stages.append(_bot("apply:naukri", "naukri_bot.cli", dry + common, lambda: _naukri_apply(dry + common)))
    for name in boards:
        stages.append(_bot("apply:%s" % name, "%s_bot.cli" % name, dry + common,
                           lambda name=name: _board_bot(name, "cli", dry + common)))
    stages.append(Stage("research:resume", lambda: _ai_stage(lambda: learning.fill_resume_learning(ask)), True))
    for agent in briefing.AGENTS:
        stages.append(Stage(
            "brief:%s" % agent.key,
            lambda agent=agent: _ai_stage(lambda: briefing.run_agent(agent, team, day, briefing.context(day))),
            True, (briefing.output_of(agent, day),)))
    return stages


def selected(stages: List[Stage], only: List[str], skip: List[str]) -> List[Stage]:
    """Stages named (or grouped, as 'apply' or 'profile') by --only, minus --skip."""
    def hit(name: str, patterns: List[str]) -> bool:
        return any(name == p or name.split(":")[0] == p for p in patterns)

    return [s for s in stages if (not only or hit(s.name, only)) and not hit(s.name, skip)]


def sync_applied(mem: memory_module.Memory, env: Optional[str]) -> None:
    from common import config, ledger as ledger_module

    try:
        ledger = ledger_module.open_ledger(config.load_settings(env))
    except Exception as exc:
        logger.warning("Could not read the ledger for today's companies: %s", exc)
        return
    try:
        mem.sync_applied(ledger.applications_between(*memory_module.day_bounds_utc(mem.day)))
    finally:
        ledger.close()


def _run(name: str, work: Callable[[], int]) -> Tuple[int, str]:
    with StageDiagnostics() as diagnostics:
        try:
            code = work()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else EXIT_FAILED
            if exc.code and not isinstance(exc.code, int):
                diagnostics.add(str(exc.code), logging.ERROR)
        except Exception as exc:  # one broken stage must not stop the rest of the day
            logger.exception("[pipeline] %s crashed", name)
            return EXIT_FAILED, sanitize_detail("crashed: %s" % exc)
        code = code or EXIT_OK
        return code, "" if code == EXIT_OK else diagnostics.summary(code)


def write_index(mem: memory_module.Memory) -> None:
    try:
        # Different dashboard runs can finish different agents together. Hold
        # the checkpoint lock only while publishing the small derived index,
        # and reload under it so a late writer cannot restore older statuses.
        mem.folder.mkdir(parents=True, exist_ok=True)
        with (mem.folder / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                current = memory_module.Memory(mem.folder, mem.day)
                briefing.write_index(current.day, {name: current.stage(name) for name in current.planned()},
                                     current.history(), current.today["applied"])
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning("Could not write the briefing index: %s", exc)


def run_day(args: argparse.Namespace, stages: List[Stage], mem: memory_module.Memory,
            planned: Optional[List[str]] = None) -> int:
    """Run the selected stages not done yet and retain a continued workflow's scope.

    `planned` remains accepted for older callers, but the full stage catalogue
    must never add unselected work to a new workflow's resumable checkpoint.
    """
    if args.fresh and not args.dry_run:
        mem.reset_day()
    run_options = {"cli": getattr(args, "cli", None) or os.getenv("PIPELINE_AI_CLI") or "both",
                   "agents": args.agents, "bots": args.bots,
                   "containers": bool(getattr(args, "containers", False))}
    if not args.dry_run:
        names = [s.name for s in stages]
        saved_plan = mem.planned()
        continuing = getattr(args, "command", None) == "continue" and bool(saved_plan)
        # A dashboard resume selects the unfinished stages of an existing
        # workflow. Do not silently add today's entire stage catalogue to that
        # historical plan when build_stages() contains additional stages.
        day_plan = list(dict.fromkeys([*saved_plan, *names])) if continuing else names
        mem.plan(day_plan, run_options,
                 replace_options=not continuing)
        if args.redo:
            # Run these stages again; the rest of the day's checkpoint stays as it is.
            for stage in stages:
                mem.mark(stage.name, memory_module.PENDING, "redo")
        if all(mem.is_done(s.name) for s in stages):
            if mem.day_status() == memory_module.DAY_DONE:
                logger.info("[pipeline] today is already done (finished %s); nothing to run. "
                            "Use --fresh to run it again.", mem.today.get("completed_at", "?"))
            else:
                logger.info("[pipeline] those stages are already done today; left: %s.", ", ".join(mem.left()))
            print(mem.markdown(), end="")
            return EXIT_OK
    failed = []
    lock = threading.Lock()

    def one(stage: Stage) -> None:
        if not args.dry_run and mem.is_done(stage.name):
            logger.info("[pipeline] %s already done today; skipping.", stage.name)
            return
        logger.info("[pipeline] %s ...", stage.name)
        if not args.dry_run:
            mem.mark(stage.name, memory_module.RUNNING, run_options=run_options)
        code, detail = _run(stage.name, stage.work)
        if args.dry_run:
            logger.info("[pipeline] %s (dry run): exit %s", stage.name, code)
            return
        if code == EXIT_OK and not all(Path(p).exists() for p in stage.outputs):
            code, detail = EXIT_FAILED, "exited 0 but wrote no %s" % ", ".join(str(p) for p in stage.outputs)
        mem.mark(stage.name, memory_module.DONE if code == EXIT_OK else memory_module.FAILED, detail,
                 stage.outputs, exit_code=code)
        logger.info("[pipeline] %s: %s", stage.name, "done" if code == EXIT_OK else "FAILED (%s)" % detail)
        with lock:
            if code != EXIT_OK:
                failed.append(stage.name)
            if stage.name.split(":")[0] == "apply":
                sync_applied(mem, args.env)
            if stage.parallel:
                write_index(mem)

    # The browser lanes start at once. `learn` runs next to them; only the agents wait for
    # it (they are told today's topics), then run in their pool next to the browser stages.
    first = [s for s in stages if s.name == "learn"]
    browser = [s for s in stages if not s.parallel and s.name != "learn"]
    agents = [s for s in stages if s.parallel]
    learned = threading.Event()

    def learn() -> None:
        try:
            for stage in first:
                one(stage)
        finally:
            learned.set()

    def agent(stage: Stage) -> None:
        learned.wait()
        one(stage)

    # --bots N: up to N sites at once, each site's stages in order in its own process;
    # unset (None) or 0: every site at once; 1: one after another in this process.
    # --containers: every site at once, each in its own container.
    containers = bool(getattr(args, "containers", False)) and bool(browser)
    wanted = args.bots or 0
    lanes = isolated_lanes(args, browser) if (wanted != 1 or containers) and browser else [browser]
    workers = len(lanes) if (containers or not wanted) else wanted
    if containers:
        show(args, [lanes_module.lane_of(stages[0].name) for stages in lanes if stages])

    def lane(stages: List[Stage]) -> None:
        for stage in stages:
            one(stage)

    with ThreadPoolExecutor(max_workers=max(1, args.agents) + 1, thread_name_prefix="agent") as pool, \
            ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="bot") as bots:
        # `learn` has its own seat in the pool, so a full set of waiting agents cannot block it.
        futures = [bots.submit(lane, stages) for stages in lanes]
        futures.append(pool.submit(learn))
        futures += [pool.submit(agent, stage) for stage in agents]
        for future in futures:
            future.result()
    if args.dry_run:
        return EXIT_OK
    if agents:
        write_index(mem)
    check_day(mem, [s.name for s in stages])
    logger.info("[pipeline] checkpoint: %s (day %s)", mem.folder / ("%s.md" % mem.key), mem.day_status())
    if failed:
        logger.warning("[pipeline] not done: %s. Run `python3 -m pipeline continue` to retry them.",
                       ", ".join(failed))
        return EXIT_FAILED
    if mem.day_status() != memory_module.DAY_DONE:
        logger.info("[pipeline] those stages are done; the day still has: %s.", ", ".join(mem.left()))
    else:
        logger.info("[pipeline] the day is done: %d companies applied to.", len(mem.today["applied"]))
    logger.info("[pipeline] briefing: %s", briefing.folder_for(mem.day) / "README.md")
    return EXIT_OK


def show(args: argparse.Namespace, sites: List[str]) -> None:
    """Write the page with every site's container screen, and open it unless --no-watch."""
    page = lanes_module.watch_page(sites, WATCH_PAGE)
    for site in sites:
        if site in lanes_module.WATCH_PORTS:
            logger.info("[pipeline] %s runs in its own container; watch it at %s", site,
                        lanes_module.watch_url(site))
        else:
            logger.warning("[pipeline] %s has no container in docker-compose.yml", site)
    if not getattr(args, "no_watch", False) and sys.platform == "darwin":
        subprocess.run(["open", str(page.resolve())], check=False)


def check_day(mem: "memory_module.Memory", ran: List[str]) -> None:
    """Report what is missing or broken in the day's study notes and briefing."""
    if not any(name == "learn" or name.startswith("brief:") for name in ran):
        return
    problems = content.day_problems(mem.day)
    for problem in problems:
        logger.warning("[pipeline] content: %s", problem)
    if not problems:
        logger.info("[pipeline] content for %s checked: study notes and all %d briefing files are there.",
                    mem.key, len(briefing.AGENTS))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m pipeline",
                                     description="Profiles, applications and the day's study material, resumable.")
    parser.add_argument("command", nargs="?", default="run",
                        choices=("run", "continue", "status", "learn", "check", "onboard"))
    parser.add_argument("--fresh", action="store_true", help="start today over instead of continuing")
    parser.add_argument("--only", action="append", default=[], metavar="STAGE",
                        help="run only this stage or group (profile, apply, research, learn, apply:naukri...)")
    parser.add_argument("--redo", action="store_true",
                        help="run the selected stages again even when done today (use with --only)")
    parser.add_argument("--skip", action="append", default=[], metavar="STAGE", help="leave this stage or group out")
    parser.add_argument("--dry-run", action="store_true", help="pass --dry-run to the bots and record nothing")
    parser.add_argument("--cli", choices=("both", "claude", "kiro"),
                        help="AI CLI(s): both (default) has the briefing agents ask claude and kiro and merge")
    parser.add_argument("--done", action="store_true", help="with learn: mark today's study day finished")
    parser.add_argument("--agents", type=int, default=AGENTS_AT_ONCE, metavar="N",
                        help="briefing agents to run at the same time (default %d: all of them)" % AGENTS_AT_ONCE)
    parser.add_argument("--bots", type=int, default=int(os.environ.get("PIPELINE_BOTS") or 0) or None,
                        metavar="N",
                        help="sites to run at the same time, each in its own process and Chrome profile "
                             "(default: every site at once; 1: one after another; PIPELINE_BOTS sets it)")
    parser.add_argument("--containers", action="store_true", default=os.environ.get("PIPELINE_CONTAINERS") == "1",
                        help="run every site at the same time, each in its own Docker container "
                             "(docker-compose.yml; PIPELINE_CONTAINERS=1 sets it)")
    parser.add_argument("--no-watch", action="store_true",
                        help="with --containers: do not open the page showing the bots' screens")
    parser.add_argument("--date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="the day to run, check or show (default: today)")
    parser.add_argument("--env", metavar="PATH", help="path to a .env file")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None, today: Optional[date] = None) -> int:
    args = parse_args(argv)
    today = args.today = args.date or today
    configure_logging(args.verbose)
    mem = memory_module.Memory(MEMORY_DIR, today)
    if args.command == "status":
        print(mem.markdown(), end="")
        return EXIT_OK
    if args.command == "check":
        problems = content.all_problems(today)
        print("\n".join(problems) if problems else "The study material is complete for %s."
              % (today or date.today()).isoformat())
        return EXIT_FAILED if problems else EXIT_OK
    if args.command == "learn":
        if args.done:
            print("Day %d marked done." % learning.mark_done(today=today))
            return EXIT_OK
        args.only = ["learn"]
    onboard_args = ["--env", args.env] if args.env else []
    if args.command == "onboard":
        from common import onboard
        return onboard.main(onboard_args)
    if not args.only:
        from common import onboard
        if onboard.needs_onboarding():
            if not sys.stdin.isatty():
                logger.error("No profile at %s yet: run `python3 -m pipeline onboard` first.",
                             paths.inputs_dir() / "profile.yaml")
                return EXIT_CONFIG
            logger.info("No profile yet: setting up first.")
            if onboard.main(onboard_args) != 0:
                return EXIT_CONFIG
    try:
        boards = board_names(args.env)
    except Exception as exc:
        if not args.only or any(name.split(":")[0] in ("profile", "apply") for name in args.only):
            logger.error("Could not load settings: %s", exc)
            return EXIT_CONFIG
        boards = []
    if args.containers:
        # The containers and this process share the ledger across Docker's file sharing,
        # where SQLite's WAL shared memory does not work; a rollback journal does.
        os.environ.setdefault("LEDGER_JOURNAL_MODE", "DELETE")
    every = build_stages(args, boards)
    stages = selected(every, args.only, args.skip)
    if not stages:
        logger.error("No stage matches --only/--skip.")
        return EXIT_CONFIG
    return run_day(args, stages, mem, [s.name for s in every])


if __name__ == "__main__":
    sys.exit(main())
