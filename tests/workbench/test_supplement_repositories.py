"""Official repository SI must remain bound to one verified parent/version."""

import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench import supplement_repositories as module

DOI = "10.1126/sciadv.aeb1911"
TITLE = "Oxalic acid conversion via oxygen vacancy-mediated catalysis"
PREFIX = "PMC12922741.1"
BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com"


def jats(links=None, extra_ids="", title=TITLE, tail="", attributes=""):
    links = ["si.pdf"] if links is None else links
    supplements = "".join(
        f'<supplementary-material {attributes}><caption><p>Supplementary information</p></caption><media xlink:href="{link}"/></supplementary-material>'
        for link in links
    )
    return (
        f'<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><article-id pub-id-type="doi">{DOI}</article-id><article-id pub-id-type="pmcid">PMC12922741</article-id><article-id pub-id-type="pmcid-ver">{PREFIX}</article-id>{extra_ids}<title-group><article-title>{title}</article-title></title-group></article-meta></front><back>{supplements}{tail}</back></article>'
    ).encode()


@pytest.fixture
def official(monkeypatch):
    source = {
        "status": "VERIFIED",
        "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
        "target": {"doi": DOI, "expected_title": TITLE},
        "retrieval": {"final_url": f"{BUCKET}/{PREFIX}/{PREFIX}.pdf?md5=redacted"},
    }
    state = {"xml": jats(), "metadata": {}, "calls": []}

    def metadata():
        return {
            "doi": DOI,
            "pmcid": "PMC12922741",
            "version": 1,
            "title": TITLE,
            "is_pmc_openaccess": True,
            "is_retracted": False,
            "license_code": "CC BY-NC",
            "xml_url": f"s3://pmc-oa-opendata/{PREFIX}/{PREFIX}.xml?md5="
            + hashlib.md5(state["xml"]).hexdigest(),
            "media_urls": [
                f"s3://pmc-oa-opendata/{PREFIX}/si.pdf?md5=" + "a" * 32,
                f"s3://pmc-oa-opendata/{PREFIX}/figure1.jpg?md5=" + "b" * 32,
            ],
            **state["metadata"],
        }

    def retrieve(url, *, output_dir, **kwargs):
        state["calls"].append((url, kwargs))
        if url == f"{BUCKET}/metadata/{PREFIX}.json":
            data = json.dumps(metadata()).encode()
        elif url.startswith(f"{BUCKET}/{PREFIX}/{PREFIX}.xml?"):
            data = state["xml"]
        else:
            pytest.fail("Discovery must not fetch unlisted URLs or any SI file")
        path = module.Path(output_dir) / f"request-{len(state['calls'])}.part"
        path.write_bytes(data)
        return SimpleNamespace(local_path=path, final_url=url)

    monkeypatch.setattr(module, "retrieve_to_temp", retrieve)
    return source, state


def discover(source):
    return module.discover_pmc_attachments(source, doi=DOI, title=TITLE)


def test_explicit_jats_media_mapping_excludes_ordinary_figures_without_downloading_files(
    official,
):
    source, state = official
    before = deepcopy(source)
    result = discover(source)
    assert result["status"] == "DISCOVERED" and not result["errors"]
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["url"] == f"{BUCKET}/{PREFIX}/si.pdf?md5=" + "a" * 32
    assert item["role"] == "SUPPLEMENT" and item["extension"] == ".pdf"
    assert item["expected_md5"] == "a" * 32
    assert item["evidence"]["doi"] == DOI
    assert item["page"] == f"{BUCKET}/metadata/{PREFIX}.json"
    assert len(state["calls"]) == 2
    assert source == before
    assert all(call[1]["max_redirects"] == 2 for call in state["calls"])


@pytest.mark.parametrize(
    "url",
    [
        "https://www.science.org/doi/10.1126/sciadv.aeb1911",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC12922741/",
        "https://pmc-oa-opendata.s3.amazonaws.com.evil.test/PMC12922741.1/PMC12922741.1.pdf",
        "https://example.org/PMC12922741.1/PMC12922741.1.pdf",
        f"{BUCKET}/{PREFIX}/different.pdf",
        f"{BUCKET}/PMC12922741.2/{PREFIX}.pdf",
    ],
)
def test_non_exact_official_verified_main_origin_makes_zero_requests(official, url):
    source, state = official
    source["retrieval"]["final_url"] = url
    # A stale candidate must not override the actual non-PMC final origin.
    source["candidate"] = {"url": f"{BUCKET}/{PREFIX}/{PREFIX}.pdf"}
    assert discover(source)["status"] == "NOT_SUPPORTED"
    assert state["calls"] == []


@pytest.mark.parametrize(
    "field,value", [("status", "REGISTERED"), ("status", "UNVERIFIED")]
)
def test_unverified_main_never_enables_repository_lookups(official, field, value):
    source, state = official
    source[field] = value
    assert discover(source)["status"] == "FAILED"
    assert not state["calls"]


@pytest.mark.parametrize("changed", ["role", "identity", "doi"])
def test_wrong_main_role_identity_or_doi_is_refused_before_network(official, changed):
    source, state = official
    if changed == "role":
        source["identity_validation"]["document_role"] = "SUPPLEMENT"
    elif changed == "identity":
        source["identity_validation"]["status"] = "DECLARED"
    else:
        source["target"]["doi"] = "10.1000/other"
    assert discover(source)["status"] == "FAILED"
    assert state["calls"] == []


@pytest.mark.parametrize(
    "override",
    [
        {"doi": "10.1000/other"},
        {"doi": [DOI, "10.1000/other"]},
        {"pmcid": "PMC999"},
        {"version": 2},
        {"version": True},
        {"is_pmc_openaccess": False},
        {"is_retracted": True},
        {"title": "A different paper"},
    ],
)
def test_metadata_parent_identity_and_permission_mismatch_is_not_absence(
    official, override
):
    source, state = official
    state["metadata"].update(override)
    result = discover(source)
    assert result["status"] == "FAILED" and result["items"] == []
    assert result["errors"]
    assert len(state["calls"]) == 1


@pytest.mark.parametrize(
    "extra,title",
    [
        ('<article-id pub-id-type="doi">10.1000/other</article-id>', TITLE),
        ('<article-id pub-id-type="pmcid-ver">PMC12922741.2</article-id>', TITLE),
        ("", "A different paper"),
    ],
)
def test_ambiguous_or_wrong_jats_parent_is_rejected(official, extra, title):
    source, state = official
    state["xml"] = jats(extra_ids=extra, title=title)
    result = discover(source)
    assert result["status"] == "FAILED" and not result["items"]


def test_reference_doi_is_not_confused_with_parent_identity(official):
    source, state = official
    state["xml"] = jats(
        tail='<ref-list><ref><pub-id pub-id-type="doi">10.1000/other</pub-id><supplementary-material xlink:href="reference.pdf"/></ref></ref-list>'
    )
    assert discover(source)["status"] == "DISCOVERED"


@pytest.mark.parametrize(
    "xml_url",
    [
        "https://evil.test/article.xml",
        f"s3://other-bucket/{PREFIX}/{PREFIX}.xml?md5=" + "a" * 32,
        "s3://pmc-oa-opendata/PMC999.1/PMC999.1.xml?md5=" + "a" * 32,
        f"s3://pmc-oa-opendata/{PREFIX}/{PREFIX}.xml?md5=bad",
        f"s3://pmc-oa-opendata/{PREFIX}/{PREFIX}.xml?md5=" + "a" * 32,
    ],
)
def test_cross_origin_wrong_version_missing_or_tampered_xml_checksum_fails(
    official, xml_url
):
    source, state = official
    state["metadata"]["xml_url"] = xml_url
    assert discover(source)["status"] == "FAILED"


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.test/si.pdf",
        "../si.pdf",
        "folder/si.pdf",
        "%2e%2e%2fsi.pdf",
        "si.pdf?download=1",
    ],
)
def test_jats_external_or_unbound_links_are_not_requested(official, href):
    source, state = official
    state["xml"] = jats([href])
    result = discover(source)
    assert result["status"] == "FAILED"
    assert not result["items"] and len(state["calls"]) == 2


@pytest.mark.parametrize(
    "media",
    [
        [],
        ["https://evil.test/si.pdf"],
        [f"s3://other-bucket/{PREFIX}/si.pdf?md5=" + "a" * 32],
    ],
)
def test_missing_or_cross_domain_media_mapping_is_explicit_failure(official, media):
    source, state = official
    state["metadata"]["media_urls"] = media
    result = discover(source)
    assert result["status"] == "FAILED" and result["errors"]


def test_ambiguous_same_filename_media_is_not_first_match(official):
    source, state = official
    state["metadata"]["media_urls"] = [
        f"s3://pmc-oa-opendata/{PREFIX}/si.pdf?md5=" + checksum * 32
        for checksum in ("a", "b")
    ]
    assert discover(source)["status"] == "FAILED"


def test_multiple_files_and_roles_remain_distinct_and_duplicates_are_not_repeated(
    official,
):
    source, state = official
    state["xml"] = jats(
        [
            "si.pdf",
            "si.pdf",
            "reporting_summary.pdf",
            "source_data.xlsx",
            "peer_review.pdf",
        ]
    )
    state["metadata"]["media_urls"] = [
        f"s3://pmc-oa-opendata/{PREFIX}/{name}?md5=" + "a" * 32
        for name in (
            "si.pdf",
            "reporting_summary.pdf",
            "source_data.xlsx",
            "peer_review.pdf",
        )
    ]
    result = discover(source)
    assert result["status"] == "DISCOVERED"
    assert [row["role"] for row in result["items"]] == [
        "SUPPLEMENT",
        "REPORTING_SUMMARY",
        "SOURCE_DATA",
        "PEER_REVIEW",
    ]
    assert len(result["items"]) == 4


def test_one_broken_attachment_does_not_erase_other_discovered_links(official):
    source, state = official
    state["xml"] = jats(["si.pdf", "missing.pdf"])
    result = discover(source)
    assert result["status"] == "DISCOVERED" and result["partial"]
    assert len(result["items"]) == 1 and len(result["errors"]) == 1


def test_valid_article_without_explicit_supplement_reports_not_found(official):
    source, state = official
    state["xml"] = jats([])
    result = discover(source)
    assert result["status"] == "NOT_FOUND" and not result["errors"]


def test_network_or_challenge_failure_does_not_become_clean_absence(
    official, monkeypatch
):
    source, _ = official
    monkeypatch.setattr(
        module,
        "retrieve_to_temp",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("公开页面暂时不可用")
        ),
    )
    result = discover(source)
    assert result["status"] == "FAILED" and result["errors"]


def test_xml_entities_are_not_expanded(official):
    source, state = official
    state["xml"] = b'<!DOCTYPE article [<!ENTITY x "not allowed">]>' + jats()
    result = discover(source)
    assert result["status"] == "FAILED" and not result["items"]


def test_jats_structural_supplement_role_does_not_require_a_filename_guess(official):
    source, state = official
    state["xml"] = jats(["aeb1911_sm.pdf"]).replace(
        b"Supplementary information", b"Figs. S1 to S42 Table S1 References"
    )
    state["metadata"]["media_urls"] = [
        f"s3://pmc-oa-opendata/{PREFIX}/aeb1911_sm.pdf?md5=" + "a" * 32
    ]
    result = discover(source)
    assert result["status"] == "DISCOVERED"
    assert result["items"][0]["role"] == "SUPPLEMENT"


def test_malformed_xml_is_a_recorded_failure(official):
    source, state = official
    state["xml"] = b"<article><broken>"
    result = discover(source)
    assert result["status"] == "FAILED" and result["errors"]


def test_source_title_cannot_be_overridden_by_the_callers_other_title(official):
    source, state = official
    source["target"]["expected_title"] = "Another original source title"
    assert discover(source)["status"] == "FAILED"
    assert not state["calls"]


@pytest.mark.parametrize(
    "final",
    [
        "https://other.example/metadata.json",
        f"{BUCKET}/metadata/another.json",
        f"http://pmc-oa-opendata.s3.amazonaws.com/metadata/{PREFIX}.json",
    ],
)
def test_repository_evidence_may_not_redirect_to_another_object_or_origin(
    official, monkeypatch, final
):
    source, _ = official
    retrieve = module.retrieve_to_temp

    def redirected(*args, **kwargs):
        result = retrieve(*args, **kwargs)
        result.final_url = final
        return result

    monkeypatch.setattr(module, "retrieve_to_temp", redirected)
    assert discover(source)["status"] == "FAILED"


@pytest.mark.parametrize(
    "value",
    [
        {"retrieval": []},
        {"retrieval": {"final_url": "https://[bad"}},
        {"candidate": []},
    ],
)
def test_malformed_source_origins_do_not_make_network_requests(official, value):
    _, state = official
    assert discover(value)["status"] == "NOT_SUPPORTED"
    assert not state["calls"]
