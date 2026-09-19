import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url

_REDACTED = "[redacted]"


def _credential_free_netloc(parts) -> str:
    """Rebuild a network location without URL userinfo credentials."""

    hostname = parts.hostname
    if hostname is None:
        return ""
    host = hostname
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    return host if port is None else f"{host}:{port}"


def redact_url_for_record(url: str | None) -> str | None:
    """Return a provenance-safe URL without persisting URL-carried secrets.

    Browser-authenticated and signed PDF URLs can contain short-lived credentials,
    SAML/OAuth state, CDN signatures, access tickets, or other sensitive values.
    AN preserves the route shape while removing URL userinfo, replacing every
    query value, and dropping the fragment.
    """

    if url is None:
        return None
    if not isinstance(url, str):
        raise TypeError("url must be a string or None")

    try:
        parts = urlsplit(url)
    except ValueError:
        return "[unparseable-url]"

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode([(key, _REDACTED) for key, _ in pairs], doseq=True)
    netloc = (
        _credential_free_netloc(parts)
        if parts.username is not None or parts.password is not None
        else parts.netloc
    )
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            parts.path,
            query,
            "",
        )
    )


_LOCAL_HOST_SUFFIXES = (".localhost", ".local")
_AMBIGUOUS_NUMERIC_HOST = re.compile(
    r"^(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*$",
    re.IGNORECASE,
)


def validate_browser_network_url(url: str) -> str:
    """Normalize a browser HTTP(S) target and reject obvious local-network access.

    Browser sessions may legitimately use VPNs, proxies, or institution-managed
    DNS, so this layer deliberately does not require local DNS resolution to match
    the browser's network view. It still rejects embedded credentials, localhost
    names, .local names, and literal non-global IP addresses before browser access.
    """

    normalized = normalize_candidate_url(url)
    parts = urlsplit(normalized)
    hostname = parts.hostname
    if hostname is None:
        raise ValueError("Browser URL must contain a host")

    lowered = hostname.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(_LOCAL_HOST_SUFFIXES):
        raise ValueError(f"Refusing local browser hostname: {hostname}")

    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        # WHATWG/browser URL parsers historically accept several shorthand
        # numeric IPv4 forms that ipaddress intentionally rejects (for example
        # 127.1 or an integer/hex representation). Scholarly publisher routes do
        # not need those ambiguous forms, so fail closed instead of risking an
        # SSRF bypass to localhost/private networks.
        if _AMBIGUOUS_NUMERIC_HOST.fullmatch(lowered):
            raise ValueError("Refusing ambiguous numeric browser hostname")
        return normalized

    if not address.is_global:
        raise ValueError(f"Refusing non-public browser network address: {hostname}")
    return normalized
