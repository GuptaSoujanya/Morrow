"""Opt-in real Chrome sessions against localhost, using only synthetic cookies."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading
import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from common import browser, connections
from common.models import Settings
from web.browser_preview import count_many
from web.run_isolation import prepare
from web.runner import resources_for
from web.state import Command


@pytest.mark.skipif(not os.environ.get("MORROW_PREVIEW_SMOKE_CHROMEDRIVER"), reason="Opt-in local Chrome isolation test")
def test_three_real_chrome_instances_keep_independent_cookies_tabs_and_lifetimes(tmp_path, monkeypatch):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            content = b"<!doctype html><title>Local parallel fixture</title><h1>Local fixture only</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_):
            pass

    source = tmp_path / "data/browser/naukri"
    connections.mark_managed(source)
    connections.write_metadata(source, {"google": {"state": "connected", "verified_account": "synthetic@example.invalid"}})
    monkeypatch.setenv("BROWSER_PROFILE_DIR", str(source))
    monkeypatch.setenv("RESUME_OUT_DIR", str(tmp_path / "data/resume/out"))
    monkeypatch.setenv("SCREENSHOT_DIR", str(tmp_path / "data/screenshots"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    drivers, registries = {}, {}

    def launch(base):
        options = browser._chrome_options(Settings(headless=True), str(base / "chrome"))
        options.binary_location = os.environ.get("MORROW_PREVIEW_SMOKE_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        options.add_argument("--disable-background-networking")
        options.add_argument("--no-first-run")
        return webdriver.Chrome(service=Service(os.environ["MORROW_PREVIEW_SMOKE_CHROMEDRIVER"]), options=options)

    seed = None
    try:
        seed = launch(source)
        seed.get(url)
        seed.add_cookie({"name": "synthetic_seed", "value": "local-only", "expiry": int(time.time()) + 3600})
        seed.quit()
        seed = None
        environments = {}
        for site in ("naukri", "hirist", "instahyre"):
            action = "naukri" if site == "naukri" else "boards"
            command = Command(site, ("synthetic", "--site", site))
            environments[site] = prepare(tmp_path, command, action, site, {}, resources_for(command, action))
        assert len({env["BROWSER_PROFILE_DIR"] for env in environments.values()}) == 3
        for site, environment in environments.items():
            registry = tmp_path / ("registry-" + site)
            registry.mkdir(mode=0o700)
            registries[site] = str(registry)
            monkeypatch.setenv("MORROW_BROWSER_PREVIEW_DIR", str(registry))
            driver = browser._register_preview(launch(Path(environment["BROWSER_PROFILE_DIR"])))
            drivers[site] = driver
            driver.get(url)
            assert driver.get_cookie("synthetic_seed")["value"] == "local-only"
            driver.add_cookie({"name": "synthetic_lane", "value": site})
            driver.execute_script("sessionStorage.setItem('lane', arguments[0])", site)
        counts = count_many(registries)
        assert all(item == {"open_browser_count": 1, "count_status": "ready"} for item in counts.values())
        for site, driver in drivers.items():
            assert driver.get_cookie("synthetic_lane")["value"] == site
            assert driver.execute_script("return sessionStorage.getItem('lane')") == site
        drivers.pop("hirist").quit()
        assert count_many(registries)["hirist"] == {"open_browser_count": 0, "count_status": "ready"}
        for site, driver in drivers.items():
            driver.refresh()
            assert driver.title == "Local parallel fixture"
            assert driver.get_cookie("synthetic_lane")["value"] == site
    finally:
        if seed is not None:
            seed.quit()
        for driver in drivers.values():
            driver.quit()
        server.shutdown()
        server.server_close()
