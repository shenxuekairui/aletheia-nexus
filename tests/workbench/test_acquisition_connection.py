"""A connection failure explains recovery without changing verified main state."""

import json
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.acquire.access.browser_engine import connection
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.workbench import acquisition, supplements


@pytest.mark.parametrize("public_main_verified", [True, False])
def test_task_exposes_connection_details_and_preserves_independent_main_status(
    monkeypatch, tmp_path, public_main_verified
):
    root = tmp_path / "library"
    root.mkdir()
    pdf = root / "fixture.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    source = acquisition_sidecar_path(pdf)
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/acquisition-record/v1",
                "status": "VERIFIED",
                "target": {"doi": "10.1000/fixture", "expected_title": "Fixture title"},
                "retrieval": {"sha256": sha256_file(pdf)},
                "pdf_validation": {"valid_pdf": True, "page_count": 1},
                "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
            }
        )
    )
    before = (pdf.read_bytes(), source.read_bytes())
    calls = []

    def connect(*args, **kwargs):
        calls.append("connect")
        raise TimeoutError("<ws connected> private-control-id")

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(browser, "_load_playwright", lambda: Manager)
    monkeypatch.setattr(
        connection,
        "inspect_local_endpoint",
        lambda value: {
            "endpoint_reachable": True,
            "page_count": 15,
            "pdf_like_page_count": 2,
        },
    )

    def batch(requests, *, browser_session, **kwargs):
        message = None
        if not public_main_verified:
            for _ in range(2):
                with pytest.raises(browser.BrowserCapabilityUnavailable) as caught:
                    browser_session._ensure_started()
            message = str(caught.value)
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    requests[0],
                    requests[0].doi,
                    BatchItemStatus.VERIFIED
                    if public_main_verified
                    else BatchItemStatus.BROWSER_UNAVAILABLE,
                    verified_path=pdf if public_main_verified else None,
                    result=SimpleNamespace(message=message),
                )
            ]
        )

    def acquire_si(main, *, browser_session, **kwargs):
        with pytest.raises(browser.BrowserCapabilityUnavailable):
            browser_session._ensure_started()
        return {
            "status": "FAILED",
            "items": [],
            "errors": [],
            "diagnostics": [
                {
                    "status": "BROWSER_CONNECTION_UNAVAILABLE",
                    **browser_session.connection_diagnostic,
                }
            ],
        }

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    monkeypatch.setattr(supplements, "acquire_supplements", acquire_si)
    report = acquisition.AcquisitionService(root).run(
        ["10.1000/fixture"],
        {
            "public_only": False,
            "browser_enabled": True,
            "include_si": True,
            "browser": {"cdp_endpoint": "http://127.0.0.1:54321"},
        },
    )
    row = report["items"][0]
    assert calls == ["connect"]
    assert row["browser_connection"]["code"] == "browser_cdp_attach_timeout"
    assert row["browser_connection"]["page_count"] == 15
    assert "private-control-id" not in json.dumps(report)
    if public_main_verified:
        assert report["status"] == "PARTIAL"
        assert row["status"] == row["main_status"] == "VERIFIED"
        assert row["si_status"] == "FAILED" and report["success"] == 1
    else:
        assert report["status"] == "FAILED"
        assert row["reason_code"] == "browser_cdp_attach_timeout"
        assert "现有窗口、标签和登录状态已保留" in row["reason"]
        assert row["si_status"] == "NOT_ATTEMPTED"
    assert (pdf.read_bytes(), source.read_bytes()) == before


def test_earlier_session_failure_does_not_taint_later_public_main_success(
    monkeypatch, tmp_path
):
    main = tmp_path / "public.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(main)
    sidecar = acquisition_sidecar_path(main)
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(
        json.dumps(
            {
                "schema": "aletheia-nexus/acquisition-record/v1",
                "status": "VERIFIED",
                "target": {"doi": "10.1000/public", "expected_title": "Fixture title"},
                "retrieval": {"sha256": sha256_file(main)},
                "pdf_validation": {"valid_pdf": True, "page_count": 1},
                "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
            }
        )
    )

    def batch(requests, *, browser_session, **kwargs):
        failed = requests[0].doi == "10.1000/failed"
        if failed:
            browser_session._connection_failure = (
                "浏览器连接超时",
                {"code": "browser_cdp_attach_timeout", "message": "浏览器连接超时"},
            )
        return SimpleNamespace(
            items=[
                BatchAcquisitionItem(
                    requests[0],
                    requests[0].doi,
                    BatchItemStatus.BROWSER_UNAVAILABLE
                    if failed
                    else BatchItemStatus.VERIFIED,
                    verified_path=None if failed else main,
                )
            ]
        )

    monkeypatch.setattr(acquisition, "acquire_full_text_batch_maximized", batch)
    report = acquisition.AcquisitionService(tmp_path).run(
        ["10.1000/failed", "10.1000/public"],
        {"include_si": False},
    )
    assert report["status"] == "PARTIAL"
    assert (
        report["items"][0]["browser_connection"]["code"] == "browser_cdp_attach_timeout"
    )
    assert report["items"][1]["status"] == "VERIFIED"
    assert "browser_connection" not in report["items"][1]
