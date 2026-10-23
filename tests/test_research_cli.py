import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.cli import entrypoint
from aletheia_nexus.library import scan_library

FIXTURES = Path(__file__).resolve().parents[1] / "benchmarks" / "v07_fixtures"


@pytest.mark.parametrize("command", ["parse", "parse-batch"])
def test_single_and_batch_forward_the_same_parser_controls(command, monkeypatch):
    from aletheia_nexus import cli, parsing_cli, research_cli

    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        raise ValueError("captured before reading a file")

    monkeypatch.setattr(cli, "parse_document", capture)
    monkeypatch.setattr(research_cli, "parse_batch", capture)
    monkeypatch.setattr(
        parsing_cli,
        "TesseractOcrBackend",
        lambda config: SimpleNamespace(config=config),
    )
    assert (
        entrypoint(
            [
                command,
                "unused",
                "--ocr",
                "--ocr-languages",
                "eng+chi_sim",
                "--ocr-tessdata-dir",
                "models-primary",
                "--ocr-alternative-tessdata-dir",
                "models-second",
                "--image-ocr",
                "rapidocr",
                "--ocr-dpi",
                "400",
                "--ocr-max-raster-pixels",
                "12345",
                "--no-merge-paragraph-lines",
                "--max-pages",
                "7",
            ]
        )
        == 2
    )
    assert seen["config"].max_pages == 7
    assert not seen["config"].merge_paragraph_lines
    configs = [b.config for b in seen["backend"].ocr_backends]
    assert [c.tessdata_dir for c in configs] == ["models-primary", "models-second"]
    assert all(
        c.languages == "eng+chi_sim"
        and c.dpi == 400
        and c.max_raster_pixels == 12345
        and c.image_ocr == "rapidocr"
        for c in configs
    )


def test_cli_local_research_loop_and_idempotent_export(tmp_path, capsys, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("Local research commands must not open a network socket")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    root = tmp_path / "corpus"
    assert (
        entrypoint(
            [
                "import",
                str(FIXTURES / "native_article.pdf"),
                "--title",
                "Local research",
                "--output-dir",
                str(root),
            ]
        )
        == 0
    )
    assert entrypoint(["parse-batch", str(root)]) == 0
    assert scan_library(root)["items"][0]["identity_basis"] == "local_declared"
    results = tmp_path / "results.json"
    assert (
        entrypoint(["search", str(root), "source-linked", "--output", str(results)])
        == 0
    )
    snapshot = json.loads(results.read_text("utf-8"))
    assert snapshot["hits"][0]["number"] == 1
    hit = snapshot["hits"][0]
    assert hit["reading_role"] == "primary"
    assert set(hit["block_ids"]) <= {
        bid for group in hit["review_locations"] for bid in group["block_ids"]
    }
    assert (
        entrypoint(
            [
                "export",
                str(root),
                "--results",
                str(results),
                "--select",
                "1",
                "--preview",
            ]
        )
        == 0
    )
    output = tmp_path / "selected.md"
    command = [
        "export",
        str(root),
        "--results",
        str(results),
        "--select",
        "1",
        "--context-page",
        "1=1",
        "--output",
        str(output),
    ]
    assert entrypoint(command) == 0
    timestamp = output.stat().st_mtime_ns
    assert entrypoint(command) == 0
    assert output.stat().st_mtime_ns == timestamp
    assert entrypoint(["open-source", str(root), str(results), "1"]) == 0
    assert "PDF pages (1-based)" in capsys.readouterr().out
    assert (
        entrypoint(
            [
                "export",
                str(root),
                "--results",
                str(results),
                "--select",
                "99",
                "--preview",
            ]
        )
        == 7
    )


def test_cli_reports_unreadable_local_pdf(tmp_path, capsys):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert (
        entrypoint(
            [
                "import",
                str(broken),
                "--title",
                "Broken",
                "--output-dir",
                str(tmp_path / "corpus"),
            ]
        )
        == 2
    )
    assert "unreadable" in capsys.readouterr().err
