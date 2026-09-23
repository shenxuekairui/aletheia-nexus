import ipaddress
import socket
from urllib.parse import urlsplit

from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url
from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionNetworkError,
    AcquisitionUnsafeUrlError,
)

_LOCAL_HOST_SUFFIXES = (".localhost", ".local")


def _reject_local_hostname(hostname: str) -> None:
    lowered = hostname.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(_LOCAL_HOST_SUFFIXES):
        raise AcquisitionUnsafeUrlError(f"Refusing local hostname: {hostname}")


def _validate_public_ip(address: str) -> None:
    ip = ipaddress.ip_address(address)
    if not ip.is_global:
        raise AcquisitionUnsafeUrlError(
            f"Refusing non-public network address: {address}"
        )


def validate_safe_url(url: str) -> str:
    """Normalize a candidate URL and reject obvious local-network targets.

    Acquisition follows external provider URLs, so each initial request and
    redirect target is checked before network access. DNS results are also
    inspected so a public-looking hostname cannot silently resolve to loopback,
    private, link-local, multicast, reserved, or otherwise non-global space.
    """

    try:
        normalized = normalize_candidate_url(url)
    except (TypeError, ValueError) as exc:
        raise AcquisitionUnsafeUrlError(str(exc)) from exc

    parts = urlsplit(normalized)
    hostname = parts.hostname
    if hostname is None:
        raise AcquisitionUnsafeUrlError("Candidate URL does not contain a host")

    _reject_local_hostname(hostname)

    try:
        _validate_public_ip(hostname)
        return normalized
    except ValueError:
        pass

    port = parts.port or (443 if parts.scheme == "https" else 80)

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise AcquisitionNetworkError(f"Could not resolve host: {hostname}") from exc

    if not addresses:
        raise AcquisitionNetworkError(f"Host resolved to no addresses: {hostname}")

    for address in addresses:
        _validate_public_ip(address)

    return normalized
