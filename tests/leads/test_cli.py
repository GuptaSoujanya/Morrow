import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common import browser_lanes
from common.models import Settings
from leads import boards, cli, mail


def test_main_runs_mail_then_every_board_in_platforms(monkeypatch, tmp_path):
    from common import config

    monkeypatch.setattr(config, "load_settings", lambda env=None, overrides=None: Settings(
        platforms="hirist, cutshort", browser_profile_dir=str(tmp_path / "naukri")))
    monkeypatch.setattr(browser_lanes, "prepare", lambda lane, base: {"BROWSER_PROFILE_DIR": str(tmp_path / lane)})
    seen = []
    monkeypatch.setattr(mail, "main", lambda flags: seen.append(("mail", flags, os.environ.get("BROWSER_PROFILE_DIR"))) or 0)
    monkeypatch.setattr(boards, "main", lambda flags: seen.append((flags[-1], flags, os.environ.get("BROWSER_PROFILE_DIR"))) or 0)
    monkeypatch.delenv("BROWSER_PROFILE_DIR", raising=False)

    assert cli.main(["--dry-run", "--limit", "2"]) == 0
    assert [name for name, _, _ in seen] == ["mail", "naukri", "hirist", "cutshort"]
    assert seen[0][1] == ["--dry-run", "--limit", "2"]
    assert seen[2][1] == ["--dry-run", "--limit", "2", "--board", "hirist"]
    assert seen[2][2] == str(tmp_path / "hirist") and seen[1][2] is None, "each board runs in its own lane profile"
    assert "BROWSER_PROFILE_DIR" not in os.environ

    seen.clear()
    assert cli.main(["--only", "wellfound", "--only", "bogus"]) == 1
    assert [name for name, _, _ in seen] == ["wellfound"]
