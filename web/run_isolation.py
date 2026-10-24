"""Private browser lanes and output directories for dashboard-owned jobs."""
from __future__ import annotations

import os
from pathlib import Path

BOARD_LANES = ("hirist", "instahyre", "cutshort", "wellfound")
OUTPUT_ACTIONS = frozenset(("naukri", "profile", "boards", "external", "resume", "cold_email", "pipeline",
                            "linkedin", "linkedin_profile", "assist"))


def board_site(command, action):
    if action != "boards":
        return None
    args = command.argv
    for index, value in enumerate(args[:-1]):
        if value == "--site" and args[index + 1] in BOARD_LANES:
            return args[index + 1]
    return None


def _settings(root, command, runtime):
    from dotenv import dotenv_values
    env_file = root / ".env"
    for index, value in enumerate(command.argv[:-1]):
        if value == "--env":
            env_file = Path(command.argv[index + 1]).expanduser()
            if not env_file.is_absolute():
                env_file = root / env_file
    return {**dotenv_values(env_file), **os.environ, **runtime, **dict(command.env)}


def prepare(root, command, action, run_id, runtime, resources=frozenset()):
    """Called under the runner reservation, before any selected process starts.

    Input documents and the shared application ledger stay in place. Compiler
    output and screenshots belong to this run and remain available afterwards.
    Browser sessions belong to a site, so later runs keep that site's sign-in.
    """
    if action not in OUTPUT_ACTIONS:
        return dict(runtime)
    from common.browser_lanes import prepare as prepare_lane, prepare_all
    values = _settings(root, command, runtime)

    def path(key, default):
        value = Path(values.get(key) or default).expanduser()
        return value if value.is_absolute() else root / value

    environment = dict(runtime)
    resume_root = path("RESUME_OUT_DIR", "data/resume/out")
    screenshot_root = path("SCREENSHOT_DIR", "data/screenshots")
    environment.update(RESUME_OUT_DIR=str(resume_root / "runs" / run_id),
                       MORROW_RESUME_LIBRARY_DIR=str(resume_root),
                       SCREENSHOT_DIR=str(screenshot_root / "runs" / run_id))
    site = board_site(command, action)
    browser_root = path("BROWSER_PROFILE_DIR", "data/browser/naukri")
    if site:
        environment.update(prepare_lane(site, str(browser_root)))
    elif action in ("naukri", "profile", "boards") or (action == "pipeline" and "browser:main" in resources):
        # Seed the other sites while the source is still closed. This also lets
        # a board join an already running Naukri job without reading live files.
        prepare_all(str(browser_root))
        environment["BROWSER_PROFILE_DIR"] = str(browser_root)
    return environment
