"""Installed CLI contract and first-run public-only path."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus import cli
from aletheia_nexus.acquire.fulltext import FullTextAcquisitionStatus


@pytest.fixture
def acquired_article(tmp_path, monkeypatch):
    from aletheia_nexus.acquire.access import service
    from aletheia_nexus.acquire.access.browser import BrowserSession

    def forbid_network(*args, **kwargs):
        raise AssertionError("Local import/resume must not acquire from network")

    monkeypatch.setattr(service, "acquire_full_text", forbid_network)
    monkeypatch.setattr(BrowserSession, "_ensure_started", forbid_network)
    source = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/v07_fixtures/native_article.pdf"
    )
    original = source.read_bytes()
    doi = "10.5555/an.v07.native"
    output = tmp_path / "articles"
    command = [
        "acquire",
        doi,
        "--local-pdf",
        f"{doi}={source}",
        "--output-dir",
        str(output),
        "--non-interactive",
    ]
    assert cli.entrypoint(command) == 0
    report = json.loads((output / "batch-report.json").read_text(encoding="utf-8"))
    pdf = next(output.glob("*.pdf"))
    assert report["items"][0]["status"] == "VERIFIED"
    assert source.read_bytes() == original == pdf.read_bytes()
    assert cli.entrypoint(command) == 0
    report = json.loads((output / "batch-report.json").read_text(encoding="utf-8"))
    assert report["items"][0]["resumed"]
    assert cli.entrypoint(["parse", str(pdf), "--doi", doi, "--fail-on-partial"]) == 0
    return pdf, pdf.with_suffix(".acquisition.json"), pdf.with_suffix(".parsed.json")


def test_cli_acquire_resume_parse_search_and_export(acquired_article, capsys):
    pdf, sidecar, parsed = acquired_article
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in acquired_article
    }
    assert cli.entrypoint(["search", str(parsed), "Methods", "--verify-sources"]) == 0
    assert "page 1" in capsys.readouterr().out
    for format_name, suffix in (
        ("markdown", ".ai.md"),
        ("jsonl", ".ai.jsonl"),
        ("chunks", ".chunks.json"),
    ):
        output = parsed.with_suffix(suffix)
        args = ["export", str(parsed), "--format", format_name, "--output", str(output)]
        assert cli.entrypoint(args) == 0
        exported = output.read_bytes()
        assert exported
        assert cli.entrypoint(args) == 7
        assert cli.entrypoint([*args, "--overwrite"]) == 0
        assert output.read_bytes() == exported
    assert before == {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in acquired_article
    }


@pytest.mark.parametrize("target_index", [0, 1, 2])
def test_cli_export_cannot_overwrite_input_or_known_sources(
    acquired_article, target_index
):
    originals = {path: path.read_bytes() for path in acquired_article}
    assert (
        cli.entrypoint(
            [
                "export",
                str(acquired_article[2]),
                "--format",
                "markdown",
                "--output",
                str(acquired_article[target_index]),
                "--overwrite",
            ]
        )
        == 7
    )
    assert originals == {path: path.read_bytes() for path in acquired_article}


def test_entrypoint_help_and_doctor(capsys):
    assert cli.entrypoint(["--help"]) == 0
    assert "aletheia-nexus acquire" in capsys.readouterr().out
    assert cli.entrypoint(["doctor"]) == 0
    assert "Python:" in capsys.readouterr().out
    assert cli.entrypoint(["doctor", "--help"]) == 0


def test_doctor_explains_optional_browser_setup(monkeypatch, capsys):
    monkeypatch.setattr(cli.util, "find_spec", lambda name: None)
    assert cli.entrypoint(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "Browser extra: not installed" in output
    assert "python -m playwright install chromium" in output


def test_entrypoint_dispatches_acquire(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 7)
    assert cli.entrypoint(["acquire", "10.1000/example"]) == 7
    assert seen == [["10.1000/example"]]


def test_installed_browser_provisioner_dispatch_without_source_checkout(monkeypatch):
    from aletheia_nexus.acquire.access.browser_engine import installer

    calls = []
    monkeypatch.setattr(installer, "main", lambda: calls.append(True) or 0)
    assert cli.entrypoint(["browser-install"]) == 0
    assert calls == [True]


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--cnki"],
        ["--no-cnki"],
        ["--no-cnki-context-request"],
        ["--cnki-context-request"],
    ],
)
def test_installed_cli_title_only_request_honors_noninteractive_and_exit_status(
    monkeypatch, tmp_path, flags
):
    from aletheia_nexus.acquire.access import (
        BatchAcquisitionItem,
        BatchAcquisitionResult,
        BatchItemStatus,
        PaperRequest,
    )

    def acquire(values, **kwargs):
        assert values == [PaperRequest(title="明确的中文题名", authors=("张三",))]
        config = kwargs["browser_config"]
        assert config.interactive is False and config.wait_for_interaction is False
        assert config.interaction_callback is None
        assert config.cnki_enabled == ("--no-cnki" not in flags)
        assert config.cnki_context_request == ("--cnki-context-request" in flags)
        assert kwargs["stop_on_interaction"] is False
        return BatchAcquisitionResult(
            items=(
                BatchAcquisitionItem(
                    input_value=values[0],
                    doi=None,
                    status=BatchItemStatus.EXHAUSTED,
                    request_key=values[0].key,
                ),
            ),
            checkpoint_path=None,
            halted_for_interaction=False,
            elapsed_seconds=0,
        )

    monkeypatch.setattr(cli, "acquire_full_text_batch_maximized", acquire)
    assert (
        cli.entrypoint(
            [
                "acquire",
                "--title",
                "明确的中文题名",
                "--author",
                "张三",
                "--non-interactive",
                "--fail-on-unverified",
                "--output-dir",
                str(tmp_path),
                *flags,
            ]
        )
        == 4
    )
    report = json.loads((tmp_path / "batch-report.json").read_text(encoding="utf-8"))
    assert report["items"][0]["doi"] is None
    assert report["items"][0]["input"]["authors"] == ["张三"]


def test_entrypoint_dispatches_parse(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "parse_main", lambda argv: seen.append(argv) or 8)
    assert cli.entrypoint(["parse", "paper.pdf", "--doi", "10.1000/example"]) == 8
    assert seen == [["paper.pdf", "--doi", "10.1000/example"]]


def test_entrypoint_dispatches_search(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "search_main", lambda argv: seen.append(argv) or 9)
    assert cli.entrypoint(["search", "paper.parsed.json", "method"]) == 9
    assert seen == [["paper.parsed.json", "method"]]


def test_entrypoint_dispatches_export(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "export_main", lambda argv: seen.append(argv) or 10)
    assert (
        cli.entrypoint(
            [
                "export",
                "paper.parsed.json",
                "--format",
                "chunks",
                "--output",
                "paper.chunks.json",
            ]
        )
        == 10
    )
    assert seen == [
        [
            "paper.parsed.json",
            "--format",
            "chunks",
            "--output",
            "paper.chunks.json",
        ]
    ]


def test_parse_cli_reports_typed_gate_error(monkeypatch, capsys):
    from aletheia_nexus.content import ParserInputError, ParserInputErrorCode

    def fail(*args, **kwargs):
        raise ParserInputError(ParserInputErrorCode.PDF_HASH_MISMATCH, "changed")

    monkeypatch.setattr(cli, "parse_document", fail)
    assert cli.parse_main(["paper.pdf", "--doi", "10.1000/example"]) == 5
    assert "PDF_HASH_MISMATCH" in capsys.readouterr().err


def test_search_cli_prints_page_anchor(monkeypatch, capsys):
    hit = SimpleNamespace(
        page=2,
        section_heading="Methods",
        score=2.5,
        bbox=(0.1, 0.2, 0.3, 0.4),
        text="Measured at 25 C.",
    )
    artifact = SimpleNamespace(
        search=lambda *args, **kwargs: [hit],
        verify_local_sources=lambda: {"pdf": True, "acquisition_sidecar": True},
    )
    monkeypatch.setattr(cli, "load_parsed_document", lambda path: artifact)
    assert cli.search_main(["paper.parsed.json", "measured"]) == 0
    output = capsys.readouterr().out
    assert "page 2 [Methods]" in output
    assert "Measured at 25 C." in output


def test_public_only_accepts_direct_doi_without_browser(monkeypatch, tmp_path, capsys):
    def acquire(doi, **options):
        assert doi == "10.1000/example"
        assert options["output_dir"] == tmp_path
        return SimpleNamespace(
            status=FullTextAcquisitionStatus.EXHAUSTED,
            verified_result=None,
            message="No verified main article.",
        )

    monkeypatch.setattr(cli, "acquire_full_text", acquire)
    assert (
        cli.main(["10.1000/example", "--public-only", "--output-dir", str(tmp_path)])
        == 0
    )
    assert "EXHAUSTED" in capsys.readouterr().out
    assert (
        cli.main(
            [
                "10.1000/example",
                "--public-only",
                "--output-dir",
                str(tmp_path),
                "--fail-on-unverified",
            ]
        )
        == 4
    )


def test_public_only_rejects_multiple_dois(tmp_path):
    path = tmp_path / "dois.txt"
    path.write_text("10.1000/one\n10.1000/two\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(path), "--public-only"])
    assert exc.value.code == 2


@pytest.mark.parametrize("use_system_proxy", [False, True])
def test_dedicated_cdp_browser_proxy_mode(monkeypatch, tmp_path, use_system_proxy):
    launched = []
    monkeypatch.setattr(cli, "_find_browser", lambda: Path("C:/Edge/msedge.exe"))
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda args, **kwargs: launched.append(args),
    )
    monkeypatch.setattr(cli, "_cdp_ready", lambda endpoint: True)

    cli._start_cdp_browser(
        "http://127.0.0.1:9222",
        tmp_path / "profile",
        use_system_proxy=use_system_proxy,
    )

    assert len(launched) == 1
    assert "--remote-debugging-address=127.0.0.1" in launched[0]
    assert ("--no-proxy-server" in launched[0]) is not use_system_proxy
