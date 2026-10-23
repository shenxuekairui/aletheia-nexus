"""Bounded, lazy use of publisher-deposited Crossref resource links."""

import re
import time
from collections.abc import Iterable

from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    FullTextVersion,
    HostType,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.ranking import merge_and_rank_candidates
from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url
from aletheia_nexus.acquire.metadata.crossref import get_crossref_metadata
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataError,
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata

MAX_SUPPLEMENT_ROUTES = 4
_PDF_URL = re.compile(r"(?:\.pdf(?:$|[?#])|/pdf(?:/|$)|/articlepdf(?:/|$))", re.I)
_VERSIONS = {
    "vor": FullTextVersion.PUBLISHED,
    "am": FullTextVersion.ACCEPTED,
    "sm": FullTextVersion.SUBMITTED,
}


def candidates_from_metadata(metadata: PaperMetadata) -> tuple[FullTextCandidate, ...]:
    """Reuse deposited links; never infer OA status or invent publisher paths."""

    candidates = []
    for link in metadata.links:
        if link.source != "crossref":
            continue
        # A similarity-checking-only endpoint is not a general full-text route.
        application = (link.intended_application or "").casefold()
        if application not in {"", "unspecified", "text-mining"}:
            continue
        try:
            url = normalize_candidate_url(link.url)
        except (TypeError, ValueError):
            continue
        host_type = refine_host_type(url, HostType.UNKNOWN)
        if host_type == HostType.RESOLVER:
            continue
        mime = (link.content_type or "").split(";", 1)[0].strip().casefold()
        if link.relation == "primary":
            url_type = CandidateUrlType.LANDING_PAGE
        elif mime == "application/pdf":
            url_type = CandidateUrlType.PDF
        elif mime in {"text/html", "application/xhtml+xml"}:
            url_type = CandidateUrlType.LANDING_PAGE
        elif mime in {"", "unspecified", "application/octet-stream"}:
            url_type = (
                CandidateUrlType.PDF
                if _PDF_URL.search(url)
                else CandidateUrlType.UNKNOWN
            )
        else:
            # XML/plain-text TDM APIs cannot produce the PDF this pipeline needs.
            continue
        candidates.append(
            FullTextCandidate(
                doi=metadata.doi,
                url=url,
                provenance=(DiscoveryProvider.CROSSREF,),
                url_type=url_type,
                version=_VERSIONS.get(
                    (link.content_version or "").casefold(), FullTextVersion.UNKNOWN
                ),
                host_type=host_type,
                source_name="Crossref deposited resource",
            )
        )
    return merge_and_rank_candidates(candidates)


def discover_crossref_supplement(
    doi: str,
    *,
    metadata: PaperMetadata | None = None,
    metadata_error: str | None = None,
    allow_lookup: bool = True,
    mailto: str | None = None,
    excluded_urls: Iterable[str] = (),
    limit: int = MAX_SUPPLEMENT_ROUTES,
) -> tuple[ProviderDiscoveryResult, PaperMetadata | None]:
    """Reuse an earlier lookup, or make one request only when recovery needs it.

    A previous metadata failure is not retried here. Crossref availability must
    not change the outcome of the original acquisition routes.
    """

    started = time.perf_counter()
    attempts = 0
    normalized_doi = normalize_doi(doi)

    def result(status, candidates=(), error=None):
        return ProviderDiscoveryResult(
            provider=DiscoveryProvider.CROSSREF,
            status=status,
            candidates=candidates,
            error=error,
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started,
        ), metadata

    if limit < 1:
        return result(
            ProviderDiscoveryStatus.SKIPPED, error="No remaining route budget"
        )
    if metadata is None:
        if not allow_lookup or metadata_error is not None:
            return result(
                ProviderDiscoveryStatus.SKIPPED,
                error="Metadata lookup disabled or already attempted",
            )
        attempts = 1
        try:
            # Direct work lookup avoids a second agency request; a non-Crossref
            # DOI simply returns NOT_FOUND. The metadata transport bounds time.
            metadata = get_crossref_metadata(normalized_doi, mailto=mailto)
        except MetadataError as exc:
            statuses = (
                (MetadataNotFoundError, ProviderDiscoveryStatus.NOT_FOUND),
                (RateLimitError, ProviderDiscoveryStatus.RATE_LIMITED),
                (MetadataNetworkError, ProviderDiscoveryStatus.NETWORK_ERROR),
                (MetadataParseError, ProviderDiscoveryStatus.PARSE_ERROR),
                (MetadataRequestError, ProviderDiscoveryStatus.REQUEST_ERROR),
                (MetadataServiceError, ProviderDiscoveryStatus.SERVICE_ERROR),
            )
            status = next(
                (status for kind, status in statuses if isinstance(exc, kind)),
                ProviderDiscoveryStatus.ERROR,
            )
            return result(status, error=str(exc))
    if not isinstance(metadata, PaperMetadata):
        return result(ProviderDiscoveryStatus.SKIPPED, error="No resource metadata")
    if normalize_doi(metadata.doi) != normalized_doi:
        return result(
            ProviderDiscoveryStatus.PARSE_ERROR, error="Metadata DOI mismatch"
        )

    excluded = set()
    for url in excluded_urls:
        try:
            excluded.add(normalize_candidate_url(url))
        except (TypeError, ValueError):
            continue
    candidates = tuple(
        candidate
        for candidate in candidates_from_metadata(metadata)
        if candidate.url not in excluded
    )[: min(limit, MAX_SUPPLEMENT_ROUTES)]
    return result(
        ProviderDiscoveryStatus.SUCCESS
        if candidates
        else ProviderDiscoveryStatus.NO_CANDIDATES,
        candidates=candidates,
    )
