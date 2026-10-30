"""Real acquisition metadata reaches the grid without rewriting source evidence."""

import json
from types import SimpleNamespace

from pypdf import PdfWriter

from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.models import PaperMetadata
from aletheia_nexus.workbench import acquisition
from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.library import LibraryService


def test_doi_only_acquisition_fills_engine_bibliography_and_keeps_source(
    tmp_path, monkeypatch
):
    library = LibraryService(tmp_path / "library")
    main = library.root / "fixture.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with main.open("wb") as handle:
        writer.write(handle)
    # This deliberately synthetic source receipt tests application behavior;
    # it is not evidence of a live main-PDF identity-verification result.
    source_record = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "status": "VERIFIED",
        "target": {
            "doi": "10.1000/metadata",
            "expected_title": "Original source title",
        },
        "retrieval": {"sha256": sha256_file(main)},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    sidecar = acquisition_sidecar_path(main)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(source_record), encoding="utf-8")
    evidence_bytes = sidecar.read_bytes()
    metadata = PaperMetadata(
        doi="10.1000/metadata",
        title="Actual engine metadata title",
        authors=("Jane Smith", "Ray Doe"),
        journal="Real Journal",
        issn=(),
        published_date="2026-10-01",
        year=2026,
        publisher="Actual publisher",
        work_type="journal-article",
        volume="12",
        issue="3",
        pages="1-8",
        url="https://example.org/metadata",
    )
    response = SimpleNamespace(base_result=SimpleNamespace(metadata=metadata))

    def batch(requests, **kwargs):
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    requests[0],
                    requests[0].doi,
                    BatchItemStatus.VERIFIED,
                    result=response,
                    verified_path=main,
                )
            ]
        )

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    service = AcquisitionService(library.root, library=library)
    report = service.run(["10.1000/metadata"], {"include_si": False})
    assert report["items"][0]["bibliography"]["status"] == "UPDATED"
    assert report["items"][0]["bibliography"]["network_requests"] == 0
    assert report["items"][0]["title"] == "Original source title"
    assert report["items"][0]["title_original"] == "Original source title"
    assert report["items"][0]["request"]["title"] is None
    row = library.scan()["items"][0]
    assert row["authors"] == ["Jane Smith", "Ray Doe"]
    assert row["first_author"] == "Jane Smith"
    assert row["year"] == 2026 and row["journal"] == "Real Journal"
    assert row["title_original"] == "Original source title"
    assert row["metadata"]["metadata_source"]["authors"]["doi"] == metadata.doi
    assert sidecar.read_bytes() == evidence_bytes
    library.update_metadata(
        row["id"],
        authors=["Researcher correction"],
        year=2025,
        journal="Researcher journal",
    )
    service.run(["10.1000/metadata"], {"include_si": False})
    row = library.get(row["id"])
    assert row["authors"] == ["Researcher correction"]
    assert row["year"] == 2025 and row["journal"] == "Researcher journal"
    assert sidecar.read_bytes() == evidence_bytes


def test_checkpoint_published_before_engine_work_for_interrupted_recovery(
    tmp_path, monkeypatch
):
    service = AcquisitionService(tmp_path)
    published = {}

    def batch(papers, **kwargs):
        assert published["checkpoint"] == str(kwargs["checkpoint_path"])
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    papers[0], papers[0].doi, BatchItemStatus.EXHAUSTED
                )
            ]
        )

    class Context:
        def progress(self, *args, **details):
            published.update(details)

        def checkpoint(self):
            pass

        def should_skip(self, key):
            return False

        def record(self, *args, **kwargs):
            pass

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    report = service.run(["10.1000/a"], {"include_si": False}, Context())
    assert report["checkpoint"] == published["checkpoint"]
