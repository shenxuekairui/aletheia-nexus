from enum import StrEnum
from urllib.parse import quote

from aletheia_nexus.acquire.metadata.crossref import (
    get_crossref_metadata,
)
from aletheia_nexus.acquire.metadata.datacite import (
    get_datacite_metadata,
)
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataParseError,
    UnsupportedAgencyError,
)
from aletheia_nexus.acquire.metadata.transport import get_json
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

    params = {"mailto": mailto} if mailto else None

    data = get_json(
        (f"{CROSSREF_API}/works/{quote(doi, safe='')}/agency"),
        context=f"DOI agency lookup for {doi}",
        params=params,
        mailto=mailto,
    )

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
            (f"Unsupported DOI registration agency '{agency_id}' for DOI: {doi}")
        ) from exc


def get_metadata(
    doi: str,
    *,
    mailto: str | None = None,
) -> PaperMetadata:
    """Retrieve metadata from the correct provider."""

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

    raise UnsupportedAgencyError(f"Unsupported DOI registration agency for DOI: {doi}")
