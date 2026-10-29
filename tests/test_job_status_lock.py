"""Real status-file IO serialization, including independent processes; no API."""

import json
import multiprocessing
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

import pytest

from aletheia_nexus import research_app
from aletheia_nexus.research_app import ResearchApplication, _lock_job_owner

JOB = "b" * 32


def _receipt(status="RUNNING", completed=0):
    return {"job_id": JOB, "status": status, "completed": completed}


def _process_writer(papers, workspace, started, proceed, done, errors):
    app = ResearchApplication([papers], workspace)
    owner = None
    try:
        owner = _lock_job_owner(Path(workspace) / "jobs" / JOB / ".owner", create=True)
        assert owner is not None
        started.set()
        assert proceed.wait(5)
        for number in range(40):
            app._save_job(_receipt(completed=number))
            time.sleep(0.001)
        app._save_job(_receipt("COMPLETED", 40))
    except Exception:
        errors.put(traceback.format_exc())
    finally:
        if owner:
            owner.close()
        app.close()
        done.set()


@pytest.mark.parametrize("second_application", [False, True])
def test_status_read_handle_blocks_replace_without_permission_race(
    tmp_path, monkeypatch, second_application
):
    papers = tmp_path / "papers"
    papers.mkdir()
    app = ResearchApplication([papers], tmp_path / "workspace")
    writer_app = (
        ResearchApplication([papers], app.workspace) if second_application else app
    )
    app._save_job(_receipt())
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    errors = []
    original_read = research_app.read_json

    def held_read(path):
        if path.name == "status.json" and threading.current_thread().name == "reader":
            # Hold a real target handle while the writer tries to atomically
            # replace it: ordinary Windows read handles deny delete sharing.
            with path.open(encoding="utf-8") as handle:
                entered.set()
                assert release.wait(3)
                return json.load(handle)
        return original_read(path)

    monkeypatch.setattr(research_app, "read_json", held_read)

    def read():
        try:
            assert app.get_run_status(JOB)["status"] == "RUNNING"
        except Exception:
            errors.append(traceback.format_exc())

    def write():
        try:
            writer_app._save_job(_receipt("COMPLETED", 1))
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            finished.set()

    reader = threading.Thread(target=read, name="reader")
    writer = threading.Thread(target=write)
    try:
        reader.start()
        assert entered.wait(3)
        writer.start()
        assert not finished.wait(0.05)
        release.set()
        reader.join(3)
        writer.join(3)
        assert not reader.is_alive() and not writer.is_alive()
        assert not errors
        assert app.get_run_status(JOB)["status"] == "COMPLETED"
    finally:
        release.set()
        reader.join(3)
        if writer.ident is not None:
            writer.join(3)
        if writer_app is not app:
            writer_app.close()
        app.close()


def test_status_lock_serializes_independent_process_and_keeps_owner_live(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    app = ResearchApplication([papers], tmp_path / "workspace")
    app._save_job(_receipt())
    path = app.workspace / "jobs" / JOB / "status.json"
    lock_path = path.with_name(".status.lock")
    stable_inode = lock_path.stat().st_ino
    ctx = multiprocessing.get_context("spawn")
    started, proceed, done = ctx.Event(), ctx.Event(), ctx.Event()
    errors = ctx.Queue()
    worker = ctx.Process(
        target=_process_writer,
        args=(str(papers), str(app.workspace), started, proceed, done, errors),
    )
    observed = []
    try:
        with app._job_status_io(path):
            worker.start()
            assert started.wait(5)
            proceed.set()
            assert not done.wait(0.05)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            status = app.get_run_status(JOB, include_manifest=False)
            observed.append(status["status"])
            assert status["status"] in {"RUNNING", "COMPLETED"}
            if status["status"] == "COMPLETED":
                break
            time.sleep(0.002)
        assert observed[-1] == "COMPLETED"
        assert done.wait(3)
        worker.join(3)
        assert worker.exitcode == 0
        assert errors.empty()
        assert app.get_run_status(JOB)["completed"] == 40
        assert lock_path.stat().st_ino == stable_inode
        # The long owner lease remains separate from the short status lock.
        assert path.with_name(".owner").is_file()
    finally:
        proceed.set()
        if worker.pid is not None:
            worker.join(3)
            if worker.is_alive():
                worker.terminate()
                worker.join(3)
        errors.close()
        app.close()


def test_status_path_resolution_is_inside_the_io_lock(tmp_path, monkeypatch):
    papers = tmp_path / "papers"
    papers.mkdir()
    app = ResearchApplication([papers], tmp_path / "workspace")
    app._save_job(_receipt())
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_path = app.path
    errors = []

    def held_resolution(path, *, write=False):
        target = original_path(path, write=write)
        if (
            target.name == "status.json"
            and threading.current_thread().name == "resolver"
        ):
            # Extend the real target-handle window of Windows resolution; locking
            # only read_json leaves this earlier access outside the transaction.
            with target.open("rb"):
                entered.set()
                assert release.wait(3)
        return target

    monkeypatch.setattr(app, "path", held_resolution)

    def read():
        try:
            app.get_run_status(JOB)
        except Exception:
            errors.append(traceback.format_exc())

    def write():
        try:
            app._save_job(_receipt("COMPLETED"))
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            finished.set()

    reader = threading.Thread(target=read, name="resolver")
    writer = threading.Thread(target=write)
    try:
        reader.start()
        assert entered.wait(3)
        writer.start()
        assert not finished.wait(0.05)
        release.set()
        reader.join(3)
        writer.join(3)
        assert not reader.is_alive() and not writer.is_alive() and not errors
        assert app.get_run_status(JOB)["status"] == "COMPLETED"
    finally:
        release.set()
        reader.join(3)
        if writer.ident is not None:
            writer.join(3)
        app.close()


def test_status_io_error_propagates_once_and_releases_lock(tmp_path, monkeypatch):
    papers = tmp_path / "papers"
    papers.mkdir()
    app = ResearchApplication([papers], tmp_path / "workspace")
    app._save_job(_receipt("COMPLETED"))
    original = research_app.read_json
    calls = []

    def denied(path):
        calls.append(path)
        raise PermissionError("genuine permission denial must remain visible")

    try:
        monkeypatch.setattr(research_app, "read_json", denied)
        with pytest.raises(PermissionError):
            app.get_run_status(JOB)
        assert len(calls) == 1
        monkeypatch.setattr(research_app, "read_json", original)
        assert app.get_run_status(JOB)["status"] == "COMPLETED"
    finally:
        app.close()


def test_history_status_resolution_and_mtime_share_short_io_lock(tmp_path, monkeypatch):
    papers = tmp_path / "papers"
    papers.mkdir()
    app = ResearchApplication([papers], tmp_path / "workspace")
    app._save_job(_receipt())
    owner = _lock_job_owner(app.workspace / "jobs" / JOB / ".owner", create=True)
    assert owner is not None
    original_io, original_path = app._job_status_io, app.path
    original_status, original_stat = app.get_run_status, Path.stat
    local = threading.local()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    errors, snapshots = [], []

    @contextmanager
    def observed_io(path):
        with original_io(path):
            local.depth = getattr(local, "depth", 0) + 1
            try:
                yield
            finally:
                local.depth -= 1

    def observed_path(path, *, write=False):
        if (
            Path(path).name == "status.json"
            and threading.current_thread().name == "history"
        ):
            assert local.depth == 1
        return original_path(path, write=write)

    def observed_stat(path, *args, **kwargs):
        if path.name == "status.json" and threading.current_thread().name == "history":
            assert local.depth == 1
            with path.open("rb"):
                entered.set()
                assert release.wait(3)
        return original_stat(path, *args, **kwargs)

    def observed_status(*args, **kwargs):
        # A second OS lock on the same file must not be nested in the history
        # snapshot lock. Its own fresh reads acquire/release the protocol again.
        assert getattr(local, "depth", 0) == 0
        return original_status(*args, **kwargs)

    monkeypatch.setattr(app, "_job_status_io", observed_io)
    monkeypatch.setattr(app, "path", observed_path)
    monkeypatch.setattr(Path, "stat", observed_stat)
    monkeypatch.setattr(app, "get_run_status", observed_status)

    def history():
        try:
            snapshots.append(app.list_research_runs())
        except Exception:
            errors.append(traceback.format_exc())

    def write():
        try:
            app._save_job(_receipt("COMPLETED", 1))
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            finished.set()

    reader = threading.Thread(target=history, name="history")
    writer = threading.Thread(target=write)
    try:
        reader.start()
        assert entered.wait(3)
        writer.start()
        assert not finished.wait(0.05)
        release.set()
        reader.join(3)
        writer.join(3)
        assert not reader.is_alive() and not writer.is_alive() and not errors
        assert snapshots and not snapshots[0]["unavailable"]
        row = next(r for r in snapshots[0]["runs"] if r["job_id"] == JOB)
        assert row["status"] in {"RUNNING", "COMPLETED"}
        assert row["history_kind"] == "application_job"
        current = app.list_research_runs()
        assert not current["unavailable"]
        assert (
            next(r for r in current["runs"] if r["job_id"] == JOB)["status"]
            == "COMPLETED"
        )
    finally:
        release.set()
        reader.join(3)
        if writer.ident is not None:
            writer.join(3)
        owner.close()
        app.close()
