"""Retrying an attachment must not undo an existing user's physical filename."""

from pathlib import Path
from types import SimpleNamespace

from pypdf import PdfWriter

from aletheia_nexus.workbench.acquisition import normalize_request
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage


def test_si_only_postprocess_keeps_existing_name_and_source_bytes(
    tmp_path, monkeypatch
):
    incoming = tmp_path / "用户整理的短名称.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with incoming.open("wb") as handle:
        writer.write(handle)
    library = LibraryService(tmp_path / "library")
    paper = library.import_pdf(
        incoming, title="Long original scholarly title", folder="分类"
    )
    request = {"doi": "10.1000/si-only", "folder": "原分类"}
    # This test isolates the postprocessing boundary: acquisition source gates
    # and checkpoint reuse have independent native integration coverage.
    row = {"status": "VERIFIED", "pdf": paper["pdf_path"], "request": request}

    def run(*args, on_item=None, **kwargs):
        return {
            "status": "COMPLETED",
            "items": [on_item(row) or row if on_item else row],
        }

    page = AcquisitionPage()
    page.ctx = SimpleNamespace(
        library=library,
        acquisition=SimpleNamespace(run=run),
    )
    before_pdf = incoming.read_bytes()
    before_source = Path(paper["sidecar_path"]).read_bytes()

    def must_not_rename(*_args, **_kwargs):
        raise AssertionError("SI-only retry would undo the existing physical filename")

    monkeypatch.setattr(library, "preview_rename", must_not_rename)
    postprocess = {
        "template": "{year}-{journal}-{title_zh}",
        "preserve_existing_names_for": [normalize_request(request).key],
    }
    report = page.acquisition_worker([request], {"include_si": True}, postprocess)(
        SimpleNamespace(progress=lambda *a, **k: None)
    )
    assert report["status"] == "COMPLETED"
    assert Path(paper["pdf_path"]).name == incoming.name
    assert Path(paper["pdf_path"]).read_bytes() == before_pdf
    assert Path(paper["sidecar_path"]).read_bytes() == before_source
