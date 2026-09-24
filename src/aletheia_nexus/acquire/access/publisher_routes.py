"""Compatibility facade for publisher route selection.

Publisher-specific rules now live in :mod:`publisher_adapters`.
"""

from aletheia_nexus.acquire.access.publisher_adapters import (
    canonical_pdf_route as canonical_pdf_route,
)


def is_ieee_doi(doi: str) -> bool:
    """Identify IEEE DOI items eligible for the optional local-file fallback."""

    return doi.casefold().startswith("10.1109/")
