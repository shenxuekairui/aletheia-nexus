"""Direct DOI- or title-driven CNKI acquisition, using the local browser."""

from pathlib import Path

from aletheia_nexus.acquire.access.browser import BrowserSession
from aletheia_nexus.acquire.access.cnki_provider import CNKIProvider
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
)
from aletheia_nexus.acquire.fulltext.storage import organized_output
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.organization import destination
from aletheia_nexus.core.paper_request import PaperRequest


def acquire_cnki_pdf(
    *,
    output_dir: str | Path,
    doi: str | None = None,
    title: str | None = None,
    authors: tuple[str, ...] = (),
    journal: str | None = None,
    year: int | None = None,
    volume: str | None = None,
    issue: str | None = None,
    pages: str | None = None,
    cnki_id: str | None = None,
    config: BrowserAccessConfig | None = None,
    browser_session: BrowserSession | None = None,
    metadata_mailto: str | None = None,
    folder: str | None = None,
    filename: str | None = None,
    tags: tuple[str, ...] = (),
) -> BrowserAccessAttempt:
    """Search by title or resolved DOI and validate the downloaded main article.

    DOI-less requests require independent PDF title, author and publication
    evidence. A discovered DOI is recorded, never synthesized or used alone
    to prove that the selected result was the requested paper.
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
    request = PaperRequest(
        doi=normalized_doi or None,
        title=title,
        authors=authors,
        journal=journal,
        year=year,
        volume=volume,
        issue=issue,
        pages=pages,
        cnki_id=cnki_id,
        folder=folder,
        filename=filename,
        tags=tags,
    )
    provider = CNKIProvider(authors=authors, request=request)

    def acquire(session):
        directory = destination(output_dir, request.folder)
        with organized_output(request):
            return session.acquire_provider(
                provider,
                doi=normalized_doi,
                output_dir=directory,
                expected_title=title,
                metadata_mailto=metadata_mailto,
            )

    if browser_session is not None:
        return acquire(browser_session)
    # Default direct acquisition waits for the user instead of destroying the
    # authentication window after an arbitrary timeout. Explicit config wins.
    with BrowserSession(
        config or BrowserAccessConfig(wait_for_interaction=True)
    ) as session:
        return acquire(session)
