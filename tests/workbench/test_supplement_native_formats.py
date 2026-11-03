"""Actual format corrections preserve source bytes and never execute attachments."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import supplements
from aletheia_nexus.workbench.supplement_formats import resolve_extension


def archive(member):
    out = io.BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(member, "<fixture/>")
    return out.getvalue()


@pytest.mark.parametrize(
    "declared,body,expected",
    [
        (".jpg", b"\x89PNG\r\n\x1a\nfixture", ".png"),
        (".doc", archive("word/document.xml"), ".docx"),
        (".doc", b"{\\rtf1 fixture}", ".rtf"),
        (".xlsx", archive("xl/workbook.xml"), ".xlsx"),
        (".jpeg", b"\xff\xd8\xfffixture", ".jpeg"),
        (".tif", b"II*\x00fixture", ".tif"),
        (".mpg", b"\x00\x00\x01\xbafixture", ".mpg"),
        (".mpeg", b"\x00\x00\x01\xb3fixture", ".mpeg"),
        (".rar", b"Rar!\x1a\x07\x00fixture", ".rar"),
        (".rar", b"Rar!\x1a\x07\x01\x00fixture", ".rar"),
        (".py", b'raise RuntimeError("must never execute")\n', ".py"),
    ],
)
def test_declared_and_actual_formats_are_resolved_without_modifying_bytes(
    tmp_path, declared, body, expected
):
    p = tmp_path / "download.part"
    p.write_bytes(body)
    assert resolve_extension(p, declared, "application/octet-stream") == expected
    report = supplements._validate_attachment(p, expected)
    assert report["parseable"] is False
    assert p.read_bytes() == body


@pytest.mark.parametrize(
    "suffix,body",
    [
        (".rar", b"not rar"),
        (".mpg", b"not video"),
        (".py", b"bad\x00text"),
        (".docx", archive("unrelated.xml")),
        (".xlsx", b"<!doctype html><html>Login</html>"),
    ],
)
def test_format_expansion_does_not_accept_invalid_archives_login_or_binary_scripts(
    tmp_path, suffix, body
):
    p = tmp_path / "download.part"
    p.write_bytes(body)
    with pytest.raises((ValueError, OSError)):
        supplements._validate_attachment(
            p, resolve_extension(p, suffix, "application/octet-stream")
        )


def test_corrected_format_receipt_keeps_declared_type_parent_and_original_bytes(
    tmp_path,
):
    main = tmp_path / "main.pdf"
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.write(main)
    register_local_pdf(
        main, output_dir=tmp_path, title="Main fixture", doi="10.1000/main"
    )
    gated = validate_parser_input(main)
    before = gated.sidecar_path.read_bytes()
    data = b"\x89PNG\r\n\x1a\nfixture"
    calls = []

    def fetch(url, output_dir, **kwargs):
        calls.append(url)
        p = output_dir / "file.part"
        p.write_bytes(data)
        return SimpleNamespace(local_path=p, sha256=sha256_file(p), final_url=url)

    options = dict(
        page_urls=["https://www.nature.com/articles/main"],
        page_fetch=lambda *a, **k: SimpleNamespace(
            text='<meta name="citation_doi" content="10.1000/main"><a href="/si.jpg">Supplementary material</a>',
            final_url="https://www.nature.com/articles/main",
            body_truncated=False,
        ),
        file_fetch=fetch,
    )
    first = supplements.acquire_supplements(main, **options)
    assert first["status"] == "COMPLETED"
    item = first["items"][0]
    record = json.loads(Path(item["source_record"]).read_text("utf-8"))
    assert (
        Path(item["path"]).suffix == ".png" and Path(item["path"]).read_bytes() == data
    )
    assert record["validation"]["declared_extension"] == ".jpg"
    assert record["validation"]["detected_extension"] == ".png"
    assert (
        record["validation"]["extension_corrected"]
        and not record["validation"]["executed"]
    )
    second = supplements.acquire_supplements(main, **options)
    assert second["items"][0]["status"] == "REUSED" and len(calls) == 1
    assert before == gated.sidecar_path.read_bytes()


def test_generic_native_fallback_does_not_treat_review_help_or_rss_as_files():
    page = "https://iopscience.iop.org/article/10.1000/main"
    html = """<meta name="citation_doi" content="10.1000/main"><h2>Peer review</h2>
    <a href="/about/peer-review">Peer review models</a><a href="/journal/rss/123">RSS</a>
    <a href="/review.pdf">Peer review file</a>
    <a href="/core/services/authors/publishing-supplementary-material">Publishing supplementary material</a>"""
    result = supplements.discover_attachments(html, page, doi="10.1000/main")
    assert [x["url"] for x in result["items"]] == [
        "https://iopscience.iop.org/review.pdf"
    ]


def test_explicit_download_hint_preserves_an_opaque_review_file_endpoint():
    result = supplements.discover_attachments(
        '<meta name="citation_doi" content="10.1000/main"><a href="/opaque/123" download>Peer review file</a><a href="/journal/rss/123" type="application/rss+xml">Peer review</a>',
        "https://iopscience.iop.org/article/10.1000/main",
        doi="10.1000/main",
    )
    assert [x["url"] for x in result["items"]] == [
        "https://iopscience.iop.org/opaque/123"
    ]
