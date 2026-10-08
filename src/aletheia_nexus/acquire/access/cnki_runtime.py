"""Bounded CNKI waits and event capture in a caller-owned browser context."""

import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from aletheia_nexus.acquire.access.challenge import classify_access_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.access.security import redact_url_for_record

_LOGGER = logging.getLogger(__name__)


class CNKIStageTimeout(TimeoutError):
    """A named automation stage exhausted its bounded wait."""


class CNKITargetClosed(RuntimeError):
    """The active page/context closed before acquisition completed."""


class CNKIFileError(ValueError):
    """A file-policy failure with a provider-authored, credential-free message."""


class CNKIInteractionRequired(RuntimeError):
    def __init__(self, page, report: ChallengeReport):
        self.page = page
        self.report = report
        super().__init__(report.kind.value)


_CAPTCHA_SELECTORS = (
    ".geetest_slider_button",
    ".geetest_panel",
    ".yidun_slider",
    ".verifybox",
    "iframe[src*='geetest']",
    "iframe[src*='captcha']",
    "iframe[title*='验证']",
)


def first_visible(surface, selectors):
    for selector in selectors:
        try:
            locator = surface.locator(selector)
            for index in range(min(locator.count(), 30)):
                item = locator.nth(index)
                if item.is_visible():
                    return item
        except Exception:
            continue
    return None


def captcha_visible(page) -> bool:
    try:
        current = urlsplit(str(page.url or ""))
        if (
            current.hostname == "kns.cnki.net"
            and current.path.casefold().startswith("/verify/")
        ) or "captchatype=" in current.query.casefold():
            return True
    except (AttributeError, ValueError):
        pass
    if first_visible(page, _CAPTCHA_SELECTORS) is not None:
        return True
    for frame in getattr(page, "frames", ()):
        if frame is getattr(page, "main_frame", None):
            continue
        # Hidden preloaded CAPTCHA frames must not stop a normal article page.
        try:
            if (
                frame.frame_element().is_visible()
                and first_visible(frame, _CAPTCHA_SELECTORS) is not None
            ):
                return True
        except Exception:
            continue
    return False


def challenge_for_page(page) -> ChallengeReport:
    if captcha_visible(page):
        return ChallengeReport(
            kind=ChallengeKind.CAPTCHA,
            evidence=("CNKI slider/CAPTCHA control is visible",),
        )
    try:
        text = page.locator("body").inner_text(timeout=500)[:100_000]
    except Exception:
        text = ""
    try:
        title = page.title()
    except Exception:
        title = ""
    report = classify_access_challenge(
        title=title, url=str(page.url or ""), visible_text=text
    )
    login_form = first_visible(page, ("input[type='password']", ".login-box input"))
    if login_form is None:
        for frame in getattr(page, "frames", ()):
            if frame is getattr(page, "main_frame", None):
                continue
            try:
                if frame.frame_element().is_visible():
                    login_form = first_visible(frame, ("input[type='password']",))
                    if login_form is not None:
                        break
            except Exception:
                continue
    if report.kind == ChallengeKind.NONE and login_form is not None:
        return ChallengeReport(
            kind=ChallengeKind.AUTHENTICATION,
            evidence=("CNKI login form is visible",),
        )
    # CNKI's ordinary navigation advertises institutional login. Only treat
    # login as a gate when the actual form/dialog is visible or this IS a login
    # destination, rather than stopping at an article's persistent navbar.
    if report.kind in {ChallengeKind.AUTHENTICATION, ChallengeKind.SSO}:
        login_form = login_form or first_visible(
            page,
            (
                "input[type='password']",
                "[role='dialog'] input[name*='user' i]",
                ".login-box input",
            ),
        )
        parts = urlsplit(str(page.url or ""))
        login_destination = any(
            term in parts.path.casefold() for term in ("/login", "/signin", "/sso")
        )
        if login_form is None and not login_destination:
            return ChallengeReport(kind=ChallengeKind.NONE)
    return report


class CNKIGate:
    """Observe manual login/CAPTCHA completion; never fill or solve challenges."""

    def __init__(self, config: BrowserAccessConfig):
        self.config = config
        self.history: list[ChallengeReport] = []
        self.interaction_used = False

    def check(self, page) -> bool:
        if page.is_closed():
            raise CNKITargetClosed()
        report = challenge_for_page(page)
        if report.kind == ChallengeKind.NONE:
            return False
        if not self.history or self.history[-1] != report:
            self.history.append(report)
        if report.kind in {ChallengeKind.ENTITLEMENT, ChallengeKind.ACCESS_DENIED}:
            raise CNKIInteractionRequired(page, report)
        if self.config.interaction_callback is not None:
            self.config.interaction_callback(
                report, redact_url_for_record(page.url) or ""
            )
        else:
            _LOGGER.warning(
                "CNKI requires manual %s. Complete verification in the browser; "
                "acquisition will resume when the challenge clears.",
                report.kind.value,
            )
        if not self.config.interactive:
            raise CNKIInteractionRequired(page, report)
        self.interaction_used = True
        deadline = (
            None
            if self.config.wait_for_interaction
            else time.monotonic() + self.config.interaction_timeout
        )
        while True:
            if page.is_closed():
                raise CNKIInteractionRequired(page, report)
            current = challenge_for_page(page)
            if current.kind == ChallengeKind.NONE:
                return True
            if current != report:
                self.history.append(current)
                report = current
            if current.kind in {ChallengeKind.ENTITLEMENT, ChallengeKind.ACCESS_DENIED}:
                raise CNKIInteractionRequired(page, current)
            if deadline is not None and time.monotonic() >= deadline:
                raise CNKIInteractionRequired(page, report)
            try:
                page.wait_for_timeout(self.config.poll_interval * 1000)
            except Exception as exc:
                raise CNKIInteractionRequired(page, report) from exc

    def wait(
        self,
        page,
        predicate,
        *,
        stage: str,
        timeout: float | None = None,
        on_resume=None,
    ):
        """Poll rendered state, giving a cleared challenge a fresh stage budget."""

        budget = self.config.navigation_timeout if timeout is None else timeout
        deadline = time.monotonic() + budget
        while True:
            if self.check(page):
                if on_resume is not None:
                    on_resume()
                deadline = time.monotonic() + budget
            result = predicate()
            if result:
                return result
            if time.monotonic() >= deadline:
                raise CNKIStageTimeout(stage)
            page.wait_for_timeout(
                min(self.config.poll_interval, max(0.01, deadline - time.monotonic()))
                * 1000
            )


@dataclass(frozen=True)
class CapturedPDF:
    url: str
    body: bytes
    status: int
    content_type: str


class CNKIFileCapture:
    """Capture only the detail page and its descendants, including PDF popups."""

    def __init__(self, context, page, max_bytes: int):
        self.context = context
        self.pages = [page]
        self.max_bytes = max_bytes
        self.downloads: list[object] = []
        self.responses: list[object] = []
        self._seen_responses: set[int] = set()
        self._subscriptions: list[tuple[object, str, object]] = []
        self._listen(page, "download", self._on_download)
        self._listen(context, "page", self._on_page)
        self._listen(context, "response", self._on_response)

    def _listen(self, emitter, event, handler):
        emitter.on(event, handler)
        self._subscriptions.append((emitter, event, handler))

    def _on_download(self, download):
        self.downloads.append(download)

    def _on_page(self, page):
        try:
            if page not in self.pages and page.opener() in self.pages:
                self.pages.append(page)
                self._listen(page, "download", self._on_download)
        except Exception:
            pass

    def _on_response(self, response):
        try:
            owner = response.frame.page
            if owner not in self.pages:
                self._on_page(owner)
            if owner not in self.pages:
                return
            content_type = response.headers.get("content-type", "").casefold()
            disposition = response.headers.get("content-disposition", "").casefold()
            path = urlsplit(response.url).path.casefold()
            if "caj" in disposition or path.endswith(".caj"):
                return
            if (
                "application/pdf" in content_type
                or ".pdf" in disposition
                or path.endswith(".pdf")
            ):
                self.responses.append(response)
        except Exception:
            pass

    def next_file(self):
        if self.downloads:
            return self.downloads.pop(0)
        for response in self.responses:
            if id(response) in self._seen_responses:
                continue
            self._seen_responses.add(id(response))
            try:
                length = response.headers.get("content-length")
                if length and int(length) > self.max_bytes:
                    raise CNKIFileError("CNKI PDF exceeds max_bytes")
                body = response.body()
                if len(body) > self.max_bytes:
                    raise CNKIFileError("CNKI PDF exceeds max_bytes")
                if response.status == 200 and body.lstrip().startswith(b"%PDF-"):
                    return CapturedPDF(
                        url=response.url,
                        body=body,
                        status=response.status,
                        content_type=response.headers.get(
                            "content-type", "application/pdf"
                        ),
                    )
            except ValueError:
                raise
            except Exception:
                continue
        return None

    def close(self, *, preserve=None):
        for emitter, event, handler in reversed(self._subscriptions):
            try:
                emitter.remove_listener(event, handler)
            except Exception:
                pass
        for popup in self.pages[1:]:
            try:
                if popup is not preserve and not popup.is_closed():
                    popup.close()
            except Exception:
                pass
