"""Task-owned browser wait wiring; no browser, publisher or model is contacted."""

import json
import time
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench import acquisition
from aletheia_nexus.workbench.jobs import TERMINAL, TaskContext, TaskManager
from aletheia_nexus.workbench.settings import SettingsStore

DOI = "10.1000/auto-wait-fixture"
URL = "https://publisher.example.test/login?session=do-not-persist"
CHALLENGE = ChallengeReport(ChallengeKind.AUTHENTICATION)
CLEAR = ChallengeReport(ChallengeKind.NONE)


class StubSession:
    def __init__(self, config):
        self.config = config
        self.connection_diagnostic = None
        self.owner = None
        self.pumps = []
        self.closed = False

    def __enter__(self):
        self.owner = get_ident()
        return self

    def __exit__(self, *_):
        self.closed = True

    def pump_events(self, seconds=0.25):
        assert get_ident() == self.owner
        self.pumps.append(seconds)
        time.sleep(min(seconds, 0.005))


@pytest.fixture
def harness(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    pdf = root / "fixture.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    sidecar = acquisition_sidecar_path(pdf)
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/acquisition-record/v1",
                "status": "VERIFIED",
                "target": {"doi": DOI, "expected_title": "Engineering fixture"},
                "retrieval": {"sha256": sha256_file(pdf)},
                "pdf_validation": {"valid_pdf": True, "page_count": 1},
                "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
            }
        ),
        encoding="utf-8",
    )
    manager = TaskManager(tmp_path / "workspace", max_workers=1)
    state = SimpleNamespace(
        manager=manager,
        service=acquisition.AcquisitionService(root),
        pdf=pdf,
        sidecar=sidecar,
        sessions=[],
        calls=[],
        native_retries=[],
        deadlines=[],
        waits=[],
        polls=[],
        after_wait=[],
        entered=Event(),
        polled=Event(),
        callback_returned=Event(),
        release=Event(),
        final_report=CLEAR,
    )

    def session(config):
        value = StubSession(config)
        state.sessions.append(value)
        return value

    native_wait, native_poll = (
        TaskContext.wait_interaction,
        TaskContext.poll_interaction,
    )

    def observed_wait(context, details, timeout=None, *, pump=None):
        state.waits.append((details, timeout, pump))
        return native_wait(context, details, timeout, pump=pump)

    def observed_poll(context, *, pump=None):
        state.polls.append(pump)
        return native_poll(context, pump=pump)

    def batch(requests, *, browser_session, **kwargs):
        state.calls.append((requests, kwargs))
        config = browser_session.config
        # Model the native Exception-as-retry boundary. Adapter control signals
        # must leave it without purchasing another acquisition attempt.
        for attempt in range(2):
            try:
                state.entered.set()
                config.interaction_callback(CHALLENGE, URL)
                state.callback_returned.set()
                report = CLEAR
                if config.interaction_poll_callback is not None:
                    deadline = (
                        None
                        if config.wait_for_interaction
                        else time.monotonic() + config.interaction_timeout
                    )
                    state.deadlines.append(deadline)
                    safety_deadline = time.monotonic() + 4
                    while True:
                        config.interaction_poll_callback("poll", CHALLENGE, URL)
                        state.polled.set()
                        if state.release.is_set():
                            report = state.final_report
                            break
                        if deadline is not None and time.monotonic() >= deadline:
                            report = CHALLENGE
                            break
                        assert time.monotonic() < safety_deadline, (
                            "stub wait did not end"
                        )
                        state.release.wait(0.005)
                    config.interaction_poll_callback("resolved", report, URL)
                state.after_wait.append(report.kind)
                status = (
                    BatchItemStatus.VERIFIED
                    if report.kind == ChallengeKind.NONE
                    else BatchItemStatus.INTERACTION_REQUIRED
                )
                return SimpleNamespace(
                    items=[
                        BatchAcquisitionItem(
                            requests[0],
                            requests[0].doi,
                            status,
                            verified_path=pdf
                            if status == BatchItemStatus.VERIFIED
                            else None,
                            attempts=1,
                        )
                    ]
                )
            except Exception as exc:
                state.native_retries.append(type(exc).__name__)
                if attempt:
                    raise

    monkeypatch.setattr(acquisition, "BrowserSession", session)
    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    monkeypatch.setattr(TaskContext, "wait_interaction", observed_wait)
    monkeypatch.setattr(TaskContext, "poll_interaction", observed_poll)

    def submit(**overrides):
        options = {
            "public_only": False,
            "browser_enabled": True,
            "include_si": False,
            "interaction_policy": "wait",
            "interaction_timeout": 0,
            **overrides,
        }
        return manager.submit(
            "acquisition",
            "Engineering wait fixture",
            [DOI],
            lambda context: state.service.run([DOI], options, context),
            parameters={"options": options},
        )

    state.submit = submit
    try:
        yield state
    finally:
        state.release.set()
        for receipt in manager.list():
            if receipt["status"] not in TERMINAL:
                manager.control(receipt["id"], "cancel")
        manager.close(wait=True)


def receipt_when(state, job, predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        receipt = state.manager.get(job["id"])
        if predicate(receipt):
            return receipt
        time.sleep(0.005)
    raise AssertionError(state.manager.get(job["id"]))


def terminal(state, job):
    return receipt_when(state, job, lambda receipt: receipt["status"] in TERMINAL)


@pytest.mark.parametrize("timeout", [0, 17.5])
def test_auto_wait_completes_without_ui_continue_and_keeps_one_core_deadline(
    harness, timeout
):
    original = (harness.pdf.read_bytes(), harness.sidecar.read_bytes())
    job = harness.submit(interaction_timeout=timeout)
    assert harness.polled.wait(2)
    waiting = harness.manager.get(job["id"])
    assert waiting["status"] == "INTERACTION_REQUIRED"
    assert waiting["interaction"]["auto_monitoring"] is True
    harness.release.set()  # Simulated human completion, not a UI continue command.
    receipt = terminal(harness, job)
    assert receipt["status"] == "COMPLETED", receipt
    assert receipt["result"]["items"][0]["identity_verified"] is True
    assert receipt["last_interaction"]["resolution"] == "auto_detected"
    assert harness.waits == [] and len(harness.deadlines) == 1
    config = harness.sessions[0].config
    assert config.wait_for_interaction is (timeout == 0)
    if timeout:
        assert config.interaction_timeout == timeout
        assert harness.deadlines[0] is not None
    else:
        assert harness.deadlines[0] is None
    assert harness.polls and all(
        pump.__self__ is harness.sessions[0] for pump in harness.polls
    )
    assert not any(event.get("action") == "continue" for event in receipt["events"])
    assert "do-not-persist" not in json.dumps(receipt)
    assert "interaction_poll_callback" not in json.dumps(receipt)
    assert original == (harness.pdf.read_bytes(), harness.sidecar.read_bytes())


@pytest.mark.parametrize(
    "options",
    [{"auto_resume_interaction": False}, {"interaction_policy": "pause"}],
)
def test_manual_or_pause_policy_requires_explicit_continue(harness, options):
    job = harness.submit(**options)
    receipt_when(harness, job, lambda receipt: receipt.get("interaction") is not None)
    harness.release.set()
    assert not harness.callback_returned.wait(0.05)
    assert harness.sessions[0].config.interaction_poll_callback is None
    harness.manager.control(job["id"], "continue")
    receipt = terminal(harness, job)
    assert receipt["status"] == "COMPLETED", receipt
    assert len(harness.waits) == 1 and harness.waits[0][1] is None
    assert harness.waits[0][2].__self__ is harness.sessions[0]
    assert harness.polls == []


def test_no_task_context_does_not_enable_auto_monitoring(harness):
    result = harness.service.run(
        [DOI],
        {
            "public_only": False,
            "browser_enabled": True,
            "include_si": False,
            "interaction_policy": "wait",
            "auto_resume_interaction": True,
            "interaction_timeout": 0,
        },
    )
    assert result["status"] == "COMPLETED"
    assert harness.sessions[0].config.interaction_poll_callback is None
    assert harness.sessions[0].config.wait_for_interaction is False
    assert harness.waits == [] and harness.polls == []


def test_manual_finite_timeout_still_skips_without_entering_native_retry(harness):
    job = harness.submit(auto_resume_interaction=False, interaction_timeout=0.03)
    receipt = terminal(harness, job)
    assert receipt["result"]["items"][0]["status"] == "SKIPPED"
    assert len(harness.waits) == 1 and harness.waits[0][1] == 0.03
    assert harness.native_retries == [] and harness.after_wait == []


def test_explicit_task_pause_is_not_cleared_by_auto_ready(harness):
    job = harness.submit()
    assert harness.polled.wait(2)
    harness.manager.control(job["id"], "pause")
    receipt_when(harness, job, lambda receipt: receipt["status"] == "PAUSED")
    harness.release.set()
    assert not harness.after_wait
    assert harness.manager.get(job["id"])["status"] == "PAUSED"
    harness.manager.control(job["id"], "resume")
    assert terminal(harness, job)["status"] == "COMPLETED"


def test_ui_continue_requests_a_recheck_but_does_not_clear_a_challenge(harness):
    job = harness.submit()
    assert harness.polled.wait(2)
    harness.manager.control(job["id"], "continue")
    waiting = receipt_when(
        harness,
        job,
        lambda receipt: receipt.get("interaction_resolution") == "recheck_requested",
    )
    assert waiting["status"] == "INTERACTION_REQUIRED"
    assert waiting["interaction"] is not None and harness.after_wait == []
    harness.final_report = CHALLENGE
    harness.release.set()
    receipt = terminal(harness, job)
    assert receipt["last_interaction"]["resolution"] == "not_ready"
    assert receipt["result"]["success"] == 0


@pytest.mark.parametrize("timeout", [0, 0.03])
def test_still_challenged_resolution_is_not_verified_and_has_no_second_boundary_wait(
    harness, timeout
):
    harness.final_report = CHALLENGE
    if timeout == 0:
        harness.release.set()
    job = harness.submit(interaction_timeout=timeout)
    receipt = terminal(harness, job)
    assert receipt["result"]["items"][0]["status"] == "INTERACTION_REQUIRED"
    assert receipt["result"]["success"] == 0
    assert receipt["last_interaction"]["resolution"] == "not_ready"
    assert harness.waits == [] and len(harness.calls) == 1
    assert len(harness.deadlines) == 1


def test_cleared_challenge_still_requires_real_pdf_hash_verification(harness):
    harness.pdf.write_bytes(harness.pdf.read_bytes() + b" changed fixture")
    harness.release.set()
    receipt = terminal(harness, harness.submit())
    assert receipt["status"] == "FAILED"
    assert "PDF_HASH_MISMATCH" in json.dumps(receipt)
    assert not any(row["status"] == "VERIFIED" for row in receipt["records"])


@pytest.mark.parametrize(
    "action", ["skip", "cancel", "cancel_and_continue", "cancel_and_skip"]
)
def test_skip_and_cancel_escape_native_retries_with_cancel_priority(harness, action):
    job = harness.submit()
    assert harness.polled.wait(2)
    with harness.manager._condition:
        if action.startswith("cancel"):
            harness.manager.control(job["id"], "cancel")
            if action != "cancel":
                harness.manager.control(job["id"], action.removeprefix("cancel_and_"))
        else:
            harness.manager.control(job["id"], "skip")
    receipt = terminal(harness, job)
    assert len(harness.calls) == 1 and harness.native_retries == []
    assert harness.after_wait == []
    if action == "skip":
        row = receipt["result"]["items"][0]
        assert row["status"] == "SKIPPED" and "pdf" not in row
        assert receipt["last_interaction"]["resolution"] == "skip"
    else:
        assert receipt["status"] == "CANCELLED"
        assert receipt["last_interaction"]["resolution"] == "cancelled"


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_auto_resume_option_is_strictly_boolean(value):
    with pytest.raises(ValueError, match="auto_resume_interaction"):
        acquisition._options({"auto_resume_interaction": value})


def test_callbacks_remain_runtime_only_not_defaults_or_saved_presets(tmp_path):
    defaults = acquisition.get_acquisition_defaults()
    assert defaults["auto_resume_interaction"] is True
    for callback in ("interaction_callback", "interaction_poll_callback"):
        assert callback not in defaults["browser"]
        with pytest.raises(ValueError, match="unsupported browser"):
            acquisition._options({"browser": {callback: None}})
    for enabled in (False, True):
        assert (
            acquisition._options({"auto_resume_interaction": enabled})[
                "auto_resume_interaction"
            ]
            is enabled
        )
    settings = SettingsStore(tmp_path)
    settings.set("acquisition", defaults)
    settings.save_preset("acquisition", "工程等待参数", defaults)
    reopened = SettingsStore(tmp_path)
    assert reopened.get("acquisition") == defaults
    assert reopened.load_preset("acquisition", "工程等待参数") == defaults
    saved = settings.path.read_text(encoding="utf-8")
    assert (
        "interaction_poll_callback" not in saved and "interaction_callback" not in saved
    )
