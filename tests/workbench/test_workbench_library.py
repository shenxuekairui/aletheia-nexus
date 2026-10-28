import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.corpus import load_corpus
from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.content.service import parse_document
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench.library import LibraryService


@pytest.fixture
def library(tmp_path):
    return LibraryService(
        tmp_path / "library", reference_roots=[tmp_path / "workspace"]
    )


def pdf(path, width=200):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=300)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def add(library, tmp_path, name="original", width=200, folder="化学"):
    return library.import_pdf(
        pdf(tmp_path / (name + ".pdf"), width),
        title="Original " + name,
        folder=folder,
        tags=["待阅读"],
    )


def test_mutable_titles_tags_views_and_selection_survive_reopen(library, tmp_path):
    one = add(library, tmp_path)
    evidence = Path(one["sidecar_path"]).read_bytes()
    library.update_metadata(
        one["id"],
        title_zh="羧酸还原",
        custom_name="重点论文",
        translation={"confirmed": True, "source": "manual"},
    )
    library.update_tags([one["id"]], add=["电合成"], remove=["待阅读"])
    library.save_collection("羧酸", [one["id"]])
    library.save_filter(
        "中文标题", {"query": "羧酸", "tags": ["电合成"], "tag_mode": "AND"}
    )
    view = {
        "columns": ["title", "title_zh", "si_count"],
        "column_state": [{"colId": "title_zh", "width": 321, "sort": "asc"}],
        "title_mode": "bilingual",
    }
    library.save_view("我的视图", view)
    library.save_tag_group("研究方向", ["电合成"])
    library.set_selection([one["id"]], mode="add")
    again = LibraryService(library.root)
    row = again.scan(query="羧酸")["items"][0]
    assert row["title_original"] == "Original original"
    assert row["title_zh"] == "羧酸还原" and row["custom_name"] == "重点论文"
    assert row["translation"]["confirmed"] and row["tags"] == ["电合成"]
    assert again.scan(**again.filters()["中文标题"])["filtered"] == 1
    assert again.collections()["羧酸"] == again.selection() == [one["id"]]
    assert again.views()["我的视图"] == view
    assert again.tag_groups()["研究方向"] == ["电合成"]
    assert Path(one["sidecar_path"]).read_bytes() == evidence
    with pytest.raises(ValueError, match="immutable"):
        again.update_metadata(one["id"], title_original="Changed")
    with pytest.raises(ValueError, match="confirmed/manual"):
        again.update_metadata(
            one["id"], title_zh="自动覆盖", translation={"source": "model"}
        )


def test_batch_rename_main_and_shared_si_preserves_id_evidence_and_rollback(
    library, tmp_path
):
    one = add(library, tmp_path, name="one")
    two = add(library, tmp_path, name="two", width=220)
    third = add(library, tmp_path, name="three", width=240)
    si_dir = Path(one["pdf_path"]).parent / "SI"
    si_dir.mkdir()
    supplement = pdf(tmp_path / "supplement.pdf", width=100)
    si_pdf = register_local_pdf(
        supplement,
        output_dir=si_dir,
        title="Supplement",
        role="SUPPLEMENT",
        parent_pdf=one["pdf_path"],
    )
    library.register_attachment(one["pdf_path"], si_pdf)
    spreadsheet = si_dir / "data.xlsx"
    spreadsheet.write_bytes(b"arbitrary registered attachment is not parsed")
    library.register_attachment(one["pdf_path"], spreadsheet)
    other_si = si_dir / "three.txt"
    other_si.write_text("third paper", encoding="utf-8")
    library.register_attachment(third["pdf_path"], other_si)
    for row in (one, two):
        library.update_metadata(
            row["id"],
            title_zh="相同译名",
            year=2026,
            journal="Actual Journal",
            translation={"confirmed": True},
        )
    before = {
        str(p): p.read_bytes()
        for p in [
            Path(one["pdf_path"]),
            Path(one["sidecar_path"]),
            Path(two["pdf_path"]),
            si_pdf,
            acquisition_sidecar_path(si_pdf),
            spreadsheet,
        ]
    }
    preview = library.preview_rename(
        [one["id"], two["id"]], "{year}-{journal}-{title_zh}", folder="电合成/羧酸"
    )
    assert preview["executable"] == 2 and preview["skipped"] == 0
    assert all("--" in item["new_name"] for item in preview["items"])
    assert all(item["translation_source"] == "confirmed" for item in preview["items"])
    first_plan = preview["items"][0]
    assert all(
        Path(m["target"]).parent.name == "SI"
        for m in first_plan["moves"]
        if m["role"] == "SUPPLEMENT"
    )
    result = library.execute_rename(preview)
    assert result["status"] == "COMPLETED"
    assert not Path(one["pdf_path"]).exists() and other_si.exists()
    assert not Path(two["pdf_path"]).exists()
    assert not (
        library.root / "电合成/羧酸" / Path(first_plan["new_path"]).stem
    ).exists()
    moved = library.get(one["id"])
    assert len(moved["attachments"]) == moved["si_count"] == 2
    assert moved["folder"] == "电合成/羧酸"
    assert moved["tags"] == ["待阅读"]
    assert all(
        Path(a["path"]).parent == library.root / "电合成/羧酸/SI"
        for a in moved["attachments"]
    )
    assert {Path(a["path"]).suffix for a in moved["attachments"]} == {".pdf", ".xlsx"}
    assert all(
        Path(a["path"]).stem.startswith(Path(moved["pdf_path"]).stem + "__SI-")
        for a in moved["attachments"]
    )
    for move in result["moves"]:
        assert Path(move["target"]).read_bytes() == before.get(
            move["source"], Path(move["target"]).read_bytes()
        )
    validate_parser_input(moved["pdf_path"])
    library.update_metadata(one["id"], custom_name="保留后续编辑")
    rollback = library.rollback(result["id"])
    assert rollback["status"] == "ROLLED_BACK"
    assert all(Path(path).read_bytes() == value for path, value in before.items())
    assert library.get(one["id"])["custom_name"] == "保留后续编辑"
    assert library.get(one["id"])["pdf_path"] == one["pdf_path"]


def test_existing_parsed_artifact_survives_rename_without_rewrite(library, tmp_path):
    fixture = Path(__file__).parents[2] / "benchmarks/v07_fixtures/native_article.pdf"
    row = library.import_pdf(fixture, title="Native Article", folder="old")
    artifact = Path(row["pdf_path"]).with_suffix(".parsed.json")
    parse_document(row["pdf_path"], output_path=artifact)
    original = artifact.read_bytes()
    preview = library.preview_rename([row["id"]], "中文新名", folder="new")
    assert preview["executable"] == 1
    assert library.execute_rename(preview)["status"] == "COMPLETED"
    assert artifact.read_bytes() == original
    corpus = load_corpus(library.root)
    assert len(corpus.documents) == 1
    assert corpus.documents[0].pdf.name == "中文新名.pdf"


def test_legacy_explicit_task_reference_is_rejected_without_mutation(library, tmp_path):
    row = add(library, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "task.json").write_text(
        json.dumps({"documents": [{"pdf": row["pdf_path"]}]})
    )
    preview = library.preview_rename([row["id"]], "new")
    assert preview["skipped"] == 1
    assert "legacy explicit references" in " ".join(preview["items"][0]["errors"])
    assert Path(row["pdf_path"]).exists()


def test_file_changed_after_preview_is_rejected(library, tmp_path):
    row = add(library, tmp_path)
    preview = library.preview_rename([row["id"]], "new")
    Path(row["pdf_path"]).write_bytes(b"changed source")
    with pytest.raises(ValueError, match="changed after preview"):
        library.execute_rename(preview)
    assert not (Path(row["pdf_path"]).parent / "new.pdf").exists()


def test_late_target_collision_never_overwrites(library, tmp_path):
    row = add(library, tmp_path)
    preview = library.preview_rename([row["id"]], "new")
    target = Path(preview["items"][0]["new_path"])
    target.write_bytes(b"user file")
    with pytest.raises(FileExistsError):
        library.execute_rename(preview)
    assert target.read_bytes() == b"user file" and Path(row["pdf_path"]).exists()


def test_failed_promotion_rolls_back_all_files(library, tmp_path, monkeypatch):
    import aletheia_nexus.workbench.library as module

    row = add(library, tmp_path)
    preview = library.preview_rename([row["id"]], "new", folder="target")
    real_link = module.os.link
    calls = []

    def fail_second(source, target, **kwargs):
        calls.append((source, target))
        if len(calls) == 2:
            raise OSError("simulated disk failure")
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(module.os, "link", fail_second)
    journal = library.execute_rename(preview)
    assert journal["status"] == "ROLLED_BACK"
    assert "simulated disk failure" in journal["errors"]
    assert Path(row["pdf_path"]).exists() and Path(row["sidecar_path"]).exists()
    assert not list(library.root.rglob(".an-move-*"))
    assert not Path(preview["items"][0]["new_path"]).exists()


def test_interrupted_stage_can_be_recovered_from_durable_journal(library, tmp_path):
    row = add(library, tmp_path)
    preview = library.preview_rename([row["id"]], "new")
    original = Path(row["pdf_path"])
    stage = original.with_name(".an-move-interrupted")
    move = {
        "source": str(original),
        "target": preview["items"][0]["new_path"],
        "stage": str(stage),
        "state": "STAGING",
        "sha256": sha256_file(original),
    }
    operation_id = "rename_123456"
    journal = {
        "id": operation_id,
        "root": str(library.root),
        "status": "RUNNING",
        "moves": [move],
        "preview": preview,
        "metadata_before": library._load(),
        "errors": [],
    }
    path = library._journal_path(operation_id)
    path.parent.mkdir()
    path.write_text(json.dumps(journal), encoding="utf-8")
    original.rename(stage)
    assert (
        LibraryService(library.root).rollback(operation_id)["status"] == "ROLLED_BACK"
    )
    assert original.exists() and not stage.exists()


def test_missing_translation_policies_and_template_validation(library, tmp_path):
    row = add(library, tmp_path)
    skipped = library.preview_rename(
        [row["id"]], "{year}-{title_zh}", missing_translation="skip"
    )
    assert skipped["skipped"] == 1
    fallback = library.preview_rename([row["id"]], "{year}-{title_zh}")
    assert fallback["executable"] == 1
    assert "None" not in fallback["items"][0]["new_name"]
    assert fallback["items"][0]["missing_metadata"] == ["year", "title_zh"]
    manual = library.preview_rename(
        [row["id"]],
        "{title_zh}",
        missing_translation="skip",
        overrides={row["id"]: "人工最终文件名"},
    )
    assert manual["executable"] == 1
    assert manual["items"][0]["new_name"] == "人工最终文件名.pdf"
    with pytest.raises(ValueError, match="unsupported field"):
        library.preview_rename([row["id"]], "{title_original.__class__}")
    library.save_template("组合", "{year}-{custom_name}")
    assert library.templates()["组合"] == "{year}-{custom_name}"


def test_subdirectory_traversal_and_unregistered_attachment_rejected(library, tmp_path):
    row = add(library, tmp_path)
    with pytest.raises(ValueError):
        library.preview_rename([row["id"]], "safe", folder="../outside")
    with pytest.raises(ValueError):
        library.path(tmp_path / "outside.pdf")
    attachment = Path(row["pdf_path"]).parent / "invalid.txt"
    attachment.write_text("attachment")
    with pytest.raises(ValueError, match="shared SI"):
        library.register_attachment(row["pdf_path"], attachment)


def test_selection_distinguishes_page_add_all_filter_and_persists(library, tmp_path):
    one = add(library, tmp_path, name="one")
    two = add(library, tmp_path, name="two", width=250)
    library.set_selection([one["id"]])
    library.set_selection([one["id"], two["id"]], mode="add")
    assert library.selection() == [one["id"], two["id"]]
    library.set_selection([one["id"]], mode="remove")
    assert library.selection() == [two["id"]]
    assert library.scan(tags=["待阅读", "unknown"], tag_mode="OR")["filtered"] == 2
    assert library.scan(tags=["待阅读", "unknown"], tag_mode="AND")["filtered"] == 0


def test_real_parse_task_receipt_does_not_block_rename(library, tmp_path):
    from aletheia_nexus.workbench.jobs import TaskManager
    from aletheia_nexus.workbench.research import WorkbenchResearch

    fixture = Path(__file__).parents[2] / "benchmarks/v07_fixtures/native_article.pdf"
    row = library.import_pdf(fixture, title="Native Article", folder="old")
    workspace = tmp_path / "workspace"
    manager = TaskManager(workspace)
    research = WorkbenchResearch(library, workspace)
    try:
        task = manager.submit(
            "parse",
            "Parse paper",
            [row["id"]],
            lambda ctx: research.parse([row["id"]], context=ctx),
        )
        manager._futures[task["id"]].result(timeout=30)
        receipt = manager.get(task["id"])
        assert receipt["status"] == "COMPLETED"
        assert receipt["current_item"] == row["pdf_path"]
        preview = library.preview_rename([row["id"]], "已解析中文论文", folder="new")
        assert preview["executable"] == 1, preview
        assert library.execute_rename(preview)["status"] == "COMPLETED"
        materials = research._materials([row["id"]])
        assert research.app.check_document(
            research._snapshot(materials[0]), "direct"
        ).pdf.is_file()
    finally:
        manager.close(wait=True)
        research.close()


def test_controlled_acquisition_checkpoint_relocation_is_explicit(library, tmp_path):
    row = add(library, tmp_path)
    directory = tmp_path / "workspace" / "acquisition"
    directory.mkdir(parents=True)
    checkpoint = directory / "batch.checkpoint.json"
    value = {
        "schema": "aletheia-nexus/access-batch-checkpoint/v1",
        "records": {"key": {"verified_path": row["pdf_path"]}},
    }
    checkpoint.write_text(json.dumps(value))
    assert library.preview_rename([row["id"]], "new")["skipped"] == 1
    library.register_reference_adapter(directory, value["schema"])
    assert library.preview_rename([row["id"]], "new")["executable"] == 1
    before = checkpoint.read_bytes()
    library.execute_rename(library.preview_rename([row["id"]], "new"))
    assert checkpoint.read_bytes() == before


def test_table_metadata_changes_reuse_validated_pdf_catalog(
    library, tmp_path, monkeypatch
):
    import aletheia_nexus.workbench.library as module

    row = add(library, tmp_path)
    calls = []
    real_scan = module.scan_library

    def track(root):
        calls.append(root)
        return real_scan(root)

    monkeypatch.setattr(module, "scan_library", track)
    library.update_metadata(row["id"], custom_name="metadata only")
    assert library.get(row["id"])["custom_name"] == "metadata only"
    library.scan(query="metadata")
    assert calls == []
    library.scan(refresh=True)
    assert len(calls) == 1


def test_identical_source_copies_share_one_stable_grid_identity(library, tmp_path):
    import shutil

    row = add(library, tmp_path, folder="Z")
    target = library.root / "A" / Path(row["pdf_path"]).name
    target.parent.mkdir()
    shutil.copyfile(row["pdf_path"], target)
    sidecar = acquisition_sidecar_path(target)
    sidecar.parent.mkdir()
    shutil.copyfile(row["sidecar_path"], sidecar)
    report = library.scan()
    assert report["total"] == 1
    assert report["items"][0]["id"] == row["id"]
    assert report["items"][0]["pdf_path"] == row["pdf_path"]
    assert report["items"][0]["duplicate_paths"] == [str(target)]
    assert LibraryService(library.root).get(row["id"])["pdf_path"] == row["pdf_path"]


def test_specific_attachment_role_never_duplicates_generic_pdf_supplement(
    library, tmp_path
):
    row = add(library, tmp_path)
    supplement = register_local_pdf(
        pdf(tmp_path / "report.pdf", width=123),
        output_dir=Path(row["pdf_path"]).parent / "SI",
        title="Historical generic supplement",
        role="SUPPLEMENT",
        parent_pdf=row["pdf_path"],
    )
    library.register_attachment(row["pdf_path"], supplement, role="REPORTING_SUMMARY")
    paper = library.get(row["id"])
    assert len(paper["attachments"]) == 1 and paper["si_count"] == 0
    assert paper["attachments"][0]["role"] == "REPORTING_SUMMARY"
    preview = library.preview_rename([row["id"]], "new")
    assert preview["executable"] == 1
    assert (
        len(
            [
                m
                for m in preview["items"][0]["moves"]
                if m["role"] == "REPORTING_SUMMARY"
            ]
        )
        == 1
    )


def test_cached_single_paper_lookup_observes_metadata_labels_and_source_changes(
    library, tmp_path, monkeypatch
):
    import aletheia_nexus.workbench.library as module

    row = add(library, tmp_path)
    calls = []
    original = module.scan_library

    def track(root):
        calls.append(root)
        return original(root)

    monkeypatch.setattr(module, "scan_library", track)
    library.update_metadata(
        row["id"],
        title_zh="中文更新",
        custom_name="单篇",
        year=2025,
        authors=["A. Author"],
    )
    item = library.get(row["id"])
    assert (
        item["title_zh"] == "中文更新"
        and item["first_author"] == "A. Author"
        and item["year"] == 2025
    )
    assert not calls
    library.update_tags([row["id"]], add=["new tag"])
    assert "new tag" in library.get(row["id"])["tags"]
    assert len(calls) == 1
    # A changed source declaration acquires a different logical identity;
    # the prior translated title must not follow it just because the path matches.
    sidecar = Path(row["sidecar_path"])
    value = json.loads(sidecar.read_text(encoding="utf-8"))
    value["target"]["title"] = "A different source declaration"
    sidecar.write_text(json.dumps(value), encoding="utf-8")
    assert library.get(row["id"]) is None
    replacement = library.scan()["items"][0]
    assert replacement["id"] != row["id"] and replacement["title_zh"] == ""


def test_import_registered_main_preserves_original_source_evidence(library, tmp_path):
    from aletheia_nexus.library import update_tags

    source = pdf(tmp_path / "outside.pdf", width=177)
    register_local_pdf(
        source, output_dir=source.parent, title="Immutable original title"
    )
    original = acquisition_sidecar_path(source).read_bytes()
    update_tags(source, add=["existing tag"])
    row = library.import_pdf(
        source, title="Incorrect replacement title", folder="资料", tags=["new tag"]
    )
    assert Path(row["sidecar_path"]).read_bytes() == original
    assert acquisition_sidecar_path(source).read_bytes() == original
    assert row["title_original"] == "Immutable original title"
    assert row["import_warnings"]
    assert set(row["tags"]) == {"existing tag", "new tag"}
    assert library.import_pdf(source)["id"] == row["id"]
    assert library.scan()["total"] == 1


def test_import_verified_main_does_not_downgrade_to_local_declaration(library):
    fixture = Path(__file__).parents[2] / "benchmarks/v07_fixtures/native_article.pdf"
    original = acquisition_sidecar_path(fixture).read_bytes()
    row = library.import_pdf(fixture)
    assert Path(row["sidecar_path"]).read_bytes() == original
    assert json.loads(original)["status"] == "VERIFIED"
    assert row["identity_basis"] == "acquisition_verified"


def test_manual_si_import_uses_shared_category_and_explicit_parent(library, tmp_path):
    row = add(library, tmp_path, name="main")
    other = add(library, tmp_path, name="other", width=222)
    source = pdf(tmp_path / "external-si.pdf", width=112)
    imported = library.import_attachment(row["id"], source, title="Supplement details")
    copied = Path(imported["path"])
    assert copied.parent == Path(row["pdf_path"]).parent / "SI"
    assert copied.name == "main__SI-01.pdf"
    gated = validate_parser_input(copied)
    assert (
        gated.document_role == "SUPPLEMENT" and gated.identity_basis == "local_declared"
    )
    assert gated.parent["pdf_sha256"] == row["pdf_sha256"]
    assert library.scan()["total"] == 2 and library.get(row["id"])["si_count"] == 1
    assert library.import_attachment(row["id"], source)["id"] == imported["id"]
    with pytest.raises(ValueError, match="SUPPLEMENT"):
        library.import_pdf(copied)
    with pytest.raises(ValueError, match="another parent"):
        library.import_attachment(other["id"], copied)
    with pytest.raises(ValueError, match="own attachment"):
        library.import_attachment(row["id"], row["pdf_path"])
    csv = tmp_path / "values.csv"
    csv.write_text("condition,value\na,1\n", encoding="utf-8")
    data = library.import_attachment(row["id"], csv)
    assert Path(data["path"]).name == "main__SI-02.csv"
    receipt = json.loads(Path(data["source"]).read_text(encoding="utf-8"))
    assert receipt["association_basis"] == "explicit_user_selected_parent"
    assert receipt["validation"]["parseable"] is False
    assert receipt["parent"]["paper_id"] == row["id"]
    report = library.execute_rename(
        library.preview_rename([row["id"]], "中文主文", folder="new")
    )
    assert report["status"] == "COMPLETED"
    moved = library.get(row["id"])
    assert moved["si_count"] == 2
    assert all(
        Path(a["path"]).parent == library.root / "new/SI" for a in moved["attachments"]
    )
    assert Path(data["source"]).is_file()


def test_local_non_si_attachment_is_saved_but_never_parsed(library, tmp_path):
    row = add(library, tmp_path)
    source = pdf(tmp_path / "reporting.pdf", width=110)
    attachment = library.import_attachment(row["id"], source, role="REPORTING_SUMMARY")
    assert Path(attachment["path"]).name == "original__REPORTING_SUMMARY-01.pdf"
    assert not acquisition_sidecar_path(attachment["path"]).exists()
    assert library.get(row["id"])["si_count"] == 0
    assert not json.loads(Path(attachment["source"]).read_text(encoding="utf-8"))[
        "validation"
    ]["parseable"]
    bad = tmp_path / "unsafe.exe"
    bad.write_bytes(b"MZ executable")
    with pytest.raises(ValueError, match="extension"):
        library.import_attachment(row["id"], bad)


def test_tag_rename_delete_changes_only_mutable_labels_groups_and_filters(
    library, tmp_path
):
    row = add(library, tmp_path)
    immutable = Path(row["sidecar_path"]).read_bytes()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = workspace / "task.json"
    task.write_text(json.dumps({"frozen_tags": ["待阅读"]}), encoding="utf-8")
    task_before = task.read_bytes()
    library.save_tag_group("阅读", ["待阅读", "已读"])
    library.save_filter("待阅读论文", {"tags": ["待阅读"], "tag_mode": "AND"})
    renamed = library.rename_tag("待阅读", "待读")
    assert renamed["paper_count"] == 1 and renamed["filters_changed"] == ["待阅读论文"]
    assert library.get(row["id"])["tags"] == ["待读"]
    assert library.tag_groups()["阅读"] == ["待读", "已读"]
    assert library.filters()["待阅读论文"]["tags"] == ["待读"]
    deleted = library.delete_tag("待读")
    assert deleted["warning"] and library.get(row["id"])["tags"] == []
    assert library.filters()["待阅读论文"]["tags"] == []
    assert library.tag_groups()["阅读"] == ["已读"]
    assert Path(row["sidecar_path"]).read_bytes() == immutable
    assert task.read_bytes() == task_before
