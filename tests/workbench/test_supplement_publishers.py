"""Publisher forms observed in the real default-profile article pages."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import supplements


def html(doi, content, *, key="citation_doi"):
    return f'<meta name="{key}" content="{doi}">{content}'


@pytest.mark.parametrize(
    "label", ["cctc201901955-sup-0001-misc_information.pdf", "Download"]
)
def test_wiley_query_doi_and_real_filename_determine_attachment_identity_and_type(
    label,
):
    doi = "10.1002/cctc.201901955"
    url = "https://chemistry-europe.onlinelibrary.wiley.com/doi/" + doi
    link = "/action/downloadSupplement?doi=10.1002%2Fcctc.201901955&amp;file=cctc201901955-sup-0001-misc_information.pdf"
    result = supplements.discover_attachments(
        html(doi, f'<a href="{link}">{label}</a>'), url, doi=doi
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["extension"] == ".pdf"
    assert result["items"][0]["role"] == "SUPPLEMENT"


@pytest.mark.parametrize(
    "query",
    [
        "doi=10.1002%2Fother&file=a.pdf",
        "doi=10.1002%2Fcctc.201901955&file=../a.pdf",
        "doi=10.1002%2Fcctc.201901955&doi=10.1002%2Fother&file=a.pdf",
    ],
)
def test_wiley_rejects_wrong_ambiguous_doi_or_path_disguised_as_filename(query):
    doi = "10.1002/cctc.201901955"
    result = supplements.discover_attachments(
        html(
            doi,
            f'<a href="/action/downloadSupplement?{query}">Supporting Information</a>',
        ),
        "https://onlinelibrary.wiley.com/doi/" + doi,
        doi=doi,
    )
    assert result["items"] == []
    assert result["excluded"][0]["reason"] == "publisher_attachment_identity_mismatch"


def test_acs_new_extensionless_route_binds_journal_article_id_and_original_doi_token():
    doi = "10.1021/ja0659323"
    page = "https://pubs.acs.org/jacsat/article/128/51/16414/3525402/Competitive-Chemisorption-between-Pairs-of"
    path = "/jacsat/article-supplement/3525402/pdf/ja0659323_si_001/"
    result = supplements.discover_attachments(
        html(doi, f'<a href="{path}">suppl-mat1</a>'), page, doi=doi
    )
    assert result["items"][0]["extension"] == ".pdf"
    assert result["items"][0]["role"] == "SUPPLEMENT"
    for wrong in [
        path.replace("3525402", "3525403"),
        path.replace("ja0659323", "ja1234567"),
        path.replace("jacsat", "other"),
    ]:
        rejected = supplements.discover_attachments(
            html(doi, f'<a href="{wrong}">Supporting Information</a>'), page, doi=doi
        )
        assert rejected["items"] == []
        assert (
            rejected["excluded"][0]["reason"]
            == "publisher_attachment_identity_mismatch"
        )


def test_elsevier_mmc_requires_same_article_pii_and_explicit_supplementary_section():
    doi = "10.1016/j.elecom.2022.107204"
    page = "https://www.sciencedirect.com/science/article/pii/S1388248122000066"
    word = "https://ars.els-cdn.com/content/image/1-s2.0-S1388248122000066-mmc1.docx"
    body = f'''<a href="/journal/electrochemistry-communications/vol/135/suppl/C">Volume 135</a>
    <h2>Appendix A. Supplementary data</h2><a href="{word}">Download: Download Word document (1MB)</a>
    <h2>References</h2><a href="https://ars.els-cdn.com/content/image/1-s2.0-S1388248122000066-mmc2.docx">A cited file</a>'''
    result = supplements.discover_attachments(html(doi, body), page, doi=doi)
    assert len(result["items"]) == 1
    assert result["items"][0]["url"] == word
    assert result["items"][0]["extension"] == ".docx"
    assert result["items"][0]["role"] == "SUPPLEMENT"
    assert (
        supplements.discover_attachments(
            html(
                doi,
                body.replace("-mmc1", "-mmc1").replace(
                    "S1388248122000066-mmc1", "S1388248122009999-mmc1"
                ),
            ),
            page,
            doi=doi,
        )["items"]
        == []
    )


def test_rsc_new_extensionless_pdf_route_is_bound_to_parent_article_and_doi_token():
    doi = "10.1039/d1cy02168k"
    page = "https://pubs.rsc.org/cy/article/12/3/834/724382/Asymmetric-hydroamination"
    path = "/cy/article-supplement/724382/pdf/d1cy02168k1_suppl/"
    result = supplements.discover_attachments(
        html(doi, f'<a href="{path}">Supplementary information (PDF)</a>'),
        page,
        doi=doi,
    )
    assert result["items"][0]["extension"] == ".pdf"
    assert result["items"][0]["role"] == "SUPPLEMENT"
    for wrong in [
        path.replace("724382", "724383"),
        path.replace("d1cy02168k", "d1cy12345a"),
    ]:
        assert (
            supplements.discover_attachments(
                html(doi, f'<a href="{wrong}">Supplementary information (PDF)</a>'),
                page,
                doi=doi,
            )["items"]
            == []
        )


def test_science_explicit_doi_supplement_path_works_with_dc_identifier_metadata():
    doi = "10.1126/sciadv.aeb1911"
    link = f"/doi/suppl/{doi}/suppl_file/sciadv.aeb1911_sm.pdf"
    result = supplements.discover_attachments(
        html(doi, f'<a href="{link}">Download, PDF (2.97 MB)</a>', key="dc.Identifier"),
        "https://www.science.org/doi/" + doi,
        doi=doi,
    )
    assert result["items"][0]["role"] == "SUPPLEMENT"
    wrong = supplements.discover_attachments(
        html(
            doi,
            f'<a href="{link.replace("aeb1911/suppl", "wrong/suppl")}">Download, PDF</a>',
            key="dc.Identifier",
        ),
        "https://www.science.org/doi/" + doi,
        doi=doi,
    )
    assert wrong["items"] == []


def test_nature_existing_si_and_source_data_roles_remain_distinct():
    doi = "10.1038/s41467-019-11903-5"
    prefix = "https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41467-019-11903-5/MediaObjects/41467_2019_11903_"
    body = f'<a href="{prefix}MOESM1_ESM.pdf">Supplementary Information</a><a href="{prefix}MOESM2_ESM.xlsx">Source data</a>'
    result = supplements.discover_attachments(
        html(doi, body), "https://www.nature.com/articles/s41467-019-11903-5", doi=doi
    )
    assert [x["role"] for x in result["items"]] == ["SUPPLEMENT", "SOURCE_DATA"]


def test_official_streaming_transport_blocks_uncovered_redirect_before_http(
    monkeypatch, tmp_path
):
    def forbidden(*args, **kwargs):
        pytest.fail("off-publisher redirect must be rejected before HTTP")

    monkeypatch.setattr(httpx.Client, "stream", forbidden)

    def retrieve(url, *, client, **kwargs):
        return client.stream("GET", "https://untrusted.example/foreign.pdf")

    monkeypatch.setattr(supplements, "retrieve_to_temp", retrieve)
    with pytest.raises(ValueError, match="attachment_redirect_host_not_covered"):
        supplements._retrieve_official_file(
            "https://www.nature.com/si.pdf",
            source_page="https://www.nature.com/article",
            output_dir=tmp_path,
        )


def test_malformed_and_linked_attachment_receipts_do_not_break_safe_reuse(
    tmp_path, monkeypatch
):
    directory = tmp_path / "SI"
    records = directory / "json"
    records.mkdir(parents=True)
    (records / "broken.pdf.attachment.json").write_text("[]")
    (records / "bad-parent.pdf.attachment.json").write_text(
        json.dumps({"schema": supplements._SCHEMA, "parent": []})
    )
    candidate = directory / "linked.pdf"
    candidate.write_bytes(b"pdf fixture")
    receipt = records / "linked.pdf.attachment.json"
    receipt.write_text(json.dumps({"schema": supplements._SCHEMA}))
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == candidate or original(p))
    main = SimpleNamespace(
        pdf_sha256="main", article_id="article", sidecar_sha256="sidecar"
    )
    assert (
        supplements._known_attachment(
            main,
            directory,
            {"url": "https://www.nature.com/si.pdf", "role": "SUPPLEMENT"},
        )
        is None
    )


def test_official_pmc_manifest_checksum_is_checked_before_attachment_registration(
    tmp_path, monkeypatch
):
    main = tmp_path / "article.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with main.open("wb") as handle:
        writer.write(handle)
    register_local_pdf(main, output_dir=tmp_path, doi="10.1000/parent", title="Parent")
    source_before = validate_parser_input(main).sidecar_path.read_bytes()
    repo_url = "https://pmc-oa-opendata.s3.amazonaws.com/PMC1234567.1/si.pdf"
    from aletheia_nexus.workbench import supplement_repositories

    monkeypatch.setattr(
        supplement_repositories,
        "discover_pmc_attachments",
        lambda *a, **k: {
            "status": "DISCOVERED",
            "page_url": repo_url.replace("si.pdf", "paper.xml"),
            "items": [
                {
                    "url": repo_url,
                    "role": "SUPPLEMENT",
                    "extension": ".pdf",
                    "label": "Explicit supplementary material",
                    "expected_md5": "0" * 32,
                }
            ],
        },
    )

    def fetch(url, *, output_dir, **kwargs):
        path = Path(output_dir) / "temporary.part"
        path.write_bytes(main.read_bytes())
        return SimpleNamespace(
            local_path=path,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            final_url=url,
        )

    result = supplements.acquire_supplements(
        main,
        file_fetch=fetch,
        page_fetch=lambda *a, **k: pytest.fail(
            "manifest already supplied a DOI-bound file"
        ),
    )
    assert result["status"] == "FAILED"
    assert result["items"][0]["error"] == "official_attachment_checksum_mismatch"
    assert validate_parser_input(main).sidecar_path.read_bytes() == source_before
    assert not list((tmp_path / "SI").glob("*__SI-*.pdf"))
