from collections.abc import Mapping

from aletheia_nexus.acquire.discovery.exceptions import (
    DiscoveryConfigurationError,
    DiscoveryParseError,
)
from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.transport import DEFAULT_TIMEOUT, get_json
from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url
from aletheia_nexus.core.identifiers.doi import normalize_doi

UNPAYWALL_API = "https://api.unpaywall.org/v2"

_VERSION_MAP = {
    "publishedVersion": FullTextVersion.PUBLISHED,
    "acceptedVersion": FullTextVersion.ACCEPTED,
    "submittedVersion": FullTextVersion.SUBMITTED,
}

_HOST_MAP = {
    "publisher": HostType.PUBLISHER,
    "repository": HostType.REPOSITORY,
}


def _clean_optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _clean_optional_url(value: object, *, field_name: str) -> str | None:
    text = _clean_optional_text(value)
    if text is None:
        return None

    try:
        return normalize_candidate_url(text)
    except (TypeError, ValueError) as exc:
        raise DiscoveryParseError(
            f"Unpaywall returned an invalid {field_name}"
        ) from exc


def _candidate_from_url(
    *,
    doi: str,
    url: str,
    url_type: CandidateUrlType,
    location: Mapping[str, object],
) -> FullTextCandidate:
    version = _VERSION_MAP.get(
        location.get("version"),
        FullTextVersion.UNKNOWN,
    )
    reported_host = _HOST_MAP.get(
        location.get("host_type"),
        HostType.UNKNOWN,
    )

    return FullTextCandidate(
        doi=doi,
        url=url,
        provenance=(DiscoveryProvider.UNPAYWALL,),
        url_type=url_type,
        access_type=AccessType.OPEN_ACCESS,
        version=version,
        host_type=refine_host_type(url, reported_host),
        license=_clean_optional_text(location.get("license")),
        is_best=location.get("is_best") is True,
    )


def _parse_location(
    doi: str,
    location: Mapping[str, object],
) -> list[FullTextCandidate]:
    candidates: list[FullTextCandidate] = []

    pdf_url = _clean_optional_url(
        location.get("url_for_pdf"),
        field_name="oa_locations.url_for_pdf",
    )
    landing_url = _clean_optional_url(
        location.get("url_for_landing_page"),
        field_name="oa_locations.url_for_landing_page",
    )

    if pdf_url:
        candidates.append(
            _candidate_from_url(
                doi=doi,
                url=pdf_url,
                url_type=CandidateUrlType.PDF,
                location=location,
            )
        )

    if landing_url and landing_url != pdf_url:
        candidates.append(
            _candidate_from_url(
                doi=doi,
                url=landing_url,
                url_type=CandidateUrlType.LANDING_PAGE,
                location=location,
            )
        )

    if not candidates:
        fallback_url = _clean_optional_url(
            location.get("url"),
            field_name="oa_locations.url",
        )
        if fallback_url:
            candidates.append(
                _candidate_from_url(
                    doi=doi,
                    url=fallback_url,
                    url_type=CandidateUrlType.UNKNOWN,
                    location=location,
                )
            )

    return candidates


def discover_unpaywall(
    doi: str,
    *,
    email: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[FullTextCandidate, ...]:
    """Discover open full-text candidates from Unpaywall."""

    normalized_doi = normalize_doi(doi)

    if not isinstance(email, str) or not email.strip():
        raise DiscoveryConfigurationError("Unpaywall requires a non-empty email")

    data = get_json(
        f"{UNPAYWALL_API}/{normalized_doi}",
        context=f"Unpaywall DOI {normalized_doi}",
        params={"email": email.strip()},
        timeout=timeout,
    )

    response_doi = data.get("doi")
    if not isinstance(response_doi, str):
        raise DiscoveryParseError("Unpaywall response is missing DOI identity")

    try:
        response_doi = normalize_doi(response_doi)
    except (TypeError, ValueError) as exc:
        raise DiscoveryParseError("Unpaywall returned an invalid DOI identity") from exc

    if response_doi != normalized_doi:
        raise DiscoveryParseError("Unpaywall returned metadata for a different DOI")

    locations = data.get("oa_locations", [])
    if not isinstance(locations, list):
        raise DiscoveryParseError("Unpaywall returned malformed oa_locations")

    candidates: list[FullTextCandidate] = []

    for location in locations:
        if isinstance(location, Mapping):
            candidates.extend(_parse_location(normalized_doi, location))

    return tuple(candidates)
