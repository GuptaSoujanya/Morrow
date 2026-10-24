"""Opt-in real Chrome capture against local fixtures and a temporary profile only."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import threading

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from common.browser import _chrome_options, _register_preview
from common.models import Settings
from web.browser_preview import inventory, snapshot


@pytest.mark.skipif(not os.environ.get('MORROW_PREVIEW_SMOKE_CHROMEDRIVER'),
                    reason='Opt in with a locally installed matching ChromeDriver')
def test_real_headless_browser_preview_without_activation(tmp_path, monkeypatch):
    class FixturePage(BaseHTTPRequestHandler):
        def do_GET(self):
            name = 'Second fixture' if self.path == '/second' else 'First fixture'
            body = (f'<!doctype html><title>{name}</title><style>body{{background:#ede9fe;'
                    'font:24px system-ui;color:#312e81;padding:60px}}</style>'
                    f'<h1>{name}</h1><p>Local browser preview verification.</p>').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    registry = tmp_path / 'registry'
    registry.mkdir(mode=0o700)
    monkeypatch.setenv('MORROW_BROWSER_PREVIEW_DIR', str(registry))
    server = ThreadingHTTPServer(('127.0.0.1', 0), FixturePage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = _chrome_options(Settings(headless=True), str(tmp_path / 'profile'))
    options.binary_location = os.environ.get('MORROW_PREVIEW_SMOKE_CHROME',
                                            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    options.add_argument('--disable-background-networking')
    options.add_argument('--no-first-run')
    driver = helper = None
    try:
        driver = _register_preview(webdriver.Chrome(
            service=Service(os.environ['MORROW_PREVIEW_SMOKE_CHROMEDRIVER']), options=options))
        root = f'http://127.0.0.1:{server.server_port}'
        driver.get(root + '/first')
        first_handle = driver.current_window_handle
        frame = snapshot(registry)
        assert frame['state'] == 'ready', frame
        assert frame['title'] == 'First fixture' and frame['site'] == '127.0.0.1'
        assert base64.b64decode(frame['image'].split(',', 1)[1]).startswith(b'\xff\xd8')
        browser_id, first_tab = frame['browser_id'], frame['tab_id']
        driver.switch_to.new_window('tab')
        driver.get(root + '/second')
        second_handle = driver.current_window_handle
        # Capturing a different tab must leave Selenium on its current tab.
        frame = snapshot(registry, browser_id, first_tab)
        assert frame['state'] == 'ready' and frame['title'] == 'First fixture'
        assert driver.current_window_handle == second_handle != first_handle
        second_tab = next(tab['id'] for tab in frame['tabs'] if tab['title'] == 'Second fixture')
        second = snapshot(registry, browser_id, second_tab)
        assert second['state'] == 'ready' and second['title'] == 'Second fixture'
        helper_options = _chrome_options(Settings(headless=True), str(tmp_path / 'helper-profile'))
        helper_options.binary_location = options.binary_location
        helper_options.add_argument('--disable-background-networking')
        helper_options.add_argument('--no-first-run')
        helper = _register_preview(webdriver.Chrome(
            service=Service(os.environ['MORROW_PREVIEW_SMOKE_CHROMEDRIVER']), options=helper_options))
        helper.get(root + '/first')
        listing = inventory(registry)
        assert listing['state'] == 'ready' and len(listing['browsers']) == 2
        assert all(browser['state'] == 'ready' and 'image' not in browser for browser in listing['browsers'])
        original = next(browser for browser in listing['browsers'] if browser['id'] == browser_id)
        assert {tab['title'] for tab in original['tabs']} == {'First fixture', 'Second fixture'}
        helper_browser = next(browser for browser in listing['browsers'] if browser['id'] != browser_id)
        direct = snapshot(registry, helper_browser['id'], helper_browser['tabs'][0]['id'])
        assert direct['state'] == 'ready' and direct['title'] == 'First fixture'
        assert direct['browser_id'] == helper_browser['id']
        assert driver.current_window_handle == second_handle
        helper.quit()
        helper = None
        assert len(inventory(registry)['browsers']) == 1
        driver.quit()
        driver = None
        assert not list(registry.glob('*.json'))
        assert snapshot(registry)['state'] == 'waiting'
    finally:
        if helper is not None:
            helper.quit()
        if driver is not None:
            driver.quit()
        server.shutdown()
        server.server_close()
