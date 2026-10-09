"""Recognize target-specific denial after an institution is already identified."""

import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

from .routes import DoiPdfAdapter


class TaylorFrancisAdapter(DoiPdfAdapter):
    def __init__(self):
        super().__init__(
            "taylor-francis", frozenset({"tandfonline.com", "www.tandfonline.com"})
        )

    def refine_page_challenge(self, page, report: ChallengeReport) -> ChallengeReport:
        if report.kind not in {
            ChallengeKind.NONE,
            ChallengeKind.SSO,
            ChallengeKind.AUTHENTICATION,
            ChallengeKind.ENTITLEMENT,
        }:
            return report
        try:
            parts = urlsplit(str(page.url))
            match = re.fullmatch(r"/doi/(?:abs|full|pdf|epdf)/(.+?)/?", parts.path)
            if not match:
                return report
            doi = unquote(match.group(1)).casefold()
            meta = page.locator("meta[name='citation_doi' i]")
            if (
                meta.count() != 1
                or (meta.get_attribute("content", timeout=2000) or "")
                .casefold()
                .strip()
                != doi
            ):
                return report
            visible = page.locator("body").inner_text(timeout=2000)
            if not re.search(r"access\s+provided\s+by\s+\S", visible, re.IGNORECASE):
                return report
            links = page.locator("a[href*='needAccess' i]")
            for index in range(min(links.count(), 40)):
                link = links.nth(index)
                if not link.is_visible():
                    continue
                target = urlsplit(
                    urljoin(page.url, link.get_attribute("href", timeout=500) or "")
                )
                target_doi = re.fullmatch(
                    r"/doi/(?:full|pdf|epdf)/(.+?)/?", target.path
                )
                if (
                    target.hostname in self.hosts
                    and target_doi
                    and unquote(target_doi.group(1)).casefold() == doi
                    and parse_qs(target.query).get("needAccess") == ["true"]
                    and re.search(r"purchase\s+options|add\s+to\s+cart", visible, re.I)
                ):
                    return ChallengeReport(
                        kind=ChallengeKind.ENTITLEMENT,
                        evidence=(
                            "Target DOI matches publisher article metadata",
                            "Publisher already identifies an institution",
                            "Target full article remains access-gated with purchase options",
                        ),
                    )
        except Exception:
            pass
        return report
