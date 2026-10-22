"""Sandbox reproductions: every test asserts the documented contract.

A failing test is a dynamically confirmed defect; a passing test means the
contract held and the hypothesis is pruned. The runner starts these with
PYTHONPATH set to the target root, sockets disabled, credentials stripped and
every writable path redirected to a scratch directory. This module additionally
disables python-dotenv so the target's own .env can never be read back in, and
refuses to run while any credential-looking variable is present.
"""

import os
import re
import sys
from pathlib import Path

import dotenv
import dotenv.main
import pytest

ROOT = Path(os.environ.get("HOUND_TARGET") or Path(__file__).resolve().parents[2])
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_CREDENTIAL = re.compile(r"(?i)password|passwd|secret|token|api_key|apikey|_email$")


def _no_dotenv(*_args, **_kwargs):
    return False


dotenv.load_dotenv = _no_dotenv
dotenv.main.load_dotenv = _no_dotenv
dotenv.find_dotenv = _no_dotenv
dotenv.main.find_dotenv = _no_dotenv

for _name in [key for key in os.environ if _CREDENTIAL.search(key)]:
    os.environ.pop(_name, None)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Run every reproduction from an empty directory with no credential in the environment."""
    leaked = sorted(key for key in os.environ if _CREDENTIAL.search(key))
    assert not leaked, f"credential-looking variables present in the sandbox: {leaked}"
    monkeypatch.chdir(tmp_path)
    yield tmp_path
