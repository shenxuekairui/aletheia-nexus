"""Installed CLI contract and first-run public-only path."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus import cli
from aletheia_nexus.acquire.fulltext import FullTextAcquisitionStatus


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
