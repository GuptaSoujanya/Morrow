"""The optional stages follow the user's real .env, so a test would plan whatever that file turns on.

STARTUP_JOBS and GMAIL_APP_PASSWORD add the startup bot and the reply reader;
each test starts with both off, and a test that wants one turns it on itself.
"""

import pytest


@pytest.fixture(autouse=True)
def _optional_stages_off(monkeypatch):
    from pipeline import run

    monkeypatch.setattr(run, "_startup_jobs_on", lambda env: False)
    monkeypatch.setattr(run, "_replies_on", lambda env: False)
    yield
