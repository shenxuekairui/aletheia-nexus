"""Select narrow publisher hooks while keeping one shared verification engine."""

from __future__ import annotations

from urllib.parse import urlsplit

from .base import PublisherAdapter
from .ieee import IeeeAdapter
from .routes import DoiPdfAdapter, MdpiAdapter, NatureAdapter
from .thieme import ThiemeAdapter

_ADAPTERS: tuple[PublisherAdapter, ...] = (
    IeeeAdapter(),
    ThiemeAdapter(),
    DoiPdfAdapter(
        "acs",
        frozenset({"pubs.acs.org"}),
        doi_prefix="10.1021/",
        canonical_host="pubs.acs.org",
    ),
    DoiPdfAdapter(
        "wiley",
        frozenset({"onlinelibrary.wiley.com"}),
        subdomain_hosts=frozenset({"onlinelibrary.wiley.com"}),
    ),
    DoiPdfAdapter(
        "taylor-francis", frozenset({"tandfonline.com", "www.tandfonline.com"})
    ),
    DoiPdfAdapter(
        "asce",
        frozenset({"ascelibrary.org"}),
        subdomain_hosts=frozenset({"ascelibrary.org"}),
    ),
    NatureAdapter(),
    MdpiAdapter(),
)
_GENERIC = PublisherAdapter()


def adapter_for_url(url: str, *, doi: str | None = None) -> PublisherAdapter:
    """Select a publisher adapter by exact host and, for DOI URLs, DOI prefix."""

    try:
        parts = urlsplit(url)
        if parts.scheme.casefold() != "https" or not parts.hostname:
            return _GENERIC
        if parts.username or parts.password or parts.port not in {None, 443}:
            return _GENERIC
        return next(
            (adapter for adapter in _ADAPTERS if adapter.matches(doi, parts)),
            _GENERIC,
        )
    except ValueError:
        return _GENERIC


def canonical_pdf_route(doi: str, page_url: str) -> tuple[str, str] | None:
    """Return only an unambiguous publisher route; validation remains shared."""

    try:
        parts = urlsplit(page_url)
    except ValueError:
        return None
    adapter = adapter_for_url(page_url, doi=doi)
    return adapter.canonical_pdf_route(doi, parts)
