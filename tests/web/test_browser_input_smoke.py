"""Opt-in real headless Chrome protocol smoke on a local page and fresh profile."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading
import time

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from common.browser import _chrome_options, _register_preview
from common.browser_preview import assistance
from common.models import Settings
from web.browser_preview import BrowserInputError, control, snapshot


@pytest.mark.skipif(not os.environ.get("MORROW_PREVIEW_SMOKE_CHROMEDRIVER"), reason="Opt-in local headless Chrome test")
def test_real_input_uses_the_waiting_browser_and_lease_removal_revokes_it(tmp_path, monkeypatch):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'''<!doctype html><title>Local input fixture</title>
<style>body{margin:0;height:2500px}input,button{position:absolute;left:40px;box-sizing:border-box}
input{top:40px;width:300px;height:50px}button{top:110px;width:200px;height:50px}</style>
<input id="typed" aria-label="Fixture text"><button id="clicked" onclick="document.body.dataset.clicks=String(Number(document.body.dataset.clicks||0)+1)">Fixture button</button>'''
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *_):
            pass

    registry = tmp_path / "registry"; registry.mkdir(mode=0o700)
    monkeypatch.setenv("MORROW_BROWSER_PREVIEW_DIR", str(registry))
    monkeypatch.setenv("MORROW_BROWSER_INTERACTIVE", "true")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = _chrome_options(Settings(headless=True), str(tmp_path / "temporary-profile"))
    options.binary_location = os.environ.get("MORROW_PREVIEW_SMOKE_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    options.add_argument("--disable-background-networking")
    options.add_argument("--no-first-run")
    driver = None
    try:
        driver = _register_preview(webdriver.Chrome(service=Service(os.environ["MORROW_PREVIEW_SMOKE_CHROMEDRIVER"]), options=options))
        driver.get(f"http://127.0.0.1:{server.server_port}/fixture")
        handle = driver.current_window_handle
        frame = snapshot(registry)
        assert not frame["control"]["enabled"]
        with assistance(driver, timeout_s=60) as enabled:
            assert enabled

            def send(action, **fields):
                frame = snapshot(registry)
                assert frame["state"] == "ready" and frame["control"]["enabled"]
                data = dict(id="local-fixture", browser=frame["browser_id"], tab=frame["tab_id"],
                            frame_id=frame["frame_id"], viewport=frame["viewport"], action=action, **fields)
                assert control(registry, data) == {"ok": True}
                return data

            send("click", x=80, y=65)
            send("type", text="hello fixture")
            assert driver.find_element("id", "typed").get_attribute("value") == "hello fixture"
            send("key", key="Backspace")
            assert driver.find_element("id", "typed").get_attribute("value") == "hello fixtur"
            send("key", key="Tab")
            assert driver.execute_script("return document.activeElement.id") == "clicked"
            send("key", key="Enter")
            assert driver.execute_script("return document.body.dataset.clicks") == "1"
            send("click", x=80, y=135)
            assert driver.execute_script("return document.body.dataset.clicks") == "2"
            final = send("scroll", x=500, y=350, deltaX=0, deltaY=600)
            deadline = time.monotonic() + 2
            while driver.execute_script("return scrollY") == 0 and time.monotonic() < deadline:
                time.sleep(.02)
            assert driver.execute_script("return scrollY") > 0
            assert driver.current_window_handle == handle
        with pytest.raises(BrowserInputError) as caught:
            control(registry, final)
        assert caught.value.status == 409
        assert snapshot(registry)["control"]["enabled"] is False
        assert driver.current_window_handle == handle and driver.title == "Local input fixture"
    finally:
        if driver is not None:
            driver.quit()
        server.shutdown(); server.server_close()
