from urllib.parse import quote

import httpx

from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataNotFoundError,
    MetadataParseError,
    MetadataRequestError,
    MetadataServiceError,
    RateLimitError,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata


CROSSREF_API = "https://api.crossref.org/v1"


def _first(
    value: object,
) -> str | None:
    """Return the first text item from a Crossref list."""

    if value is None:
        return None

    if not isinstance(value, list):
        raise TypeError(
            "Crossref list field must be a list"
        )

    if not value:
        return None

    first = value[0]

    if not isinstance(first, str):
        raise TypeError(
            "Crossref list field must contain strings"
        )

    return first or None


def _author_name(
    author: object,
) -> str:
    """Convert one Crossref author record into a readable name."""

    if not isinstance(author, dict):
        raise TypeError(
            "Crossref author must be an object"
        )

    name = author.get("name")

    if name is not None:
        if not isinstance(name, str):
            raise TypeError(
                "Crossref author name must be a string"
            )

        return name

    given = author.get("given")
    family = author.get("family")

    if given is not None and not isinstance(
        given,
        str,
    ):
        raise TypeError(
            "Crossref author given name must be a string"
        )

    if family is not None and not isinstance(
        family,
        str,
    ):
        raise TypeError(
            "Crossref author family name must be a string"
        )

    return " ".join(
        part
        for part in (
            given,
            family,
        )
        if part
    )


def _authors(
    work: dict,
) -> tuple[str, ...]:
    """Return validated Crossref author names."""

    value = work.get(
        "author",
        [],
    )

    if value is None:
        return ()

    if not isinstance(value, list):
        raise TypeError(
            "Crossref author field must be a list"
        )

    return tuple(
        name
        for author in value
        if (name := _author_name(author))
    )


def _issn(
    work: dict,
) -> tuple[str, ...]:
    """Return validated Crossref ISSN values."""

    value = work.get(
        "ISSN",
        [],
    )

    if value is None:
        return ()

    if not isinstance(value, list):
        raise TypeError(
            "Crossref ISSN must be a list"
        )

    if not all(
        isinstance(item, str)
        for item in value
    ):
        raise TypeError(
            "Crossref ISSN must contain strings"
        )

    return tuple(value)


def _publication_date(
    work: dict,
) -> tuple[str | None, int | None]:
    """Extract the best available publication date."""

    for field in (
        "published",
        "published-online",
        "published-print",
        "issued",
    ):
        date_record = work.get(field)

        if date_record is None:
            continue

        if not isinstance(
            date_record,
            dict,
        ):
            raise TypeError(
                f"Crossref {field} field must be an object"
            )

        date_parts = date_record.get(
            "date-parts"
        )

        if not date_parts:
            continue

        if (
            not isinstance(date_parts, list)
            or not isinstance(
                date_parts[0],
                list,
            )
            or not date_parts[0]
        ):
            raise TypeError(
                f"Crossref {field} date-parts "
                "must contain a non-empty list"
            )

        parts = date_parts[0]

        if not all(
            isinstance(part, int)
            and not isinstance(part, bool)
            for part in parts
        ):
            raise TypeError(
                f"Crossref {field} date-parts "
                "must contain integers"
            )

        year = parts[0]

        date = "-".join(
            (
                str(part)
                if index == 0
                else f"{part:02d}"
            )
            for index, part in enumerate(parts)
        )

        return date, year

    return None, None


def parse_crossref_work(
    work: dict,
) -> PaperMetadata:
    """Convert a Crossref work record into PaperMetadata."""

    if not isinstance(work, dict):
        raise MetadataParseError(
            "Crossref work record must be an object"
        )

    try:
        published_date, year = (
            _publication_date(work)
        )

        return PaperMetadata(
            doi=normalize_doi(
                work["DOI"]
            ),
            title=_first(
                work.get("title")
            ),
            authors=_authors(work),
            journal=_first(
                work.get(
                    "container-title"
                )
            ),
            issn=_issn(work),
            published_date=published_date,
            year=year,
            publisher=work.get(
                "publisher"
            ),
            work_type=work.get(
                "type"
            ),
            volume=work.get(
                "volume"
            ),
            issue=work.get(
                "issue"
            ),
            pages=work.get(
                "page"
            ),
            url=work.get(
                "URL"
            ),
        )

    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
    ) as exc:
        raise MetadataParseError(
            f"Failed to parse Crossref work record: {exc}"
        ) from exc


def get_crossref_metadata(
    doi: str,
    *,
    mailto: str | None = None,
) -> PaperMetadata:
    """Retrieve metadata for one DOI from Crossref."""

    doi = normalize_doi(
        doi
    )

    params = {}

    if mailto:
        params["mailto"] = mailto

    try:
        response = httpx.get(
            (
                f"{CROSSREF_API}/works/"
                f"{quote(doi, safe='')}"
            ),
            params=params,
            headers={
                "User-Agent": (
                    "Aletheia-Nexus/0.3"
                ),
            },
            timeout=10.0,
        )

    except httpx.TimeoutException as exc:
        raise MetadataNetworkError(
            f"Timed out while requesting "
            f"Crossref metadata for DOI: {doi}"
        ) from exc

    except httpx.RequestError as exc:
        raise MetadataNetworkError(
            f"Network error while requesting "
            f"Crossref metadata for DOI: {doi}"
        ) from exc

    if response.status_code == 404:
        raise MetadataNotFoundError(
            f"Crossref metadata not found "
            f"for DOI: {doi}"
        )

    if response.status_code == 429:
        raise RateLimitError(
            f"Crossref rate limit exceeded "
            f"for DOI: {doi}"
        )

    if 400 <= response.status_code < 500:
        raise MetadataRequestError(
            f"Crossref request failed with HTTP "
            f"{response.status_code} "
            f"for DOI: {doi}"
        )

    if 500 <= response.status_code < 600:
        raise MetadataServiceError(
            f"Crossref server error "
            f"{response.status_code} "
            f"for DOI: {doi}"
        )

    try:
        data = response.json()

    except ValueError as exc:
        raise MetadataParseError(
            f"Crossref returned invalid JSON "
            f"for DOI: {doi}"
        ) from exc

    if (
        not isinstance(data, dict)
        or "message" not in data
        or not isinstance(
            data["message"],
            dict,
        )
    ):
        raise MetadataParseError(
            f"Crossref response has invalid "
            f"structure for DOI: {doi}"
        )

    return parse_crossref_work(
        data["message"]
    )