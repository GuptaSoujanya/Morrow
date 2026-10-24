"""Run the bots side by side: one lane per site, each in its own process and Chrome profile.

With `--bots N` the pipeline runs up to N sites at the same time. A lane is one
site's browser stages in order (profile:hirist, then apply:hirist). Each stage runs
as `python3 -m <bot> ...` in a child process, so the bots share no module state
(settings, the browser agent's count), and each lane gets its own Chrome profile:
Chrome refuses to open a profile another Chrome already holds.

    naukri    BROWSER_PROFILE_DIR as configured (its own session, as before)
    linkedin  LINKEDIN_BROWSER_PROFILE_DIR as configured (already separate)
    <board>   <BROWSER_PROFILE_DIR>/../lanes/<board>, first copied from the Naukri
              profile so a Google sign-in there carries over

The child reads the same .env; the variables set here win because python-dotenv
never overrides the environment. Only the parent writes .memory/.

With --containers each site's stages run in that site's own Docker container instead
(`docker compose run <site>`, docker-compose.yml): its own Chromium, virtual screen and
Chrome profile under data/docker/browser/. Each screen is shown in a web page on its own
port (WATCH_PORTS), and watch_page() puts them all on one page so you can see every bot.
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from common.pipeline_diagnostics import capture_stage_output

logger = logging.getLogger(__name__)

# Lock files Chrome leaves in a profile it has open; copying them makes the copy look in use.
_CHROME_LOCKS = ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile")
_OWN_PROFILE = ("naukri", "linkedin")
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


def profile_dir(lane: str, base: str) -> Optional[Path]:
    """The lane's Chrome profile base directory, or None for the sites that keep their own."""
    if lane in _OWN_PROFILE or not base.strip():
        return None
    return Path(base).expanduser().resolve().parent / "lanes" / lane


def prepare(lane: str, base: str) -> Dict[str, str]:
    """Environment overrides for the lane; seeds its profile from the Naukri one the first time."""
    folder = profile_dir(lane, base)
    if folder is None:
        return {}
    source = Path(base).expanduser().resolve()
    if not folder.exists() and source.is_dir():
        logger.info("[lanes] %s: copying the Chrome profile from %s", lane, source)
        try:
            shutil.copytree(source, folder, symlinks=True, ignore=shutil.ignore_patterns(*_CHROME_LOCKS),
                            ignore_dangling_symlinks=True)
        except (OSError, shutil.Error) as exc:
            # A partial copy still beats signing in from nothing; the bot logs in if it must.
            logger.warning("[lanes] %s: could not copy the whole profile (%s)", lane, exc)
    folder.mkdir(parents=True, exist_ok=True)
    return {"BROWSER_PROFILE_DIR": str(folder)}


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
        capture_stage_output(line)
        with _print_lock:
            sys.stderr.write("[%s] %s" % (lane, line))
    return process.wait()
