"""Derive stable PMC Article Dataset PDF routes from discovered PMC records.

PMC retired its legacy OA Web Service and legacy article files in August 2026.
The supported replacement is the public ``pmc-oa-opendata`` S3 bucket. This
module only activates when another discovery provider has already supplied a
PMC article URL; it does not scrape PMC article pages.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryError,
    DiscoveryNetworkError,
    DiscoveryNotFoundError,
    DiscoveryParseError,
    DiscoveryRateLimitError,
    DiscoveryRequestError,
    DiscoveryServiceError,
)
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    FullTextVersion,
    HostType,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.discovery.ranking import merge_and_rank_candidates
from aletheia_nexus.acquire.discovery.retry import (
    RetryCallError,
    call_with_retry,
    validate_retry_config,
)
from aletheia_nexus.acquire.discovery.transport import get_json, get_text
from aletheia_nexus.core.identifiers.doi import normalize_doi

PMC_BUCKET_HTTPS = "https://pmc-oa-opendata.s3.amazonaws.com"
PMC_CLOUD_SOURCE_NAME = "PubMed Central Article Datasets (AWS)"
_PMC_ID_RE = re.compile(r"(?<![A-Z0-9])PMC(\d+)(?!\d)", re.IGNORECASE)


def _pmc_ids(candidates: tuple[FullTextCandidate, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for candidate in candidates:
        try:
            parts = urlsplit(candidate.url)
        except ValueError:
            continue
        host = (parts.hostname or "").casefold()
        if host not in {
            "pmc.ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
            "ncbi.nlm.nih.gov",
        }:
            continue
        match = _PMC_ID_RE.search(parts.path)
        if match is None:
            match = re.search(r"/pmc/articles/(\d+)(?:/|$)", parts.path, re.I)
        if match is None:
            continue
        pmcid = f"PMC{match.group(1)}"
        if pmcid not in found:
            found.append(pmcid)
    return tuple(found)


def _version_prefixes(pmcid: str, *, timeout: float) -> tuple[str, ...]:
    listing = get_text(
        PMC_BUCKET_HTTPS + "/",
        context=f"PMC Cloud versions for {pmcid}",
        params={"list-type": "2", "prefix": f"{pmcid}.", "delimiter": "/"},
        timeout=timeout,
    )
    try:
        root = ElementTree.fromstring(listing)
    except ElementTree.ParseError as exc:
        raise DiscoveryParseError("PMC Cloud returned an invalid S3 listing") from exc

    prefixes: list[str] = []
    for node in root.findall("{*}CommonPrefixes/{*}Prefix"):
        value = (node.text or "").strip().rstrip("/")
        if re.fullmatch(rf"{re.escape(pmcid)}\.\d+", value, re.I):
            prefixes.append(value)
    if not prefixes:
        raise DiscoveryNotFoundError(f"PMC Cloud has no article version for {pmcid}")
    return tuple(dict.fromkeys(prefixes))


def _https_pdf_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme != "s3" or parts.netloc != "pmc-oa-opendata":
        raise DiscoveryParseError(
            "PMC Cloud metadata returned an unexpected PDF bucket"
        )
    if not parts.path.lower().endswith(".pdf"):
        raise DiscoveryParseError("PMC Cloud metadata returned a non-PDF object")
    return urlunsplit(
        ("https", "pmc-oa-opendata.s3.amazonaws.com", parts.path, parts.query, "")
    )


def _candidate_from_metadata(
    *,
    doi: str,
    prefix: str,
    timeout: float,
) -> FullTextCandidate | None:
    metadata = get_json(
        f"{PMC_BUCKET_HTTPS}/metadata/{prefix}.json",
        context=f"PMC Cloud metadata for {prefix}",
        timeout=timeout,
    )
    metadata_doi = metadata.get("doi")
    if not isinstance(metadata_doi, str):
        raise DiscoveryParseError("PMC Cloud metadata is missing DOI identity")
    try:
        metadata_doi = normalize_doi(metadata_doi)
    except (TypeError, ValueError) as exc:
        raise DiscoveryParseError("PMC Cloud metadata returned an invalid DOI") from exc
    if metadata_doi != doi:
        raise DiscoveryParseError("PMC Cloud metadata returned a different DOI")

    is_open = metadata.get("is_pmc_openaccess") is True
    is_manuscript = metadata.get("is_manuscript") is True
    if not (is_open or is_manuscript) or metadata.get("is_retracted") is True:
        return None
    pdf_url = metadata.get("pdf_url")
    if not isinstance(pdf_url, str) or not pdf_url.strip():
        return None

    return FullTextCandidate(
        doi=doi,
        url=_https_pdf_url(pdf_url),
        provenance=(DiscoveryProvider.PMC_CLOUD,),
        url_type=CandidateUrlType.PDF,
        access_type=AccessType.OPEN_ACCESS,
        version=(
            FullTextVersion.ACCEPTED if is_manuscript else FullTextVersion.PUBLISHED
        ),
        host_type=HostType.REPOSITORY,
        license=(
            metadata.get("license_code")
            if isinstance(metadata.get("license_code"), str)
            else None
        ),
        source_name=PMC_CLOUD_SOURCE_NAME,
        is_best=True,
    )


def _status_for_error(error: DiscoveryError) -> ProviderDiscoveryStatus:
    if isinstance(error, DiscoveryNotFoundError):
        return ProviderDiscoveryStatus.NOT_FOUND
    if isinstance(error, DiscoveryRequestError):
        return ProviderDiscoveryStatus.REQUEST_ERROR
    if isinstance(error, DiscoveryNetworkError):
        return ProviderDiscoveryStatus.NETWORK_ERROR
    if isinstance(error, DiscoveryRateLimitError):
        return ProviderDiscoveryStatus.RATE_LIMITED
    if isinstance(error, DiscoveryServiceError):
        return ProviderDiscoveryStatus.SERVICE_ERROR
    if isinstance(error, DiscoveryParseError):
        return ProviderDiscoveryStatus.PARSE_ERROR
    return ProviderDiscoveryStatus.ERROR


def augment_with_pmc_cloud(
    discovery: DiscoveryResult,
    *,
    timeout: float,
    max_attempts: int = 3,
    backoff_base: float = 0.5,
) -> DiscoveryResult:
    """Add official PMC Cloud PDF candidates for discovered PMC article URLs."""

    validate_retry_config(max_attempts, backoff_base)
    if any(
        provider.provider == DiscoveryProvider.PMC_CLOUD
        for provider in discovery.providers
    ):
        return discovery

    pmcids = _pmc_ids(discovery.candidates)
    if not pmcids:
        return discovery

    started_at = time.perf_counter()
    doi = normalize_doi(discovery.doi)
    candidates: list[FullTextCandidate] = []
    errors: list[DiscoveryError] = []
    attempts = 0

    for pmcid in pmcids:
        try:
            prefixes, used_attempts, _ = call_with_retry(
                lambda pmcid=pmcid: _version_prefixes(pmcid, timeout=timeout),
                max_attempts=max_attempts,
                backoff_base=backoff_base,
            )
            attempts = max(attempts, used_attempts)
        except RetryCallError as exc:
            attempts = max(attempts, exc.attempts)
            errors.append(exc.error)
            continue

        for prefix in prefixes:
            try:
                candidate, used_attempts, _ = call_with_retry(
                    lambda prefix=prefix: _candidate_from_metadata(
                        doi=doi,
                        prefix=prefix,
                        timeout=timeout,
                    ),
                    max_attempts=max_attempts,
                    backoff_base=backoff_base,
                )
                attempts = max(attempts, used_attempts)
            except RetryCallError as exc:
                attempts = max(attempts, exc.attempts)
                errors.append(exc.error)
                continue

            if candidate is not None:
                candidates.append(candidate)

    if errors and not candidates:
        error = errors[0]
        provider = ProviderDiscoveryResult(
            provider=DiscoveryProvider.PMC_CLOUD,
            status=_status_for_error(error),
            candidates=(),
            error=str(error),
            attempts=attempts,
            elapsed_seconds=time.perf_counter() - started_at,
        )
        return replace(discovery, providers=(*discovery.providers, provider))

    error_summary = None
    if errors:
        error_summary = (
            f"Ignored {len(errors)} unusable PMC Cloud record(s); "
            f"first error: {errors[0]}"
        )

    provider = ProviderDiscoveryResult(
        provider=DiscoveryProvider.PMC_CLOUD,
        status=(
            ProviderDiscoveryStatus.SUCCESS
            if candidates
            else ProviderDiscoveryStatus.NO_CANDIDATES
        ),
        candidates=tuple(candidates),
        error=error_summary,
        attempts=attempts,
        elapsed_seconds=time.perf_counter() - started_at,
    )
    return replace(
        discovery,
        candidates=merge_and_rank_candidates([*discovery.candidates, *candidates]),
        providers=(*discovery.providers, provider),
    )
