"""Synthetic template coverage, kept distinct from real publisher acceptance."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import supplements
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.supplement_formats import (
    resolve_extension,
    response_filename_suffix,
)
from aletheia_nexus.workbench.supplement_pages import expand_supplement_pages
from aletheia_nexus.workbench.supplement_plos import storage_url_allowed

DOI = "10.1000/coverage"
PAGE = "https://www.nature.com/articles/coverage"


def html(body, doi=DOI):
    return f'<meta name="citation_doi" content="{doi}">{body}'


def discover(body, page=PAGE):
    return supplements.discover_attachments(html(body), page, doi=DOI)


def pdf(width=200):
    writer, output = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=width, height=200)
    writer.write(output)
    return output.getvalue()


def office(suffix):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        member = {
            ".docx": "word/document.xml",
            ".xlsx": "xl/workbook.xml",
            ".pptx": "ppt/presentation.xml",
        }.get(suffix)
        if member:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr(member, "<fixture/>")
        elif suffix in {".odt", ".ods", ".odp"}:
            mime = {".odt": "text", ".ods": "spreadsheet", ".odp": "presentation"}[
                suffix
            ]
            archive.writestr("mimetype", "application/vnd.oasis.opendocument." + mime)
            archive.writestr("content.xml", "<fixture/>")
        else:
            archive.writestr("data.csv", "name,value\na,1\n")
    return output.getvalue()


@pytest.mark.parametrize(
    "page,target",
    [
        (
            "https://www.nature.com/articles/x",
            "https://static-content.springer-cdn.com/x.pdf",
        ),
        (
            "https://link.springer.com/article/x",
            "https://static-content.springer-cdn.com/x.pdf",
        ),
        ("https://pubs.acs.org/doi/x", "/assets/x.pdf"),
        ("https://pubs.rsc.org/en/content/articlehtml/x", "/suppdata/x/si.zip"),
        ("https://onlinelibrary.wiley.com/doi/x", "/assets/x.docx"),
        ("https://www.sciencedirect.com/science/article/x", "/assets/x.xlsx"),
        ("https://www.science.org/doi/x", "/assets/x.pdf"),
        ("https://journals.plos.org/plosone/article", "/assets/x.csv"),
        ("https://www.mdpi.com/article/x", "https://mdpi-res.com/files/x.pdf"),
        ("https://www.pnas.org/doi/x", "/assets/x.pdf"),
        ("https://www.frontiersin.org/articles/x", "/files/x.docx"),
        (
            "https://academic.oup.com/journal/x",
            "https://oup.silverchair-cdn.com/files/x.zip",
        ),
        ("https://www.cambridge.org/core/journals/x", "/core/services/aop/file/x.pdf"),
        ("https://www.tandfonline.com/doi/x", "/assets/x.pdf"),
        ("https://journals.sagepub.com/doi/x", "/assets/x.xlsx"),
        ("https://www.bmj.com/content/x", "/content/x/dc1.pdf"),
        ("https://ieeexplore.ieee.org/document/x", "/files/x.zip"),
        ("https://iopscience.iop.org/article/x", "/files/x.csv"),
        (
            "https://pubs.aip.org/journal/x",
            "https://aip.silverchair-cdn.com/files/x.pdf",
        ),
        ("https://journals.aps.org/prl/x", "/files/x.pdf"),
        ("https://elifesciences.org/articles/x", "/files/x.xlsx"),
        ("https://karger.com/journal/x", "/files/x.pdf"),
        ("https://independent-journal.example/article/x", "/assets/x.pdf"),
        (
            "https://royalsocietypublishing.org/doi/x",
            "https://royalsociety.silverchair-cdn.com/files/x.pdf",
        ),
        (
            "https://journals.biologists.com/journal/x",
            "https://biologists.silverchair-cdn.com/files/x.xlsx",
        ),
        ("https://peerj.com/articles/x", "/files/x.csv"),
        ("https://bg.copernicus.org/articles/x", "/files/x.zip"),
    ],
)
def test_generic_semantic_section_across_publisher_families(page, target):
    result = discover(
        f'<section aria-label="Supplementary materials"><a href="{target}">Download 1</a></section><a href="/main.pdf">Article</a>',
        page,
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["role"] == "SUPPLEMENT"


def test_headings_repeated_urls_buttons_boundaries_and_hidden_navigation():
    result = discover("""<nav><a href="/nav.pdf">Supplementary material</a></nav>
    <h2>Supporting information</h2><a href="/one.pdf">S1</a>
    <a href="/one.pdf">Again</a><button data-href="/two.zip" aria-label="Supporting information">S2</button>
    <h3>References</h3><a href="/cited.pdf">Reference document</a>
    <script><a href="/hidden.zip">Supplementary material</a></script>
    <section class="supplementary-material"><a href="/three.csv">Additional file 3</a></section>""")
    assert [Path(i["url"]).name for i in result["items"]] == [
        "one.pdf",
        "two.zip",
        "three.csv",
    ]


def test_long_article_does_not_lose_late_si_but_limits_remain_visible():
    body = "".join(f'<a href="/reference/{i}">Citation</a>' for i in range(500))
    assert (
        len(discover(body + '<a href="/si.pdf">Supplementary material</a>')["items"])
        == 1
    )
    result = discover(
        "".join(f'<a href="/si{i}.csv">Supplementary data</a>' for i in range(260))
    )
    assert len(result["items"]) == 256 and result["truncated"]


@pytest.mark.parametrize(
    "field", ["associatedMedia", "hasPart", "supplementaryMaterial"]
)
def test_jsonld_article_binds_structured_attachments_without_using_citations(field):
    article = {
        "@type": "ScholarlyArticle",
        "identifier": {"propertyID": "doi", "value": DOI},
        field: [
            {
                "name": "Supplementary material",
                "contentUrl": "/download?id=si",
                "encodingFormat": "application/pdf",
            }
        ],
        "citation": {"@type": "ScholarlyArticle", "doi": "10.1000/cited"},
    }
    body = (
        '<script type="application/ld+json">'
        + json.dumps({"@graph": [article]})
        + "</script>"
    )
    result = supplements.discover_attachments(body, PAGE, doi=DOI)
    assert len(result["items"]) == 1 and result["items"][0]["extension"] == ".pdf"
    conflict = body + '<meta name="citation_doi" content="10.1000/other">'
    assert (
        supplements.discover_attachments(conflict, PAGE, doi=DOI)["status"]
        == "IDENTITY_NOT_CONFIRMED"
    )
    article[field][0]["name"] = "Main article PDF"
    if field != "supplementaryMaterial":
        assert not supplements.discover_attachments(
            '<script type="application/ld+json">' + json.dumps(article) + "</script>",
            PAGE,
            doi=DOI,
        )["items"]


@pytest.mark.parametrize(
    "query,accepted",
    [
        ("type=supplementary&id=10.1000/coverage.s001", True),
        ("type=supplementary&id=info:doi/10.1000/coverage.s012", True),
        ("type=supplementary&id=10.1000/wrong.s001", False),
        ("type=supplementary&id=10.1000/coverage.g001", False),
        ("type=manuscript&id=10.1000/coverage", False),
        ("type=supplementary&id=10.1000/coverage.s001&id=10.1000/other.s001", False),
    ],
)
def test_plos_extensionless_query_identity(query, accepted):
    result = discover(
        f'<a href="/plosone/article/file?{query}">File S1</a>',
        "https://journals.plos.org/plosone/article",
    )
    assert bool(result["items"]) == accepted


@pytest.mark.parametrize(
    "host", ["science.org", "pnas.org", "tandfonline.com", "journals.sagepub.com"]
)
def test_doi_supplement_routes_cannot_bind_another_article(host):
    page = f"https://{host}/doi/{DOI}"
    for target, accepted in [(DOI, True), ("10.1000/other", False)]:
        result = discover(
            f'<a href="/doi/suppl/{target}/suppl_file/x.pdf">Download</a>', page
        )
        assert bool(result["items"]) == accepted


@pytest.mark.parametrize(
    "suffix,body,mime",
    [
        (".pdf", pdf(), "application/octet-stream"),
        *(
            (s, office(s), "application/octet-stream")
            for s in (".xlsx", ".docx", ".pptx", ".zip", ".odt", ".ods", ".odp")
        ),
        (".rtf", b"{\\rtf1 fixture}", "application/octet-stream"),
        (".csv", b"name,value\na,1\n", "text/csv; charset=utf-8"),
        (
            ".xls",
            bytes.fromhex("d0cf11e0a1b11ae1") + b"fixture",
            "application/vnd.ms-excel",
        ),
        (".png", b"\x89PNG\r\n\x1a\nfixture", "image/png"),
        (".tiff", b"II*\x00fixture", "image/tiff"),
        (".gif", b"GIF89afixture", "image/gif"),
    ],
)
def test_extensionless_file_format_resolution_and_existing_validation(
    tmp_path, suffix, body, mime
):
    path = tmp_path / "download.part"
    path.write_bytes(body)
    assert resolve_extension(path, "", mime) == suffix
    checked = supplements._validate_attachment(path, suffix)
    assert checked["type"] == suffix[1:]


@pytest.mark.parametrize(
    "body,mime",
    [
        (b"<html>Login</html>", "application/pdf"),
        (b"arbitrary binary\x00", "application/octet-stream"),
        (b"not a spreadsheet", "application/vnd.ms-excel"),
    ],
)
def test_extensionless_responses_never_turn_login_or_unknown_bytes_into_si(
    tmp_path, body, mime
):
    path = tmp_path / "download.part"
    path.write_bytes(body)
    with pytest.raises(ValueError):
        supplements._validate_attachment(path, resolve_extension(path, "", mime))


@pytest.mark.parametrize(
    "case",
    ["success", "wrong_doi", "challenge", "outside", "nested", "truncated", "failed"],
)
def test_one_level_supplement_landing_page_gate(case):
    discovery = discover('<a href="/supplementary-material">Supplementary material</a>')
    # Generic /supplementary-material is an explicit landing route.
    assert discovery["items"][0]["kind"] == "page"
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if case == "failed":
            raise OSError("fixture network")
        body = (
            '<a href="/si.pdf">Supplementary material</a>'
            if case != "nested"
            else '<a href="/s2">Supplementary material</a>'
        )
        if case == "challenge":
            body += " Verify you are human"
        return SimpleNamespace(
            text=html(body, "10.1000/other" if case == "wrong_doi" else DOI),
            final_url="https://untrusted.example/page" if case == "outside" else url,
            body_truncated=case == "truncated",
        )

    result = expand_supplement_pages(
        discovery, fetch=fetch, doi=DOI, title=None, timeout=2
    )
    assert len(calls) == 1
    assert bool(result["items"]) == (case == "success")
    assert bool(result["errors"]) == (case != "success")
    if case == "success":
        assert result["items"][0]["evidence"]["article_page"] == PAGE


@pytest.mark.parametrize("failure,max_files", [(False, 20), (True, 20), (False, 2)])
def test_multi_file_multi_format_save_reuse_and_main_immutability(
    tmp_path, failure, max_files
):
    library = LibraryService(tmp_path / "library")
    main = library.root / "main.pdf"
    main.write_bytes(pdf(200))
    register_local_pdf(main, output_dir=main.parent, title="Fixture main", doi=DOI)
    library.scan()
    sidecar = validate_parser_input(main).sidecar_path
    before = (main.read_bytes(), sidecar.read_bytes())
    bodies = {
        "pdf": (pdf(300), "application/pdf"),
        "xlsx": (office(".xlsx"), "application/octet-stream"),
        "docx": (office(".docx"), "application/octet-stream"),
        "zip": (office(".zip"), "application/zip"),
        "csv": (b"a,b\n1,2\n", "text/csv"),
    }
    article = html(
        "".join(
            f'<a href="/download?file={key}">Supplementary material {key}</a>'
            for key in bodies
        )
    )
    calls = []

    def fetch(url, output_dir, **kwargs):
        key = url.rsplit("=", 1)[1]
        calls.append(key)
        body, mime = bodies[key]
        if failure and key == "docx":
            body = b"<html>Login</html>"
        path = output_dir / "download.part"
        path.write_bytes(body)
        return SimpleNamespace(
            local_path=path, sha256=sha256_file(path), final_url=url, content_type=mime
        )

    kwargs = dict(
        library=library,
        page_urls=[PAGE],
        max_files=max_files,
        page_fetch=lambda *a, **k: SimpleNamespace(
            text=article, final_url=PAGE, body_truncated=False
        ),
        file_fetch=fetch,
    )
    result = supplements.acquire_supplements(main, **kwargs)
    assert result["status"] == ("PARTIAL" if failure or max_files < 5 else "COMPLETED")
    saved = [i for i in result["items"] if i["status"] == "SAVED"]
    assert len(saved) == min(max_files, 5) - int(failure)
    second = supplements.acquire_supplements(main, **kwargs)
    assert sum(i["status"] == "REUSED" for i in second["items"]) == len(saved)
    assert len(calls) == min(max_files, 5) + int(failure)
    assert (main.read_bytes(), sidecar.read_bytes()) == before
    rows = library.scan()["items"]
    assert len(rows) == 1 and len(rows[0]["attachments"]) == len(saved)
    for item in saved:
        receipt = json.loads(Path(item["source_record"]).read_text("utf-8"))
        assert receipt["sha256"] == sha256_file(Path(item["path"]))
        assert receipt["parent"]["doi"] == DOI
    assert not list((main.parent / "SI").glob("*.part"))


def test_known_pdf_source_candidates_recover_article_routes():
    for source, doi, expected in [
        (
            "https://link.springer.com/content/pdf/10.1000/coverage.pdf",
            DOI,
            "https://link.springer.com/article/" + DOI,
        ),
        (
            "https://pubs.rsc.org/en/content/articlepdf/2024/cc/d4cc01176g",
            "10.1039/d4cc01176g",
            "https://pubs.rsc.org/en/content/articlehtml/2024/cc/d4cc01176g",
        ),
    ]:
        assert (
            supplements._source_page_candidates({"candidate": {"url": source}}, doi)[0]
            == expected
        )


@pytest.mark.parametrize(
    "change,allowed",
    [
        ("", True),
        ("wrong_parent", False),
        ("wrong_file", False),
        ("wrong_host", False),
        ("other_cloud", False),
        ("http", False),
        ("traversal", False),
        ("unknown_format", False),
    ],
)
def test_plos_cloud_redirect_is_scoped_to_exact_article_and_supplement(change, allowed):
    source = "https://journals.plos.org/plosone/article/file?type=supplementary&id=10.1371/journal.pone.0039704.s001"
    target = (
        "https://corpus-prod."
        + "a" * 32
        + ".r2.cloudflarestorage.com/10.1371/journal.pone.0039704/1/pone.0039704.s001.xls?X-Amz-Signature=fixture"
    )
    if change == "wrong_parent":
        target = target.replace("/journal.pone.0039704/", "/journal.pone.9999999/")
    if change == "wrong_file":
        target = target.replace("s001.xls", "s002.xls")
    if change == "wrong_host":
        target = target.replace(".com/", ".com.attacker.example/")
    if change == "other_cloud":
        target = target.replace("corpus-prod.", "other.")
    if change == "http":
        target = target.replace("https:", "http:")
    if change == "traversal":
        target = target.replace("/1/", "/1/../")
    if change == "unknown_format":
        target = target.replace(".xls?", ".exe?")
    assert storage_url_allowed(source, target) == allowed
    assert (
        supplements._attachment_url_allowed(
            "https://journals.plos.org/plosone/article", target, {"url": source}
        )
        == allowed
    )


def test_unhandled_format_remains_visible_and_landing_page_budget_is_bounded():
    discovery = discover(
        '<a href="/code.exe">Supplementary material</a>'
        + "".join(f'<a href="/s{i}">Supplementary material</a>' for i in range(1, 5))
    )
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(
            text=html('<a href="/file.csv">Additional file</a>'),
            final_url=url,
            body_truncated=False,
        )

    result = expand_supplement_pages(
        discovery, fetch=fetch, doi=DOI, title=None, timeout=2
    )
    assert len(calls) == 2 and result["truncated"]
    assert any(e["status"] == "UNHANDLED_ATTACHMENT" for e in result["errors"])
    assert len(result["items"]) == 1


def test_client_challenge_is_not_reported_as_no_supplements():
    assert (
        discover("<title>Client Challenge</title>")["status"] == "INTERACTION_REQUIRED"
    )


def test_landing_page_redirect_is_blocked_before_untrusted_http_request(monkeypatch):
    discovery = discover('<a href="/s1">Supplementary material</a>')

    def forbidden(*args, **kwargs):
        pytest.fail("untrusted host must not be requested")

    monkeypatch.setattr(httpx.Client, "stream", forbidden)
    from aletheia_nexus.workbench import supplement_pages

    def fake_fetch(url, *, client, **kwargs):
        return client.stream("GET", "https://untrusted.example/data")

    monkeypatch.setattr(supplement_pages, "retrieve_page", fake_fetch)
    result = expand_supplement_pages(
        discovery, fetch=fake_fetch, doi=DOI, title=None, timeout=2
    )
    assert result["errors"][0]["status"] == "SUPPLEMENT_PAGE_FAILED"


@pytest.mark.parametrize(
    "case", ["resolver", "no_redirect", "wrong_doi", "explicit_untrusted"]
)
def test_unknown_publisher_uses_doi_authority_and_same_host_only(tmp_path, case):
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf())
    register_local_pdf(main, output_dir=tmp_path, title="Local main", doi=DOI)
    resolver = "https://doi.org/" + DOI
    article = "https://independent-journal.example/article/coverage"

    def page_fetch(url, **kwargs):
        return SimpleNamespace(
            text=html(
                '<a href="/file.csv">Supplementary material</a>',
                "10.1000/other" if case == "wrong_doi" else DOI,
            ),
            requested_url=resolver,
            final_url=article,
            body_truncated=False,
            redirects=()
            if case == "no_redirect"
            else (SimpleNamespace(from_url=resolver, to_url=article),),
        )

    calls = []

    def file_fetch(url, output_dir, **kwargs):
        calls.append(url)
        path = output_dir / "file.part"
        path.write_bytes(b"key,value\na,1\n")
        return SimpleNamespace(local_path=path, sha256=sha256_file(path), final_url=url)

    result = supplements.acquire_supplements(
        main,
        page_urls=[article if case == "explicit_untrusted" else resolver],
        page_fetch=page_fetch,
        file_fetch=file_fetch,
    )
    assert result["status"] == ("COMPLETED" if case == "resolver" else "FAILED")
    assert len(calls) == (1 if case == "resolver" else 0)


@pytest.mark.parametrize(
    "header,suffix",
    [
        (None, ""),
        ('attachment; filename="si.xlsx"', ".xlsx"),
        ("attachment; filename*=UTF-8''%E6%95%B0%E6%8D%AE.doc", ".doc"),
        ('attachment; filename="../../foreign.pdf"', ".pdf"),
    ],
)
def test_response_filename_is_only_a_type_hint(header, suffix):
    assert response_filename_suffix(header) == suffix


def test_extensionless_legacy_file_uses_header_without_saving_remote_filename(
    tmp_path, monkeypatch
):
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf())
    register_local_pdf(main, output_dir=tmp_path, doi=DOI, title="Main fixture")
    original_init = httpx.Client.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=bytes.fromhex("d0cf11e0a1b11ae1") + b"fixture",
                headers={
                    "content-type": "application/octet-stream",
                    "content-disposition": "attachment; filename*=UTF-8''%E6%95%B0%E6%8D%AE.doc",
                },
            )
        )
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", init)
    result = supplements.acquire_supplements(
        main,
        page_urls=[PAGE],
        page_fetch=lambda *a, **k: SimpleNamespace(
            text=html('<a href="/download">Supplementary material</a>'),
            final_url=PAGE,
            body_truncated=False,
        ),
    )
    assert result["status"] == "COMPLETED"
    item = result["items"][0]
    assert Path(item["path"]).name == "main__SI-01.doc"
    record = json.loads(Path(item["source_record"]).read_text("utf-8"))
    assert record["transport_diagnostics"][-1]["filename_extension"] == ".doc"
    assert "数据" not in json.dumps(record, ensure_ascii=False)
