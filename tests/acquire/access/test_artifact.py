import hashlib
import json

from pypdf import PdfWriter

from aletheia_nexus.acquire.access.artifact import finalize_browser_resource
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionStatus,
    RetrievedResource,
)


def _candidate() -> FullTextCandidate:
    return FullTextCandidate(
        doi="10.1000/browser-target",
        url="https://publisher.example/article.pdf",
        provenance=(),
        url_type=CandidateUrlType.PDF,
        source_name="authenticated browser test",
    )


def _resource(path, *, content_type="application/pdf") -> RetrievedResource:
    body = path.read_bytes()
    return RetrievedResource(
        requested_url="https://publisher.example/article.pdf",
        final_url="https://publisher.example/article.pdf",
        http_status=200,
        content_type=content_type,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        local_path=path,
    )


def test_browser_artifact_still_requires_scientific_identity_validation(tmp_path):
    source = tmp_path / "browser.part"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Expected Browser Article"})
    with source.open("wb") as handle:
        writer.write(handle)

    result = finalize_browser_resource(
        candidate=_candidate(),
        resource=_resource(source),
        output_dir=tmp_path / "out",
        expected_title="Expected Browser Article",
        keep_unverified=False,
        profile_name="institution",
        source_page_url="https://publisher.example/article",
        access_evidence=("test authenticated session",),
    )

    assert result.status == AcquisitionStatus.VERIFIED
    assert result.file_path is not None
    assert result.sidecar_path is not None

    payload = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert payload["transport"] == "authenticated_browser_session"
    assert payload["access"]["sensitive_session_state_recorded"] is False
    serialized = json.dumps(payload).lower()
    assert "cookie" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized


def test_browser_artifact_rejects_non_pdf_and_cleans_temp_file(tmp_path):
    source = tmp_path / "not-a-pdf.part"
    source.write_text("<html>login</html>", encoding="utf-8")

    result = finalize_browser_resource(
        candidate=_candidate(),
        resource=_resource(source, content_type="text/html"),
        output_dir=tmp_path / "out",
        expected_title="Expected Browser Article",
        keep_unverified=False,
        profile_name="institution",
        source_page_url="https://publisher.example/article",
    )

    assert result.status == AcquisitionStatus.INVALID_PDF
    assert result.file_path is None
    assert result.retrieved is not None
    assert result.retrieved.local_path is None
    assert not source.exists()


def test_access_details_reject_credential_like_fields(tmp_path):
    source = tmp_path / "browser-secret.part"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Expected Browser Article"})
    with source.open("wb") as handle:
        writer.write(handle)

    from aletheia_nexus.acquire.access.artifact import finalize_access_resource

    try:
        finalize_access_resource(
            candidate=_candidate(),
            resource=_resource(source),
            output_dir=tmp_path / "out",
            expected_title="Expected Browser Article",
            keep_unverified=False,
            transport="test",
            access_details={"api_key": "must-not-persist"},
        )
    except ValueError as exc:
        assert "credential-like" in str(exc)
    else:
        raise AssertionError("credential-like access details must be rejected")


def test_access_detail_urls_are_redacted_before_persistence(tmp_path):
    source = tmp_path / "browser-url.part"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Expected Browser Article"})
    with source.open("wb") as handle:
        writer.write(handle)

    from aletheia_nexus.acquire.access.artifact import finalize_access_resource

    result = finalize_access_resource(
        candidate=_candidate(),
        resource=_resource(source),
        output_dir=tmp_path / "out",
        expected_title="Expected Browser Article",
        keep_unverified=False,
        transport="test",
        access_details={"source_url": "https://idp.example/login?state=super-secret"},
    )

    payload = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert payload["access"]["source_url"] == (
        "https://idp.example/login?state=%5Bredacted%5D"
    )
    assert "super-secret" not in json.dumps(payload)
