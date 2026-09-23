"""Small, auditable publisher access-route rules for the v0.6 layer.

Only documented article-to-PDF routes are derived here. A route is a candidate,
never evidence that the requester has entitlement or that its bytes are valid.
"""

import re
from urllib.parse import quote, urlsplit


def canonical_pdf_route(doi: str, page_url: str) -> tuple[str, str] | None:
    """Return a publisher PDF URL and its provenance label, when unambiguous."""

    try:
        parts = urlsplit(page_url)
        host = (parts.hostname or "").casefold()
        if parts.username or parts.password or parts.port not in {None, 443}:
            return None
    except ValueError:
        return None
    if host in {"pubs.acs.org", "tandfonline.com", "www.tandfonline.com"} or (
        host == "onlinelibrary.wiley.com"
        or host.endswith(".onlinelibrary.wiley.com")
        or host == "ascelibrary.org"
        or host.endswith(".ascelibrary.org")
    ):
        return (
            f"https://{parts.netloc}/doi/pdf/{quote(doi, safe='/')}",
            "Publisher canonical DOI PDF route",
        )

    path = parts.path.rstrip("/")
    if (
        doi.casefold().startswith("10.1021/")
        and host in {"doi.org", "dx.doi.org"}
        and path.casefold() == f"/{doi}".casefold()
    ):
        return (
            f"https://pubs.acs.org/doi/pdf/{quote(doi, safe='/')}",
            "Publisher canonical DOI PDF route",
        )

    if (
        doi.casefold().startswith("10.1055/")
        and host in {"doi.org", "dx.doi.org"}
        and path.casefold() == f"/{doi}".casefold()
    ):
        return (
            f"https://www.thieme-connect.com/products/ejournals/pdf/{quote(doi, safe='/')}.pdf",
            "Publisher canonical DOI PDF route",
        )

    if host in {
        "thieme-connect.com",
        "www.thieme-connect.com",
        "thieme-connect.de",
        "www.thieme-connect.de",
    } and re.fullmatch(
        rf"/products/ejournals/(?:abstract|html|pdf)/{re.escape(doi)}(?:\.pdf)?",
        path,
        flags=re.IGNORECASE,
    ):
        return (
            f"https://{parts.netloc}/products/ejournals/pdf/{quote(doi, safe='/')}.pdf",
            "Publisher canonical article PDF route",
        )

    if host in {"mdpi.com", "www.mdpi.com"} and re.fullmatch(
        r"/\d{4}-\d{4}/\d+/\d+/\d+", path
    ):
        return (
            f"https://{parts.netloc}{path}/pdf",
            "Publisher canonical article PDF route",
        )

    if host in {"nature.com", "www.nature.com"}:
        match = re.fullmatch(r"/articles/([A-Za-z0-9._-]+)", path)
        if match and doi.casefold() == f"10.1038/{match.group(1)}".casefold():
            return (
                f"https://www.nature.com/articles/{match.group(1)}.pdf",
                "Publisher canonical article PDF route",
            )
    return None


def is_ieee_doi(doi: str) -> bool:
    """Identify IEEE DOI items eligible for the optional local-file fallback."""

    return doi.casefold().startswith("10.1109/")
