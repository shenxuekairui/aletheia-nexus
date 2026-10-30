"""Same DOI is a review hint, never authority to merge distinct declarations."""

import shutil
from pathlib import Path

from pypdf import PdfWriter

from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench.library import LibraryService


def add(library, directory, name, width):
    path = directory / (name + ".pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=200)
    with path.open("wb") as handle:
        writer.write(handle)
    return library.import_pdf(path, title="Same-title fixture", doi="10.1000/Same")


def test_same_doi_sources_are_diagnosed_without_changing_ids_or_registry(tmp_path):
    library = LibraryService(tmp_path / "library")
    papers = [add(library, tmp_path, "one", 200), add(library, tmp_path, "two", 210)]
    ids = [paper["id"] for paper in papers]
    assert len(set(ids)) == 2
    library.set_selection(ids[:1])
    library.save_collection("版本核对", ids)
    library.scan()
    registry = library.state_path.read_bytes()
    paths = [
        Path(paper[key]) for paper in papers for key in ("pdf_path", "sidecar_path")
    ]
    evidence = [path.read_bytes() for path in paths]
    report = library.scan()
    assert {row["id"] for row in report["items"]} == set(ids)
    warning = next(w for w in report["warnings"] if w.get("doi") == "10.1000/same")
    assert set(warning["paper_ids"]) == set(ids) and warning["count"] == 2
    assert "多个来源或版本" in warning["error"]
    assert library.selection() == ids[:1] and library.collections()["版本核对"] == ids
    assert library.state_path.read_bytes() == registry
    assert [path.read_bytes() for path in paths] == evidence


def test_identical_source_copy_stays_one_identity_instead_of_multiple_doi_versions(
    tmp_path,
):
    library = LibraryService(tmp_path / "library")
    paper = add(library, tmp_path, "one", 200)
    copied = library.root / "另一分类" / "copy.pdf"
    copied.parent.mkdir()
    shutil.copyfile(paper["pdf_path"], copied)
    sidecar = acquisition_sidecar_path(copied)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paper["sidecar_path"], sidecar)
    report = library.scan()
    assert report["total"] == 1 and report["items"][0]["id"] == paper["id"]
    assert report["items"][0]["duplicate_paths"] == [str(copied)]
    assert not any(w.get("doi") == "10.1000/same" for w in report["warnings"])
