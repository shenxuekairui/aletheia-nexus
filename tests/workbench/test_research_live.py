"""No HTTP: observe a blocked mock call, ambiguous runs and orphaned receipts."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_research import research as research_fixture

from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.research_app import read_json
from aletheia_nexus.workbench.research_live import LiveResearchRuns


@pytest.fixture(name="research")
def live_research(tmp_path):
    yield from research_fixture.__wrapped__(tmp_path)


def test_observe_inflight_cost_and_group_progress_without_new_requests(research):
    main = research.library.get("p1")
    si = register_local_pdf(
        research.library.get("p2")["pdf_path"],
        output_dir=research.library.root / "SI",
        title="Explicit supplement",
        role="SUPPLEMENT",
        parent_pdf=main["pdf_path"],
        parent_sidecar=main["sidecar_path"],
    )
    main["attachments"].append(
        {
            "id": "si_live",
            "path": str(si),
            "role": "SUPPLEMENT",
            "sidecar_path": str(acquisition_sidecar_path(si)),
        }
    )
    task = research.local_plan("观察现有请求", ["p1"], include_si=True, mode="parsed")
    entered, release = Event(), Event()

    class Context:
        job_id = "f" * 32
        updates = []

        def checkpoint(self):
            pass

        def record(self, *args, **kwargs):
            pass

        def progress(self, current, total, **kwargs):
            self.updates.append({"current": current, "total": total, **kwargs})

    class Provider:
        identity = {"provider": "blocked-mock"}
        count = 0

        def generate(self, request, schema, images, budget, max_output_tokens):
            self.count += 1
            row = budget.reserve(0.02)
            row["phase"] = "document_extraction"
            budget.checkpoint()
            entered.set()
            assert release.wait(20)
            row.update(
                status="completed",
                estimated_cost=0.001,
                usage={"input_tokens": 1, "output_tokens": 1},
            )
            budget.checkpoint()
            source = request["material"]["documents"][0]
            return {
                "records": [],
                "claims": [],
                "requests": [],
                "issues": [
                    {
                        "kind": "material_insufficient",
                        "detail": "Self-authored mock only",
                        "source_id": source["id"],
                        "page": 1,
                    }
                ],
            }

    provider, context = Provider(), Context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            research.execute, task, consent=True, context=context, provider=provider
        )
        try:
            assert entered.wait(10)
            live = research.live_run(context.job_id)
            assert live["status"] == "RUNNING"
            assert live["material_count"] == 2 and live["group_count"] == 1
            assert live["progress_current"] == 0 and live["progress_total"] == 1
            assert live["current_item"]["title"] == "Alpha catalysis"
            assert (
                len(live["calls"]) == 1 and live["calls"][0]["estimated_cost"] is None
            )
            assert live["calls"][0]["reserved_cost"] == 0.02
            assert live["phase_label"] == "单篇科研提取"
            # A simultaneous, identical task cannot be guessed to be this run.
            copy = read_json(research.app.path(live["manifest"]))
            ambiguous = (
                research.workspace / "research" / "runs" / "ambiguous" / "manifest.json"
            )
            write_json(ambiguous, copy)
            assert research.live_run(context.job_id)["status"] == "UNCERTAIN"
            assert research.live_run(context.job_id)["calls"] is None
            ambiguous.unlink()
            assert provider.count == 1
        finally:
            release.set()
        receipt = future.result(timeout=10)
    final = research.live_run(receipt["job_id"])
    assert final["status"] == "PARTIAL" and final["finished_groups"] == 1
    assert final["finished_materials"] == 2
    assert context.updates[-1]["current"] == context.updates[-1]["total"] == 1
    reloaded = LiveResearchRuns(research.app).get(receipt["job_id"])
    assert len(reloaded["calls"]) == 1 and provider.count == 1


def test_live_read_does_not_rewrite_orphaned_state_or_invent_zero(research):
    task = research.local_plan("读取中断记录", ["p1"])
    checked = research.validate_plan(task)
    native_id = "e" * 32
    directory = research.workspace / "jobs" / native_id
    receipt = {"job_id": native_id, "status": "RUNNING"}
    research.live.register(receipt, checked, set())
    write_json(directory / "status.json", receipt)
    (directory / ".owner").write_bytes(b"0")
    before = (directory / "status.json").read_bytes()
    live = research.live_run(native_id)
    assert live["status"] == "INTERRUPTED"
    assert live["calls"] is None and live["usage"] is None
    assert (directory / "status.json").read_bytes() == before
    assert research.live_run("unknown")["calls"] is None
