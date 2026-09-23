"""Import a PDF explicitly saved by the user, through the normal science gate."""

import hashlib
import shutil
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from aletheia_nexus.acquire.access.artifact import finalize_access_resource
from aletheia_nexus.acquire.access.models import (
    MaximizedAcquisitionResult,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryResult,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    TitleSource,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi


def import_local_pdf(
    doi: str,
    path: str | Path,
    *,
    output_dir: str | Path,
    expected_title: str | None = None,
    max_bytes: int = 100 * 1024 * 1024,
    keep_unverified: bool = False,
) -> AcquisitionResult:
    """Copy an explicitly chosen file; never mutate the user's original.

    Local import is useful when a publisher requires user-operated download. It
    creates VERIFIED only after the same PDF, identity and document-role checks
    used for browser and official-API bytes.
    """

    normalized_doi = normalize_doi(doi)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if not isinstance(keep_unverified, bool):
        raise TypeError("keep_unverified must be a boolean")
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    size = source.stat().st_size
    if size < 1 or size > max_bytes:
        raise ValueError("Local PDF is empty or exceeds max_bytes")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f".an-local-import-{uuid4().hex}.part"
    doi_url = f"https://doi.org/{quote(normalized_doi, safe='/')}"
    candidate = FullTextCandidate(
        doi=normalized_doi,
        url=doi_url,
        provenance=(),
        url_type=CandidateUrlType.PDF,
        source_name="User-selected local PDF",
    )
    try:
        shutil.copyfile(source, temporary)
        copied_size = temporary.stat().st_size
        if copied_size < 1 or copied_size > max_bytes:
            raise ValueError("Copied local PDF is empty or exceeds max_bytes")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        resource = RetrievedResource(
            requested_url=doi_url,
            final_url=doi_url,
            http_status=0,  # No HTTP request was made for a user-supplied file.
            content_type="application/pdf",
            size_bytes=copied_size,
            sha256=digest.hexdigest(),
            local_path=temporary,
        )
        return finalize_access_resource(
            candidate=candidate,
            resource=resource,
            output_dir=destination,
            expected_title=expected_title,
            keep_unverified=keep_unverified,
            transport="user_selected_local_file",
            access_details={"user_selected": True},
            access_evidence=("The user explicitly selected the local PDF",),
        )
    finally:
        temporary.unlink(missing_ok=True)


def resolve_user_operated_access(
    doi: str,
    *,
    output_dir: str | Path,
    expected_title: str | None,
    local_pdf_path: str | Path | None,
    max_bytes: int,
    keep_unverified: bool,
) -> MaximizedAcquisitionResult:
    """Represent a no-network handoff or validate the explicitly chosen file."""

    normalized_doi = normalize_doi(doi)
    base = MultiRouteAcquisitionResult(
        doi=normalized_doi,
        status=FullTextAcquisitionStatus.NO_CANDIDATES,
        discovery=DiscoveryResult(doi=normalized_doi, candidates=(), providers=()),
        expected_title=expected_title,
        title_source=TitleSource.USER if expected_title else TitleSource.NONE,
        message="Automated network acquisition was not used for this DOI",
    )
    if local_pdf_path is None:
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.INTERACTION_REQUIRED,
            base_result=base,
            message=(
                "No local PDF was selected. Open "
                f"https://doi.org/{quote(normalized_doi, safe='/')} yourself, "
                "save the single article PDF, then provide its local path."
            ),
        )

    try:
        imported = import_local_pdf(
            normalized_doi,
            local_pdf_path,
            output_dir=output_dir,
            expected_title=expected_title,
            max_bytes=max_bytes,
            keep_unverified=keep_unverified,
        )
    except (OSError, ValueError) as exc:
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.INTERACTION_REQUIRED,
            base_result=base,
            message=f"Local PDF import failed: {type(exc).__name__}",
        )
    if imported.status == AcquisitionStatus.VERIFIED:
        return MaximizedAcquisitionResult(
            doi=normalized_doi,
            status=MaximizedAcquisitionStatus.VERIFIED,
            base_result=base,
            verified_result=imported,
            message="User-selected PDF passed scientific validation.",
        )
    return MaximizedAcquisitionResult(
        doi=normalized_doi,
        status=MaximizedAcquisitionStatus.INTERACTION_REQUIRED,
        base_result=base,
        message=(
            f"User-selected file was {imported.status.value}; choose the "
            "main-article PDF for this DOI."
        ),
    )
