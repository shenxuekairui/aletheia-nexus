"""Only explicit native viewer delivery codes get actionable Chinese wording."""

import json

import pytest

from aletheia_nexus.workbench.messages import error_record, user_message

CODES = [
    ("NativePdfViewerCaptureUnavailable", "安全捕获"),
    ("NativePdfViewerOwnedTargetNotFound", "可靠关联"),
    ("NativePdfViewerTargetAmbiguous", "无法唯一确认"),
    ("NativePdfViewerTargetNotFound", "没有找到"),
    ("NativePdfViewerLocalSaveControlUnavailable", "本机保存控件"),
    ("NativePdfViewerLocalSaveNotAcknowledged", "没有确认操作开始"),
    ("NativePdfViewerOwnedDownloadIncomplete", "尚未完整交付"),
    ("NativePdfViewerDownloadSizeLimit", "超过本次大小上限"),
    ("NativePdfViewerNonPdfDelivery", "不是可识别的 PDF"),
]


@pytest.mark.parametrize("code,expected", CODES)
def test_exact_delivery_code_is_translated_without_mutating_native_diagnostic(
    code, expected
):
    for value in (code, ValueError(code), {"code": code, "message": code}):
        record = error_record(value)
        assert record["known"] and expected in record["message"]
        assert record["raw"] == code
        assert "请" in record["message"]
        assert (
            "已获得" not in record["message"] and "正文已验证" not in record["message"]
        )
        assert code not in user_message(value)
        assert code in user_message(value, include_detail=True)


@pytest.mark.parametrize(
    "exception_type", ["TimeoutError", "PermissionError", "UnexpectedFixtureFailure"]
)
def test_save_error_uses_existing_colon_code_mechanism_and_keeps_cause(exception_type):
    raw = "NativePdfViewerSaveError:" + exception_type
    record = error_record(raw)
    assert record["known"] and "保存过程中发生异常" in record["message"]
    assert "尚未确认文件交付" in record["message"]
    assert record["raw"] == raw
    assert exception_type in user_message(raw, include_detail=True)
    assert exception_type not in user_message(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "NativePdfViewerUnexpectedFailure",
        "NativePdfViewerTargetNotFoundOther",
        "NativePdfViewerSaveErrorOther:TimeoutError",
        "UnrelatedPrefix:NativePdfViewerTargetNotFound",
        "TargetNotFound",
    ],
)
def test_similar_or_unknown_errors_are_not_broadly_swallowed(raw):
    record = error_record(raw)
    assert record["known"] is False
    assert record["raw"] == raw and "原始诊断" in record["message"]


def test_save_error_diagnostics_keep_existing_credential_redaction(monkeypatch):
    secret = "fixture-native-viewer-secret-key"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    record = error_record("NativePdfViewerSaveError:RuntimeError " + secret)
    assert record["known"]
    assert secret not in json.dumps(record)
    assert "[已隐藏凭据]" in record["raw"]
