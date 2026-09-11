import re


DOI_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    re.IGNORECASE,
)


def normalize_doi(value: str) -> str:
    """Normalize a DOI or DOI URL into a canonical DOI string."""

    value = value.strip()

    value = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^doi:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    match = DOI_PATTERN.search(value)

    if not match:
        raise ValueError(f"Invalid DOI: {value}")

    return match.group(0).lower()
