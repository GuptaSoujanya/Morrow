"""A running job keeps its identity, its log and its life across a dashboard restart."""
import importlib.util
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JOBSTORE = ROOT / "studio" / "api" / "jobstore.py"
API = ROOT / "studio" / "api" / "studio_api.py"

pytestmark = pytest.mark.skipif(not JOBSTORE.exists(), reason="the private studio folder is not checked out")


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def store(tmp_path, monkeypatch):
    module = _module(JOBSTORE, "studio_jobstore_test")
    monkeypatch.setattr(module, "HOME", tmp_path / "jobs")
    return module


def _record(store, number, **extra):
    job = {"id": number, "kind": "make", "action": "render", "name": "day-01", "group": "",
           "state": "running", "started": time.time(), "finished": None, "rc": None, "pid": os.getpid()}
    return store.save(job | extra)


def test_a_job_number_is_never_reused_after_a_restart(store):
    assert store.next_id() == 1
    _record(store, 1, state="done")
    _record(store, 7, state="done")
    assert store.next_id() == 8


def test_a_record_is_written_whole_so_a_reader_never_sees_half_of_it(store):
    _record(store, 3, state="done", rc=0)
    assert list(store.HOME.glob("*.writing")) == []
    kept = store.read(3)
    assert kept["kind"] == "make" and kept["rc"] == 0 and kept["epoch"] == store.EPOCH
    assert json.loads(store.record_path(3).read_text(encoding="utf-8"))["id"] == 3


def test_a_made_up_job_number_is_refused_before_it_touches_the_folder(store):
    for junk in ("abc", "", "0", "-2", "1.5", "../secret", "1" * 13):
        with pytest.raises(ValueError):
            store.job_id(junk)
    assert store.read("abc") is None


def test_the_end_of_a_long_log_is_read_without_loading_all_of_it(store):
    store.HOME.mkdir(parents=True, exist_ok=True)
    # Past the read window, so the seek-from-the-end path is the one under test.
    store.log_path(4).write_text("\n".join(f"line {number}" for number in range(40000)), encoding="utf-8")
    tail = store.tail(4, limit=5)
    assert tail[-1] == "line 39999" and len(tail) == 5
    assert store.log_size(4) > store.TAIL_BYTES
    assert store.tail(99) == [] and store.log_size(99) == 0


def test_a_job_that_died_with_its_dashboard_is_marked_interrupted(store):
    gone = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
    gone.wait()
    _record(store, 5, pid=gone.pid, epoch="an-earlier-dashboard")
    assert store.reconcile() == []
    settled = store.read(5)
    assert settled["state"] == "interrupted" and "cut short" in settled["note"]


def test_a_job_still_running_is_adopted_and_followed_to_its_end(store):
    child = subprocess.Popen(["/bin/sh", "-c", "sleep 30"])
    try:
        _record(store, 6, pid=child.pid, epoch="an-earlier-dashboard")
        adopted = store.reconcile()
        assert [job["id"] for job in adopted] == [6]
        assert adopted[0]["adopted"] is True and adopted[0]["state"] == "running"
        assert store.read(6)["state"] == "running"

        ended = []
        store.watch(adopted[0], on_end=ended.append)
        child.send_signal(signal.SIGTERM)
        child.wait()
        for _ in range(60):
            if store.read(6)["state"] == "ended":
                break
            time.sleep(0.2)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    closed = store.read(6)
    assert closed["state"] == "ended" and closed["finished"]
    assert [job["id"] for job in ended] == [6]


def test_this_dashboards_own_jobs_are_left_alone_by_reconcile(store):
    _record(store, 8)
    assert store.reconcile() == []
    assert store.read(8)["state"] == "running"


def test_a_watcher_is_woken_when_a_log_grows_not_only_when_a_state_changes(store):
    job = _record(store, 9)
    quiet = store.signature([job])
    store.HOME.mkdir(parents=True, exist_ok=True)
    with store.log_path(9).open("a", encoding="utf-8") as handle:
        handle.write("a new line of output\n")
    assert store.signature([job]) != quiet


def test_old_runs_are_cleared_out_with_their_logs(store):
    store.HOME.mkdir(parents=True, exist_ok=True)
    for number in range(1, 9):
        _record(store, number, state="done")
        store.log_path(number).write_text("output", encoding="utf-8")
    store.prune(keep=3)
    assert sorted(int(path.stem) for path in store.HOME.glob("*.json")) == [6, 7, 8]
    assert not store.log_path(1).exists() and store.log_path(8).exists()


def test_a_live_process_is_recognised_without_being_disturbed(store):
    child = subprocess.Popen(["/bin/sh", "-c", "sleep 20"])
    try:
        assert store.alive(child.pid) is True
        assert child.poll() is None, "asking must never stop the process"
    finally:
        child.kill()
        child.wait()
    assert store.alive(child.pid) is False
    for nonsense in (None, 0, 1, -5, "123"):
        assert store.alive(nonsense) is False


@pytest.mark.skipif(not API.exists(), reason="the studio api is not checked out")
def test_a_second_dashboard_picks_up_the_job_the_first_one_started(tmp_path, monkeypatch):
    monkeypatch.setenv("MORROW_STUDIO_JOBS", str(tmp_path / "jobs"))
    first = _module(API, "studio_api_first")
    assert first.jobstore.HOME == tmp_path / "jobs", "the test must not touch the real job folder"
    job = first._start_job("probe", "sleeper", "", kind="skills",
                           argv=["/bin/sh", "-c", "echo working; sleep 30"])
    try:
        for _ in range(50):
            if first.jobstore.tail(job["id"]):
                break
            time.sleep(0.1)
        assert first._job_view(job)["log"] == ["working"]

        # Importing the api is a dashboard starting up: it adopts what it finds.
        second = _module(API, "studio_api_second")
        carried = second._jobs.get(job["id"])
        assert carried and carried["state"] == "running" and carried["adopted"] is True
        assert second.jobstore.tail(job["id"]) == ["working"]
        assert second._job_summary()["running"] == ["skills"]
        assert second._running("skills") is not None
        later, output = second.jobstore.claim({"kind": "skills", "state": "running"})
        output.close()
        assert later["id"] > job["id"], "a new job must not reuse a live job's number"
        assert second.jobstore.tail(job["id"]) == ["working"], "the live job's log must survive untouched"
    finally:
        if job.get("pid"):
            try:
                os.killpg(os.getpgid(job["pid"]), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def test_two_dashboards_cannot_be_handed_the_same_job_number(store):
    """Both studios share this folder, so the number has to be claimed on disk, not counted in memory."""
    taken, logs = [], []
    for _ in range(6):
        job, output = store.claim({"kind": "make", "state": "running"})
        output.write(f"job {job['id']} speaking\n".encode())
        output.flush()
        taken.append(job["id"])
        logs.append(output)
    for output in logs:
        output.close()
    assert taken == sorted(set(taken)) == [1, 2, 3, 4, 5, 6]
    for number in taken:
        assert store.tail(number) == [f"job {number} speaking"], "a claim must never truncate another run's log"
        assert store.read(number)["epoch"] == store.EPOCH


def test_a_number_already_on_disk_is_stepped_over(store):
    _record(store, 1, state="done")
    _record(store, 2, state="running")
    job, output = store.claim({"kind": "make", "state": "running"})
    output.close()
    assert job["id"] == 3
    assert store.read(2)["state"] == "running", "the running record must be left as it was"
