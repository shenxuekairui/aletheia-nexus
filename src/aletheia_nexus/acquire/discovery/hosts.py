from urllib.parse import urlsplit

from aletheia_nexus.acquire.discovery.models import HostType

_RESOLVER_HOSTS = {
    "doi.org",
    "www.doi.org",
    "dx.doi.org",
    "hdl.handle.net",
    "handle.net",
}

_INDEX_HOSTS = {
    "pubmed.ncbi.nlm.nih.gov",
    "doaj.org",
    "www.doaj.org",
}


def refine_host_type(url: str, reported: HostType) -> HostType:
    """Refine provider host metadata when the URL exposes a clearer route type.

    Only a small set of route types proven by real acceptance data is handled
    here. Publisher and repository classification otherwise remains provider-
    reported to avoid maintaining a brittle catalogue of publisher domains.
    """

    parts = urlsplit(url)
    hostname = (parts.hostname or "").lower().rstrip(".")
    path = parts.path.lower()

    if hostname in _RESOLVER_HOSTS:
        return HostType.RESOLVER

    if hostname in _INDEX_HOSTS:
        return HostType.INDEX

    if hostname == "pmc.ncbi.nlm.nih.gov":
        return HostType.REPOSITORY

    if hostname == "www.ncbi.nlm.nih.gov":
        if path.startswith("/pmc/"):
            return HostType.REPOSITORY
        if path.startswith("/pubmed"):
            return HostType.INDEX

    return reported
