import os
import subprocess
from pathlib import Path

import pytest
from selenium import webdriver

from common import browser


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "darwin")
    monkeypatch.delenv("CHROMEDRIVER", raising=False)
    monkeypatch.delenv("MORROW_CHROMEDRIVER_DIRECT", raising=False)
    monkeypatch.delenv("SE_CHROMEDRIVER", raising=False)


def test_on_mac_chromedriver_is_started_through_the_shell_wrapper(mac, tmp_path):
    real = tmp_path / "chromedriver"
    real.write_text("")
    service = browser.chromedriver_service(webdriver.ChromeOptions(), str(real))
    assert service.path == str(browser.CHROMEDRIVER_WRAPPER)
    assert service.env["MORROW_CHROMEDRIVER"] == str(real)
    assert os.access(browser.CHROMEDRIVER_WRAPPER, os.X_OK)


def test_the_chromedriver_env_names_the_driver_behind_the_wrapper(mac, monkeypatch, tmp_path):
    monkeypatch.setenv("CHROMEDRIVER", str(tmp_path / "driver"))
    service = browser.chromedriver_service(webdriver.ChromeOptions())
    assert service.path == str(browser.CHROMEDRIVER_WRAPPER)
    assert service.env["MORROW_CHROMEDRIVER"] == str(tmp_path / "driver")


def test_without_a_known_path_selenium_finds_the_driver_first(mac, monkeypatch):
    monkeypatch.setattr(browser.DriverFinder, "get_driver_path", lambda self: "/found/chromedriver")
    service = browser.chromedriver_service(webdriver.ChromeOptions())
    assert service.env["MORROW_CHROMEDRIVER"] == "/found/chromedriver"


def test_elsewhere_chromedriver_is_started_directly(monkeypatch):
    monkeypatch.setattr(browser.sys, "platform", "linux")
    monkeypatch.delenv("SE_CHROMEDRIVER", raising=False)
    service = browser.chromedriver_service(webdriver.ChromeOptions(), "/usr/bin/chromedriver")
    assert service.path == "/usr/bin/chromedriver"
    assert "MORROW_CHROMEDRIVER" not in service.env


def test_the_wrapper_can_be_switched_off(mac, monkeypatch):
    monkeypatch.setenv("MORROW_CHROMEDRIVER_DIRECT", "1")
    service = browser.chromedriver_service(webdriver.ChromeOptions(), "/opt/chromedriver")
    assert service.path == "/opt/chromedriver"


def test_the_wrapper_execs_the_named_driver_with_its_arguments(tmp_path):
    fake = tmp_path / "fake-driver"
    fake.write_text("#!/bin/bash\necho \"driver $@\"\n")
    fake.chmod(0o700)
    result = subprocess.run(
        [str(browser.CHROMEDRIVER_WRAPPER), "--port=1234", "--verbose"],
        env={**os.environ, "MORROW_CHROMEDRIVER": str(fake)},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "driver --port=1234 --verbose"


def test_the_wrapper_refuses_to_run_without_a_driver_path():
    env = {key: value for key, value in os.environ.items() if key != "MORROW_CHROMEDRIVER"}
    result = subprocess.run([str(browser.CHROMEDRIVER_WRAPPER)], env=env, capture_output=True, text=True)
    assert result.returncode == 64
    assert "MORROW_CHROMEDRIVER" in result.stderr
    assert Path(browser.CHROMEDRIVER_WRAPPER).name == "chromedriver.sh"
