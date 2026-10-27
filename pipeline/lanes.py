"""Run the bots side by side: one lane per site, each in its own process and Chrome profile.

With `--bots N` the pipeline runs up to N sites at the same time. A lane is one
site's browser stages in order (profile:hirist, then apply:hirist). Each stage runs
as `python3 -m <bot> ...` in a child process, so the bots share no module state
(settings, the browser agent's count), and each lane gets its own Chrome profile:
Chrome refuses to open a profile another Chrome already holds.

    naukri    BROWSER_PROFILE_DIR as configured (its own session, as before)
    linkedin  LINKEDIN_BROWSER_PROFILE_DIR as configured (already separate)
    <board>   <BROWSER_PROFILE_DIR>/../lanes/<board>, safely initialized from a
              closed managed Naukri profile when one is available

The child reads the same .env; the variables set here win because python-dotenv
never overrides the environment. Only the parent writes user/memory/.

With --containers each site's stages run in that site's own Docker container instead
(`docker compose run <site>`, docker-compose.yml): its own Chromium, virtual screen and
Chrome profile under user/docker/browser/. Each screen is shown in a web page on its own
port (WATCH_PORTS), and watch_page() puts them all on one page so you can see every bot.
"""

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from common.pipeline_diagnostics import capture_stage_output
from common.browser_lanes import prepare as _prepare_browser, prepare_all, profile_dir
from common.answer_events import PREFIX as ANSWER_EVENT_PREFIX

logger = logging.getLogger(__name__)

_print_lock = threading.Lock()

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
# Each site's container and the port its screen is shown on (keep in step with docker-compose.yml).
WATCH_PORTS = {"naukri": 6081, "linkedin": 6082, "hirist": 6083, "instahyre": 6084,
               "cutshort": 6085, "wellfound": 6086}


def lane_of(stage_name: str) -> str:
    """The site a browser stage belongs to: 'apply:hirist' -> 'hirist'."""
    return stage_name.split(":", 1)[1] if ":" in stage_name else stage_name


def group(names: Sequence[str]) -> List[List[str]]:
    """Stage names grouped by site, each lane in the given order, lanes by first appearance."""
    lanes: Dict[str, List[str]] = {}
    for name in names:
        lanes.setdefault(lane_of(name), []).append(name)
    return list(lanes.values())


def prepare(lane: str, base: str) -> Dict[str, str]:
    """Give every local worker its own browser and résumé output directory."""
    from common.models import Settings

    environment = _prepare_browser(lane, base)
    output = Path(os.environ.get("RESUME_OUT_DIR") or Settings().resume_out_dir).expanduser().resolve()
    library = Path(os.environ.get("MORROW_RESUME_LIBRARY_DIR") or output).expanduser().resolve()
    environment.update({
        "RESUME_OUT_DIR": str(output / "lanes" / lane),
        "MORROW_RESUME_LIBRARY_DIR": str(library),
    })
    return environment


def in_container(lane: str, command: Sequence[str]) -> List[str]:
    """`python3 -m <command>` in the site's own container, its screen published on its watch port."""
    return ["docker", "compose", "-f", str(COMPOSE_FILE), "run", "--rm", "--service-ports", "-T",
            lane, "python3", "-m", *command]


def watch_url(lane: str) -> str:
    """The page showing the lane's container screen (noVNC), reconnecting until the container is up."""
    return ("http://localhost:%d/vnc.html?autoconnect=1&reconnect=1&reconnect_delay=2000&resize=scale"
            % WATCH_PORTS[lane])


def watch_page(lanes: Sequence[str], path: Path) -> Path:
    """One page with every lane's screen side by side."""
    frames = "\n".join(
        '<figure><figcaption>%s <a href="%s" target="_blank">open</a></figcaption>'
        '<iframe src="%s"></iframe></figure>' % (lane, watch_url(lane), watch_url(lane))
        for lane in lanes if lane in WATCH_PORTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("""<!doctype html>
<meta charset="utf-8"><title>Bots</title>
<style>
body { margin: 0; background: #111; color: #ddd; font: 14px system-ui, sans-serif; }
main { display: grid; grid-template-columns: repeat(auto-fit, minmax(640px, 1fr)); gap: 8px; padding: 8px; }
figure { margin: 0; }
figcaption { padding: 4px 0; font-weight: 600; }
a { color: #8ab4f8; font-weight: 400; margin-left: 8px; }
iframe { width: 100%%; aspect-ratio: 16 / 10; border: 1px solid #333; background: #000; }
</style>
<main>
%s
</main>
""" % frames)
    return path


def run_isolated(lane: str, command: Sequence[str], overrides: Mapping[str, str],
                 container: bool = False) -> int:
    """Run `python3 -m <command>` with the lane's environment, its output prefixed with the lane.

    With container, in the site's own Docker container (in_container) instead of here.
    """
    env = dict(os.environ)
    env.update(overrides)
    env["PYTHONUNBUFFERED"] = "1"
    argv = in_container(lane, command) if container else [sys.executable, "-m", *command]
    try:
        process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as exc:  # no docker on PATH
        logger.error("[%s] could not start %s: %s", lane, argv[0], exc)
        return 3
    for line in process.stdout or ():
        if line.startswith(ANSWER_EVENT_PREFIX):
            # Preserve the private structured record for the parent runner.
            # Prefixing/capturing it as a diagnostic would lose the notification
            # and expose its per-run token in ordinary logs.
            with _print_lock:
                sys.stdout.write(line)
                sys.stdout.flush()
            continue
        capture_stage_output(line)
        with _print_lock:
            sys.stderr.write("[%s] %s" % (lane, line))
    return process.wait()
