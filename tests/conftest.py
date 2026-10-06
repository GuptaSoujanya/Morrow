"""Keep every test out of the repository's working directory.

The bot writes external_jobs.md and unanswered_questions.md relative to the
current directory, so any test that exercises those paths wrote into the real
files the user reads each morning. Running the suite was appending GCP and Java
questions to unanswered_questions.md, which looked like genuine findings from a
run. Each test now starts in its own temporary directory.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def _reset_unanswered_dedup_cache():
    """The record-once cache is module state and would leak between tests."""
    from naukri_bot import answers

    answers._seen_unanswered.clear()
    answers._unanswered_loaded = False
    yield
    answers._seen_unanswered.clear()
    answers._unanswered_loaded = False
