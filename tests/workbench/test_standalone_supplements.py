import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.core.models import PaperMetadata
from aletheia_nexus.workbench import supplements
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.standalone_supplements import StandaloneSupplementService

DOI = "10.1000/independent"
TITLE = "Independent SI study"
PAGE = "https://www.nature.com/articles/independent"


def pdf_bytes(width=100):
    out = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    writer.write(out)
    return out.getvalue()


def metadata(doi=DOI, title=TITLE):
    return PaperMetadata(
        doi,
        title,
        (),
        None,
        (),
        None,
        None,
        None,
        "journal-article",
        None,
        None,
        None,
        PAGE,
    )


@pytest.fixture
def setup(tmp_path):
    library = LibraryService(tmp_path / "library")
    service = StandaloneSupplementService(library)
    calls = []
    state = {
        "html": f'<meta name="citation_doi" content="{DOI}"><a href="/si.pdf">Supplementary Information</a><a href="/table.csv">Supplementary Table</a>',
        "bodies": {
            "/si.pdf": pdf_bytes(),
            "/table.csv": b"column,value\na,1\n",
            "/review.pdf": pdf_bytes(140),
        },
    }

    def fetch(url, *, output_dir, **_):
        calls.append(url)
        path = Path(output_dir) / (uuid4().hex + ".part")
        body = state["bodies"]["/" + url.split("/")[-1].split("?")[0]]
        if isinstance(body, Exception):
            raise body
        path.write_bytes(body)
        return SimpleNamespace(
            local_path=path,
            final_url=url,
            sha256=sha256_file(path),
            content_type="application/octet-stream",
        )

    options = {
        "metadata_lookup": lambda _: metadata(),
        "pmc_lookup": lambda *_: None,
        "page_fetch": lambda *_a, **_k: SimpleNamespace(
            text=state["html"], final_url=PAGE, body_truncated=False, redirects=()
        ),
        "file_fetch": fetch,
    }
    return library, service, options, state, calls


def main_paper(library, *, doi=DOI, title=TITLE):
    path = library.root / ("main-" + uuid4().hex[:6] + ".pdf")
    path.write_bytes(pdf_bytes(220))
    register_local_pdf(path, output_dir=library.root, doi=doi, title=title)
    library.scan()
    return path


def test_no_main_download_or_fabricated_parser_identity_and_durable_reuse(setup):
    library, service, options, _, calls = setup
    first = service.acquire(DOI, **options)
    assert first["status"] == "COMPLETED" and first["si_count"] == 2
    assert first["main_status"] == "NOT_REQUESTED"
    assert library.scan()["items"] == []
    assert not list(library.root.rglob("*.acquisition.json"))
    for item in first["items"]:
        receipt = json.loads(Path(item["source_record"]).read_text("utf-8"))
        assert (
            receipt["association_status"] == "DOI_ONLY" and receipt["main_pdf"] is None
        )
        assert "parent" not in receipt and not item["parseable"]
        if Path(item["path"]).suffix == ".pdf":
            with pytest.raises((ValueError, FileNotFoundError)):
                validate_parser_input(item["path"])
    assert service.list()["pending"] == 2
    second = service.acquire(DOI, **options)
    assert [item["status"] for item in second["items"]] == ["REUSED", "REUSED"]
    assert len(calls) == 2


def test_later_binding_preserves_originals_and_becomes_reusable_pdf_si(setup):
    library, service, options, _, calls = setup
    first = service.acquire(DOI, **options)
    originals = {
        path: sha256_file(Path(path))
        for item in first["items"]
        for path in [item["path"], item["source_record"]]
    }
    main = main_paper(library)
    main_before = sha256_file(main), sha256_file(acquisition_sidecar_path(main))
    bound = service.bind(main)
    assert bound["status"] == "COMPLETED" and len(bound["items"]) == 2
    assert len(library.scan()["items"]) == 1 and service.list()["pending"] == 0
    assert originals == {path: sha256_file(Path(path)) for path in originals}
    assert main_before == (
        sha256_file(main),
        sha256_file(acquisition_sidecar_path(main)),
    )
    for item in bound["items"]:
        record = json.loads(Path(item["source"]).read_text("utf-8"))
        assert record["association_status"] == "MAIN_LINKED"
        assert record["parent"]["doi"] == DOI and record["standalone_origin"]["id"]
        if Path(item["path"]).suffix == ".pdf":
            source = validate_parser_input(library.path(item["path"]))
            assert (
                source.document_role == "SUPPLEMENT"
                and source.identity_basis != "acquisition_verified"
            )
    again = service.bind(main)
    assert all(item["import_status"] == "ALREADY_PRESENT" for item in again["items"])
    result = supplements.acquire_supplements(
        main,
        library=library,
        page_urls=[PAGE],
        page_fetch=options["page_fetch"],
        file_fetch=options["file_fetch"],
    )
    assert result["status"] == "COMPLETED" and all(
        item["status"] == "REUSED" for item in result["items"]
    )
    assert len(calls) == 2 and service.list()["pending"] == 0


@pytest.mark.parametrize("wrong", ["doi", "title"])
def test_wrong_parent_rejected_before_any_binding(setup, wrong):
    library, service, options, _, _ = setup
    first = service.acquire(DOI, **options)
    main = main_paper(
        library,
        doi="10.1000/other" if wrong == "doi" else DOI,
        title="Another study" if wrong == "title" else TITLE,
    )
    before = sha256_file(main)
    with pytest.raises(ValueError, match="does not match"):
        service.bind(main, [first["items"][0]["id"]])
    assert service.list()["pending"] == 2 and sha256_file(main) == before


def test_known_standalone_pdf_cannot_be_promoted_to_main(setup, tmp_path):
    library, service, options, _, _ = setup
    result = service.acquire(DOI, **options)
    path = next(
        item["path"] for item in result["items"] if item["path"].endswith(".pdf")
    )
    with pytest.raises(ValueError, match="SI"):
        library.import_pdf(path, title=TITLE, doi=DOI)
    with pytest.raises(ValueError, match="SI"):
        register_local_pdf(path, output_dir=tmp_path / "another", title=TITLE, doi=DOI)
    assert not list(library.root.rglob("*.acquisition.json"))


def test_one_failed_file_keeps_completed_other_file_and_receipt(setup):
    _, service, options, state, _ = setup
    state["bodies"]["/table.csv"] = OSError("network fixture")
    result = service.acquire(DOI, **options)
    assert result["status"] == "PARTIAL"
    assert [item["status"] for item in result["items"]] == ["SAVED", "FAILED"]
    assert service.list()["pending"] == 1


def test_file_limit_is_partial_and_unhandled_files_are_not_called(setup):
    _, service, options, _, calls = setup
    result = service.acquire(DOI, max_files=1, **options)
    assert result["status"] == "PARTIAL" and result["truncated"] and len(calls) == 1


def test_peer_review_is_separate_and_opt_in(setup):
    _, service, options, state, calls = setup
    state["html"] = (
        f'<meta name="citation_doi" content="{DOI}"><a href="/review.pdf">Peer review history</a>'
    )
    assert service.acquire(DOI, **options)["status"] == "NOT_FOUND"
    assert not calls
    result = service.acquire(DOI, include_peer_review=True, **options)
    assert result["status"] == "COMPLETED" and result["si_count"] == 0
    assert result["items"][0]["role"] == "PEER_REVIEW"


@pytest.mark.parametrize("change", ["doi", "title"])
def test_metadata_conflict_never_downloads(setup, change):
    _, service, options, _, calls = setup
    options["metadata_lookup"] = lambda _: metadata(
        "10.1000/other" if change == "doi" else DOI,
        "Another paper" if change == "title" else TITLE,
    )
    with pytest.raises(ValueError):
        service.acquire(DOI, title=TITLE, **options)
    assert not calls


def test_file_tampering_is_reported_and_never_overwritten(setup):
    _, service, options, _, _ = setup
    first = service.acquire(DOI, **options)
    path = Path(first["items"][0]["path"])
    path.write_bytes(b"changed evidence")
    assert service.list()["warnings"]
    second = service.acquire(DOI, **options)
    assert second["status"] == "PARTIAL" and second["items"][0]["status"] == "FAILED"
    assert path.read_bytes() == b"changed evidence"


def test_receipt_traversal_is_rejected(setup):
    _, service, options, _, _ = setup
    first = service.acquire(DOI, **options)
    item = first["items"][0]
    path = Path(item["source_record"])
    data = json.loads(path.read_text("utf-8"))
    data["file_name"] = "../outside.pdf"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        service.get(item["id"])


def test_relocated_library_keeps_standalone_receipts_and_can_bind(setup, tmp_path):
    import shutil

    library, service, options, _, _ = setup
    service.acquire(DOI, **options)
    target = tmp_path / "new-drive-library"
    shutil.copytree(library.root, target)
    moved = LibraryService(target)
    service = StandaloneSupplementService(moved)
    assert service.list()["pending"] == 2
    assert service.bind(main_paper(moved))["status"] == "COMPLETED"


def test_batch_skips_bad_doi_before_network_and_cancellation_keeps_prior_data(setup):
    _, service, options, _, calls = setup
    with pytest.raises(ValueError):
        service.acquire_many([{"title": TITLE}], **options)
    assert not calls
    result = service.acquire_many([{"doi": DOI}], **options)
    assert result["status"] == "COMPLETED" and result["main_status"] == "NOT_REQUESTED"


@pytest.mark.parametrize(
    "limits",
    [
        {"max_files": 0},
        {"max_files": True},
        {"max_files": 101},
        {"max_bytes": 0},
        {"timeout": 0},
        {"timeout": float("nan")},
    ],
)
def test_invalid_limits_are_rejected_before_remote_metadata(setup, limits):
    _, service, options, _, calls = setup
    options["metadata_lookup"] = lambda _: pytest.fail(
        "invalid limits must not query metadata"
    )
    with pytest.raises(ValueError):
        service.acquire(DOI, **options, **limits)
    assert not calls


def test_cli_acquire_list_and_attach_use_shared_service_and_saved_paths(
    setup, tmp_path, monkeypatch, capsys
):
    from aletheia_nexus import si_cli
    from aletheia_nexus.cli import entrypoint
    from aletheia_nexus.storage_paths import PathPreferences, StoragePaths

    library, service, options, _, _ = setup
    service.acquire(DOI, **options)
    preferences = PathPreferences(tmp_path / "prefs")
    preferences.save(StoragePaths(library.root, library.state_dir, tmp_path / "work"))
    monkeypatch.setattr(si_cli, "PathPreferences", lambda: preferences)
    assert entrypoint(["si", "list", "--pending-only"]) == 0
    assert json.loads(capsys.readouterr().out)["pending"] == 2
    main = main_paper(library)
    assert entrypoint(["si", "attach", "--main-pdf", str(main)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "COMPLETED"
    assert entrypoint(["si", "list", "--pending-only"]) == 0
    assert json.loads(capsys.readouterr().out)["pending"] == 0
    assert entrypoint(["si", "acquire", DOI, DOI, "--title", TITLE]) == 2
    assert "--title" in capsys.readouterr().err
