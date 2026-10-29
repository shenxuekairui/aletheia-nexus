"""A native viewer shell is readable as an incomplete file delivery, not access."""

from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access.batch import BatchAcquisitionItem, BatchItemStatus
from aletheia_nexus.core.paper_request import PaperRequest
from aletheia_nexus.workbench.acquisition import _outcome
from aletheia_nexus.workbench.task_view import task_rows

SHELL_ERROR = "NativePdfViewerPlaceholder: browser returned its HTML viewer shell; native delivery is required"


def outcome(
    status=BatchItemStatus.EXHAUSTED, *, shell_error=SHELL_ERROR, later_error=None
):
    candidate = SimpleNamespace(url="https://pubs.acs.org/doi/epdf/10.1000/fixture")
    files = [
        SimpleNamespace(
            candidate=candidate,
            result=None,
            error=shell_error,
            method="browser_response",
        )
    ]
    if later_error:
        files.append(
            SimpleNamespace(
                candidate=candidate,
                result=None,
                error=later_error,
                method="native_download",
            )
        )
    result = SimpleNamespace(
        browser_attempts=[
            SimpleNamespace(
                source_candidate=candidate,
                status="EXHAUSTED",
                error=None,
                challenge_history=[],
                bibliographic_conflicts=[],
                file_attempts=files,
            )
        ],
    )
    return _outcome(
        BatchAcquisitionItem(
            PaperRequest(doi="10.1000/fixture"),
            "10.1000/fixture",
            status,
            result=result,
            error="generic final failure",
            attempts=1,
        )
    )


def test_shell_failure_explains_no_saved_pdf_without_asserting_article_access():
    result = outcome()
    assert result["main_status"] == "EXHAUSTED"
    assert result["phase"] == "阅读器已响应，PDF 尚未交付"
    assert "页面打开不代表文件已保存" in result["reason"]
    assert "也不能据此判断正文访问授权" in result["reason"]
    assert "只选这篇论文重试" in result["reason"]
    assert result["reason_code"] == result["error"] == "generic final failure"
    assert result["diagnostics"][1]["reason_code"] == SHELL_ERROR
    assert "pdf" not in result and "sidecar" not in result
    rows = task_rows(
        {
            "kind": "acquisition",
            "result": {
                "items": [
                    {
                        "request": {"doi": "10.1000/fixture"},
                        "status": "EXHAUSTED",
                        **result,
                    }
                ]
            },
        }
    )
    assert rows[0]["phase"] == result["phase"]
    assert rows[0]["reason"] == result["reason"]
    assert "NativePdfViewerPlaceholder" not in rows[0]["reason"]


def test_shell_diagnostic_is_not_hidden_by_a_later_generic_transport_failure():
    result = outcome(later_error="NativeTransferIncomplete: no completed file")
    assert "尚未交付可验证的 PDF 文件" in result["reason"]
    assert len(result["diagnostics"]) == 3
    assert result["diagnostics"][-1]["reason_code"].startswith(
        "NativeTransferIncomplete"
    )


@pytest.mark.parametrize(
    "status", [BatchItemStatus.VERIFIED, BatchItemStatus.RETRIEVED_UNVERIFIED]
)
def test_an_earlier_shell_does_not_hide_a_later_delivered_file(status):
    result = outcome(status)
    assert result["main_status"] == status.value
    assert "尚未交付" not in result["reason"]
    assert result["diagnostics"][1]["reason_code"] == SHELL_ERROR


def test_legacy_top_level_shell_error_is_explained_without_browser_attempt_details():
    result = _outcome(
        BatchAcquisitionItem(
            PaperRequest(doi="10.1000/fixture"),
            "10.1000/fixture",
            BatchItemStatus.EXHAUSTED,
            result=None,
            error=SHELL_ERROR,
            attempts=1,
        )
    )
    assert result["phase"] == "阅读器已响应，PDF 尚未交付"
    assert result["error"] == result["reason_code"] == SHELL_ERROR
    assert result["diagnostics"] == []


@pytest.mark.parametrize(
    "error",
    [
        "UnrelatedPlaceholder: no body",
        "NativePdfViewerPlaceholderOther: not this failure",
        None,
    ],
)
def test_unrelated_diagnostics_do_not_claim_a_viewer_delivery_state(error):
    result = outcome(shell_error=error)
    assert result["phase"] == "获取正文结束"
    assert "PDF 阅读器页面" not in result["reason"]
