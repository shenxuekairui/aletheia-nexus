"""Thieme route and entitlement-page rules."""

from __future__ import annotations

import re
from urllib.parse import SplitResult, quote

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

from .base import PublisherAdapter

_HOSTS = frozenset(
    {
        "thieme-connect.com",
        "www.thieme-connect.com",
        "thieme-connect.de",
        "www.thieme-connect.de",
    }
)


class ThiemeAdapter(PublisherAdapter):
    name = "thieme"

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        host = (parts.hostname or "").casefold()
        return host in _HOSTS or (
            host in {"doi.org", "dx.doi.org"}
            and bool(doi)
            and doi.casefold().startswith("10.1055/")
        )

    def canonical_pdf_route(
        self, doi: str, parts: SplitResult
    ) -> tuple[str, str] | None:
        host = (parts.hostname or "").casefold()
        path = parts.path.rstrip("/")
        if host in {"doi.org", "dx.doi.org"}:
            if path.casefold() != f"/{doi}".casefold():
                return None
            return (
                f"https://www.thieme-connect.com/products/ejournals/pdf/"
                f"{quote(doi, safe='/')}.pdf",
                "Publisher canonical DOI PDF route",
            )
        if re.fullmatch(
            rf"/products/ejournals/(?:abstract|html|pdf)/{re.escape(doi)}(?:\.pdf)?",
            path,
            flags=re.IGNORECASE,
        ):
            return (
                f"https://{parts.netloc}/products/ejournals/pdf/"
                f"{quote(doi, safe='/')}.pdf",
                "Publisher canonical article PDF route",
            )
        return None

    def refine_non_pdf_challenge(
        self, parts: SplitResult, visible_text: str, report: ChallengeReport
    ) -> ChallengeReport:
        if (
            report.kind == ChallengeKind.NONE
            and "/products/ejournals/abstract/" in parts.path.casefold()
            and "buy article" in visible_text.casefold()
        ):
            return ChallengeReport(
                kind=ChallengeKind.ENTITLEMENT,
                evidence=("Publisher PDF route returned a Buy Article page",),
            )
        return report
