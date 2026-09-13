from enum import StrEnum
from urllib.parse import quote

import httpx

from aletheia_nexus.acquire.metadata.crossref import get_crossref_metadata
from aletheia_nexus.acquire.metadata.datacite import get_datacite_metadata
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
    UnsupportedAgencyError,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata


CROSSREF_API = "https://api.crossref.org/v1"


class DoiAgency(StrEnum):
    """DOI registration agencies supported by Aletheia Nexus."""

    CROSSREF = "crossref"
    DATACITE = "datacite"


def get_doi_agency(
    doi: str,
    *,
    mailto: str | None = None,
) -> DoiAgency:
    """Identify the registration agency responsible for a DOI."""

    doi = normalize_doi(doi)

    params = {}
    if mailto:
        params["mailto"] = mailto

    try:
        response = httpx.get(
            f"{CROSSREF_API}/works/{quote(doi, safe='')}/agency",
            params=params,
            headers={
                "User-Agent": "Aletheia-Nexus/0.3",
            },
            timeout=10.0,
        )

    except httpx.TimeoutException as exc:
        raise MetadataNetworkError(
            f"Timed out while identifying DOI agency: {doi}"
        ) from exc

    except httpx.RequestError as exc:
        raise MetadataNetworkError(
            f"Network error while identifying DOI agency: {doi}"
        ) from exc

    if response.status_code == 404:
        raise MetadataNotFoundError(
            f"DOI registration agency not found: {doi}"
    )

    if response.status_code == 429:
        raise RateLimitError(
            f"Rate limit exceeded while identifying DOI agency: {doi}"
    )

    if 400 <= response.status_code < 500:
        raise MetadataRequestError(
            f"Agency lookup request failed with HTTP {response.status_code} for DOI: {doi}"
    )

    if 500 <= response.status_code < 600:
        raise MetadataServiceError(
            f"Agency lookup server error {response.status_code} for DOI: {doi}"
    )

    try:
        data = response.json()
    except ValueError as exc:
        raise MetadataParseError(
            f"Agency lookup returned invalid JSON for DOI: {doi}"
        ) from exc

    try:
        agency_id = data["message"]["agency"]["id"]
    except (KeyError, TypeError) as exc:
        raise MetadataParseError(
            f"Agency lookup returned invalid structure for DOI: {doi}"
        ) from exc

    if not isinstance(agency_id, str):
        raise MetadataParseError(
            f"Agency lookup returned invalid agency for DOI: {doi}"
        )

    agency_id = agency_id.lower()

    try:
        return DoiAgency(agency_id)
    except ValueError as exc:
        raise UnsupportedAgencyError(
            f"Unsupported DOI registration agency '{agency_id}' for DOI: {doi}"
        ) from exc


def get_metadata(
    doi: str,
    *,
    mailto: str | None = None,
) -> PaperMetadata:
    """Retrieve metadata from the correct provider for one DOI."""

    doi = normalize_doi(doi)

    agency = get_doi_agency(
        doi,
        mailto=mailto,
    )

    if agency == DoiAgency.CROSSREF:
        return get_crossref_metadata(
            doi,
            mailto=mailto,
        )

    if agency == DoiAgency.DATACITE:
        return get_datacite_metadata(
            doi,
            mailto=mailto,
        )
    raise UnsupportedAgencyError(
        f"Unsupported DOI registration agency for DOI: {doi}"
    )