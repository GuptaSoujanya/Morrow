"""The CLI-backed LLM clients: what counts as a reply."""

import subprocess

from common import llm
from common.models import Settings


def _kiro(monkeypatch, returncode, stdout):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", run)
    return llm.KiroCLIClient(Settings())


def test_a_complete_json_reply_counts_even_when_the_cli_exits_non_zero(monkeypatch):
    """Kiro printed a whole edit plan for Hirist and then exited 1; the plan was thrown away and the
    agent worked without one for 100 minutes."""
    client = _kiro(monkeypatch, 1, 'Here it is:\n{"completeness": "70%", "sections": [{"name": "About"}]}\n')
    assert client.complete_json("plan the edits", "{}") == {"completeness": "70%", "sections": [{"name": "About"}]}


def test_a_non_zero_exit_without_a_reply_is_still_a_failure(monkeypatch):
    client = _kiro(monkeypatch, 1, "Error: not signed in")
    assert client.complete_json("plan the edits", "{}") is None


def test_a_cut_off_reply_is_not_mistaken_for_a_whole_one(monkeypatch):
    client = _kiro(monkeypatch, 1, '{"completeness": "70%", "sections": [{"name": "About"')
    assert client.complete_json("plan the edits", "{}") is None
