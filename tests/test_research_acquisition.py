"""Public acquisition uses real batch/checkpoints and source gates, mocked network only."""

import json
import runpy
from pathlib import Path

import pytest

from aletheia_nexus.acquire.access import service
from aletheia_nexus.acquire.discovery.models import DiscoveryResult, FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionResult, AcquisitionStatus
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
)
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import ResearchApplication, read_json

FIXTURE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/generate_v07_fixtures.py")
)


@pytest.fixture
def public_network(tmp_path, monkeypatch):
    calls = []
    state = {"second_available": False}

    def public(doi, *, output_dir, **kwargs):
        calls.append(doi)
        assert kwargs["max_route_attempts"] == kwargs["max_file_attempts"] == 4
        candidate = FullTextCandidate(
            doi=doi, url="https://example.org/article.pdf", provenance=()
        )
        discovery = DiscoveryResult(doi=doi, candidates=(candidate,), providers=())
        if doi.endswith("second") and not state["second_available"]:
            return MultiRouteAcquisitionResult(
                doi=doi, status=FullTextAcquisitionStatus.EXHAUSTED, discovery=discovery
            )
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf = output_dir / (doi.rsplit("/", 1)[1] + ".pdf")
        FIXTURE["_write_pdf"](
            pdf,
            [
                [
                    (50, 730, 14, "Self-authored public acquisition test"),
                    (50, 680, 12, doi),
                ]
            ],
            title="Self-authored public acquisition test",
        )
        FIXTURE["_sidecar"](pdf, doi)
        verified = AcquisitionResult(
            candidate=candidate, status=AcquisitionStatus.VERIFIED, file_path=pdf
        )
        return MultiRouteAcquisitionResult(
            doi=doi,
            status=FullTextAcquisitionStatus.VERIFIED,
            discovery=discovery,
            verified_result=verified,
        )

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "public acquisition must not escalate to browser/official credentials"
        )

    monkeypatch.setattr(service, "acquire_full_text", public)
    monkeypatch.setattr(service, "applicable_browser_providers", forbidden)
    monkeypatch.setattr(service.ElsevierAccessConfig, "from_env", forbidden)
    yield calls, state


def make_app(tmp_path, **kwargs):
    papers = tmp_path / "papers"
    papers.mkdir(exist_ok=True)
    return ResearchApplication([papers], tmp_path / "results", **kwargs)


def request():
    return {"papers": [{"doi": "10.5555/first"}, {"doi": "10.5555/second"}]}


def test_independent_network_switch_preview_and_scope_bound_one_use(
    tmp_path, public_network
):
    calls, _ = public_network
    app = make_app(tmp_path, remote=True)
    try:
        with pytest.raises(ProcessingError, match="network_disabled"):
            app.acquire_documents(request())
        app.network = True
        preview = app.acquire_documents(request())
        assert (
            preview["status"] == "AUTHORIZATION_REQUIRED"
            and not preview["network_access"]
        )
        saved = read_json(Path(preview["authorization_request"]))
        assert saved["scope"] == "acquire" and calls == []
        with pytest.raises(ProcessingError, match="local_authorization_required"):
            app.acquire_documents(
                request(), authorization="confirmed=true", background=False
            )
        token = app.authorize("acquire", request())
        with pytest.raises(ProcessingError, match="expired_or_changed"):
            app.acquire_documents(
                {"papers": [{"doi": "10.5555/other"}]},
                authorization=token,
                background=False,
            )
        job = app.acquire_documents(request(), authorization=token, background=False)
        assert job["status"] == "PARTIAL" and job["kind"] == "acquisition"
        assert job["model_calls"] == 0 and len(job["items"]) == 2
        assert (
            job["items"][0]["identity_verified"]
            and job["items"][1]["public_status"] == "EXHAUSTED"
        )
        assert app.get_run_status(job["job_id"])["items"] == job["items"]
        with pytest.raises(ProcessingError, match="missing_or_used"):
            app.acquire_documents(request(), authorization=token, background=False)
    finally:
        app.close()


def test_resume_copies_only_verified_bytes_and_retries_failed_item(
    tmp_path, public_network
):
    calls, state = public_network
    app = make_app(tmp_path, network=True)
    try:
        first = app.acquire_documents(
            request(),
            authorization=app.authorize("acquire", request()),
            background=False,
        )
        old_paths = [
            Path(first["checkpoint"]),
            Path(first["items"][0]["pdf"]),
            Path(first["items"][0]["sidecar"]),
        ]
        old_hashes = {p: sha256_file(p) for p in old_paths}
        state["second_available"] = True
        resume = {**request(), "resume_job_id": first["job_id"]}
        recovered = app.acquire_documents(
            resume, authorization=app.authorize("acquire", resume), background=False
        )
        assert recovered["status"] == "COMPLETED"
        assert recovered["job_id"] != first["job_id"]
        assert recovered["items"][0]["resumed"] and not recovered["items"][1]["resumed"]
        assert calls == ["10.5555/first", "10.5555/second", "10.5555/second"]
        assert all(sha256_file(p) == checksum for p, checksum in old_hashes.items())
        assert Path(recovered["items"][0]["pdf"]) != old_paths[1]
        assert (
            sha256_file(Path(recovered["items"][0]["pdf"])) == old_hashes[old_paths[1]]
        )
        prepared = app.prepare_documents([row["pdf"] for row in recovered["items"]])
        assert len(prepared["documents"]) == 2 and not prepared["failures"]
    finally:
        app.close()


def test_resume_checkpoint_change_and_out_of_job_paths_are_rejected(
    tmp_path, public_network
):
    app = make_app(tmp_path, network=True)
    try:
        first = app.acquire_documents(
            request(),
            authorization=app.authorize("acquire", request()),
            background=False,
        )
        resume = {**request(), "resume_job_id": first["job_id"]}
        token = app.authorize("acquire", resume)
        path = Path(first["checkpoint"])
        data = read_json(path)
        data["changed_after_approval"] = True
        path.write_text(json.dumps(data), "utf-8")
        with pytest.raises(ProcessingError, match="expired_or_changed"):
            app.acquire_documents(resume, authorization=token, background=False)
        entry = next(r for r in data["records"].values() if r["status"] == "VERIFIED")
        entry["verified_path"] = str(app.roots[0] / "unselected.pdf")
        path.write_text(json.dumps(data), "utf-8")
        with pytest.raises(ProcessingError, match="checkpoint_path_outside_job"):
            app.acquire_documents(resume)
        with pytest.raises(ProcessingError, match="resume_scope_changed"):
            app.acquire_documents(
                {"papers": [{"doi": "10.5555/first"}], "resume_job_id": first["job_id"]}
            )
    finally:
        app.close()


def test_public_only_rejects_title_only_and_cnki_before_any_access(
    tmp_path, public_network
):
    from aletheia_nexus.core.paper_request import PaperRequest

    calls, _ = public_network
    with pytest.raises(ValueError, match="requires a DOI"):
        service.acquire_full_text_maximized(
            PaperRequest(title="A title"), output_dir=tmp_path, public_only=True
        )
    with pytest.raises(ValueError, match="CNKI"):
        service.acquire_full_text_maximized(
            "10.5555/first",
            output_dir=tmp_path,
            public_only=True,
            source_preference="cnki",
        )
    assert calls == []


def test_interruption_before_checkpoint_restarts_only_approved_scope(
    tmp_path, public_network
):
    calls, state = public_network
    app = make_app(tmp_path, network=True)
    try:
        first = app.acquire_documents(
            request(),
            authorization=app.authorize("acquire", request()),
            background=False,
        )
        Path(first["checkpoint"]).unlink()
        resume = {**request(), "resume_job_id": first["job_id"]}
        preview = app.acquire_documents(resume)
        assert "未留下断点文件" in preview["plan"]
        state["second_available"] = True
        recovered = app.acquire_documents(
            resume, authorization=app.authorize("acquire", resume), background=False
        )
        assert recovered["status"] == "COMPLETED"
        assert not any(item["resumed"] for item in recovered["items"])
        assert calls == ["10.5555/first", "10.5555/second"] * 2
    finally:
        app.close()
