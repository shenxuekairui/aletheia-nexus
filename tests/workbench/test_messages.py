import ast
import errno
import json
from pathlib import Path

import httpx
import pytest

from aletheia_nexus.content.errors import ParserInputError, ParserInputErrorCode
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.workbench.messages import error_record, user_message


@pytest.mark.parametrize("code", list(ParserInputErrorCode))
def test_parser_identity_failures_have_chinese_recovery_without_changing_code(code):
    original = ParserInputError(code, "original source detail")
    record = error_record(original)
    assert record["known"]
    assert record["code"] == code.value
    assert record["raw"] == str(original)
    assert "请" in record["message"]
    assert original.code == code and original.detail == "original source detail"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("cost_budget_exhausted", "费用"),
        ("call_budget_exhausted", "请求次数"),
        ("cost_estimate_unavailable", "可能已计费"),
        ("timeout", "可能已计费"),
        ("missing_api_key", "系统环境"),
        ("title_translation_remote_consent_required", "尚未授权"),
        ("translation_identity_mismatch", "编号"),
        ("AUTH_REQUIRED", "认证"),
        ("INTERACTION_REQUIRED", "人工"),
        ("AMBIGUOUS", "人工确认"),
        ("UNSAFE_URL", "安全"),
        ("BROWSER_UNAVAILABLE", "浏览器"),
    ],
)
def test_important_codes_explain_actual_cause_and_next_step(code, expected):
    error = ProcessingError(code)
    assert expected in user_message(error)
    assert error.code == code


def test_dynamic_file_risk_retains_actual_path_and_safe_recovery():
    path = r"F:\文献库\化学\paper.pdf"
    message = user_message(ValueError("source changed after preview: " + path))
    assert path in message and "重新" in message
    record = error_record("legacy explicit references require review: " + path)
    assert (
        record["known"] and path in record["message"] and "已拒绝" in record["message"]
    )


@pytest.mark.parametrize(
    "error,expected",
    [
        (FileNotFoundError(errno.ENOENT, "not found", "paper.pdf"), "找不到"),
        (PermissionError(errno.EACCES, "permission denied", "paper.pdf"), "权限"),
        (OSError(errno.ENOSPC, "disk full"), "空间不足"),
        (OSError(errno.EXDEV, "cross-device link"), "文件系统"),
        (ModuleNotFoundError("No module named optional_component"), "组件"),
        (httpx.ReadTimeout("original timeout detail"), "可能已计费"),
    ],
)
def test_operating_system_and_dependency_errors_are_actionable(error, expected):
    record = error_record(error)
    assert record["known"] and expected in record["message"]
    assert record["raw"] == str(error)


def test_unknown_error_preserves_complete_diagnostic_and_requires_review():
    original = RuntimeError("new unsupported failure: block 17 became unavailable")
    record = error_record(original)
    assert not record["known"]
    assert record["raw"] == str(original) and record["code"] == "RuntimeError"
    assert "原始诊断" in record["message"]
    assert str(original) not in user_message(original)
    assert str(original) in user_message(original, include_detail=True)


def test_credentials_are_redacted_in_messages_and_expert_diagnostics(monkeypatch):
    secret = "secret-test-deepseek-key-123"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    original = RuntimeError(
        "failed with " + secret + " Authorization: Bearer token123456789"
    )
    record = error_record(original)
    assert secret not in json.dumps(record)
    assert "token123456789" not in json.dumps(record)
    assert secret not in user_message(original, include_detail=True)


def test_json_error_and_numeric_parameter_details_remain_specific():
    try:
        json.loads('{"a":}')
    except json.JSONDecodeError as exc:
        assert "第 1 行、第 6 列" in user_message(exc)
    assert "0.25–0.75" in user_message(
        "column_split_ratio must be between 0.25 and 0.75"
    )
    assert "正整数" in user_message("max_pages must be a positive integer")
    assert "不能为负数" in user_message("min_native_characters cannot be negative")
    assert "300" in user_message("OCR dpi must be at least 300")


@pytest.mark.parametrize(
    "raw,secret",
    [
        ('{"api_key": "another-secret-123"}', "another-secret-123"),
        ("https://name:secret-pass@service.test/data", "secret-pass"),
        ("request https://service.test/?api_key=private-value&x=2", "private-value"),
        ("Authorization: Basic cHJpdmF0ZTpwYXNz", "cHJpdmF0ZTpwYXNz"),
        ("Cookie: session=private-session", "private-session"),
    ],
)
def test_credentials_in_raw_headers_and_urls_are_never_exposed(raw, secret):
    result = error_record(RuntimeError(raw))
    assert secret not in json.dumps(result)
    assert secret not in user_message(RuntimeError(raw), include_detail=True)


def test_chinese_file_path_does_not_misclassify_unknown_english_error_as_translated():
    result = error_record(
        RuntimeError(r"unexpected storage failure at F:\中文文库\paper.pdf")
    )
    assert not result["known"]
    assert "unexpected" not in result["message"]
    assert "unexpected" in result["raw"]


def test_current_backend_literal_errors_are_all_localized():
    # Protect the ordinary UI boundary as application services evolve. Codes and
    # the original diagnostics stay untouched; this is not a snapshot of wording.
    package = Path(__file__).parents[2] / "src/aletheia_nexus/workbench"
    missing = []
    for path in package.glob("*.py"):
        if path.name.startswith("ui") or path.name in {"messages.py", "labels.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                not isinstance(node, ast.Raise)
                or not isinstance(node.exc, ast.Call)
                or not node.exc.args
            ):
                continue
            value = node.exc.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                if not error_record(ValueError(value.value))["known"]:
                    missing.append((path.name, value.value))
    assert missing == []
