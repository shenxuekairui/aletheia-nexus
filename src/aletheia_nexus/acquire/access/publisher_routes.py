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


def requires_user_operated_access(doi: str) -> bool:
    """IEEE Xplore disallows bot/agent access; use explicit local-file import."""

    return doi.casefold().startswith("10.1109/")
