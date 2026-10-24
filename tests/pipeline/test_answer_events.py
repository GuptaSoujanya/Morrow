from types import SimpleNamespace

from common.answer_events import PREFIX
from pipeline import lanes


def test_lane_forwards_answer_event_without_diagnostic_or_log_prefix(monkeypatch, capsys):
    event = PREFIX + '{"token":"private","kind":"answer_saved"}\n'
    captured = []
    child = SimpleNamespace(stdout=[event, "Applying to the next role\n"], wait=lambda: 0)
    monkeypatch.setattr(lanes.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(lanes, "capture_stage_output", captured.append)
    assert lanes.run_isolated("hirist", ["sites_bot"], {}) == 0
    output = capsys.readouterr()
    assert output.out == event
    assert output.err == "[hirist] Applying to the next role\n"
    assert captured == ["Applying to the next role\n"]
