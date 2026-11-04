"""--bots 1 runs the sites one after another, and each board still gets its own browser profile."""

import argparse
import os
from datetime import date

from common.memory import Memory
from pipeline import run

DAY = date(2026, 11, 4)


def _args(**kw):
    base = dict(fresh=False, dry_run=False, env=None, verbose=False, cli=None, only=[], skip=[], redo=False,
                agents=2, bots=1, containers=False, no_watch=True, today=DAY)
    base.update(kw)
    return argparse.Namespace(**base)


def test_each_board_runs_in_its_own_profile_dir_one_after_another(tmp_path, monkeypatch):
    base = tmp_path / "browser" / "naukri"
    (base / "chrome").mkdir(parents=True)
    (base / "chrome" / "Cookies").write_text("session")
    from common.connections import mark_managed
    mark_managed(base)
    monkeypatch.setattr(run, "base_profile", lambda env: str(base))
    monkeypatch.delenv("BROWSER_PROFILE_DIR", raising=False)
    seen = []

    def bot(name):
        def work():
            seen.append((name, os.environ.get("BROWSER_PROFILE_DIR"), os.environ.get("RESUME_OUT_DIR")))
            return 0
        return work

    stages = [run._bot("profile:naukri", "naukri_bot.update_profile", [], bot("profile:naukri")),
              run._bot("apply:hirist", "hirist_bot.cli", [], bot("apply:hirist")),
              run._bot("apply:cutshort", "cutshort_bot.cli", [], bot("apply:cutshort")),
              run.Stage("learn", lambda: 0)]
    assert run.run_day(_args(), stages, Memory(tmp_path / "m", DAY)) == run.EXIT_OK
    by_name = {name: (profile, out) for name, profile, out in seen}
    assert by_name["profile:naukri"][0] is None, "Naukri keeps the base profile"
    hirist = str(tmp_path / "browser" / "lanes" / "hirist")
    assert by_name["apply:hirist"][0] == hirist
    assert by_name["apply:cutshort"][0] == str(tmp_path / "browser" / "lanes" / "cutshort")
    assert by_name["apply:hirist"][1] != by_name["apply:cutshort"][1]
    assert (tmp_path / "browser" / "lanes" / "hirist" / "chrome" / "Cookies").read_text() == "session"
    assert "BROWSER_PROFILE_DIR" not in os.environ, "the override is scoped to the stage"


def test_stages_without_a_bot_command_are_left_alone():
    stage = run.Stage("apply:hirist", lambda: 0)
    assert run.own_profile_stages(_args(), [stage]) == [stage]
