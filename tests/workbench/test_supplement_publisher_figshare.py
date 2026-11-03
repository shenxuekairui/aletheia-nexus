"""Shared Figshare rules retain publisher and file boundaries across portals."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.workbench import supplement_figshare as module
from aletheia_nexus.workbench import supplements
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.standalone_supplements import StandaloneSupplementService


@pytest.fixture(params=["AIP", "Royal_Society", "Taylor_Francis"])
def portal(request, monkeypatch):
    from tests.workbench.test_supplement_figshare import pdf_bytes

    publisher = request.param
    prefix, host, _ = module.PUBLISHERS[publisher]
    doi, title = prefix + "fixture.01234", "Independent publisher fixture"
    supplement = (
        "10.60893/figshare.apl.123.v1"
        if publisher == "AIP"
        else "10.6084/m9.figshare.123.v2"
    )
    body = pdf_bytes()
    record = {
        "id": 123,
        "doi": supplement,
        "resource_doi": doi,
        "resource_title": title,
        "title": "Supplement Number 1",
        "url_public_html": f"https://{host}/articles/journal_contribution/SI/123",
        "is_public": True,
        "is_confidential": False,
        "is_embargoed": False,
        "status": "public",
        "version": 1,
        "files": [
            {
                "id": 456,
                "name": "Supporting Information.pdf",
                "size": len(body),
                "is_link_only": False,
                "computed_md5": hashlib.md5(body).hexdigest(),
                "download_url": "https://ndownloader.figshare.com/files/456",
            }
        ],
    }
    state = dict(publisher=publisher, doi=doi, title=title, record=record, body=body)

    def read(url, *, search=None, **_):
        assert search is None or search["resource_doi"] == doi
        value = [record] if search else record
        return deepcopy(value), hashlib.sha256(json.dumps(value).encode()).hexdigest()

    monkeypatch.setattr(module, "_read_json", read)
    return state


def discover(portal):
    return module.discover_publisher_attachments(
        doi=portal["doi"], title=None, allow_publisher_title=True
    )


def test_publisher_manifest_preserves_parent_checksum_and_file_scope(portal):
    result = discover(portal)
    assert result["status"] == "DISCOVERED" and not result["errors"]
    item = result["items"][0]
    assert result["parent_title"] == portal["title"]
    assert item["evidence"]["publisher"] == portal["publisher"]
    assert item["expected_md5"] == hashlib.md5(portal["body"]).hexdigest()
    buckets = {
        "AIP": "figshare-production-eu-aip-storage5262-eu-west-1",
        "Royal_Society": "pstorage-rs-4828782598",
        "Taylor_Francis": "pstorage-tf-iopjsd8797887",
    }
    name = item["evidence"]["filename"]
    if portal["publisher"] == "AIP":
        name = name.replace(" ", "")
    url = (
        f"https://s3-eu-west-1.amazonaws.com/{buckets[portal['publisher']]}/456/{name}"
    )
    assert supplements._attachment_url_allowed(item["page"], url, item)
    for bad in [
        url.replace("/456/", "/457/"),
        url.replace(buckets[portal["publisher"]], "other-bucket"),
        url.replace(name, "other.pdf"),
    ]:
        assert not supplements._attachment_url_allowed(item["page"], bad, item)


@pytest.mark.parametrize(
    "field,value",
    [
        ("resource_doi", "10.1063/wrong"),
        ("resource_title", "A different article"),
        ("url_public_html", "https://figshare.com/articles/SI/123"),
        ("doi", "10.6084/m9.figshare.124.v1"),
        ("is_public", False),
        ("is_embargoed", True),
    ],
)
def test_publisher_conflicts_do_not_authorize_files(portal, field, value):
    if field == "resource_title":
        result = module.discover_publisher_attachments(doi=portal["doi"], title=value)
    else:
        portal["record"][field] = value
        result = discover(portal)
    assert not result["items"] and result["errors"]


def test_review_role_uses_record_title_even_for_numeric_filenames(portal):
    portal["record"]["title"] = "Peer review history"
    portal["record"]["files"][0]["name"] = "123.pdf"
    assert discover(portal)["items"][0]["role"] == "PEER_REVIEW"


def test_independent_publisher_saves_and_reuses_without_a_main(portal, tmp_path):
    def fetch(url, *, output_dir, **_):
        path = output_dir / "file.part"
        path.write_bytes(portal["body"])
        return SimpleNamespace(local_path=path, final_url=url, sha256=sha256_file(path))

    library = LibraryService(tmp_path / "library")
    service = StandaloneSupplementService(library)
    options = dict(
        metadata_lookup=lambda *_: (_ for _ in ()).throw(RuntimeError("unavailable")),
        pmc_lookup=lambda *_: None,
        file_fetch=fetch,
    )
    first = service.acquire(portal["doi"], **options)
    assert first["status"] == "COMPLETED" and first["si_count"] == 1
    assert not library.scan()["items"]
    item = service.get(first["items"][0]["id"])
    original = Path(item["source_record"]).read_bytes()
    second = service.acquire(portal["doi"], **options)
    assert second["items"][0]["status"] == "REUSED"
    assert Path(item["source_record"]).read_bytes() == original


def test_unknown_publisher_does_not_query_repository(monkeypatch):
    monkeypatch.setattr(
        module, "_read_json", lambda *_a, **_k: pytest.fail("unsupported")
    )
    assert (
        module.discover_publisher_attachments(doi="10.9999/fixture", title="A")[
            "status"
        ]
        == "NOT_SUPPORTED"
    )


def test_review_only_repository_still_discovers_actual_si(portal, monkeypatch):
    from aletheia_nexus.workbench import supplement_repositories

    monkeypatch.setattr(
        supplement_repositories,
        "discover_pmc_attachments",
        lambda *_a, **_k: {
            "status": "DISCOVERED",
            "page_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/",
            "items": [
                {
                    "role": "PEER_REVIEW",
                    "url": "https://www.ncbi.nlm.nih.gov/review.pdf",
                }
            ],
        },
    )
    result = supplements.discover_supplement_candidates(
        doi=portal["doi"],
        title=portal["title"],
        page_fetch=lambda *_a, **_k: pytest.fail(
            "official manifest already supplied SI"
        ),
    )
    assert [item["role"] for item in result["items"]] == ["PEER_REVIEW", "SUPPLEMENT"]
