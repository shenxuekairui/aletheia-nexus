import httpx
import pytest

from aletheia_nexus.workbench import supplements

DOI = "10.1000/native"
PAGE = "https://www.nature.com/articles/native"


def discover(body, doi=DOI):
    return supplements.discover_attachments(
        f'<meta name="citation_doi" content="{doi}">{body}', PAGE, doi=DOI
    )


def test_explicit_supplementary_metadata_and_rel_links_use_parent_gate():
    body = """<meta name="citation_supplementary_material" content="/files/data.xlsx">
    <meta name="citation_supplementary_material_url" content="/files/si.pdf">
    <link rel="supplementary" href="/files/tables.csv">
    <a href="/files/si.pdf">Supplementary Information</a>
    <meta name="citation_pdf_url" content="/files/main.pdf">"""
    result = discover(body)
    assert len(result["items"]) == 3
    assert {x["extension"] for x in result["items"]} == {".xlsx", ".pdf", ".csv"}
    assert all(x["role"] == "SUPPLEMENT" for x in result["items"])
    assert not discover(body, "10.1000/other")["items"]
    assert not discover(body + '<meta name="citation_doi" content="10.1000/other">')[
        "items"
    ]


def test_metadata_and_base_cannot_authorize_other_hosts_or_main_pdf():
    result = discover("""<base href="https://untrusted.example/">
    <meta name="citation_supplementary_material" content="https://untrusted.example/si.pdf">
    <meta name="citation_supplementary_material" content="/files/good.pdf">
    <a href="/main.pdf">Main article</a>""")
    assert [x["url"] for x in result["items"]] == [
        "https://www.nature.com/files/good.pdf"
    ]
    assert result["excluded"][0]["reason"] == "attachment_host_not_covered"


def test_same_official_base_is_used_for_relative_supplement_links():
    result = discover(
        '<base href="/static/files/"><a href="si.pdf">Supplementary Information</a>'
    )
    assert result["items"][0]["url"] == "https://www.nature.com/static/files/si.pdf"


def test_http_download_uses_verified_article_referer_without_query_tokens(
    monkeypatch, tmp_path
):
    observed = []
    monkeypatch.setattr(
        httpx.Client,
        "stream",
        lambda self, method, target, **kwargs: observed.append((target, kwargs)),
    )
    monkeypatch.setattr(
        supplements,
        "retrieve_to_temp",
        lambda url, *, client, **kwargs: client.stream(
            "GET", url, headers={"User-Agent": "test"}
        ),
    )
    supplements._retrieve_official_file(
        "https://static-content.springer-cdn.com/si.pdf",
        source_page=PAGE + "?access_token=private",
        output_dir=tmp_path,
    )
    headers = observed[0][1]["headers"]
    assert headers["Referer"] == PAGE and headers["User-Agent"] == "test"
    assert "private" not in repr(observed) and "Cookie" not in headers


def test_sciencedirect_article_candidate_reuses_recorded_pii_before_doi_redirect():
    record = {
        "access": {
            "source_page_url": "https://linkinghub.elsevier.com/retrieve/pii/S1234567890123456"
        }
    }
    assert supplements._source_page_candidates(record, DOI) == [
        "https://www.sciencedirect.com/science/article/pii/S1234567890123456",
        "https://doi.org/" + DOI,
    ]


def test_figshare_file_gate_is_applied_before_untrusted_redirect_http(
    monkeypatch, tmp_path
):
    from aletheia_nexus.workbench.supplement_figshare import BASIS

    item = {
        "association_basis": BASIS,
        "evidence": {"file_id": 123, "filename": "si.pdf"},
    }

    def forbidden(*args, **kwargs):
        pytest.fail("untrusted redirect must not be requested")

    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    monkeypatch.setattr(
        supplements,
        "retrieve_to_temp",
        lambda url, *, client, **kwargs: client.stream(
            "GET", "https://s3-eu-west-1.amazonaws.com/other/123/si.pdf"
        ),
    )
    with pytest.raises(ValueError, match="attachment_redirect_host_not_covered"):
        supplements._retrieve_official_file(
            "https://ndownloader.figshare.com/files/123",
            source_page="https://acs.figshare.com/articles/record/321",
            attachment=item,
            output_dir=tmp_path,
        )
