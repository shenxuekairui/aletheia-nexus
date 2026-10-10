import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from aletheia_nexus import cli
from aletheia_nexus.acquire.access import BrowserSession, PaperRequest, service
from aletheia_nexus.acquire.access.batch import acquire_full_text_batch_maximized
from aletheia_nexus.acquire.fulltext.models import RetrievedResource
from aletheia_nexus.acquire.fulltext.storage import organized_output, promote_resource
from aletheia_nexus.core.organization import destination, filename_stem
from aletheia_nexus.library import scan_library


@pytest.mark.parametrize(
    "folder",
    [
        "../escape",
        "C:/papers",
        "/papers",
        "\\\\server\\papers",
        "a/../b",
        "a//b",
        "CON",
        "paper.",
        "paper ",
        "a:b",
        "_unverified",
        "_UNVERIFIED",
        "a\x00b",
    ],
)
def test_unsafe_folders_are_rejected(folder):
    with pytest.raises(ValueError):
        PaperRequest(doi="10.1000/one", folder=folder)


def test_classification_does_not_change_scholarly_identity():
    base = PaperRequest(doi="10.1000/one", title="Paper")
    organized = replace(
        base,
        folder="化学/催化",
        filename="Selected paper.pdf",
        tags=("综述", "重点", "重点"),
    )
    assert base.key == organized.key and base.article_id == organized.article_id
    assert base.batch_key != organized.batch_key
    assert organized.tags == ("综述", "重点")
    assert organized.filename == "Selected paper"
    assert organized.batch_key != replace(organized, folder="材料").batch_key


@pytest.mark.parametrize("value", [1, False, {"x": "tag"}])
def test_invalid_input_tags_rejected(tmp_path, value):
    path = tmp_path / "input.json"
    path.write_text(json.dumps([{"doi": "10.1000/one", "tags": value}]))
    with pytest.raises(ValueError):
        cli._load_inputs(path)


def test_csv_classification_is_loaded(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text(
        "doi,folder,filename,tags\n10.1000/one,化学/综述,我的论文,重点;待阅读\n",
        encoding="utf-8",
    )
    values, _ = cli._load_inputs(path)
    assert values == [
        PaperRequest(
            doi="10.1000/one",
            folder="化学/综述",
            filename="我的论文",
            tags=("重点", "待阅读"),
        )
    ]


def test_symlink_folder_cannot_escape_root(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(ValueError, match="outside"):
        destination(root, "linked")


def test_readable_names_are_portable_bounded_and_collision_safe(tmp_path):
    assert filename_stem("CON") == "paper_CON"
    assert len(filename_stem("中文" * 300).encode()) <= 140
    paths = []
    for index in range(2):
        original = tmp_path / f"{index}.tmp"
        original.write_bytes(b"verified fixture")
        resource = RetrievedResource(
            "",
            "",
            200,
            "application/pdf",
            original.stat().st_size,
            hashlib.sha256(original.read_bytes()).hexdigest(),
            original,
        )
        with organized_output(
            PaperRequest(doi=f"10.1000/{index}", filename="相同标题?")
        ):
            path, _ = promote_resource(
                resource, doi=f"10.1000/{index}", output_dir=tmp_path
            )
        paths.append(path)
    assert paths[0] != paths[1] and all(p.is_file() for p in paths)
    assert all(p.name.startswith("相同标题_--") for p in paths)


def test_one_doi_can_target_two_folders_and_resume_requires_provenance(
    monkeypatch, tmp_path
):
    def forbidden(*args, **kwargs):
        pytest.fail("must use local files")

    monkeypatch.setattr(service, "acquire_full_text", forbidden)
    monkeypatch.setattr(BrowserSession, "_ensure_started", forbidden)
    source = Path(__file__).parents[1] / "benchmarks/v07_fixtures/native_article.pdf"
    doi = "10.5555/an.v07.native"
    requests = [PaperRequest(doi=doi, folder=name) for name in ("主题A", "主题B")]
    checkpoint = tmp_path / "checkpoint.json"
    kwargs = dict(local_pdfs={doi: source}, checkpoint_path=checkpoint)
    first = acquire_full_text_batch_maximized(
        requests, output_dir=tmp_path / "out", **kwargs
    )
    assert first.verified_count == 2
    assert first.items[0].request_key != first.items[1].request_key
    assert first.items[0].verified_path.parent != first.items[1].verified_path.parent
    resumed = acquire_full_text_batch_maximized(
        requests, output_dir=tmp_path / "out", **kwargs
    )
    assert all(item.resumed for item in resumed.items)
    first.items[0].verified_path.with_suffix(".acquisition.json").unlink()
    repaired = acquire_full_text_batch_maximized(
        requests, output_dir=tmp_path / "out", **kwargs
    )
    assert not repaired.items[0].resumed and repaired.items[1].resumed
    relocated = acquire_full_text_batch_maximized(
        requests, output_dir=tmp_path / "new", **kwargs
    )
    assert relocated.verified_count == 2 and not any(
        item.resumed for item in relocated.items
    )
    assert all(
        item.verified_path.is_relative_to(tmp_path / "new") for item in relocated.items
    )
    assert all(item.verified_path.is_file() for item in first.items)


@pytest.mark.parametrize("folder", ["公开文献", None])
def test_public_only_organization_reaches_shared_storage(monkeypatch, tmp_path, folder):
    calls = []
    request = PaperRequest(
        doi="10.1000/public", folder=folder, year=2024, journal="Test Journal"
    )

    def acquire(doi, *, output_dir, **kwargs):
        calls.append((doi, output_dir))
        original = tmp_path / "public.tmp"
        original.write_bytes(b"fixture")
        resource = RetrievedResource(
            "",
            "",
            200,
            "application/pdf",
            7,
            hashlib.sha256(b"fixture").hexdigest(),
            original,
        )
        return promote_resource(
            resource, doi=doi, title="Public Article", output_dir=output_dir
        )[0]

    monkeypatch.setattr(cli, "acquire_full_text", acquire)
    path = cli._acquire_public_organized(
        request.doi, request=request, output_dir=tmp_path / "root"
    )
    assert calls[0][1] == tmp_path / "root" / (folder or "")
    assert path.name.startswith("2024-Test Journal-Public Article--")


def test_real_local_import_classification_resume_parse_and_catalog(
    monkeypatch, tmp_path, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("local import/resume must not request network or browser")

    monkeypatch.setattr(service, "acquire_full_text", forbidden)
    monkeypatch.setattr(BrowserSession, "_ensure_started", forbidden)
    source = Path(__file__).parents[1] / "benchmarks/v07_fixtures/native_article.pdf"
    root = tmp_path / "library"
    command = [
        "acquire",
        "10.5555/an.v07.native",
        "--title",
        "A Self-Authored Study of Traceable Parsing",
        "--folder",
        "方法/解析",
        "--filename",
        "文献解析研究",
        "--tag",
        "重点",
        "--local-pdf",
        f"10.5555/an.v07.native={source}",
        "--output-dir",
        str(root),
        "--non-interactive",
        "--fail-on-unverified",
    ]
    assert cli.entrypoint(command) == 0
    pdf = next((root / "方法/解析").glob("*.pdf"))
    assert pdf.name.startswith("文献解析研究--")
    assert pdf.read_bytes() == source.read_bytes()
    sidecar = pdf.with_suffix(".acquisition.json")
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    assert record["organization"]["tags"] == ["重点"]
    assert record["retrieval"]["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert cli.entrypoint(command) == 0
    report = json.loads((root / "batch-report.json").read_text(encoding="utf-8"))
    assert report["items"][0]["resumed"]
    assert Path(report["items"][0]["verified_path"]) == pdf
    assert (
        cli.entrypoint(
            ["parse", str(pdf), "--doi", "10.5555/an.v07.native", "--fail-on-partial"]
        )
        == 0
    )
    assert len(scan_library(root, folder="方法", tag="重点")["items"]) == 1
    assert not scan_library(root, tag="非重点")["items"]
    capsys.readouterr()
    assert cli.entrypoint(["library", str(root), "--query", "解析", "--json"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["items"][0]["integrity"] == "verified"
    before = {
        p: p.read_bytes() for p in (pdf, sidecar, pdf.with_suffix(".parsed.json"))
    }
    assert (
        cli.entrypoint(
            ["library", "tag", str(pdf), "--add", "已阅读", "--remove", "重点"]
        )
        == 0
    )
    assert scan_library(root, tag="已阅读")["items"][0]["tags"] == ["已阅读"]
    assert not scan_library(root, tag="重点")["items"]
    assert all(p.read_bytes() == data for p, data in before.items())
    # Re-acquiring identical bytes must not invalidate already-parsed evidence.
    assert cli.entrypoint([*command, "--no-resume"]) == 0
    assert all(p.read_bytes() == data for p, data in before.items())
    pdf.unlink()
    assert cli.entrypoint([*command, "--no-resume"]) == 0
    assert all(p.read_bytes() == data for p, data in before.items())
    pdf.write_bytes(b"changed")
    assert scan_library(root)["items"][0]["integrity"] == "hash_mismatch"


@pytest.mark.parametrize(
    "schema",
    [
        "aletheia-nexus/acquisition-record/v1",
        "aletheia-nexus/access-acquisition-record/v1",
    ],
)
def test_catalog_omits_unverified_and_reports_missing_and_bad_records(tmp_path, schema):
    for status in ("VERIFIED", "RETRIEVED_UNVERIFIED"):
        (tmp_path / f"{status}.acquisition.json").write_text(
            json.dumps(
                {
                    "schema": schema,
                    "status": status,
                    "target": {
                        "doi": None,
                        "article_id": "cnki:cjfd:test",
                        "expected_title": "无 DOI 文献",
                    },
                    "retrieval": {"sha256": "a" * 64},
                    "pdf_validation": {"valid_pdf": True, "page_count": 1},
                    "identity_validation": {
                        "status": "MATCH",
                        "document_role": "ARTICLE",
                    },
                }
            )
        )
    (tmp_path / "broken.acquisition.json").write_text("{")
    catalog = scan_library(tmp_path)
    assert len(catalog["items"]) == 1 and len(catalog["warnings"]) == 1
    assert catalog["items"][0]["doi"] is None
    assert catalog["items"][0]["integrity"] == "missing"


def test_malformed_labels_do_not_hide_verified_papers(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"fixture")
    record = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "status": "VERIFIED",
        "target": {"doi": "10.1000/test"},
        "retrieval": {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
        "pdf_validation": {"valid_pdf": True, "page_count": 1},
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
        "organization": {"tags": ["待读"]},
    }
    pdf.with_suffix(".acquisition.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    pdf.with_suffix(".library.json").write_text("{", encoding="utf-8")
    catalog = scan_library(tmp_path)
    assert len(catalog["items"]) == 1 and len(catalog["warnings"]) == 1
    assert catalog["items"][0]["tags"] == ["待读"]
    assert catalog["items"][0]["integrity"] == "verified"
    record["identity_validation"]["status"] = "MISMATCH"
    pdf.with_suffix(".acquisition.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    assert not scan_library(tmp_path)["items"]
