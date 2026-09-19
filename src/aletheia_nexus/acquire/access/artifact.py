import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from aletheia_nexus.acquire.access.security import redact_url_for_record
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.identity import validate_paper_identity
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    DocumentRole,
    IdentityStatus,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.storage import promote_resource, write_json_sidecar
from aletheia_nexus.acquire.fulltext.validation import inspect_pdf
from aletheia_nexus.core.identifiers.doi import normalize_doi

_SENSITIVE_ACCESS_KEY_MARKERS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "cookie",
    "authorization",
)


def _sanitize_access_details(
    value: object,
    *,
    key_hint: str = "",
) -> object:
    """Reject credential-like fields and redact URL values before persistence."""

    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise TypeError("access_details keys must be strings")
            lowered = raw_key.lower()
            if any(marker in lowered for marker in _SENSITIVE_ACCESS_KEY_MARKERS):
                raise ValueError(
                    f"Refusing to persist credential-like access detail: {raw_key}"
                )
            sanitized[raw_key] = _sanitize_access_details(
                item,
                key_hint=lowered,
            )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_access_details(item, key_hint=key_hint) for item in value]
    if isinstance(value, str) and "url" in key_hint:
        return redact_url_for_record(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        "access_details values must be JSON-compatible primitives, lists, or dicts"
    )


def _classify(
    identity_status: IdentityStatus,
    role: DocumentRole,
) -> AcquisitionStatus:
    if role == DocumentRole.SUPPLEMENT:
        return AcquisitionStatus.SUPPLEMENT
    if identity_status == IdentityStatus.MATCH and role == DocumentRole.ARTICLE:
        return AcquisitionStatus.VERIFIED
    if identity_status == IdentityStatus.MISMATCH:
        return AcquisitionStatus.MISMATCH
    return AcquisitionStatus.RETRIEVED_UNVERIFIED


def _delete_temp(resource: RetrievedResource) -> RetrievedResource:
    if resource.local_path is not None:
        resource.local_path.unlink(missing_ok=True)
    return replace(resource, local_path=None)


def finalize_access_resource(
    *,
    candidate: FullTextCandidate,
    resource: RetrievedResource,
    output_dir: str | Path,
    expected_title: str | None,
    keep_unverified: bool,
    transport: str,
    access_details: dict[str, object],
    access_evidence: tuple[str, ...] = (),
) -> AcquisitionResult:
    """Apply the scientific validation gates to any authenticated-access artifact.

    Access mechanisms are intentionally decoupled from scholarly validation.
    Browser sessions, official APIs, or future legitimate access providers may
    retrieve bytes, but only PDF structure + identity + document-role validation
    can create VERIFIED.
    """

    if not isinstance(transport, str) or not transport.strip():
        raise ValueError("transport must be a non-empty string")
    if not isinstance(access_details, dict):
        raise TypeError("access_details must be a dict")
    safe_access_details = _sanitize_access_details(access_details)

    started_at = time.perf_counter()
    normalized_doi = normalize_doi(candidate.doi)
    file_path: Path | None = None
    promoted_new = False

    try:
        if resource.local_path is None:
            raise ValueError("Access resource has no local file")

        inspection = inspect_pdf(resource.local_path)
        pdf_validation = inspection.report

        if not pdf_validation.valid_pdf:
            resource = _delete_temp(resource)
            return AcquisitionResult(
                candidate=candidate,
                status=AcquisitionStatus.INVALID_PDF,
                retrieved=resource,
                pdf_validation=pdf_validation,
                error=pdf_validation.warning,
                attempts=1,
                elapsed_seconds=time.perf_counter() - started_at,
            )

        identity = validate_paper_identity(
            target_doi=normalized_doi,
            source_url=resource.final_url,
            inspection=inspection,
            expected_title=expected_title,
        )
        status = _classify(identity.status, identity.document_role)
        should_persist = status == AcquisitionStatus.VERIFIED or keep_unverified

        sidecar_path: Path | None = None
        if should_persist:
            subdirectory = (
                None if status == AcquisitionStatus.VERIFIED else "_unverified"
            )
            file_path, promoted_new = promote_resource(
                resource,
                doi=normalized_doi,
                output_dir=output_dir,
                subdirectory=subdirectory,
            )
            resource = replace(resource, local_path=file_path)
            elapsed_seconds = time.perf_counter() - started_at
            payload = {
                "schema": "aletheia-nexus/access-acquisition-record/v1",
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "status": status.value,
                "transport": transport,
                "target": {
                    "doi": normalized_doi,
                    "expected_title": expected_title,
                },
                "candidate": {
                    "url": redact_url_for_record(candidate.url),
                    "url_type": candidate.url_type.value,
                    "access_type": candidate.access_type.value,
                    "version": candidate.version.value,
                    "host_type": candidate.host_type.value,
                    "license": candidate.license,
                    "source_name": candidate.source_name,
                    "is_best": candidate.is_best,
                    "provenance": [provider.value for provider in candidate.provenance],
                },
                "access": {
                    **safe_access_details,
                    "evidence": list(access_evidence),
                    "sensitive_session_state_recorded": False,
                },
                "retrieval": {
                    "requested_url": redact_url_for_record(resource.requested_url),
                    "final_url": redact_url_for_record(resource.final_url),
                    "http_status": resource.http_status,
                    "content_type": resource.content_type,
                    "size_bytes": resource.size_bytes,
                    "sha256": resource.sha256,
                    "redirects": [
                        {
                            "from_url": redact_url_for_record(hop.from_url),
                            "status_code": hop.status_code,
                            "location": redact_url_for_record(hop.location),
                            "to_url": redact_url_for_record(hop.to_url),
                        }
                        for hop in resource.redirects
                    ],
                },
                "pdf_validation": {
                    "valid_pdf": pdf_validation.valid_pdf,
                    "magic_bytes_ok": pdf_validation.magic_bytes_ok,
                    "parseable": pdf_validation.parseable,
                    "page_count": pdf_validation.page_count,
                    "encrypted": pdf_validation.encrypted,
                    "warning": pdf_validation.warning,
                },
                "identity_validation": {
                    "status": identity.status.value,
                    "document_role": identity.document_role.value,
                    "doi_match": identity.doi_match,
                    "title_similarity": identity.title_similarity,
                    "evidence": list(identity.evidence),
                },
            }
            sidecar_path = write_json_sidecar(file_path, payload)
        else:
            resource = _delete_temp(resource)
            elapsed_seconds = time.perf_counter() - started_at

        return AcquisitionResult(
            candidate=candidate,
            status=status,
            retrieved=resource,
            pdf_validation=pdf_validation,
            identity_validation=identity,
            file_path=file_path,
            sidecar_path=sidecar_path,
            attempts=1,
            elapsed_seconds=elapsed_seconds,
        )
    except Exception:
        if file_path is None:
            if resource.local_path is not None:
                resource.local_path.unlink(missing_ok=True)
        elif promoted_new:
            file_path.unlink(missing_ok=True)
        raise


def finalize_browser_resource(
    *,
    candidate: FullTextCandidate,
    resource: RetrievedResource,
    output_dir: str | Path,
    expected_title: str | None,
    keep_unverified: bool,
    profile_name: str,
    source_page_url: str | None,
    access_evidence: tuple[str, ...] = (),
) -> AcquisitionResult:
    """Validate browser-retrieved bytes with the shared authenticated-access gate."""

    return finalize_access_resource(
        candidate=candidate,
        resource=resource,
        output_dir=output_dir,
        expected_title=expected_title,
        keep_unverified=keep_unverified,
        transport="authenticated_browser_session",
        access_details={
            "profile_name": profile_name,
            "source_page_url": redact_url_for_record(source_page_url),
        },
        access_evidence=access_evidence,
    )
