from collections.abc import Mapping

from aletheia_nexus.acquire.discovery.exceptions import DiscoveryParseError
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

OPENALEX_API = "https://api.openalex.org/works"

_VERSION_MAP = {
    "publishedVersion": FullTextVersion.PUBLISHED,
    "acceptedVersion": FullTextVersion.ACCEPTED,
    "submittedVersion": FullTextVersion.SUBMITTED,
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
        raise DiscoveryParseError(f"OpenAlex returned an invalid {field_name}") from exc


def _reported_host_type(location: Mapping[str, object]) -> HostType:
    source = location.get("source")
    if not isinstance(source, Mapping):
        return HostType.UNKNOWN

    source_type = source.get("type")
    if source_type == "repository":
        return HostType.REPOSITORY
    if source_type in {"journal", "conference", "book series", "ebook platform"}:
        return HostType.PUBLISHER
    return HostType.UNKNOWN


def _source_name(location: Mapping[str, object]) -> str | None:
    source = location.get("source")
    if not isinstance(source, Mapping):
        return None
    return _clean_optional_text(source.get("display_name"))


def _location_is_best(
    location: Mapping[str, object],
    best_location: Mapping[str, object] | None,
) -> bool:
    if best_location is None:
        return False

    location_id = _clean_optional_text(location.get("id"))
    best_id = _clean_optional_text(best_location.get("id"))
    if location_id and best_id:
        return location_id == best_id

    for field in ("pdf_url", "landing_page_url"):
        location_url = _clean_optional_url(
            location.get(field),
            field_name=field,
        )
        best_url = _clean_optional_url(
            best_location.get(field),
            field_name=f"best_oa_location.{field}",
        )
        if location_url and location_url == best_url:
            return True

    return False


def _candidate_from_url(
    *,
    doi: str,
    url: str,
    url_type: CandidateUrlType,
    location: Mapping[str, object],
    is_best: bool,
) -> FullTextCandidate:
    version = _VERSION_MAP.get(
        location.get("version"),
        FullTextVersion.UNKNOWN,
    )
    access_type = (
        AccessType.OPEN_ACCESS if location.get("is_oa") is True else AccessType.UNKNOWN
    )
    reported_host = _reported_host_type(location)

    return FullTextCandidate(
        doi=doi,
        url=url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=url_type,
        access_type=access_type,
        version=version,
        host_type=refine_host_type(url, reported_host),
        license=_clean_optional_text(location.get("license")),
        source_name=_source_name(location),
        is_best=is_best,
    )


def _parse_location(
    doi: str,
    location: Mapping[str, object],
    best_location: Mapping[str, object] | None,
) -> list[FullTextCandidate]:
    candidates: list[FullTextCandidate] = []
    is_best = _location_is_best(location, best_location)

    pdf_url = _clean_optional_url(
        location.get("pdf_url"),
        field_name="locations.pdf_url",
    )
    landing_url = _clean_optional_url(
        location.get("landing_page_url"),
        field_name="locations.landing_page_url",
    )

    if pdf_url:
        candidates.append(
            _candidate_from_url(
                doi=doi,
                url=pdf_url,
                url_type=CandidateUrlType.PDF,
                location=location,
                is_best=is_best,
            )
        )

    if landing_url and landing_url != pdf_url:
        candidates.append(
            _candidate_from_url(
                doi=doi,
                url=landing_url,
                url_type=CandidateUrlType.LANDING_PAGE,
                location=location,
                is_best=is_best,
            )
        )

    return candidates


def discover_openalex(
    doi: str,
    *,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[FullTextCandidate, ...]:
    """Discover possible full-text routes from OpenAlex."""

    normalized_doi = normalize_doi(doi)
    params: dict[str, object] = {
        "select": "doi,locations,best_oa_location",
    }

    if api_key:
        params["api_key"] = api_key

    data = get_json(
        f"{OPENALEX_API}/doi:{normalized_doi}",
        context=f"OpenAlex DOI {normalized_doi}",
        params=params,
        timeout=timeout,
    )

    response_doi = data.get("doi")
    if not isinstance(response_doi, str):
        raise DiscoveryParseError("OpenAlex response is missing DOI identity")

    try:
        response_doi = normalize_doi(response_doi)
    except (TypeError, ValueError) as exc:
        raise DiscoveryParseError("OpenAlex returned an invalid DOI identity") from exc

    if response_doi != normalized_doi:
        raise DiscoveryParseError("OpenAlex returned metadata for a different DOI")

    locations = data.get("locations", [])
    if not isinstance(locations, list):
        raise DiscoveryParseError("OpenAlex returned malformed locations")

    raw_best = data.get("best_oa_location")
    best_location = raw_best if isinstance(raw_best, Mapping) else None

    candidates: list[FullTextCandidate] = []

    for location in locations:
        if isinstance(location, Mapping):
            candidates.extend(
                _parse_location(
                    normalized_doi,
                    location,
                    best_location,
                )
            )

    return tuple(candidates)
