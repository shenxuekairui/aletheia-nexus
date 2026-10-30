"""Cross-service fixtures: physical rename, evidence integrity and UI resume."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.paper_request import PaperRequest
from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.supplements import acquire_supplements


def make_pdf(path, width=200):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=200)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def test_checkpoint_rename_and_category_move_resume_by_verified_source_hash(
    tmp_path, monkeypatch
):
    """A synthetic VERIFIED receipt tests locators, never scientific validation."""
    from aletheia_nexus.acquire.access import batch as native_batch

    library = LibraryService(tmp_path / "library")
    original = make_pdf(library.root / "旧分类" / "original.pdf")
    sidecar = acquisition_sidecar_path(original)
    sidecar.parent.mkdir(parents=True)
    payload = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "status": "VERIFIED",
        "target": {"doi": "10.1000/fixture", "expected_title": "Fixture paper"},
        "retrieval": {"sha256": sha256_file(original)},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
    }
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    source = validate_parser_input(original)
    request = PaperRequest(
        doi="10.1000/fixture", title="Fixture paper", folder="旧分类"
    )
    service = AcquisitionService(library.root, library=library)
    checkpoint = service.state_dir / "original.checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/access-batch-checkpoint/v1",
                "records": {
                    request.batch_key: {
                        "doi": request.doi,
                        "status": "VERIFIED",
                        "verified_path": str(original),
                        "sha256": source.pdf_sha256,
                        "sidecar_sha256": source.sidecar_sha256,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    checkpoint_bytes = checkpoint.read_bytes()
    row = library.scan()["items"][0]
    library.update_metadata(
        row["id"],
        title_zh="人工确认的中文题目",
        translation={"confirmed": True, "source": "manual"},
    )
    preview = library.preview_rename([row["id"]], "{title_zh}", folder="新分类")
    assert preview["executable"] == 1, preview
    library.execute_rename(preview)
    relocated = library.scan()["items"][0]
    assert relocated["id"] == row["id"]
    assert Path(relocated["pdf_path"]).parent.name == "新分类"
    monkeypatch.setattr(
        native_batch,
        "_acquire_item",
        lambda *a, **k: pytest.fail(
            "relocated verified file must resume without downloading"
        ),
    )
    report = service.run([request], {"include_si": False}, checkpoint_path=checkpoint)
    assert report["status"] == "COMPLETED"
    assert report["items"][0]["resumed"] is True
    assert report["items"][0]["pdf"] == relocated["pdf_path"]
    assert report["items"][0]["request"]["folder"] == "新分类"
    assert checkpoint.read_bytes() == checkpoint_bytes
    assert report["checkpoint"] != str(checkpoint)
    assert len(report["relocations"]) == 1
    assert library.preview_rename([row["id"]], "{title_zh}-第二版")["executable"] == 1


def test_three_articles_share_si_and_rename_preserves_official_source_receipt(tmp_path):
    library = LibraryService(tmp_path / "library")
    supplement_bytes = make_pdf(tmp_path / "si.pdf", 150).read_bytes()
    fetched = []

    def fetch(url, output_dir, **kwargs):
        fetched.append(url)
        temporary = Path(output_dir) / ".si.part"
        temporary.write_bytes(supplement_bytes)
        return SimpleNamespace(
            local_path=temporary,
            sha256=hashlib.sha256(supplement_bytes).hexdigest(),
            final_url=url,
        )

    def page_for(doi):
        return f'<meta name="citation_doi" content="{doi}"><a href="/files/si.pdf">Supplementary Information</a>'

    def page_fetch(doi):
        return lambda *a, **kw: SimpleNamespace(
            text=page_for(doi),
            final_url="https://www.nature.com/articles/example",
            body_truncated=False,
        )

    for index in range(3):
        main = make_pdf(library.root / "羧酸还原" / f"paper-{index}.pdf", 200 + index)
        doi = f"10.1000/main-{index}"
        register_local_pdf(
            main, output_dir=main.parent, title=f"Research {index}", doi=doi
        )
        result = acquire_supplements(
            main, library=library, page_fetch=page_fetch(doi), file_fetch=fetch
        )
        assert result["status"] == "COMPLETED", result
    assert len(library.scan()["items"]) == 3
    assert len(list((library.root / "羧酸还原").glob("*.pdf"))) == 3
    assert len(list((library.root / "羧酸还原" / "SI").glob("*.pdf"))) == 3
    assert len(list((library.root / "羧酸还原").glob("*/SI"))) == 0
    first = library.scan()["items"][0]
    receipt = Path(first["attachments"][0]["source"])
    before_receipt = receipt.read_bytes()
    before_source = Path(first["sidecar_path"]).read_bytes()
    library.update_metadata(
        first["id"],
        title_zh="羧酸还原中文题名",
        translation={"source": "manual", "confirmed": True},
    )
    preview = library.preview_rename([first["id"]], "{title_zh}", folder="已整理")
    assert preview["executable"] == 1, preview
    library.execute_rename(preview)
    updated = library.scan(ids=[first["id"]])["items"][0]
    assert updated["si_count"] == 1
    assert (
        Path(updated["attachments"][0]["path"]).parent == library.root / "已整理" / "SI"
    )
    assert Path(updated["sidecar_path"]).read_bytes() == before_source
    assert receipt.read_bytes() == before_receipt
    result = acquire_supplements(
        updated["pdf_path"],
        library=library,
        page_fetch=page_fetch(updated["doi"]),
        file_fetch=lambda *a, **k: pytest.fail(
            "official SI already downloaded and relocated"
        ),
    )
    assert result["status"] == "COMPLETED" and result["items"][0]["status"] == "REUSED"
    assert len(fetched) == 3
    assert len(list((library.root / "羧酸还原" / "SI").glob("*.pdf"))) == 2
