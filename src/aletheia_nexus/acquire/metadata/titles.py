"""Resolve title language without weakening the shared PDF identity policy."""

import re


def contains_cjk(value: str | None) -> bool:
    return bool(value and re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def validation_title(requested: str | None, registered: str | None) -> str | None:
    """Use DOI-bound original metadata for a missing or translated CJK title.

    Callers must establish that the metadata belongs to the requested DOI.
    Same-language user constraints are never silently replaced. This does not
    accept a PDF: the original identity and document-role gates still run.
    """
    original = registered.strip() if registered else None
    if not requested:
        return original
    if (
        original
        and contains_cjk(requested)
        and not contains_cjk(original)
        and re.search(r"[A-Za-z]", original)
    ):
        return original
    return requested


def page_validation_title(doi: str, requested: str | None, identity) -> str | None:
    """Accept page metadata only when its sole scholarly DOI matches the target."""
    if (
        identity is not None
        and getattr(identity, "doi_match", False)
        and getattr(identity, "metadata_dois", ()) == (doi,)
    ):
        return validation_title(requested, identity.metadata_title)
    return requested
