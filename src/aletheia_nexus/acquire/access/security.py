from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_REDACTED = "[redacted]"


def redact_url_for_record(url: str | None) -> str | None:
    """Return a provenance-safe URL without persisting query secrets.

    Browser-authenticated and signed PDF URLs can contain short-lived credentials,
    SAML/OAuth state, CDN signatures, access tickets, or other sensitive values.
    AN preserves the route shape (scheme/host/path and query-key names) while
    replacing every query value and dropping the fragment.
    """

    if url is None:
        return None
    if not isinstance(url, str):
        raise TypeError("url must be a string or None")

    try:
        parts = urlsplit(url)
    except ValueError:
        return url.split("#", 1)[0]

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode([(key, _REDACTED) for key, _ in pairs], doseq=True)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            query,
            "",
        )
    )
