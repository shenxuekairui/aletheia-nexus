import json
import os
import sys

from scripts import verify_v07_rc as verifier


def test_release_checks_import_current_checkout_over_another_install(tmp_path):
    shadow = tmp_path / "aletheia_nexus"
    shadow.mkdir()
    (shadow / "__init__.py").write_text(
        "raise RuntimeError('wrong checkout')", encoding="utf-8"
    )
    environment = {**os.environ, "PYTHONPATH": str(tmp_path)}
    code = (
        "from pathlib import Path; import aletheia_nexus; "
        "assert Path(aletheia_nexus.__file__).resolve() == "
        f"Path({str(verifier.ROOT / 'src/aletheia_nexus/__init__.py')!r}).resolve()"
    )
    result = verifier._run(
        "source-import", [sys.executable, "-c", code], env=environment
    )
    assert result["passed"]
    assert environment["PYTHONPATH"] == str(tmp_path)


def test_requested_browser_failure_fails_release_report(monkeypatch, tmp_path):
    def run(name, command, *, env=None):
        if name == "real-browser-smoke":
            assert env["AN_RUN_BROWSER_SMOKE"] == "1"
            assert "tests/acquire/access/test_cnki_browser_integration.py" in command
        return {"name": name, "passed": name != "real-browser-smoke"}

    monkeypatch.setattr(verifier, "_run", run)
    report = tmp_path / "report.json"
    assert verifier.main(["--browser-smoke", "--report", str(report)]) == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert not payload["passed"]
    assert payload["checks"][-1]["name"] == "real-browser-smoke"


def test_visible_default_browser_is_an_explicit_release_check(monkeypatch):
    captured = []

    def run(name, command, *, env=None):
        if name == "normal-browser-smoke":
            assert env["AN_RUN_VISIBLE_BROWSER_SMOKE"] == "1"
            assert "tests/acquire/access/test_normal_browser_integration.py" in command
            captured.append(name)
        return {"name": name, "passed": True}

    monkeypatch.setattr(verifier, "_run", run)
    assert verifier.main(["--visible-browser-smoke"]) == 0
    assert captured == ["normal-browser-smoke"]
