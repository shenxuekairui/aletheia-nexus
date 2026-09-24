"""Installed CLI contract and first-run public-only path."""

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
