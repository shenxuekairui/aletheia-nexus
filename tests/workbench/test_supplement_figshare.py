"""Native public SI discovery must prove publisher, parent and file identity."""

import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import supplement_figshare as module
from aletheia_nexus.workbench import supplements
from aletheia_nexus.workbench.library import LibraryService

DOI = "10.1021/fixture.01234"
TITLE = "Native TiO2 supplementary fixture"
PAGE = "https://acs.figshare.com/articles/journal_contribution/Fixture/123"
FILE = "https://ndownloader.figshare.com/files/456"


def pdf_bytes(width=200):
    writer, buffer = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=width, height=300)
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def official(monkeypatch):
    body = pdf_bytes()
    record = {
        "id": 123,
        "doi": DOI + ".s001",
        "resource_doi": DOI,
        "resource_title": "Native TiO<sub>2</sub> supplementary fixture",
        "url_public_html": PAGE,
        "is_public": True,
        "is_confidential": False,
        "is_embargoed": False,
        "status": "public",
        "version": 1,
        "files": [
            {
                "id": 456,
                "name": "fixture_si_001.pdf",
                "size": len(body),
                "is_link_only": False,
                "download_url": FILE,
                "computed_md5": hashlib.md5(body).hexdigest(),
            }
        ],
    }
    state = {"record": record, "listing": [record], "calls": [], "body": body}

    def read(url, *, search=None, **kwargs):
        state["calls"].append((url, search))
        data = state["listing"] if url.endswith("/search") else state["record"]
        return deepcopy(data), hashlib.sha256(json.dumps(data).encode()).hexdigest()

    monkeypatch.setattr(module, "_read_json", read)
    return state


def discover():
    return module.discover_acs_attachments(doi=DOI, title=TITLE)


def test_doi_only_uses_official_parent_title_without_weakening_default(official):
    assert (
        module.discover_acs_attachments(doi=DOI, title=None)["status"]
        == "NOT_SUPPORTED"
    )
    result = module.discover_acs_attachments(
        doi=DOI, title=None, allow_publisher_title=True
    )
    assert result["status"] == "DISCOVERED" and not result["errors"]
    assert result["parent_title"] == official["record"]["resource_title"]
    assert (
        result["items"][0]["expected_md5"] == hashlib.md5(official["body"]).hexdigest()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_doi", "10.1021/wrong"),
        ("doi", DOI + ".s001.evil"),
        ("is_public", False),
        ("is_embargoed", True),
    ],
)
def test_doi_only_keeps_official_identity_publication_and_embargo_gates(
    official, field, value
):
    official["record"][field] = value
    result = module.discover_acs_attachments(
        doi=DOI, title=None, allow_publisher_title=True
    )
    assert not result["items"] and result["errors"]


def test_independent_acs_can_save_without_auxiliary_metadata(
    official, tmp_path, monkeypatch
):
    from aletheia_nexus.content.gate import sha256_file
    from aletheia_nexus.workbench import standalone_supplements as independent

    monkeypatch.setattr(
        independent,
        "get_metadata",
        lambda *_: pytest.fail("ACS DOI-only must not depend on Crossref"),
    )

    def fetch(url, *, output_dir, **_):
        path = output_dir / "native.part"
        path.write_bytes(official["body"])
        return SimpleNamespace(local_path=path, final_url=url, sha256=sha256_file(path))

    library = LibraryService(tmp_path / "new-library")
    result = independent.StandaloneSupplementService(library).acquire(
        DOI, pmc_lookup=lambda *_: None, file_fetch=fetch
    )
    assert result["status"] == "COMPLETED" and result["main_status"] == "NOT_REQUESTED"
    assert "<sub>" not in result["title"] and library.scan()["items"] == []


def test_explicit_manifest_preserves_parent_type_checksum_and_metadata_evidence(
    official,
):
    result = discover()
    item = result["items"][0]
    assert result["status"] == "DISCOVERED" and not result["errors"]
    assert item["url"] == FILE and item["page"] == PAGE
    assert item["extension"] == ".pdf" and item["role"] == "SUPPLEMENT"
    assert item["expected_md5"] == hashlib.md5(official["body"]).hexdigest()
    assert item["expected_size"] == len(official["body"])
    assert item["evidence"]["resource_doi"] == DOI
    assert len(item["evidence"]["metadata_sha256"]) == 64
    assert official["calls"][0][1]["resource_doi"] == DOI
    assert official["calls"][1][0] == module.API + "/123"


@pytest.mark.parametrize(
    "key,value",
    [
        ("resource_doi", "10.1021/other"),
        ("doi", DOI + ".s001.evil"),
        ("doi", DOI),
        ("resource_title", "Wrong title"),
        ("resource_title", ""),
        ("url_public_html", PAGE.replace("acs.figshare.com", "figshare.com")),
        ("url_public_html", PAGE + "?token=private"),
        ("url_public_html", PAGE + "4"),
        ("url_public_html", PAGE.replace("https:", "http:")),
        ("id", True),
    ],
)
def test_wrong_or_ambiguous_parent_is_rejected_before_detail_request(
    official, key, value
):
    official["record"][key] = value
    result = discover()
    assert not result["items"] and result["status"] == "FAILED"
    assert len(official["calls"]) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("is_public", False),
        ("is_embargoed", True),
        ("is_confidential", True),
        ("status", "private"),
        ("files", None),
    ],
)
def test_nonpublic_or_invalid_detail_does_not_authorize_files(official, key, value):
    official["record"][key] = value
    assert not discover()["items"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("name", "../escape.pdf"),
        ("name", "folder\\evil.pdf"),
        ("name", "script.exe"),
        ("id", False),
        ("is_link_only", True),
        ("size", -1),
        ("size", 200 * 1024**2),
        ("computed_md5", "not-md5"),
        ("computed_md5", None),
        ("download_url", FILE.replace("456", "457")),
        ("download_url", "https://untrusted.example/file.pdf"),
    ],
)
def test_invalid_file_identity_or_limits_are_rejected(official, key, value):
    official["record"]["files"][0][key] = value
    result = discover()
    assert not result["items"] and result["errors"]


def test_partial_manifest_retains_valid_file_but_reports_unavailable_parts(official):
    second = {**official["record"]["files"][0], "id": 457, "is_link_only": True}
    official["record"]["files"].append(second)
    result = discover()
    assert len(result["items"]) == 1 and len(result["errors"]) == 1


def test_manifest_work_is_bounded_and_non_acs_does_not_request(official):
    assert (
        module.discover_acs_attachments(doi="10.1000/parent", title=TITLE)["status"]
        == "NOT_SUPPORTED"
    )
    assert not official["calls"]
    official["listing"] = [official["record"]] * (module.MAX_RECORDS + 1)
    result = discover()
    assert len(official["calls"]) == 2
    assert any(e["error"] == "figshare_record_limit_reached" for e in result["errors"])
    assert len(result["items"]) == 1


@pytest.mark.parametrize(
    "url,allowed",
    [
        (FILE, True),
        (FILE + "?token=secret", False),
        (
            "https://s3-eu-west-1.amazonaws.com/pstorage-acs-6854636/456/fixture_si_001.pdf?X-Amz-Signature=test",
            True,
        ),
        (
            "https://s3-eu-west-1.amazonaws.com/other-bucket/456/fixture_si_001.pdf",
            False,
        ),
        (
            "https://s3-eu-west-1.amazonaws.com/pstorage-acs-6854636/457/fixture_si_001.pdf",
            False,
        ),
        (
            "https://s3-eu-west-1.amazonaws.com/pstorage-acs-6854636/456/other.pdf",
            False,
        ),
        ("https://ndownloader.figshare.com.evil.example/files/456", False),
        ("http://ndownloader.figshare.com/files/456", False),
        ("https://user:pass@ndownloader.figshare.com/files/456", False),
        ("https://api.figshare.com/v2/files/456", False),
    ],
)
def test_download_origin_and_redirect_are_scoped_to_manifest_file(
    official, url, allowed
):
    attachment = discover()["items"][0]
    assert module.file_url_allowed(url, attachment) is allowed
    assert supplements._attachment_url_allowed(PAGE, url, attachment) is allowed
    assert not supplements._official_link("https://pubs.acs.org/article", FILE)


@pytest.mark.parametrize("failure", [None, "size", "checksum"])
def test_native_acquisition_registers_reuses_and_checks_manifest_before_save(
    official, tmp_path, monkeypatch, failure
):
    library = LibraryService(tmp_path / "library")
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf_bytes(150))
    parent = library.import_pdf(main, title=TITLE, doi=DOI)
    main = Path(parent["pdf_path"])
    parent_record = validate_parser_input(main).sidecar_path
    original = main.read_bytes(), parent_record.read_bytes()
    if failure == "size":
        official["record"]["files"][0]["size"] += 1
    if failure == "checksum":
        official["record"]["files"][0]["computed_md5"] = "0" * 32
    calls = []

    def download(url, *, output_dir, **kwargs):
        calls.append(url)
        path = Path(output_dir) / "download.part"
        path.write_bytes(official["body"])
        return SimpleNamespace(
            local_path=path,
            final_url=url,
            sha256=hashlib.sha256(official["body"]).hexdigest(),
        )

    def browser(*args, **kwargs):
        pytest.fail("native public route must not need a browser")

    monkeypatch.setattr(supplements, "retrieve_page", browser)
    result = supplements.acquire_supplements(main, library=library, file_fetch=download)
    assert (main.read_bytes(), parent_record.read_bytes()) == original
    assert not list(main.parent.rglob("*.part"))
    if failure:
        assert (
            result["status"] == "FAILED"
            and not library.get(parent["id"])["attachments"]
        )
        assert (
            result["items"][0]["error"]
            == f"official_attachment_{'size' if failure == 'size' else 'checksum'}_mismatch"
        )
        return
    assert result["status"] == "COMPLETED" and result["items"][0]["transport"] == "http"
    source = validate_parser_input(result["items"][0]["path"])
    assert (
        source.document_role == "SUPPLEMENT"
        and source.parent["pdf_sha256"] == parent["pdf_sha256"]
    )
    receipt = json.loads(
        Path(result["items"][0]["source_record"]).read_text(encoding="utf-8")
    )
    assert receipt["association_basis"] == module.BASIS
    second = supplements.acquire_supplements(main, library=library, file_fetch=download)
    assert second["items"][0]["status"] == "REUSED" and len(calls) == 1
    # A changed official manifest cannot reuse a previously valid file merely
    # because its URL and local SHA-256 still match the historical receipt.
    official["record"]["files"][0]["computed_md5"] = "0" * 32
    changed = supplements.acquire_supplements(
        main, library=library, file_fetch=download
    )
    assert changed["status"] == "FAILED"
    assert changed["items"][0]["error"] == "official_attachment_checksum_mismatch"
    assert len(calls) == 2 and Path(result["items"][0]["path"]).is_file()


def test_metadata_reader_streams_bounded_public_requests_and_rejects_redirects(
    monkeypatch,
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[{"id": 123}])

    real_client = httpx.Client
    monkeypatch.setattr(module, "validate_safe_url", lambda u: u)
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    value, fingerprint = module._read_json(
        module.API + "/search", timeout=2, search={"resource_doi": DOI}
    )
    assert value == [{"id": 123}] and len(fingerprint) == 64
    assert (
        requests[0].method == "POST"
        and json.loads(requests[0].content)["resource_doi"] == DOI
    )
    assert (
        "authorization" not in requests[0].headers
        and "cookie" not in requests[0].headers
    )
    monkeypatch.setattr(module, "MAX_JSON_BYTES", 1)
    with pytest.raises(ValueError, match="exceeds_limit"):
        module._read_json(module.API, timeout=2)


def test_metadata_redirect_is_not_followed(monkeypatch):
    real_client = httpx.Client
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(
            302, headers={"location": "https://untrusted.example/metadata"}
        )

    monkeypatch.setattr(module, "validate_safe_url", lambda u: u)
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(respond), **kw),
    )
    with pytest.raises(Exception):
        module._read_json(module.API, timeout=2)
    assert len(calls) == 1


def test_native_no_result_keeps_existing_official_html_fallback(official, tmp_path):
    official["listing"] = []
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf_bytes(100))
    register_local_pdf(main, output_dir=tmp_path, title=TITLE, doi=DOI)
    url = "https://pubs.acs.org/doi/suppl/" + DOI + "/suppl_file/si.pdf"
    pages = []

    def page_fetch(*args, **kwargs):
        pages.append(args[0])
        return SimpleNamespace(
            text=f'<meta name="citation_doi" content="{DOI}"><a href="{url}">Supporting information</a>',
            final_url="https://pubs.acs.org/doi/" + DOI,
            body_truncated=False,
        )

    def file_fetch(url, *, output_dir, **kwargs):
        path = Path(output_dir) / "download.part"
        path.write_bytes(official["body"])
        return SimpleNamespace(
            local_path=path,
            final_url=url,
            sha256=hashlib.sha256(official["body"]).hexdigest(),
        )

    result = supplements.acquire_supplements(
        main, page_fetch=page_fetch, file_fetch=file_fetch
    )
    assert pages and result["status"] == "COMPLETED"
    assert result["items"][0]["transport"] == "http"


def test_api_failure_keeps_diagnostic_and_does_not_retry_endpoint(monkeypatch):
    from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionRateLimitError

    calls = []

    def failed(*args, **kwargs):
        calls.append(args)
        raise AcquisitionRateLimitError("stop")

    monkeypatch.setattr(module, "_read_json", failed)
    result = discover()
    assert result["status"] == "FAILED" and len(calls) == 1
    assert result["errors"][0]["error"] == "AcquisitionRateLimitError"


def test_roles_remain_distinct_and_duplicate_files_are_not_counted_twice(official):
    file = official["record"]["files"][0]
    official["record"]["files"] = [
        file,
        dict(file),
        {
            **file,
            "id": 457,
            "name": "Source_Data.csv",
            "download_url": FILE.replace("456", "457"),
        },
    ]
    result = discover()
    assert [item["role"] for item in result["items"]] == ["SUPPLEMENT", "SOURCE_DATA"]
