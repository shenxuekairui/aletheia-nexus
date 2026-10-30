"""Bound official manifest work with operation counts, never wall-clock claims."""

import hashlib
import json

import pytest

from aletheia_nexus.workbench import supplement_repositories as module

DOI, PREFIX, TITLE = "10.1000/repository", "PMC12345.1", "Fixture parent"
BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com"


@pytest.fixture
def repository(monkeypatch):
    state = {
        "nodes": "",
        "media": [
            f"s3://pmc-oa-opendata/{PREFIX}/si{i:04}.pdf?md5=" + "a" * 32
            for i in range(2000)
        ],
        "reads": [],
        "url_reads": 0,
    }
    original_split = module.urlsplit

    def split(value):
        state["url_reads"] += 1
        return original_split(value)

    def read(url, *_):
        state["reads"].append(url)
        xml = (
            f'<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>'
            f'<article-id pub-id-type="doi">{DOI}</article-id>'
            f'<article-id pub-id-type="pmcid">PMC12345</article-id>'
            f'<article-id pub-id-type="pmcid-ver">{PREFIX}</article-id>'
            f"<title-group><article-title>{TITLE}</article-title></title-group>"
            f"</article-meta></front><back>{state['nodes']}</back></article>"
        ).encode()
        if url == f"{BUCKET}/metadata/{PREFIX}.json":
            payload = json.dumps(
                {
                    "doi": DOI,
                    "pmcid": "PMC12345",
                    "version": 1,
                    "title": TITLE,
                    "is_pmc_openaccess": True,
                    "is_retracted": False,
                    "xml_url": f"s3://pmc-oa-opendata/{PREFIX}/{PREFIX}.xml?md5="
                    + hashlib.md5(xml).hexdigest(),
                    "media_urls": state["media"],
                }
            ).encode()
        else:
            assert url.startswith(f"{BUCKET}/{PREFIX}/{PREFIX}.xml?md5=")
            payload = xml
        return payload, {"url": url, "sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(module, "_read", read)
    monkeypatch.setattr(module, "urlsplit", split)
    source = {
        "status": "VERIFIED",
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
        "target": {"doi": DOI, "expected_title": TITLE},
        "retrieval": {"final_url": f"{BUCKET}/{PREFIX}/{PREFIX}.pdf"},
    }
    return source, state


def nodes(links):
    return "".join(
        f'<supplementary-material><media xlink:href="{name}"/></supplementary-material>'
        for name in links
    )


def test_many_unselected_media_files_are_indexed_once(repository):
    source, state = repository
    state["nodes"] = nodes([f"si{i:04}.pdf" for i in range(64)])
    result = module.discover_pmc_attachments(source, doi=DOI, title=TITLE)
    assert result["status"] == "DISCOVERED" and len(result["items"]) == 64
    assert not result["errors"] and not result["truncated"]
    assert state["url_reads"] < 3 * len(state["media"])
    assert len(state["reads"]) == 2  # Metadata + JATS, no SI request.
    assert all(item["expected_md5"] == "a" * 32 for item in result["items"])


def test_file_cap_stops_instead_of_scanning_all_remaining_links(repository):
    source, state = repository
    state["nodes"] = nodes([f"si{i:04}.pdf" for i in range(256)])
    result = module.discover_pmc_attachments(source, doi=DOI, title=TITLE)
    assert result["status"] == "PARTIAL" and result["partial"] and result["truncated"]
    assert len(result["items"]) == 64 and len(result["errors"]) == 1
    assert result["scanned_candidates"] == 65
    assert state["url_reads"] < 3 * len(state["media"])


def test_missing_file_candidates_have_a_bound_even_when_no_file_is_found(repository):
    source, state = repository
    state["nodes"] = (
        "<supplementary-material>"
        + "".join(f'<media xlink:href="missing{i:04}.pdf"/>' for i in range(300))
        + "</supplementary-material>"
    )
    result = module.discover_pmc_attachments(source, doi=DOI, title=TITLE)
    assert result["status"] == "PARTIAL" and result["truncated"]
    assert not result["items"] and result["scanned_candidates"] == 256
    assert len(result["errors"]) == 257 and len(state["reads"]) == 2
    assert state["url_reads"] < 3 * len(state["media"])


def test_empty_supplement_nodes_cannot_produce_unbounded_diagnostics(repository):
    source, state = repository
    state["nodes"] = "<supplementary-material/>" * 300
    result = module.discover_pmc_attachments(source, doi=DOI, title=TITLE)
    assert result["status"] == "PARTIAL" and result["truncated"]
    assert result["scanned_nodes"] == 256 and len(result["errors"]) == 257


def test_index_keeps_wrong_origin_conflict_for_strict_object_authorization(repository):
    source, state = repository
    state["nodes"] = nodes(["si0000.pdf"])
    state["media"][-1] = (
        "s3://foreign-bucket/another-version/si0000.pdf?md5=" + "b" * 32
    )
    result = module.discover_pmc_attachments(source, doi=DOI, title=TITLE)
    assert result["status"] == "FAILED" and not result["items"]
    assert "官方存档" in result["errors"][0]["error"]
