"""IEEE Xplore article chrome and institution-dialog behavior."""

from __future__ import annotations

import re
from urllib.parse import SplitResult

from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport

from .base import PublisherAdapter

_CONTROLS = "a, button, [role='button'], [role='link']"
_DIALOGS = "dialog, [role='dialog'], .js-react-modal"


class IeeeAdapter(PublisherAdapter):
    name = "ieee"

    def matches(self, doi: str | None, parts: SplitResult) -> bool:
        return (parts.hostname or "").casefold() == "ieeexplore.ieee.org"

    def _article(self, page) -> bool:
        try:
            from urllib.parse import urlsplit

            return bool(re.fullmatch(r"/document/\d+/?", urlsplit(str(page.url)).path))
        except Exception:
            return False

    def _access_dialogs(self, page):
        return page.locator(_DIALOGS).filter(
            has_text="Full text access may be available"
        )

    def refine_page_challenge(self, page, report: ChallengeReport) -> ChallengeReport:
        if not self._article(page) or report.kind not in {
            ChallengeKind.SSO,
            ChallengeKind.AUTHENTICATION,
            ChallengeKind.ENTITLEMENT,
        }:
            return report
        try:
            pdf_controls = page.locator("a, button").filter(
                has_text=re.compile(r"\bPDF\b", re.IGNORECASE)
            )
            has_pdf_control = any(
                pdf_controls.nth(index).is_visible()
                for index in range(min(pdf_controls.count(), 20))
            )
            dialogs = self._access_dialogs(page)
            access_dialog_open = any(
                dialogs.nth(index).is_visible()
                for index in range(min(dialogs.count(), 8))
            )
            if has_pdf_control and not access_dialog_open:
                return ChallengeReport(kind=ChallengeKind.NONE)
        except Exception:
            pass
        return report

    def prepare_article_controls(self, page) -> None:
        if not self._article(page):
            return
        try:
            page.wait_for_function(
                """() => Array.from(document.querySelectorAll(
                  'a, button, [role="button"], [role="link"]'
                )).some(element => /\\bpdf\\b/i.test([
                  element.innerText || '',
                  element.getAttribute('aria-label') || ''
                ].join(' ')))""",
                timeout=8000,
            )
        except Exception:
            pass

    def click_institution_control(self, page, control_semantics) -> bool:
        try:
            dialogs = self._access_dialogs(page)
            for dialog_index in range(min(dialogs.count(), 8)):
                dialog = dialogs.nth(dialog_index)
                if not dialog.is_visible():
                    continue
                controls = dialog.locator(_CONTROLS)
                for control_index in range(min(controls.count(), 40)):
                    control = controls.nth(control_index)
                    if not control.is_visible():
                        continue
                    if not re.match(
                        r"^access\s+through\b",
                        control_semantics(control),
                        re.IGNORECASE,
                    ):
                        continue
                    control.click(timeout=5000)
                    return True
        except Exception:
            pass
        return False

    def remembered_institution(self, page, control_semantics) -> bool:
        try:
            dialogs = self._access_dialogs(page)
            for dialog_index in range(min(dialogs.count(), 8)):
                dialog = dialogs.nth(dialog_index)
                if not dialog.is_visible():
                    continue
                controls = dialog.locator(_CONTROLS)
                for control_index in range(min(controls.count(), 40)):
                    control = controls.nth(control_index)
                    if not control.is_visible():
                        continue
                    label = control_semantics(control).casefold()
                    if label.startswith("access through ") and not label.startswith(
                        "access through your institution"
                    ):
                        return True
        except Exception:
            pass
        return False
