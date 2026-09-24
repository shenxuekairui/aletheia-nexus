"""Conservative, publisher-owned article-to-PDF candidate routes."""

from __future__ import annotations

import re
from urllib.parse import SplitResult, quote

from .base import PublisherAdapter

_DOI_RESOLVERS = frozenset({"doi.org", "dx.doi.org"})


class DoiPdfAdapter(PublisherAdapter):
    """One publisher using a documented ``/doi/pdf/`` article route."""

    def __init__(
        self,
        name: str,
        hosts: frozenset[str],
        *,
        subdomain_hosts: frozenset[str] = frozenset(),
        doi_prefix: str | None = None,
        canonical_host: str | None = None,
    ) -> None:
        self.name = name
        self.hosts = hosts
        self.subdomain_hosts = subdomain_hosts
        self.doi_prefix = doi_prefix
        self.canonical_host = canonical_host

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        host = (parts.hostname or "").casefold()
        return (
            host in self.hosts
            or any(host.endswith(f".{allowed}") for allowed in self.subdomain_hosts)
            or (
                host in _DOI_RESOLVERS
                and bool(doi)
                and self.doi_prefix is not None
                and doi.casefold().startswith(self.doi_prefix)
            )
        )

    def canonical_pdf_route(
        self, doi: str, parts: SplitResult
    ) -> tuple[str, str] | None:
        host = (parts.hostname or "").casefold()
        if host in _DOI_RESOLVERS:
            if parts.path.rstrip("/").casefold() != f"/{doi}".casefold():
                return None
            host = self.canonical_host or host
        return (
            f"https://{host}/doi/pdf/{quote(doi, safe='/')}",
            "Publisher canonical DOI PDF route",
        )


class NatureAdapter(PublisherAdapter):
    name = "nature"

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        return (parts.hostname or "").casefold() in {"nature.com", "www.nature.com"}

    def canonical_pdf_route(
        self, doi: str, parts: SplitResult
    ) -> tuple[str, str] | None:
        match = re.fullmatch(r"/articles/([A-Za-z0-9._-]+)", parts.path.rstrip("/"))
        if match and doi.casefold() == f"10.1038/{match.group(1)}".casefold():
            return (
                f"https://www.nature.com/articles/{match.group(1)}.pdf",
                "Publisher canonical article PDF route",
            )
        return None


class MdpiAdapter(PublisherAdapter):
    name = "mdpi"

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        return (parts.hostname or "").casefold() in {"mdpi.com", "www.mdpi.com"}

    def canonical_pdf_route(
        self, doi: str, parts: SplitResult
    ) -> tuple[str, str] | None:
        path = parts.path.rstrip("/")
        if re.fullmatch(r"/\d{4}-\d{4}/\d+/\d+/\d+", path):
            return (
                f"https://{parts.netloc}{path}/pdf",
                "Publisher canonical article PDF route",
            )
        return None
