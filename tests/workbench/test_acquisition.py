from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import acquisition
from aletheia_nexus.workbench.acquisition import AcquisitionService


def work(doi, title="Selective electrocatalytic reduction", year=2026, author="Smith"):
    return {
        "DOI": doi,
        "title": [title],
        "author": [{"family": author}],
        "published": {"date-parts": [[year]]},
        "container-title": ["Research Journal"],
    }


def search(*works):
    return lambda *args, **kwargs: {"message": {"items": list(works)}}


def test_preview_inputs_preserves_citations_and_deduplicates(tmp_path):
    service = AcquisitionService(tmp_path)
    preview = service.preview_inputs(
        "10.1000/abc\nhttps://doi.org/10.1000/abc\n碳酸电还原\nSelective reduction of carboxylic acids"
    )
    assert preview["count"] == 3
    assert preview["items"][1]["duplicate"] is True
    assert preview["items"][2]["request"]["title"] == "碳酸电还原"
    papers = tmp_path / "papers.csv"
    papers.write_text(
        "doi,title,year,authors,tags\n10.1000/abc,Test title,2026,Jane Smith;Ray Doe,review;electro\n",
        encoding="utf-8-sig",
    )
    row = service.preview_inputs(papers)["items"][0]["request"]
    assert row["year"] == 2026 and row["authors"] == ("Jane Smith", "Ray Doe")
    assert row["tags"] == ("review", "electro")


def test_title_resolution_requires_unique_identity_and_checks_constraints(tmp_path):
    service = AcquisitionService(tmp_path)
    request = {
        "title": "Selective electrocatalytic reduction",
        "authors": ["Smith"],
        "year": 2026,
    }
    assert (
        service.resolve_title(request, fetch=search(work("10.1000/a")))["status"]
        == "RESOLVED"
    )
    result = service.resolve_title(
        request, fetch=search(work("10.1000/a"), work("10.1000/b"))
    )
    assert result["status"] == "AMBIGUOUS" and result["request"] is None
    result = service.resolve_title(request, fetch=search(work("10.1000/a", year=2024)))
    assert result["status"] == "AMBIGUOUS"
    assert result["candidates"][0]["conflicts"] == ["year"]
    assert service.resolve_title(request, fetch=search())["status"] == "NOT_FOUND"
    # Similarity alone never manufactures or automatically chooses a DOI.
    assert (
        service.resolve_title(
            request,
            fetch=search(
                work("10.1000/a", title="Selective electrocatalytic reduction of acids")
            ),
        )["request"]
        is None
    )
    assert (
        service.resolve_title(
            "碳酸电还原",
            fetch=lambda *a, **kw: pytest.fail("CNKI must not search Crossref"),
        )["status"]
        == "CNKI_TITLE"
    )


def test_run_maps_complete_parameters_and_honors_item_boundaries(tmp_path, monkeypatch):
    service = AcquisitionService(tmp_path)
    calls, events = [], []

    def batch(papers, **kwargs):
        calls.append((papers, kwargs))
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    papers[0], papers[0].doi, BatchItemStatus.EXHAUSTED
                )
            ]
        )

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)

    class Context:
        def checkpoint(self):
            events.append("boundary")

        def should_skip(self, key):
            return key.endswith("never")

        def progress(self, *args, **kwargs):
            events.append(kwargs.get("stage"))

        def record(self, *args, **kwargs):
            events.append("record")

    result = service.run(
        ["10.1000/a", "10.1000/b"],
        {
            "include_si": False,
            "max_item_attempts": 2,
            "retry_backoff": 3,
            "timeout": 17,
            "max_route_attempts": 7,
            "browser_enabled": True,
            "public_only": False,
            "browser": {"cnki_paper_interval": 13},
        },
        Context(),
    )
    assert result["status"] == "FAILED" and len(calls) == 2
    assert calls[0][1]["timeout"] == 17
    assert calls[0][1]["max_route_attempts"] == 7
    assert calls[0][1]["max_item_attempts"] == 2
    assert calls[0][1]["retry_backoff"] == 3
    assert calls[0][1]["browser_session"] is calls[1][1]["browser_session"]
    assert calls[0][1]["browser_session"].config.cnki_paper_interval == 13
    assert events.count("boundary") == 4
    assert Path(result["checkpoint"]).is_relative_to(service.state_dir)


def test_run_rejects_unresolved_titles_and_unsafe_checkpoint(tmp_path, monkeypatch):
    service = AcquisitionService(tmp_path)
    monkeypatch.setattr(
        acquisition,
        "acquire_full_text_batch_maximized",
        lambda *a, **k: pytest.fail("must validate before network"),
    )
    with pytest.raises(ValueError, match="resolve and confirm"):
        service.run(["An unresolved English title"])
    with pytest.raises(ValueError, match="checkpoint"):
        service.run(["10.1000/a"], checkpoint_path=tmp_path.parent / "bad.json")
    with pytest.raises(ValueError, match="unsupported acquisition options"):
        service.run(["10.1000/a"], {"api_key": "secret"})
    with pytest.raises(ValueError, match="explicitly enabling"):
        service.run(["10.1000/a"], {"public_only": False})


def test_checkpoint_resume_still_validates_source_not_only_recorded_hash(
    tmp_path, monkeypatch
):
    pdf = tmp_path / "wrong.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open("wb") as handle:
        writer.write(handle)
    registered = register_local_pdf(
        pdf, output_dir=tmp_path, title="User declared", doi="10.1000/a"
    )
    original = sha256_file(registered)

    def batch(papers, **kwargs):
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    papers[0],
                    "10.1000/a",
                    BatchItemStatus.VERIFIED,
                    verified_path=registered,
                    resumed=True,
                )
            ]
        )

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    with pytest.raises(ValueError, match="unverified main"):
        AcquisitionService(tmp_path).run(["10.1000/a"], {"include_si": False})
    assert sha256_file(registered) == original
