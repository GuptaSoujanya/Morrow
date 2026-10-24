"""Parallel selections use synthetic processes and temporary workspaces only."""
import http.client
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from web import server, state
from web.state import Command


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "APPLY", tmp_path)
    httpd = server.ControlServer(0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.runner.shutdown()
    httpd.shutdown()
    httpd.server_close()


def call(site, path, body, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", site.server_port, timeout=10)
    connection.request("POST", path, json.dumps(body), {"Content-Type": "application/json", **(headers or {})})
    response = connection.getresponse()
    value = json.loads(response.read())
    connection.close()
    return response.status, value


def install(monkeypatch, *actions):
    for action in actions:
        monkeypatch.setitem(server.ACTIONS, action,
                            lambda options, save, label=action: Command(label, (
                                sys.executable, "-c", "import time; print('Synthetic agent ready', flush=True); time.sleep(30)")))


def payload(*actions):
    return {"runs": [{"key": action, "action": action, "options": {}} for action in actions]}


def test_preview_has_commands_and_resources_but_no_saved_files_or_runs(site, monkeypatch):
    saved = []
    for action in ("first", "second"):
        monkeypatch.setitem(server.ACTIONS, action, lambda options, save, label=action:
                            saved.append(save) or Command(label, (sys.executable, "-c", "print('preview')")))
    status, plan = call(site, "/api/run/batch/preview", payload("first", "second"))
    assert status == 200 and plan["ready"]
    assert plan["active_count"] == 0 and plan["max_active"] == 8
    assert plan["conflicts"] == []
    assert [item["key"] for item in plan["items"]] == ["first", "second"]
    assert all(item["shown"] and item["resources"] for item in plan["items"])
    assert saved == [False, False]
    assert site.runner.snapshot()["runs"] == []


def test_compatible_selection_starts_each_agent_with_its_own_id(site, monkeypatch):
    install(monkeypatch, "first", "second", "third")
    status, result = call(site, "/api/run/batch", payload("first", "second", "third"))
    assert status == 200 and result["ok"]
    assert len({item["id"] for item in result["results"]}) == 3
    assert all(item["ok"] for item in result["results"])
    assert len([run for run in result["run"]["runs"] if run["running"]]) == 3


def test_shared_browser_selection_starts_nothing(site, monkeypatch):
    install(monkeypatch, "naukri", "boards", "linkedin")
    data = payload("naukri", "boards", "linkedin")
    status, plan = call(site, "/api/run/batch/preview", data)
    assert status == 200 and not plan["ready"]
    assert plan["conflicts"][0]["keys"] == ["naukri", "boards"]
    assert "browser session" in plan["conflicts"][0]["message"]
    status, rejected = call(site, "/api/run/batch", data)
    assert status == 409 and not rejected["ready"] and not rejected["ok"]
    assert site.runner.snapshot()["runs"] == []


def test_active_run_conflicts_are_rechecked_when_selection_starts(site, monkeypatch):
    install(monkeypatch, "naukri", "boards", "linkedin")
    data = payload("boards", "linkedin")
    assert call(site, "/api/run/batch/preview", data)[1]["ready"]
    active = site.runner.start(server.build("naukri", {}), "naukri")
    status, plan = call(site, "/api/run/batch", data)
    assert status == 409 and plan["active_count"] == 1
    assert plan["conflicts"][0]["keys"] == ["boards"]
    assert "Wait for that run" in plan["conflicts"][0]["message"]
    assert [run["id"] for run in site.runner.snapshot()["runs"]] == [active]


def test_resume_output_conflict_has_specific_explanation(site, monkeypatch):
    install(monkeypatch, "resume", "cold_email")
    status, plan = call(site, "/api/run/batch/preview", payload("resume", "cold_email"))
    assert status == 200 and not plan["ready"]
    assert "résumé files" in plan["conflicts"][0]["message"]


def test_invalid_command_and_saved_validation_start_nothing(site, monkeypatch):
    install(monkeypatch, "first")
    status, plan = call(site, "/api/run/batch", payload("first", "unknown-agent"))
    assert status == 409 and "unknown action" in plan["items"][1]["error"]
    assert site.runner.snapshot()["runs"] == []

    def fail_on_save(options, save):
        assert options == {"mode": "real", "limit": 7}
        if save:
            raise ValueError("Required input changed. Reload the agent settings.")
        return Command("Revalidate", (sys.executable, "-c", "print('unused')"))

    monkeypatch.setitem(server.ACTIONS, "revalidate", fail_on_save)
    data = payload("first", "revalidate")
    data["runs"][1]["options"] = {"mode": "real", "limit": 7}
    assert call(site, "/api/run/batch/preview", data)[1]["ready"]
    status, plan = call(site, "/api/run/batch", data)
    assert status == 409 and "Required input changed" in plan["items"][1]["error"]
    assert site.runner.snapshot()["runs"] == []


@pytest.mark.parametrize("body", [
    {}, {"runs": []}, {"runs": "first"}, {"runs": [None]},
    {"runs": [{"key": "", "action": "first", "options": {}}]},
    {"runs": [{"key": "first", "action": 12, "options": {}}]},
    {"runs": [{"key": "first", "action": "first", "options": []}]},
    {"runs": [{"key": "first", "action": "first"}]},
    payload("first", "first"), payload(*(f"agent-{index}" for index in range(9))),
])
@pytest.mark.parametrize("path", ["/api/run/batch/preview", "/api/run/batch"])
def test_malformed_selection_is_a_bad_request(site, body, path):
    status, result = call(site, path, body)
    assert status == 400 and result["error"]
    assert site.runner.snapshot()["runs"] == []


def test_capacity_race_starts_one_complete_batch_and_rejects_the_other(site, monkeypatch):
    install(monkeypatch, "first", "second", "third", "fourth")
    site.runner.MAX_ACTIVE = 2
    ready = threading.Barrier(2)

    def start(data):
        ready.wait(timeout=5)
        return call(site, "/api/run/batch", data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(start, payload("first", "second"))
        two = pool.submit(start, payload("third", "fourth"))
        results = [one.result(), two.result()]
    assert sorted(status for status, _ in results) == [200, 409]
    rejected = next(result for status, result in results if status == 409)
    assert rejected["active_count"] == 2 and rejected["max_active"] == 2
    assert "0 slots" in rejected["conflicts"][0]["message"]
    assert len(site.runner.snapshot()["runs"]) == 2


def test_creation_failure_reports_successful_runs_without_retry_or_rollback(site, monkeypatch, tmp_path):
    install(monkeypatch, "first", "last")
    monkeypatch.setitem(server.ACTIONS, "broken", lambda options, save:
                        Command("Broken executable", (str(tmp_path / "does-not-exist"),)))
    status, result = call(site, "/api/run/batch", payload("first", "broken", "last"))
    assert status == 200 and not result["ok"]
    assert [item["ok"] for item in result["results"]] == [True, False, True]
    assert "Could not start" in result["results"][1]["error"]
    assert "id" not in result["results"][1]
    assert {run["id"] for run in result["run"]["runs"]} == {
        result["results"][0]["id"], result["results"][2]["id"]}


def test_explicit_live_mode_reaches_subprocess_despite_inherited_practice_mode(site, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setitem(server.ACTIONS, "mode-probe", lambda options, save: Command("Mode probe", (
        sys.executable, "-c", "import os; print(os.environ['DRY_RUN'], flush=True)")))
    data = payload("mode-probe")
    data["runs"][0]["options"] = {"dry_run": False}
    assert call(site, "/api/run/batch/preview", data)[1]["items"][0]["shown"].startswith("DRY_RUN=false ")
    status, result = call(site, "/api/run/batch", data)
    assert status == 200 and result["ok"]
    deadline = time.monotonic() + 5
    while site.runner.running and time.monotonic() < deadline:
        time.sleep(0.01)
    snapshot = site.runner.snapshot(after=0)
    assert any(line[1] == "false" for line in snapshot["lines"])
    assert snapshot["runs"][0]["status"] == "completed"


@pytest.mark.parametrize("path", ["/api/run/batch/preview", "/api/run/batch"])
def test_batch_endpoints_keep_same_origin_protection(site, path):
    status, result = call(site, path, payload("first"), {"Origin": "https://other.example"})
    assert status == 403 and "only this site" in result["error"]
    assert site.runner.snapshot()["runs"] == []


def test_dashboard_accounts_cannot_reach_owner_batch_routes(site, monkeypatch):
    location = Path(__file__).resolve().parents[2] / "froned-dashbord" / "server.py"
    spec = importlib.util.spec_from_file_location("dashboard_batch_boundary_tests", location)
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)
    site.RequestHandlerClass = dashboard.DashboardHandler

    class Bridge:
        def identity(self, handler):
            identity = handler.headers.get("X-Test-Identity")
            return {"id": identity, "role": "member", "modules": []} if identity else None

        def is_owner(self, handler, user):
            return user["id"] == "owner"

    site.account_bridge = Bridge()
    install(monkeypatch, "first")
    for path in ("/api/run/batch/preview", "/api/run/batch"):
        assert call(site, path, payload("first"))[0] == 401
        assert call(site, path, payload("first"), {"X-Test-Identity": "tenant"})[0] == 403
        assert site.runner.snapshot()["runs"] == []
    status, plan = call(site, "/api/run/batch/preview", payload("first"), {"X-Test-Identity": "owner"})
    assert status == 200 and plan["ready"]
    status, result = call(site, "/api/run/batch", payload("first"), {"X-Test-Identity": "owner"})
    assert status == 200 and result["ok"]
