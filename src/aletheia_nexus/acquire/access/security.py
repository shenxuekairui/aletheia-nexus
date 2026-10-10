import ipaddress
import re
from urllib.parse import urlsplit

from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url
from aletheia_nexus.core.urls import redact_url_for_record as redact_url_for_record

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
