"""Exercise HTML export through native results with self-authored sources only."""

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_research import research as research_fixture

from aletheia_nexus.processing.engine import write_json
from aletheia_nexus.processing.materials import build_package
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import make_result


@pytest.fixture
def native_result(tmp_path):
    fixture = research_fixture.__wrapped__(tmp_path)
    research = next(fixture)
    try:
        task = research.local_plan("合成夹具结果", ["p1"])
        package, _ = build_package(
            task, [research.app.check_document(task["documents"][0], "parsed")]
        )
        source = package["documents"][0]
        block = next(b for b in source["blocks"] if "sample" in b["text"])
        citation = {
            "source_id": source["id"],
            "page": block["page"],
            "block_id": block["id"],
            "quote": block["text"],
        }
        field = {
            "value": "25 C for 2 h",
            "raw_value": "25 C for 2 h",
            "unit": None,
            "status": "reported",
            "nature": "reported",
            "context": "Self-authored fixture, not scientific evidence.",
            "step_ids": [],
            "citations": [citation],
        }
        response = {
            "records": [
                {
                    "id": "r1",
                    "subject": "fixture",
                    "stage": "measurement",
                    "fields": {"finding": field},
                    "steps": [],
                }
            ],
            "claims": [],
            "issues": [],
            "requests": [],
        }
        value = make_result(task, package, {"provider": "deterministic-test"}, response)
        path = research.workspace / "research/runs/fixture/result.json"
        write_json(path, value)
        yield research, path
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass


def test_default_export_does_not_read_source_images(native_result, monkeypatch):
    research, path = native_result
    before = path.read_bytes()

    def unexpected_render(*args, **kwargs):
        raise AssertionError("HTML/source rendering must be explicitly selected")

    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page", unexpected_render
    )
    report = research.export([str(path)])
    assert not (Path(report["directory"]) / "report.html").exists()
    assert path.read_bytes() == before


def test_explicit_html_is_offline_and_preserves_native_result(
    native_result, monkeypatch
):
    research, path = native_result
    before = path.read_bytes()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j9xkAAAAASUVORK5CYII="
    )
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page", lambda *a, **k: png
    )
    report = research.export([str(path)], formats=["html"])
    html = (Path(report["directory"]) / "report.html").read_text(encoding="utf-8")
    assert "25 C for 2 h" in html
    assert "data:image/png;base64," in html
    assert report["network_access"] is False
    assert path.read_bytes() == before
    assert not report["warnings"]


def test_source_changed_during_render_discards_images(native_result, monkeypatch):
    research, path = native_result
    before = path.read_bytes()
    calls = []

    def verify():
        calls.append(True)
        if len(calls) > 1:
            raise ProcessingError("source_changed")

    monkeypatch.setattr(
        research.app,
        "check_document",
        lambda *a, **k: SimpleNamespace(pdf="unused", verify=verify),
    )
    monkeypatch.setattr(
        "aletheia_nexus.processing.materials.render_page",
        lambda *a, **k: b"untrusted-image",
    )
    report = research.export([str(path)], formats=["html"])
    html = (Path(report["directory"]) / "report.html").read_text(encoding="utf-8")
    assert report["warnings"]
    assert "25 C for 2 h" in html
    assert "data:image/png;base64," not in html
    assert path.read_bytes() == before
