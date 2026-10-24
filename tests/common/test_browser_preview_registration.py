"""Preview registration cannot interrupt or control an agent's browser."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import browser, browser_preview
from common.models import Settings


def test_registration_is_disabled_without_run_directory(monkeypatch):
    monkeypatch.delenv(browser_preview.ENV_NAME, raising=False)
    class Driver:
        @property
        def capabilities(self):
            raise AssertionError("Disabled previews must not inspect the browser")
    browser_preview.register(Driver())


def test_failed_optional_registration_does_not_interrupt_browser(tmp_path, monkeypatch):
    monkeypatch.setenv(browser_preview.ENV_NAME, str(tmp_path))
    driver = SimpleNamespace(capabilities={"goog:chromeOptions": {"debuggerAddress": "remote.example:9222"}})
    browser_preview.register(driver)
    assert list(tmp_path.iterdir()) == []


def test_browser_registers_only_after_initial_positioning(monkeypatch):
    events = []
    driver = SimpleNamespace()
    monkeypatch.setattr(browser, "_try_create_driver", lambda settings, use_profile: driver)
    monkeypatch.setattr(browser, "_position_visible_window", lambda value, settings: events.append("position") or value)
    monkeypatch.setattr(browser_preview, "register", lambda value: events.append("register"))
    assert browser.create_driver(Settings(browser_profile_dir="")) is driver
    assert events == ["position", "register"]


def test_managed_driver_is_registered_without_repositioning(monkeypatch):
    from common import connections
    events = []
    driver = SimpleNamespace()
    monkeypatch.setattr(connections, "create_driver", lambda settings: driver)
    monkeypatch.setattr(browser, "_position_visible_window", lambda *args: events.append("unexpected position"))
    monkeypatch.setattr(browser_preview, "register", lambda value: events.append("register"))
    assert browser.create_driver(Settings(session_only=True)) is driver
    assert events == ["register"]
