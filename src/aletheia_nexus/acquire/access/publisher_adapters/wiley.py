"""Wiley's remembered institution activation on its PDF access panel."""

import re

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

from .routes import DoiPdfAdapter

_REMEMBERED = re.compile(
    r"^\s*access\s+through\s+(?!your\s+(?:institution|organi[sz]ation)\b)\S",
    re.IGNORECASE,
)


class WileyAdapter(DoiPdfAdapter):
    def __init__(self):
        super().__init__(
            "wiley",
            frozenset({"onlinelibrary.wiley.com"}),
            subdomain_hosts=frozenset({"onlinelibrary.wiley.com"}),
        )

    def prefer_browser_pdf_navigation(self) -> bool:
        return True

    def prefer_visible_pdf_controls(self) -> bool:
        return True

    def _remembered_control(self, page):
        # The actual label may be a span/div with a delegated click handler.
        # Only use one unambiguous visible remembered entry, not a random IdP.
        matches = page.get_by_text(_REMEMBERED)
        visible = []
        for index in range(min(matches.count(), 40)):
            control = matches.nth(index)
            text = control.inner_text(timeout=2000).strip()
            if len(text) <= 180 and _REMEMBERED.match(text) and control.is_visible():
                visible.append(control)
        return visible[0] if len(visible) == 1 else None

    def remembered_institution(self, page, control_semantics) -> bool:
        try:
            return self._remembered_control(page) is not None
        except Exception:
            return False

    def click_institution_control(self, page, control_semantics) -> bool:
        try:
            control = self._remembered_control(page)
            if control is not None:
                control.click(timeout=5000)
                return True
        except Exception:
            pass
        return False

    def refine_page_challenge(self, page, report: ChallengeReport) -> ChallengeReport:
        if report.kind in {
            ChallengeKind.NONE,
            ChallengeKind.SSO,
            ChallengeKind.AUTHENTICATION,
            ChallengeKind.ENTITLEMENT,
        } and self.remembered_institution(page, None):
            return ChallengeReport(
                kind=ChallengeKind.SSO,
                evidence=("Publisher offers an unambiguous remembered access entry",),
            )
        return report
