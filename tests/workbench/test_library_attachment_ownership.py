import json
import shutil
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.translation import TranslationService


def write_pdf(path, title):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.add_metadata({"/Title": title})
    with path.open("wb") as output:
        writer.write(output)
    return path


def same_bytes_distinct_declarations(tmp_path):
    library = LibraryService(tmp_path / "library")
    first = write_pdf(tmp_path / "first.pdf", "Same immutable content")
    second = tmp_path / "second.pdf"
    shutil.copyfile(first, second)
    one = library.import_pdf(first, title="Declaration A", folder="category")
    two = library.import_pdf(second, title="Declaration B", folder="category")
    assert one["id"] != two["id"]
    assert one["pdf_sha256"] == two["pdf_sha256"]
    assert one["article_id"] == two["article_id"]
    return library, one, two


def add_si(library, parent, source, *, explicit):
    target = register_local_pdf(
        source,
        output_dir=Path(parent["pdf_path"]).parent / "SI",
        title=source.stem,
        role="SUPPLEMENT",
        parent_pdf=parent["pdf_path"],
    )
    if explicit:
        library.register_attachment(parent["pdf_path"], target)
    return target


def test_explicit_parent_id_prevents_other_identical_pdf_declaration_stealing_si(
    tmp_path,
):
    library, one, two = same_bytes_distinct_declarations(tmp_path)
    si_one = add_si(
        library,
        one,
        write_pdf(tmp_path / "one-si.pdf", "Distinct SI one"),
        explicit=True,
    )
    si_two = add_si(
        library,
        two,
        write_pdf(tmp_path / "two-si.pdf", "Distinct SI two"),
        explicit=True,
    )
    two_original = {
        str(p): sha256_file(p)
        for p in (
            Path(two["pdf_path"]),
            Path(two["sidecar_path"]),
            si_two,
            acquisition_sidecar_path(si_two),
        )
    }
    assert {a["path"] for a in library.get(one["id"])["attachments"]} == {str(si_one)}
    assert {a["path"] for a in library.get(two["id"])["attachments"]} == {str(si_two)}
    preview = library.preview_rename([one["id"]], "中文论文甲", folder="moved")
    assert all(m["source"] != str(si_two) for m in preview["items"][0]["moves"])
    assert library.execute_rename(preview)["status"] == "COMPLETED"
    assert all(
        Path(path).is_file() and sha256_file(Path(path)) == digest
        for path, digest in two_original.items()
    )
    assert library.get(two["id"])["attachments"][0]["path"] == str(si_two)
    moved = library.get(one["id"])
    assert len(moved["attachments"]) == 1
    assert Path(moved["attachments"][0]["path"]).parent == library.root / "moved/SI"


def test_unregistered_legacy_si_with_ambiguous_parent_is_diagnosed_not_guessed(
    tmp_path,
):
    library, one, two = same_bytes_distinct_declarations(tmp_path)
    legacy = add_si(
        library,
        one,
        write_pdf(tmp_path / "legacy.pdf", "Legacy ambiguous SI"),
        explicit=False,
    )
    report = library.scan()
    assert all(not paper["attachments"] for paper in report["items"])
    ambiguity = next(
        w for w in report["warnings"] if w.get("attachment_path") == str(legacy)
    )
    assert set(ambiguity["candidate_ids"]) == {one["id"], two["id"]}
    assert "歧义" in ambiguity["error"]
    # An explicit user association resolves the ambiguity for exactly one ID.
    library.register_attachment(one["pdf_path"], legacy)
    assert len(library.get(one["id"])["attachments"]) == 1
    assert library.get(two["id"])["attachments"] == []


def test_registered_attachment_path_cannot_be_claimed_by_another_parent(tmp_path):
    library, one, two = same_bytes_distinct_declarations(tmp_path)
    attachment = add_si(
        library, one, write_pdf(tmp_path / "owned.pdf", "Owned SI"), explicit=True
    )
    with pytest.raises(ValueError, match="已明确归属"):
        library.register_attachment(two["pdf_path"], attachment)


def test_unique_legacy_parent_keeps_compatibility(tmp_path):
    library = LibraryService(tmp_path / "library")
    main = library.import_pdf(
        write_pdf(tmp_path / "main.pdf", "Unique main"),
        title="Unique main",
        folder="category",
    )
    legacy = add_si(
        library,
        main,
        write_pdf(tmp_path / "legacy.pdf", "Legacy unique SI"),
        explicit=False,
    )
    library.scan()
    assert library.get(main["id"])["attachments"][0]["path"] == str(legacy)
    assert library.scan()["warnings"] == []


def test_missing_attachment_receipt_is_reported_without_downgrading_verified_main(
    tmp_path,
):
    library = LibraryService(tmp_path / "library")
    main = library.import_pdf(
        Path(__file__).parents[2] / "benchmarks/v07_fixtures/native_article.pdf"
    )
    attachment = library.import_attachment(
        main["id"], write_pdf(tmp_path / "si.pdf", "Local SI receipt check")
    )
    Path(attachment["source"]).unlink()
    report = library.scan()
    current = report["items"][0]
    assert current["identity_basis"] == "acquisition_verified"
    assert current["integrity"] == "verified"
    assert current["attachments"][0]["source_status"] == "MISSING"
    assert any(
        w.get("sidecar") == attachment["source"] and "来源记录缺失" in w["error"]
        for w in report["warnings"]
    )


def test_forty_unique_synthetic_papers_translate_reordered_ids_cache_and_move(
    tmp_path, monkeypatch
):
    """Forty distinct synthetic PDFs, never forty copies of one PDF identity.

    MockTransport forbids a real network/paid call. This exercises scale and
    ownership, not scientific translation quality or realistic PDF performance.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-only-for-local-mock-transport")
    library = LibraryService(tmp_path / "library")
    ids, expected, before = [], {}, {}
    for index in range(40):
        title = f"Synthetic scientific title {index:02d}"
        row = library.import_pdf(
            write_pdf(tmp_path / f"paper-{index:02d}.pdf", title),
            title=title,
            folder="合成材料",
        )
        library.update_metadata(row["id"], year=2026, journal="Fixture Journal")
        si = library.import_attachment(
            row["id"],
            write_pdf(
                tmp_path / f"si-{index:02d}.pdf", f"Distinct synthetic SI {index:02d}"
            ),
        )
        ids.append(row["id"])
        expected[row["id"]] = f"合成中文标题{index:02d}"
        before[row["id"]] = {
            "pdf": row["pdf_sha256"],
            "source": sha256_file(Path(row["sidecar_path"])),
            "si": si["sha256"],
        }
    assert len({entry["pdf"] for entry in before.values()}) == 40
    assert len(library.scan()["items"]) == 40
    assert len(list((library.root / "合成材料/SI").glob("*.pdf"))) == 40
    calls = []

    def handler(request):
        wire = json.loads(request.content)
        payload = json.loads(wire["input"][0]["content"][0]["text"])
        assert payload["phase"] == "title_translation"
        assert all(set(row) == {"id", "title"} for row in payload["titles"])
        assert not any(".pdf" in row["title"] for row in payload["titles"])
        calls.append(payload["titles"])
        translations = [
            {"id": row["id"], "title": expected[row["id"]]}
            for row in reversed(payload["titles"])
        ]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"translations": translations}),
                            }
                        ],
                    }
                ],
            },
        )

    options = {
        "batch_size": 10,
        "max_calls": 4,
        "max_cost": 1,
        "model": {"min_interval_seconds": 0},
    }
    state = tmp_path / "translation-state"
    service = TranslationService(library, state, transport=httpx.MockTransport(handler))
    assert service.translate(ids[:10], options, consent=True)["status"] == "COMPLETED"
    estimate = service.estimate(ids, options)
    assert len(estimate["cached"]) == 10 and len(estimate["pending"]) == 30
    assert service.translate(ids[::-1], options, consent=True)["status"] == "COMPLETED"
    assert len(calls) == 4
    service.edit(ids[0], "人工确认合成标题00", confirmed=True)
    expected[ids[0]] = "人工确认合成标题00"
    cached_service = TranslationService(
        library,
        state,
        transport=httpx.MockTransport(
            lambda r: pytest.fail("Cache/confirmed titles must issue no HTTP calls")
        ),
    )
    cached = cached_service.translate(ids[::-1], options)
    assert cached["calls"] == []
    assert len(cached["items"]) == 40
    assert all(
        library.get(paper_id)["title_zh"] == title
        for paper_id, title in expected.items()
    )
    preview = library.preview_rename(
        ids,
        "{year}-{journal}-{title_zh}",
        folder="整理后/合成材料",
        missing_translation="skip",
    )
    assert preview["executable"] == 40 and preview["skipped"] == 0
    operation = library.execute_rename(preview)
    assert operation["status"] == "COMPLETED"
    after = library.scan()
    assert len(after["items"]) == 40
    assert len(list((library.root / "整理后/合成材料").glob("*.pdf"))) == 40
    assert len(list((library.root / "整理后/合成材料/SI").glob("*.pdf"))) == 40
    for paper_id, hashes in before.items():
        paper = library.get(paper_id)
        assert (
            Path(paper["pdf_path"]).name
            == f"2026-Fixture Journal-{expected[paper_id]}.pdf"
        )
        assert sha256_file(Path(paper["pdf_path"])) == hashes["pdf"]
        assert sha256_file(Path(paper["sidecar_path"])) == hashes["source"]
        assert len(paper["attachments"]) == 1
        assert sha256_file(Path(paper["attachments"][0]["path"])) == hashes["si"]
        assert (
            Path(paper["attachments"][0]["path"]).name
            == Path(paper["pdf_path"]).stem + "__SI-01.pdf"
        )
