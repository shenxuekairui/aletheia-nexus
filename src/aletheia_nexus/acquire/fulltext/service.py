import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from aletheia_nexus.acquire.discovery.models import CandidateUrlType, FullTextCandidate
from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionError,
    AcquisitionNetworkError,
    AcquisitionNotFoundError,
    AcquisitionRateLimitError,
    AcquisitionRedirectError,
    AcquisitionRequestError,
    AcquisitionServiceError,
    AcquisitionTooLargeError,
    AcquisitionUnsafeUrlError,
)
from aletheia_nexus.acquire.fulltext.identity import validate_paper_identity
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    DocumentRole,
    IdentityStatus,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.retry import (
    AcquisitionRetryError,
    call_with_retry,
    validate_retry_config,
)
from aletheia_nexus.acquire.fulltext.storage import promote_resource, write_json_sidecar
from aletheia_nexus.acquire.fulltext.transport import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_TIMEOUT,
    retrieve_to_temp,
)
from aletheia_nexus.acquire.fulltext.validation import inspect_pdf
from aletheia_nexus.core.identifiers.doi import normalize_doi


def _status_for_error(error: AcquisitionError) -> AcquisitionStatus:
    if isinstance(error, AcquisitionAuthRequiredError):
        return AcquisitionStatus.AUTH_REQUIRED
    if isinstance(error, AcquisitionAccessBlockedError):
        return AcquisitionStatus.ACCESS_BLOCKED
    if isinstance(error, AcquisitionNotFoundError):
        return AcquisitionStatus.NOT_FOUND
    if isinstance(error, AcquisitionTooLargeError):
        return AcquisitionStatus.TOO_LARGE
    if isinstance(error, AcquisitionUnsafeUrlError):
        return AcquisitionStatus.UNSAFE_URL
    if isinstance(error, AcquisitionRedirectError):
        return AcquisitionStatus.REDIRECT_ERROR
    if isinstance(error, AcquisitionRequestError):
        return AcquisitionStatus.REQUEST_ERROR
    if isinstance(error, AcquisitionNetworkError):
        return AcquisitionStatus.NETWORK_ERROR
    if isinstance(error, AcquisitionRateLimitError):
        return AcquisitionStatus.RATE_LIMITED
    if isinstance(error, AcquisitionServiceError):
        return AcquisitionStatus.SERVICE_ERROR
    return AcquisitionStatus.ERROR


def _classify_retrieved(
    identity_status: IdentityStatus, role: DocumentRole
) -> AcquisitionStatus:
    if role == DocumentRole.SUPPLEMENT:
        return AcquisitionStatus.SUPPLEMENT
    if identity_status == IdentityStatus.MATCH and role == DocumentRole.ARTICLE:
        return AcquisitionStatus.VERIFIED
    if identity_status == IdentityStatus.MISMATCH:
        return AcquisitionStatus.MISMATCH
    return AcquisitionStatus.RETRIEVED_UNVERIFIED


def _record_payload(
    *,
    target_doi: str,
    candidate: FullTextCandidate,
    status: AcquisitionStatus,
    resource: RetrievedResource,
    pdf_validation,
    identity_validation,
    expected_title: str | None,
    attempts: int,
    elapsed_seconds: float,
) -> dict[str, object]:
    return {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "acquired_at": datetime.now(timezone.utc).isoformat(),
        "status": status.value,
        "attempts": attempts,
        "elapsed_seconds": elapsed_seconds,
        "target": {
            "doi": target_doi,
            "expected_title": expected_title,
        },
        "candidate": {
            "url": candidate.url,
            "url_type": candidate.url_type.value,
            "access_type": candidate.access_type.value,
            "version": candidate.version.value,
            "host_type": candidate.host_type.value,
            "license": candidate.license,
            "source_name": candidate.source_name,
            "is_best": candidate.is_best,
            "provenance": [provider.value for provider in candidate.provenance],
        },
        "retrieval": {
            "requested_url": resource.requested_url,
            "final_url": resource.final_url,
            "http_status": resource.http_status,
            "content_type": resource.content_type,
            "size_bytes": resource.size_bytes,
            "sha256": resource.sha256,
            "redirects": [
                {
                    "from_url": hop.from_url,
                    "status_code": hop.status_code,
                    "location": hop.location,
                    "to_url": hop.to_url,
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
            "status": identity_validation.status.value,
            "document_role": identity_validation.document_role.value,
            "doi_match": identity_validation.doi_match,
            "title_similarity": identity_validation.title_similarity,
            "evidence": list(identity_validation.evidence),
        },
    }


def _delete_retained_path(resource: RetrievedResource) -> RetrievedResource:
    if resource.local_path is not None:
        resource.local_path.unlink(missing_ok=True)
    return replace(resource, local_path=None)


def acquire_direct_pdf(
    candidate: FullTextCandidate,
    *,
    output_dir: str | Path,
    expected_title: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    keep_unverified: bool = False,
) -> AcquisitionResult:
    """Retrieve and validate one provider-reported direct PDF candidate."""

    if not isinstance(candidate, FullTextCandidate):
        raise TypeError("candidate must be a FullTextCandidate")
    if candidate.url_type != CandidateUrlType.PDF:
        raise ValueError("v0.5.0 direct acquisition only accepts PDF candidates")
    if expected_title is not None and not isinstance(expected_title, str):
        raise TypeError("expected_title must be a string or None")
    if not isinstance(keep_unverified, bool):
        raise TypeError("keep_unverified must be a boolean")

    normalized_doi = normalize_doi(candidate.doi)
    validate_retry_config(max_attempts, backoff_base)
    started_at = time.perf_counter()

    try:
        resource, attempts, _ = call_with_retry(
            lambda: retrieve_to_temp(
                candidate.url,
                output_dir=output_dir,
                max_bytes=max_bytes,
                timeout=timeout,
                max_redirects=max_redirects,
            ),
            max_attempts=max_attempts,
            backoff_base=backoff_base,
        )
    except AcquisitionRetryError as exc:
        return AcquisitionResult(
            candidate=candidate,
            status=_status_for_error(exc.error),
            error=str(exc.error),
            attempts=exc.attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    file_path: Path | None = None
    promoted_new = False

    try:
        if resource.local_path is None:
            raise RuntimeError("Retriever returned a resource without a local file")

        inspection = inspect_pdf(resource.local_path)
        pdf_validation = inspection.report

        if not pdf_validation.valid_pdf:
            resource = _delete_retained_path(resource)
            return AcquisitionResult(
                candidate=candidate,
                status=AcquisitionStatus.INVALID_PDF,
                retrieved=resource,
                pdf_validation=pdf_validation,
                error=pdf_validation.warning,
                attempts=attempts,
                elapsed_seconds=time.perf_counter() - started_at,
            )

        identity = validate_paper_identity(
            target_doi=normalized_doi,
            source_url=resource.final_url,
            inspection=inspection,
            expected_title=expected_title,
        )
        status = _classify_retrieved(identity.status, identity.document_role)

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
            sidecar_path = write_json_sidecar(
                file_path,
                _record_payload(
                    target_doi=normalized_doi,
                    candidate=candidate,
                    status=status,
                    resource=resource,
                    pdf_validation=pdf_validation,
                    identity_validation=identity,
                    expected_title=expected_title,
                    attempts=attempts,
                    elapsed_seconds=elapsed_seconds,
                ),
            )
        else:
            resource = _delete_retained_path(resource)
            elapsed_seconds = time.perf_counter() - started_at

        return AcquisitionResult(
            candidate=candidate,
            status=status,
            retrieved=resource,
            pdf_validation=pdf_validation,
            identity_validation=identity,
            file_path=file_path,
            sidecar_path=sidecar_path,
            attempts=attempts,
            elapsed_seconds=elapsed_seconds,
        )
    except Exception:
        if file_path is None:
            if resource.local_path is not None:
                resource.local_path.unlink(missing_ok=True)
        elif promoted_new:
            file_path.unlink(missing_ok=True)
        raise
