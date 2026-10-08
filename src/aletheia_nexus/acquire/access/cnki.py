"""Direct DOI- or title-driven CNKI acquisition, using the local browser."""

from pathlib import Path

from aletheia_nexus.acquire.access.browser import BrowserSession
from aletheia_nexus.acquire.access.cnki_provider import CNKIProvider
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
)
from aletheia_nexus.core.identifiers.doi import normalize_doi


def acquire_cnki_pdf(
    *,
    output_dir: str | Path,
    doi: str | None = None,
    title: str | None = None,
    authors: tuple[str, ...] = (),
    config: BrowserAccessConfig | None = None,
    browser_session: BrowserSession | None = None,
    metadata_mailto: str | None = None,
) -> BrowserAccessAttempt:
    """Search by title or resolved DOI and validate the downloaded main article.

    A title-only request resolves its DOI from the selected article's metadata
    or a unique DOI on the PDF's first page; it never invents an identifier.
    Pass a reusable BrowserSession to retain handoff tabs across calls. When a
    session is supplied, configure that session instead of passing ``config``.
    """

    normalized_doi = normalize_doi(doi) if doi is not None else ""
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string")
    if not normalized_doi and title is None:
        raise ValueError("CNKI acquisition requires a DOI or a title")
    if browser_session is not None and config is not None:
        raise ValueError("Use either config or a configured browser_session")
    provider = CNKIProvider(authors=authors)

    def acquire(session):
        return session.acquire_provider(
            provider,
            doi=normalized_doi,
            output_dir=output_dir,
            expected_title=title,
            metadata_mailto=metadata_mailto,
        )

    if browser_session is not None:
        return acquire(browser_session)
    with BrowserSession(config) as session:
        return acquire(session)
