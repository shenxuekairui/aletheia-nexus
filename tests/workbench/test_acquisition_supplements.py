import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench.supplements import (
    acquire_supplements,
    discover_attachments,
)

DOI = "10.1000/main"
URL = "https://www.nature.com/articles/test"
HTML = f'''<html><head><meta name="citation_doi" content="{DOI}"><meta name="citation_title" content="Research main"></head><body>
<a href="/files/supplement.pdf">Supplementary Information</a>
<a href="https://static-content.springer-cdn.com/files/data.csv">Supplementary Data 2</a>
<a href="/files/review.pdf">Peer Review File</a>
<a href="/files/report.pdf">Reporting Summary</a>
<a href="/files/source.csv">Source Data</a>
<a href="https://evil.example/data.pdf">Supplementary Information</a>
<a href="/files/main.pdf">Download article PDF</a>
</body></html>'''


def pdf_bytes(tmp_path, name, width=100):
    pdf = tmp_path / name
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    with pdf.open("wb") as handle:
        writer.write(handle)
    return pdf.read_bytes()


def test_discovery_requires_sole_scholarly_doi_and_separates_roles():
    found = discover_attachments(HTML, URL, doi=DOI)
    assert [a["role"] for a in found["items"]] == [
        "SUPPLEMENT",
        "SUPPLEMENT",
        "PEER_REVIEW",
        "REPORTING_SUMMARY",
        "SOURCE_DATA",
    ]
    assert len(found["excluded"]) == 1
    assert (
        discover_attachments(HTML.replace(DOI, "10.1000/other"), URL, doi=DOI)["status"]
        == "IDENTITY_NOT_CONFIRMED"
    )
    dual = HTML.replace(
        "</head>", '<meta name="citation_doi" content="10.1000/other"></head>'
    )
    assert discover_attachments(dual, URL, doi=DOI)["items"] == []
    blocked = HTML.replace("<body>", "<body>Verify you are human CAPTCHA")
    assert (
        discover_attachments(blocked, URL, doi=DOI)["status"] == "INTERACTION_REQUIRED"
    )


def test_si_shared_folder_independent_provenance_dedup_and_partial_failure(tmp_path):
    main = tmp_path / "分类" / "2026-中文主文.pdf"
    main.parent.mkdir()
    main.write_bytes(pdf_bytes(tmp_path, "main-source.pdf"))
    register_local_pdf(main, output_dir=main.parent, title="Research main", doi=DOI)
    source = validate_parser_input(main)
    original = source.sidecar_path.read_bytes()
    si_pdf = pdf_bytes(tmp_path, "si-source.pdf", 120)
    calls, registrations = [], []

    def page_fetch(url, **kwargs):
        return SimpleNamespace(text=HTML, final_url=URL, body_truncated=False)

    def file_fetch(url, output_dir, **kwargs):
        calls.append(url)
        body = (
            si_pdf
            if url.endswith("supplement.pdf")
            else b"<!doctype html><html>Login required</html>"
            if url.endswith("report.pdf")
            else b"condition,value\na,1\n"
        )
        temporary = Path(output_dir) / f".{len(calls)}.part"
        temporary.write_bytes(body)
        return SimpleNamespace(
            local_path=temporary, sha256=hashlib.sha256(body).hexdigest(), final_url=url
        )

    library = SimpleNamespace(
        register_attachment=lambda *args, **kw: registrations.append((args, kw))
    )
    result = acquire_supplements(
        main, library=library, page_fetch=page_fetch, file_fetch=file_fetch
    )
    assert result["status"] == "PARTIAL"
    assert source.sidecar_path.read_bytes() == original
    saved = [item for item in result["items"] if item["status"] == "SAVED"]
    assert {Path(item["path"]).parent for item in saved} == {main.parent / "SI"}
    assert all(Path(item["path"]).stem.startswith(main.stem + "__") for item in saved)
    supplement = next(item for item in saved if item["path"].endswith(".pdf"))
    validated = validate_parser_input(supplement["path"])
    assert validated.document_role == "SUPPLEMENT"
    assert validated.identity_basis == "local_declared"
    assert validated.parent["pdf_sha256"] == sha256_file(main)
    assert (
        json.loads(Path(supplement["source_record"]).read_text("utf-8"))["parent"][
            "article_id"
        ]
        == source.article_id
    )
    assert len(registrations) == len(saved)
    first_calls = len(calls)
    second = acquire_supplements(
        main, library=library, page_fetch=page_fetch, file_fetch=file_fetch
    )
    assert sum(item["status"] == "REUSED" for item in second["items"]) == len(saved)
    assert len(calls) == first_calls + 2  # Only the two invalid PDF attachments retry.


def test_si_symlink_directory_rejected_before_network(tmp_path):
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf_bytes(tmp_path, "source.pdf"))
    register_local_pdf(main, output_dir=tmp_path, title="Research main", doi=DOI)
    outside = tmp_path / "other"
    outside.mkdir()
    try:
        (tmp_path / "SI").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="unsafe_SI_directory"):
        acquire_supplements(
            main, page_fetch=lambda *a, **k: pytest.fail("network must not run")
        )
