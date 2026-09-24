"""Publisher hooks used by the shared browser engine.

Adapters may identify article routes and interpret visible publisher UI, but
they do not authenticate, bypass access controls, or mark a PDF as verified.
"""

from __future__ import annotations

from urllib.parse import SplitResult

from aletheia_nexus.acquire.access.models import ChallengeReport


class PublisherAdapter:
    name = "generic"

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        return False

    def canonical_pdf_route(
        self, doi: str, parts: SplitResult
    ) -> tuple[str, str] | None:
        return None

    def refine_page_challenge(self, page, report: ChallengeReport) -> ChallengeReport:
        return report

    def prepare_article_controls(self, page) -> None:
        return None

    def click_institution_control(self, page, control_semantics) -> bool:
        return False

    def remembered_institution(self, page, control_semantics) -> bool:
        return False

    def prefer_browser_pdf_navigation(self) -> bool:
        """Avoid a duplicate pre-navigation HTTP request for sensitive PDF routes."""

        return False

    def refine_non_pdf_challenge(
        self, parts: SplitResult, visible_text: str, report: ChallengeReport
    ) -> ChallengeReport:
        return report
