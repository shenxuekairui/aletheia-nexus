"""Credential-free URLs for persistent provenance, never for network requests."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def redact_url_for_record(url: str | None) -> str | None:
    """Keep route shape, but remove userinfo, query values and challenge tickets."""
    if url is None:
        return None
    if not isinstance(url, str):
        raise TypeError("url must be a string or None")
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return "[unparseable-url]"
    netloc = parts.netloc
    if parts.username is not None or parts.password is not None:
        host = hostname or ""
        host = f"[{host}]" if ":" in host else host
        netloc = host if port is None else f"{host}:{port}"
    query = urlencode(
        [
            (key, "[redacted]")
            for key, _ in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    path = re.sub(
        r"(?i)(/cdn-cgi/challenge-platform)(?:/.*)?$",
        r"\1/[redacted]",
        parts.path,
    )
    path = re.sub(
        r"(?i);(?:jsessionid|phpsessid|sessionid)=[^;/]*",
        ";sessionid=[redacted]",
        path,
    )
    return urlunsplit((parts.scheme, netloc, path, query, ""))
