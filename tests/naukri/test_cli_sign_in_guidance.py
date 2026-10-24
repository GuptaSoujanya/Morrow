"""CLI recovery messages with mocked runs; no browser, auth, files or alerts."""
import logging

import pytest

from common import assist, browser, config, profile
from common.models import Profile, Settings
from naukri_bot import cli, update_profile


REASON = ("Naukri is not connected in this automation browser. Open Connections → Naukri → Sign in, "
          "complete sign-in, check it, and close the browser before trying again.")


@pytest.mark.parametrize("module,run_method", [(cli, "run"), (update_profile, "run_once")], ids=["apply", "profile-update"])
@pytest.mark.parametrize("managed", [True, False], ids=["managed", "local"])
@pytest.mark.parametrize("failure_type", ["_NeedsHuman", "_LoginUnavailable"])
def test_cli_preserves_specific_recovery_and_only_local_runs_get_browser_flag_help(monkeypatch, caplog, module, run_method, managed, failure_type):
    settings = Settings(session_only=managed, headless=True, dry_run=True,
                        email="unused@example.test", password="unused-test-password")
    attempts, alerts = [], []
    monkeypatch.setattr(config, "load_settings", lambda *args: settings)
    monkeypatch.setattr(module, "configure_logging", lambda *args: None)
    monkeypatch.setattr(module, "keep_log", lambda *args: None)
    monkeypatch.setattr(assist, "run_pass", lambda *args, **kwargs: None)
    monkeypatch.setattr(profile, "load_profile", lambda *args: Profile())
    monkeypatch.setattr(update_profile, "_resume_to_upload", lambda *args: None)
    monkeypatch.setattr(update_profile, "send_alert", lambda settings, message: alerts.append(message))
    monkeypatch.setattr(browser, "create_driver", lambda *args: pytest.fail("No browser should be launched"))

    def needs_sign_in(*args, **kwargs):
        attempts.append(True)
        raise getattr(module, failure_type)(REASON)

    monkeypatch.setattr(module, run_method, needs_sign_in)
    caplog.set_level(logging.ERROR, logger=module.__name__)

    assert module.main(["--headless"]) == module.EXIT_LOGIN
    messages = [record.getMessage() for record in caplog.records if record.name == module.__name__]
    assert attempts == [True], "Manual sign-in failures must not retry the run"
    primary = ("Login needs a human: " if failure_type == "_NeedsHuman" else "Naukri sign-in could not be verified: ") + REASON
    assert messages[0] == primary
    assert not any(record.exc_info for record in caplog.records), "Expected authentication failures must not print a traceback"
    if managed or failure_type == "_LoginUnavailable":
        assert messages == [primary]
        assert "HEADLESS=false" not in caplog.text and "BACKGROUND=false" not in caplog.text
    else:
        assert len(messages) == 2
        assert "HEADLESS=false" in messages[1] and "BACKGROUND=false" in messages[1]
        assert "omit --headless for a local run" in messages[1]
    alert = ("Naukri profile update: login needs a human (" if failure_type == "_NeedsHuman" else
             "Naukri profile update: sign-in could not be verified (") + REASON + ")"
    assert alerts == ([alert] if module is update_profile else [])
