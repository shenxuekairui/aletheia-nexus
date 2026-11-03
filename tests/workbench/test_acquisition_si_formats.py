"""Exercise the real main acquisition engine and SI pipeline over fixture HTTP."""

import io
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.workbench.acquisition import AcquisitionService
from aletheia_nexus.workbench.library import LibraryService

DOI = "10.1000/si-integration"
TITLE = "Synthetic article about catalytic material stability"
PAGE = "https://www.nature.com/articles/material-stability"
MAIN = PAGE + ".pdf"


def pdf(title):
    writer, output = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=600, height=800)
    writer.add_metadata({"/Title": title})
    writer.write(output)
    return output.getvalue()


def spreadsheet():
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return output.getvalue()


@pytest.mark.parametrize(
    "case", ["complete", "one_failed", "limited", "main_mismatch", "disabled"]
)
def test_main_engine_through_multi_format_si_and_checkpoint_resume(
    tmp_path, monkeypatch, case
):
    calls = []
    original_init = httpx.Client.__init__
    article = f'<meta name="citation_doi" content="{DOI}"><meta name="citation_title" content="{TITLE}"><a href="{MAIN}">Article PDF</a><section aria-label="Supplementary material"><a href="/files/si.pdf">S1</a><a href="/download?file=table">S2</a><a href="/files/data.csv">S3</a></section>'
    work = {
        "DOI": DOI,
        "title": [TITLE],
        "type": "journal-article",
        "publisher": "Fixture publisher",
        "link": [
            {
                "URL": MAIN,
                "content-type": "application/pdf",
                "content-version": "vor",
                "intended-application": "text-mining",
            }
        ],
        "resource": {"primary": {"URL": PAGE}},
    }

    def handler(request):
        url = str(request.url)
        calls.append(url)
        if request.url.host == "api.crossref.org":
            return httpx.Response(
                200, json={"status": "ok", "message-type": "work", "message": work}
            )
        if url == MAIN:
            return httpx.Response(
                200,
                content=pdf(
                    "An unrelated document" if case == "main_mismatch" else TITLE
                ),
                headers={"content-type": "application/pdf"},
            )
        if url == PAGE or request.url.host == "doi.org":
            return httpx.Response(
                200, text=article, headers={"content-type": "text/html"}
            )
        if request.url.path == "/files/si.pdf":
            return httpx.Response(
                200,
                content=pdf("Supplementary Information fixture"),
                headers={"content-type": "application/pdf"},
            )
        if request.url.path == "/download":
            return httpx.Response(
                200,
                content=b"<html>Login</html>"
                if case == "one_failed"
                else spreadsheet(),
                headers={"content-type": "application/octet-stream"},
            )
        if request.url.path == "/files/data.csv":
            return httpx.Response(
                200,
                content=b"condition,value\na,1\n",
                headers={"content-type": "text/csv"},
            )
        return httpx.Response(
            404, json={"error": "fixture has no alternate repository"}
        )

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", init)
    for name in ("OPENALEX_API_KEY", "UNPAYWALL_EMAIL", "ELSEVIER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    library = LibraryService(tmp_path / "library")
    service = AcquisitionService(library.root, library=library)
    options = {
        "public_only": True,
        "include_si": case != "disabled",
        "timeout": 2,
        "max_si_files": 2 if case == "limited" else 20,
        "metadata_max_attempts": 1,
        "discovery_max_attempts": 1,
        "max_attempts_per_route": 1,
        "max_attempts_per_file": 1,
    }
    report = service.run([{"doi": DOI, "title": TITLE}], options)
    row = report["items"][0]
    if case == "main_mismatch":
        assert row["status"] != "VERIFIED" and report["success"] == 0
        assert not any("/files/" in url or "/download?" in url for url in calls)
        return
    assert row["status"] == "VERIFIED" and row["identity_verified"], (row, calls)
    main = validate_parser_input(row["pdf"])
    assert main.identity_basis == "acquisition_verified"
    before = main.pdf_sha256, main.sidecar_path.read_bytes()
    if case == "disabled":
        assert not any("/files/" in url or "/download?" in url for url in calls)
        assert report["status"] == "COMPLETED"
        return
    assert row["si_status"] == (
        "PARTIAL" if case in {"one_failed", "limited"} else "COMPLETED"
    )
    assert report["status"] == row["si_status"]
    saved = [i for i in row["supplements"]["items"] if i["status"] == "SAVED"]
    assert len(saved) == (3 if case == "complete" else 2)
    assert {Path(i["path"]).suffix for i in saved} == (
        {".pdf", ".csv"}
        if case == "one_failed"
        else {".pdf", ".xlsx"}
        if case == "limited"
        else {".pdf", ".xlsx", ".csv"}
    )
    for item in saved:
        receipt = json.loads(Path(item["source_record"]).read_text("utf-8"))
        assert receipt["parent"]["pdf_sha256"] == main.pdf_sha256
    main_calls = calls.count(MAIN)
    result = service.run(
        [{"doi": DOI, "title": TITLE}], options, checkpoint_path=report["checkpoint"]
    )
    assert result["items"][0]["resumed"]
    assert calls.count(MAIN) == main_calls
    assert sum(
        i["status"] == "REUSED" for i in result["items"][0]["supplements"]["items"]
    ) == len(saved)
    assert (sha256_file(main.pdf_path), main.sidecar_path.read_bytes()) == before
    assert len(library.scan()["items"]) == 1
