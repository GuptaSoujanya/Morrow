import logging
import urllib.error

import pytest

from common import run
from common.models import Settings


def _settings(**overrides):
    return Settings(email="e", password="p", **overrides)


def test_no_alert_is_sent_without_both_telegram_values(monkeypatch):
    calls = []
    monkeypatch.setattr(run.urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    run.send_alert(_settings(telegram_bot_token="123:abc"), "down")
    run.send_alert(_settings(telegram_chat_id="42"), "down")
    assert calls == []


def test_the_alert_carries_the_message_to_telegram(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"], seen["body"], seen["timeout"] = request.full_url, request.data, timeout

    monkeypatch.setattr(run.urllib.request, "urlopen", fake_urlopen)
    run.send_alert(_settings(telegram_bot_token="123:abc", telegram_chat_id="42"), "bot down")
    assert seen["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert b'"chat_id": "42"' in seen["body"] and b"bot down" in seen["body"]
    assert seen["timeout"] == 15


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("https://api.telegram.org/bot123:abc/sendMessage unreachable"),
        ValueError("unknown url type: https://api.telegram.org/bot123:abc/sendMessage"),
    ],
)
def test_a_failed_alert_is_logged_without_the_bot_token(monkeypatch, caplog, error):
    def fake_urlopen(request, timeout=None):
        raise error

    monkeypatch.setattr(run.urllib.request, "urlopen", fake_urlopen)
    with caplog.at_level(logging.WARNING, logger="common.run"):
        run.send_alert(_settings(telegram_bot_token="123:abc", telegram_chat_id="42"), "bot down")
    assert "Telegram alert failed" in caplog.text
    assert "123:abc" not in caplog.text and "<token>" in caplog.text
