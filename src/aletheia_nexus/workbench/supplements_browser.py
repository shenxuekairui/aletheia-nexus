"""Use an explicitly allowed AN session for verified-page SI delivery.

No cookies are copied to another HTTP stack. Existing article tabs are only
observed. Missing official article pages and native downloads use owned tabs;
unresolved challenges are retained for manual action without navigating any
existing authentication tab.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import httpx

from aletheia_nexus.acquire.access.browser import BrowserCapabilityUnavailable
from aletheia_nexus.acquire.access.browser_engine.downloads import CdpDownloadCapture
from aletheia_nexus.acquire.access.browser_engine.observation import bounded_read
from aletheia_nexus.acquire.access.browser_engine.viewer import (
    _PDF_FETCH_SCRIPT,
    NativeViewerDownloadError,
    is_native_pdf_placeholder,
    trigger_pdf_viewer_save,
)
from aletheia_nexus.acquire.access.browser_route import (
    _resolve_page_challenge,
    _resource_from_bytes,
)
from aletheia_nexus.acquire.access.models import ChallengeKind
from aletheia_nexus.acquire.access.security import validate_browser_network_url
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionTooLargeError
from aletheia_nexus.acquire.fulltext.orchestration.route_expansion import (
    _embedded_redirect_target,
    derive_route_expansions,
)
from aletheia_nexus.acquire.fulltext.resolution.identity import validate_page_identity
from aletheia_nexus.acquire.fulltext.resolution.models import (
    ResolutionStatus,
    RetrievedPage,
    RouteResolutionResult,
)
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.core.urls import redact_url_for_record


class SupplementBrowserError(ValueError):
    pass


def _root_request_url(request):
    while request.redirected_from is not None:
        request = request.redirected_from
    return str(httpx.URL(request.url))


def _looks_like_pdf_url(url):
    """Do not navigate a recorded main PDF merely to find its article HTML."""
    path = unquote(urlsplit(url).path).casefold().rstrip("/")
    return path.endswith(".pdf") or bool(re.search(r"/(?:e?pdf)(?:/|$)", path))


class SupplementBrowserTransport:
    def __init__(self, session, *, doi, title=None):
        self.session, self.doi, self.title = session, doi, title
        self.pages = {}
        self.diagnostics = []
        self._owned_pages = []
        self._retained_pages = []

    def close(self):
        """Release only our clear article tabs after every attachment is handled."""
        for page in self._owned_pages:
            if any(page is retained for retained in self._retained_pages):
                continue
            try:
                if not page.is_closed():
                    page.close()
            except Exception as exc:
                self.diagnostics.append(
                    {
                        "status": "BROWSER_ARTICLE_CLEANUP_FAILED",
                        "error_type": type(exc).__name__,
                    }
                )
        self._owned_pages.clear()

    def _remember_page(self, page, requested_url, html, *, transport, http_status=None):
        self.pages[str(page.url)] = page
        self.pages[redact_url_for_record(str(page.url))] = page
        self.pages[requested_url] = page
        return SimpleNamespace(
            requested_url=requested_url,
            final_url=str(page.url),
            text=html,
            size_bytes=len(html.encode("utf-8")),
            http_status=http_status,
            body_truncated=False,
            transport=transport,
        )

    def _confirmed_html(self, page, *, deadline, max_bytes):
        from .supplements import _OFFICIAL_GROUPS, _under

        target = validate_browser_network_url(str(page.url))
        host = (urlsplit(target).hostname or "").casefold()
        if not any(_under(host, d) for group in _OFFICIAL_GROUPS for d in group):
            return None
        html = bounded_read(
            page, "content", timeout=min(max(0.01, deadline - time.monotonic()), 5.0)
        )
        if len(html.encode("utf-8")) > max_bytes:
            return None
        identity = validate_page_identity(
            target_doi=self.doi,
            parsed=parse_html(html),
            expected_title=self.title,
        )
        if identity.metadata_dois != (self.doi,) or not identity.doi_match:
            return None
        return html

    def page_fetch(self, url, *, timeout=30.0, max_bytes=5 * 1024 * 1024):
        from .supplements import _OFFICIAL_GROUPS, _official_link, _under

        url = str(httpx.URL(validate_browser_network_url(url)))
        # Passing this session is an explicit caller decision. Ordinary startup
        # reuses the named profile under its existing lease; never infer CDP.
        try:
            context = self.session._ensure_started()
        except BrowserCapabilityUnavailable as exc:
            diagnostic = getattr(exc, "diagnostic", None)
            self.diagnostics.append(
                {
                    "status": "BROWSER_CONNECTION_UNAVAILABLE",
                    "message": str(exc),
                    **(diagnostic or {"error_type": type(exc).__name__}),
                }
            )
            raise
        self.session.pump_events(0)
        # Route-attempt budgets do not limit the user's existing tab inventory.
        # Prefer the requested URL/family, then newest tabs (canonical publisher
        # URLs may differ completely from the DOI/PDF route we were given).
        pages = list(reversed(context.pages))
        pages.sort(
            key=lambda page: (
                str(page.url) != url,
                not _official_link(url, str(page.url)),
            )
        )
        deadline = time.monotonic() + timeout
        # Leave time to recover a missing page; an inventory of old tabs is not
        # the entire SI source-route budget.
        scan_deadline = min(deadline, time.monotonic() + min(5.0, timeout / 3))
        for page in pages:
            if time.monotonic() >= scan_deadline:
                self.diagnostics.append({"status": "BROWSER_TAB_SCAN_TRUNCATED"})
                break
            if page.is_closed():
                continue
            host = (urlsplit(str(page.url)).hostname or "").casefold()
            if not any(
                _under(host, domain) for group in _OFFICIAL_GROUPS for domain in group
            ):
                continue
            try:
                html = self._confirmed_html(
                    page, deadline=scan_deadline, max_bytes=max_bytes
                )
                if html is None:
                    continue
                return self._remember_page(
                    page, url, html, transport="browser_existing_DOM"
                )
            except Exception as exc:
                self.diagnostics.append(
                    {
                        "status": "BROWSER_OBSERVATION_FAILED",
                        "host": host,
                        "error": type(exc).__name__,
                    }
                )
                continue
        # Main acquisition closes its own successful article tab. Recovery must
        # not depend on a user manually reopening every paper, or download the
        # main again via BrowserSession.acquire.
        host = (urlsplit(url).hostname or "").casefold()
        candidates = []
        if not _looks_like_pdf_url(url) and any(
            _under(host, d) for group in _OFFICIAL_GROUPS for d in group
        ):
            candidates.append(url)
        candidates.append("https://doi.org/" + self.doi)
        return self._open_article_page(
            context,
            list(dict.fromkeys(candidates)),
            requested_url=url,
            deadline=deadline,
            max_bytes=max_bytes,
        )

    def _open_article_page(
        self, context, candidates, *, requested_url, deadline, max_bytes
    ):
        if not callable(getattr(context, "new_page", None)):
            raise SupplementBrowserError("browser_parent_page_not_available")
        pending, visited = list(candidates), set()
        route_limit = min(4, self.session.config.max_source_routes)
        while pending and len(visited) < route_limit and time.monotonic() < deadline:
            candidate = pending.pop(0)
            candidate = validate_browser_network_url(candidate)
            if candidate in visited:
                continue
            visited.add(candidate)
            page = context.new_page()
            self._owned_pages.append(page)
            blocked, pdf_targets = [], []

            def guard(route):
                if (
                    not str(route.request.url)
                    .lower()
                    .startswith(("http://", "https://"))
                ):
                    route.fallback()
                    return
                try:
                    target = validate_browser_network_url(str(route.request.url))
                except (TypeError, ValueError):
                    blocked.append(True)
                    route.abort("blockedbyclient")
                    return
                if (
                    route.request.is_navigation_request()
                    and route.request.frame == page.main_frame
                    and _looks_like_pdf_url(target)
                ):
                    pdf_targets.append(True)
                    route.abort("blockedbyclient")
                    return
                route.fallback()

            try:
                # This also protects explicitly attached contexts where the
                # normal AN-owned context guard is intentionally unavailable.
                page.route("**/*", guard)
                response, error_type = None, None
                try:
                    response = page.goto(
                        candidate,
                        wait_until="domcontentloaded",
                        timeout=min(
                            self.session.config.navigation_timeout,
                            max(0.01, deadline - time.monotonic()),
                        )
                        * 1000,
                    )
                except Exception as exc:
                    error_type = type(exc).__name__
                diagnostic = {
                    "status": "BROWSER_ARTICLE_NAVIGATION",
                    "page": redact_url_for_record(candidate),
                    "http_status": getattr(response, "status", None),
                    "error_type": error_type,
                    "pdf_target_blocked": bool(pdf_targets),
                    "unsafe_request_blocked": bool(blocked),
                }
                self.diagnostics.append(diagnostic)
                if blocked or pdf_targets:
                    continue
                if str(page.url).startswith("about:") or page.is_closed():
                    continue
                validate_browser_network_url(str(page.url))
                report, _, _ = _resolve_page_challenge(
                    page,
                    config=replace(
                        self.session.config,
                        interactive=False,
                        wait_for_interaction=False,
                        interaction_callback=None,
                        interaction_poll_callback=None,
                        auto_challenge_grace=min(
                            self.session.config.auto_challenge_grace,
                            max(0, deadline - time.monotonic()),
                        ),
                    ),
                )
                gate = {
                    "status": "BROWSER_ARTICLE_PAGE",
                    "stage": "si_article_page",
                    "page": redact_url_for_record(str(page.url)),
                    "challenge": report.kind.value,
                    "page_retained": False,
                }
                self.diagnostics.append(gate)
                if report.kind in {
                    ChallengeKind.BOT_CHALLENGE,
                    ChallengeKind.CAPTCHA,
                    ChallengeKind.AUTHENTICATION,
                    ChallengeKind.SSO,
                    ChallengeKind.MFA,
                }:
                    self._retained_pages.append(page)
                    gate.update(
                        page_retained=True,
                        needs_manual_check=True,
                        message="正文已保留；查找补充材料的官方文章页需要人工登录或验证。完成后可仅补取 SI。",
                    )
                    raise SupplementBrowserError("attachment_interaction_required")
                if report.kind == ChallengeKind.ACCESS_DENIED:
                    raise SupplementBrowserError("attachment_access_denied")
                if report.kind == ChallengeKind.ENTITLEMENT:
                    raise SupplementBrowserError("attachment_entitlement_required")
                if report.kind != ChallengeKind.NONE:
                    continue
                if response is not None and (
                    response.headers.get("content-type", "").split(";", 1)[0].strip()
                    == "application/pdf"
                ):
                    diagnostic["pdf_document_observed"] = True
                    continue
                html = self._confirmed_html(
                    page, deadline=deadline, max_bytes=max_bytes
                )
                if html is not None:
                    gate["identity"] = "UNIQUE_DOI_CONFIRMED"
                    return self._remember_page(
                        page,
                        requested_url,
                        html,
                        transport="browser_owned_article_DOM",
                        http_status=getattr(response, "status", None),
                    )
                gate["identity"] = "IDENTITY_NOT_CONFIRMED"
                # An official DOI resolver can expose a genuine article route
                # without scholarly metadata of its own. Follow only the core's
                # explicit canonical/refresh/article signals, never arbitrary
                # links, and still require unique DOI metadata at the final page.
                following = self._article_expansions(
                    page,
                    deadline=deadline,
                    max_bytes=max_bytes,
                    http_status=getattr(response, "status", None),
                )
                for target, method in reversed(following):
                    if target not in visited and target not in pending:
                        pending.insert(0, target)
                        self.diagnostics.append(
                            {
                                "status": "BROWSER_ARTICLE_ROUTE_FOLLOWED",
                                "page": redact_url_for_record(str(page.url)),
                                "target": redact_url_for_record(target),
                                "method": method,
                            }
                        )
            except SupplementBrowserError:
                raise
            except Exception as exc:
                self.diagnostics.append(
                    {
                        "status": "BROWSER_ARTICLE_OBSERVATION_FAILED",
                        "error_type": type(exc).__name__,
                    }
                )
            finally:
                # A valid page stays alive through all file_fetch calls. Every
                # rejected clear page can be released immediately.
                remembered = any(value is page for value in self.pages.values())
                retained = any(value is page for value in self._retained_pages)
                if not remembered and not retained and not page.is_closed():
                    page.close()
        raise SupplementBrowserError("browser_parent_page_not_available")

    def _article_expansions(self, page, *, deadline, max_bytes, http_status):
        from .supplements import _OFFICIAL_GROUPS, _official_link, _under

        current = validate_browser_network_url(str(page.url))
        host = (urlsplit(current).hostname or "").casefold()
        if not any(_under(host, d) for group in _OFFICIAL_GROUPS for d in group):
            return []
        html = bounded_read(
            page, "content", timeout=min(5.0, max(0.01, deadline - time.monotonic()))
        )
        if len(html.encode("utf-8")) > max_bytes:
            return []
        identity = validate_page_identity(target_doi=self.doi, parsed=parse_html(html))
        if identity.metadata_dois and identity.metadata_dois != (self.doi,):
            return []
        parent = FullTextCandidate(doi=self.doi, url=current, provenance=())
        resolution = RouteResolutionResult(
            source_candidate=parent,
            status=ResolutionStatus.NO_FILE_CANDIDATES,
            page=RetrievedPage(
                requested_url=current,
                final_url=current,
                http_status=http_status,
                content_type="text/html",
                text=html,
                size_bytes=len(html.encode("utf-8")),
            ),
        )
        output = []
        for item in derive_route_expansions(
            parent=parent, resolution=resolution, max_candidates=4
        ):
            target = validate_browser_network_url(item.candidate.url)
            embedded = _embedded_redirect_target(target)
            if (
                _official_link(current, target)
                and not _looks_like_pdf_url(target)
                and (embedded is None or _official_link(current, embedded))
            ):
                output.append((target, item.method.value))
        return output

    def file_fetch(
        self,
        url,
        *,
        source_page,
        extension,
        output_dir,
        max_bytes,
        timeout,
        diagnostics=None,
    ):
        start = len(self.diagnostics)
        try:
            return self._file_fetch(
                url,
                source_page=source_page,
                extension=extension,
                output_dir=output_dir,
                max_bytes=max_bytes,
                timeout=timeout,
            )
        finally:
            if diagnostics is not None:
                diagnostics.extend(self.diagnostics[start:])

    def _file_fetch(
        self, url, *, source_page, extension, output_dir, max_bytes, timeout
    ):
        from .supplements import _official_link

        url = str(httpx.URL(validate_browser_network_url(url)))
        if not _official_link(source_page, url):
            raise SupplementBrowserError("attachment_host_not_covered")
        if source_page not in self.pages:
            self.page_fetch(source_page, timeout=timeout)
        source = self.pages.get(source_page)
        if source is None:
            raise SupplementBrowserError("browser_parent_page_not_available")
        if extension == ".pdf":
            # Reuse the core viewer's bounded, abortable same-origin byte stream.
            # It uses the browser's own TLS/session and never answers a challenge.
            blocked = []

            def safe_fetch(route):
                if (
                    not str(route.request.url)
                    .lower()
                    .startswith(("http://", "https://"))
                ):
                    route.fallback()
                    return
                try:
                    target = validate_browser_network_url(str(route.request.url))
                except (TypeError, ValueError):
                    blocked.append(True)
                    route.abort("blockedbyclient")
                    return
                if _root_request_url(route.request) == url and not _official_link(
                    source_page, target
                ):
                    blocked.append(True)
                    route.abort("blockedbyclient")
                else:
                    route.fallback()

            source.route("**/*", safe_fetch)
            try:
                fetched = bounded_read(
                    source,
                    "evaluate",
                    _PDF_FETCH_SCRIPT,
                    {
                        "url": url,
                        "maxBytes": max_bytes,
                        "timeoutMs": max(1, int(timeout * 1000)),
                        "cache": "default",
                        "returnBody": True,
                        "diagnostics": True,
                    },
                    timeout=timeout + 2,
                )
            finally:
                source.unroute("**/*", safe_fetch)
            if blocked:
                raise SupplementBrowserError("unsafe_attachment_redirect")
            if isinstance(fetched, dict):
                self.diagnostics.append(
                    {
                        "status": "BROWSER_PDF_FETCH",
                        "http_status": fetched.get("status"),
                        "content_type": fetched.get("contentType"),
                        "reason": fetched.get("reason", "PDF_BYTES_RECEIVED"),
                        "declared_bytes": fetched.get("declaredBytes"),
                        "received_bytes": fetched.get("receivedBytes"),
                        "document_type": fetched.get("documentType"),
                        "error_type": fetched.get("errorType"),
                        "url": redact_url_for_record(fetched.get("url") or url),
                    }
                )
                if fetched.get("reason") in {
                    "DECLARED_SIZE_LIMIT",
                    "STREAM_SIZE_LIMIT",
                }:
                    raise AcquisitionTooLargeError(
                        "Browser attachment exceeds the byte limit"
                    )
            else:
                self.diagnostics.append(
                    {"status": "BROWSER_PDF_FETCH", "reason": "NO_FETCH_DIAGNOSTICS"}
                )
            if fetched and isinstance(fetched.get("bodyBase64"), str):
                final = validate_browser_network_url(fetched["url"])
                if not _official_link(source_page, final):
                    raise SupplementBrowserError("attachment_redirect_host_not_covered")
                body = base64.b64decode(fetched["bodyBase64"], validate=True)
                if len(body) > max_bytes:
                    raise AcquisitionTooLargeError(
                        "Browser attachment exceeds the byte limit"
                    )
                return _resource_from_bytes(
                    candidate=FullTextCandidate(doi=self.doi, url=url, provenance=()),
                    final_url=final,
                    status=fetched.get("status"),
                    content_type="application/pdf",
                    body=body,
                    output_dir=output_dir,
                )
        return self._native_file(
            url,
            source_page=source_page,
            output_dir=output_dir,
            max_bytes=max_bytes,
            timeout=timeout,
        )

    def _native_file(self, url, *, source_page, output_dir, max_bytes, timeout):
        from .supplements import _official_link

        context = self.session._context
        page = context.new_page()
        capture = CdpDownloadCapture(context, output_dir)
        owned_urls, owned_guids, too_large, blocked = {url}, {}, [], []
        owned_frames, cancelled, completed = set(), set(), set()
        pdf_responses, finished_requests, read_responses = [], set(), set()
        viewer_attempted = False
        frame_session = None
        retained = False
        started = time.monotonic()
        navigation_response, navigation_error, navigation_error_code = None, None, None

        def guard(route):
            if not str(route.request.url).lower().startswith(("http://", "https://")):
                route.fallback()
                return
            try:
                target = validate_browser_network_url(str(route.request.url))
            except (TypeError, ValueError):
                blocked.append(True)
                route.abort("blockedbyclient")
                return
            if _root_request_url(route.request) == url:
                if not _official_link(source_page, target):
                    blocked.append(True)
                    route.abort("blockedbyclient")
                    return
                owned_urls.add(target)
            route.fallback()

        def begun(event):
            guid = event.get("guid")
            if (
                event.get("url") in owned_urls
                and event.get("frameId") in owned_frames
                and isinstance(guid, str)
                and re.fullmatch(r"[A-Za-z0-9-]{1,128}", guid)
            ):
                owned_guids[guid] = event["url"]
            elif event.get("url") in owned_urls or event.get("frameId") in owned_frames:
                self.diagnostics.append(
                    {
                        "status": "BROWSER_NATIVE_DOWNLOAD_NOT_CORRELATED",
                        "request_url_matched": event.get("url") in owned_urls,
                        "owned_frame_matched": event.get("frameId") in owned_frames,
                    }
                )

        def progress(event):
            guid = event.get("guid")
            if guid not in owned_guids:
                return
            if event.get("state") in {"completed", "canceled"}:
                completed.add(guid)
            if (
                max(event.get("receivedBytes", 0), event.get("totalBytes", 0))
                > max_bytes
            ):
                too_large.append(True)
                try:
                    capture.session.send(
                        "Browser.cancelDownload",
                        {"guid": event["guid"], **capture._context_params},
                    )
                    cancelled.add(guid)
                except Exception:
                    pass  # The byte-cap failure below still prevents saving it.

        def observed_response(response):
            try:
                if _root_request_url(response.request) == url:
                    self.diagnostics.append(
                        {
                            "status": "NATIVE_ATTACHMENT_RESPONSE",
                            "http_status": response.status,
                            "content_type": response.headers.get("content-type"),
                            "content_length": response.headers.get("content-length"),
                            "url": redact_url_for_record(response.url),
                        }
                    )
                    if (
                        response.status == 200
                        and response.request.frame == page.main_frame
                        and response.headers.get("content-type", "")
                        .split(";", 1)[0]
                        .strip()
                        .lower()
                        == "application/pdf"
                        and _official_link(source_page, str(response.url))
                    ):
                        pdf_responses.append(response)
            except Exception:
                pass

        def request_finished(request):
            try:
                if (
                    request.frame == page.main_frame
                    and _root_request_url(request) == url
                ):
                    finished_requests.add(id(request))
            except Exception:
                pass

        try:
            page.route("**/*", guard)
            page.on("response", observed_response)
            page.on("requestfinished", request_finished)
            if capture.active:
                capture.session.on("Browser.downloadWillBegin", begun)
                capture.session.on("Browser.downloadProgress", progress)
            if not capture.active:
                raise SupplementBrowserError("browser_native_capture_unavailable")
            frame_session = context.new_cdp_session(page)
            frame_session.send("Page.enable")
            tree = frame_session.send("Page.getFrameTree")
            frame_id = tree.get("frameTree", {}).get("frame", {}).get("id")
            if not isinstance(frame_id, str) or not frame_id:
                raise SupplementBrowserError("browser_download_owner_not_confirmed")
            owned_frames.add(frame_id)

            def navigated(event):
                frame = event.get("frame", {})
                if (
                    not frame.get("parentId") or frame.get("parentId") in owned_frames
                ) and isinstance(frame.get("id"), str):
                    owned_frames.add(frame["id"])

            frame_session.on("Page.frameNavigated", navigated)

            def attached(event):
                if event.get("parentFrameId") in owned_frames and isinstance(
                    event.get("frameId"), str
                ):
                    owned_frames.add(event["frameId"])

            frame_session.on("Page.frameAttached", attached)
            try:
                navigation_response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,
                    referer=source_page.split("?", 1)[0].split("#", 1)[0],
                )
            except Exception as exc:
                # Native attachment navigation commonly reports download-started.
                # Only a correlated completed transfer below is accepted.
                navigation_error = type(exc).__name__
                match = re.search(r"net::[A-Z_]+", str(exc))
                navigation_error_code = match.group(0) if match else None
            self.diagnostics.append(
                {
                    "status": "NATIVE_ATTACHMENT_NAVIGATION",
                    "http_status": getattr(navigation_response, "status", None),
                    "error_type": navigation_error,
                    "error_code": navigation_error_code,
                }
            )
            deadline = started + timeout
            if not owned_guids:
                report, _, _ = _resolve_page_challenge(
                    page,
                    config=replace(
                        self.session.config,
                        interactive=False,
                        wait_for_interaction=False,
                        interaction_callback=None,
                        interaction_poll_callback=None,
                        auto_challenge_grace=min(
                            self.session.config.auto_challenge_grace,
                            max(0, deadline - time.monotonic()),
                        ),
                    ),
                )
                try:
                    content_type = bounded_read(
                        page, "evaluate", "document.contentType", timeout=2
                    )
                    title = bounded_read(page, "title", timeout=2)
                except Exception:
                    content_type, title = None, None
                gate = {
                    "status": "NATIVE_ATTACHMENT_PAGE",
                    "challenge": report.kind.value,
                    "content_type": content_type,
                    "title": title[:200] if isinstance(title, str) else None,
                    "url": redact_url_for_record(str(page.url)),
                    "page_retained": False,
                }
                self.diagnostics.append(gate)
                if report.kind in {
                    ChallengeKind.BOT_CHALLENGE,
                    ChallengeKind.CAPTCHA,
                    ChallengeKind.AUTHENTICATION,
                    ChallengeKind.SSO,
                    ChallengeKind.MFA,
                }:
                    retained = True
                    gate.update(
                        page_retained=True,
                        needs_manual_check=True,
                        message="正文已保留；附件地址另需人工登录或验证。请在 AN 浏览器完成后选择仅补取 SI。",
                    )
                    raise SupplementBrowserError("attachment_interaction_required")
                if report.kind == ChallengeKind.ACCESS_DENIED:
                    raise SupplementBrowserError("attachment_access_denied")
                if report.kind == ChallengeKind.ENTITLEMENT:
                    raise SupplementBrowserError("attachment_entitlement_required")
            while time.monotonic() < deadline:
                if blocked:
                    raise SupplementBrowserError("unsafe_attachment_redirect")
                if too_large:
                    raise AcquisitionTooLargeError(
                        "Browser attachment exceeds the byte limit"
                    )
                for response in pdf_responses:
                    if id(response) in read_responses:
                        continue
                    request = response.request
                    if (
                        id(request) not in finished_requests
                        and request.timing.get("responseEnd", -1) < 0
                    ):
                        continue
                    read_responses.add(id(response))
                    resource = self._inline_pdf_response(
                        response,
                        url=url,
                        source_page=source_page,
                        output_dir=output_dir,
                        max_bytes=max_bytes,
                        deadline=deadline,
                    )
                    if resource is not None:
                        return resource
                if pdf_responses and not viewer_attempted:
                    viewer_attempted = True
                    if not owned_guids:
                        resource = self._save_owned_pdf_viewer(
                            page,
                            url=url,
                            expected_urls={
                                str(response.url) for response in pdf_responses
                            },
                            source_page=source_page,
                            output_dir=output_dir,
                            max_bytes=max_bytes,
                            deadline=deadline,
                            capture=capture,
                            owned_frames=owned_frames,
                            owned_guids=owned_guids,
                            blocked=blocked,
                            too_large=too_large,
                        )
                        if resource is not None:
                            return resource
                    resource = self._inline_pdf_viewer(
                        page,
                        url=url,
                        expected_urls={str(response.url) for response in pdf_responses},
                        source_page=source_page,
                        output_dir=output_dir,
                        max_bytes=max_bytes,
                        deadline=deadline,
                    )
                    if resource is not None:
                        return resource
                    if not owned_guids and str(page.url).split("#", 1)[0] in {
                        str(response.url).split("#", 1)[0] for response in pdf_responses
                    }:
                        retained = True
                        self.diagnostics.append(
                            {
                                "status": "BROWSER_PDF_VIEWER_MANUAL_SAVE_REQUIRED",
                                "stage": "si_attachment_file",
                                "page_retained": True,
                                "needs_manual_check": True,
                                "message": "正文已保留；附件已在独立 PDF 阅读页打开，但尚未取得可验证的保存文件。请在保留的附件页人工保存或完成验证后，再明确补取 SI。",
                            }
                        )
                        raise SupplementBrowserError("attachment_interaction_required")
                for guid, observed in tuple(owned_guids.items()):
                    delivery = capture.wait(
                        page, 0.05, expected_url=observed, expected_guid=guid
                    )
                    if delivery:
                        path, final = delivery
                        if path.stat().st_size > max_bytes:
                            raise AcquisitionTooLargeError(
                                "Browser attachment exceeds the byte limit"
                            )
                        body = path.read_bytes()
                        self.diagnostics.append(
                            {
                                "status": "BROWSER_NATIVE_COMPLETED",
                                "received_bytes": len(body),
                                "owned_downloads": len(owned_guids),
                            }
                        )
                        return _resource_from_bytes(
                            candidate=FullTextCandidate(
                                doi=self.doi, url=url, provenance=()
                            ),
                            final_url=final,
                            status=None,
                            content_type=None,
                            body=body,
                            output_dir=output_dir,
                        )
                if not capture.active or page.is_closed():
                    break
                page.wait_for_timeout(100)
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_INCOMPLETE",
                    "owned_downloads": len(owned_guids),
                    "completed_downloads": len(completed),
                    "cancelled_downloads": len(cancelled),
                    "reason": "OWNED_DOWNLOAD_NOT_COMPLETED"
                    if owned_guids
                    else "NO_OWNED_DOWNLOAD_STARTED",
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            if pdf_responses and str(page.url).split("#", 1)[0] in {
                str(response.url).split("#", 1)[0] for response in pdf_responses
            }:
                retained = True
                self.diagnostics.append(
                    {
                        "status": "BROWSER_PDF_VIEWER_MANUAL_SAVE_REQUIRED",
                        "stage": "si_attachment_file",
                        "page_retained": True,
                        "needs_manual_check": True,
                        "message": "附件已打开但未完成保存，需人工操作；已验证正文保留，请检查保留的附件阅读页和下载状态。",
                    }
                )
                raise SupplementBrowserError("attachment_interaction_required")
            raise SupplementBrowserError("browser_attachment_delivery_not_completed")
        finally:
            # Restore browser defaults, but do not delete unrelated transfers the
            # user may have initiated in another tab of this owned AN context.
            if capture.active:
                for guid in owned_guids.keys() - completed - cancelled:
                    try:
                        capture.session.send(
                            "Browser.cancelDownload",
                            {"guid": guid, **capture._context_params},
                        )
                        cancelled.add(guid)
                    except Exception:
                        if guid not in completed:
                            self.diagnostics.append(
                                {
                                    "status": "BROWSER_DOWNLOAD_CANCEL_UNCONFIRMED",
                                    "message": "浏览器未确认取消该附件传输，请检查独立浏览器中的下载状态。",
                                    "download_id": guid,
                                    "staging_directory": str(capture.staging_dir),
                                    "needs_manual_check": True,
                                }
                            )
            capture.close(remove_files=False)
            if frame_session is not None:
                try:
                    frame_session.detach()
                except Exception:
                    pass
            if capture.staging_dir is not None:
                for guid in owned_guids.keys() & (completed | cancelled):
                    if isinstance(guid, str) and re.fullmatch(
                        r"[A-Za-z0-9-]{1,128}", guid
                    ):
                        for name in (guid, guid + ".crdownload"):
                            try:
                                (capture.staging_dir / name).unlink(missing_ok=True)
                            except OSError:
                                pass
            if not retained and not page.is_closed():
                page.close()

    def _inline_pdf_response(
        self, response, *, url, source_page, output_dir, max_bytes, deadline
    ):
        """Read only a completed PDF response already bound to our main frame."""
        from .supplements import _official_link

        final = validate_browser_network_url(str(response.url))
        if not _official_link(source_page, final):
            raise SupplementBrowserError("attachment_redirect_host_not_covered")
        if response.status != 200:
            return None
        declared = response.headers.get("content-length", "")
        try:
            declared = int(declared)
        except (TypeError, ValueError):
            declared = 0
        if declared > max_bytes:
            raise AcquisitionTooLargeError("Browser attachment exceeds the byte limit")
        if declared <= 0:
            # response.body is not a streaming size cap. Unknown-length data
            # uses the core abortable JS stream below, never an unbounded read.
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_PDF_RESPONSE",
                    "reason": "CONTENT_LENGTH_UNAVAILABLE",
                }
            )
            return None
        try:
            body = bounded_read(
                response,
                "body",
                timeout=min(3.0, max(0.01, deadline - time.monotonic())),
            )
        except Exception as exc:
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_PDF_RESPONSE",
                    "reason": "BODY_UNAVAILABLE",
                    "error_type": type(exc).__name__,
                }
            )
            return None
        if len(body) > max_bytes:
            raise AcquisitionTooLargeError("Browser attachment exceeds the byte limit")
        if is_native_pdf_placeholder(body) or b"%PDF-" not in body[:1024]:
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_PDF_RESPONSE",
                    "reason": "VIEWER_PLACEHOLDER_OR_NON_PDF",
                }
            )
            return None
        self.diagnostics.append(
            {
                "status": "BROWSER_NATIVE_PDF_RESPONSE",
                "reason": "PDF_BYTES_RECEIVED",
                "received_bytes": len(body),
                "http_status": response.status,
            }
        )
        return _resource_from_bytes(
            candidate=FullTextCandidate(doi=self.doi, url=url, provenance=()),
            final_url=final,
            status=response.status,
            content_type=response.headers.get("content-type"),
            body=body,
            output_dir=output_dir,
        )

    def _save_owned_pdf_viewer(
        self,
        page,
        *,
        url,
        expected_urls,
        source_page,
        output_dir,
        max_bytes,
        deadline,
        capture,
        owned_frames,
        owned_guids,
        blocked,
        too_large,
    ):
        from .supplements import _official_link

        current = validate_browser_network_url(str(page.url))
        if current.split("#", 1)[0] not in {
            value.split("#", 1)[0] for value in expected_urls
        } or not _official_link(source_page, current):
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None

        def wait_owned_pdf(owner, seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if blocked:
                    raise SupplementBrowserError("unsafe_attachment_redirect")
                if too_large:
                    raise AcquisitionTooLargeError(
                        "Browser attachment exceeds the byte limit"
                    )
                for guid, observed in tuple(owned_guids.items()):
                    delivery = capture.wait(
                        owner, 0.05, expected_url=observed, expected_guid=guid
                    )
                    if delivery is not None:
                        return delivery
                if owner.is_closed():
                    break
                owner.wait_for_timeout(100)
            return None

        try:
            saved = trigger_pdf_viewer_save(
                self.session._context,
                page,
                doi=self.doi,
                expected_title=None,
                output_dir=output_dir,
                timeout=remaining,
                max_bytes=max_bytes,
                owned_page_only=True,
                native_capture=capture,
                owned_frame_ids=owned_frames,
                download_wait=wait_owned_pdf,
            )
        except AcquisitionTooLargeError:
            raise
        except NativeViewerDownloadError as exc:
            if str(exc) == "NativeDownloadSizeLimit":
                raise AcquisitionTooLargeError(
                    "Browser attachment exceeds the byte limit"
                ) from exc
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_VIEWER_SAVE",
                    "reason": str(exc),
                    "owned_page_only": True,
                }
            )
            return None
        except Exception as exc:
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_VIEWER_SAVE",
                    "reason": "SAVE_UNAVAILABLE",
                    "error_type": type(exc).__name__,
                    "owned_page_only": True,
                }
            )
            return None
        if saved is None:
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_VIEWER_SAVE",
                    "reason": "OWNED_SAVE_CONTROL_NOT_CONFIRMED",
                    "owned_page_only": True,
                }
            )
            return None
        path, _ = saved
        if path.stat().st_size > max_bytes:
            raise AcquisitionTooLargeError("Browser attachment exceeds the byte limit")
        body = path.read_bytes()
        self.diagnostics.append(
            {
                "status": "BROWSER_NATIVE_VIEWER_SAVE",
                "reason": "PDF_BYTES_RECEIVED",
                "received_bytes": len(body),
                "owned_page_only": True,
            }
        )
        return _resource_from_bytes(
            candidate=FullTextCandidate(doi=self.doi, url=url, provenance=()),
            final_url=current,
            status=None,
            content_type="application/pdf",
            body=body,
            output_dir=output_dir,
        )

    def _inline_pdf_viewer(
        self, page, *, url, expected_urls, source_page, output_dir, max_bytes, deadline
    ):
        """Use the core bounded stream only on our exact observed PDF document."""
        from .supplements import _official_link

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        current = validate_browser_network_url(str(page.url))
        if current.split("#", 1)[0] not in {
            target.split("#", 1)[0] for target in expected_urls
        } or not _official_link(source_page, current):
            return None
        try:
            fetched = bounded_read(
                page,
                "evaluate",
                _PDF_FETCH_SCRIPT,
                {
                    "url": url,
                    "maxBytes": max_bytes,
                    "timeoutMs": max(1, int(remaining * 1000)),
                    "cache": "force-cache",
                    "returnBody": True,
                    "diagnostics": True,
                },
                timeout=remaining,
            )
        except Exception as exc:
            self.diagnostics.append(
                {
                    "status": "BROWSER_NATIVE_VIEWER_FETCH",
                    "reason": "BODY_UNAVAILABLE",
                    "error_type": type(exc).__name__,
                }
            )
            return None
        if not isinstance(fetched, dict):
            return None
        self.diagnostics.append(
            {
                "status": "BROWSER_NATIVE_VIEWER_FETCH",
                "reason": fetched.get("reason", "PDF_BYTES_RECEIVED"),
                "http_status": fetched.get("status"),
                "received_bytes": fetched.get("receivedBytes"),
            }
        )
        if fetched.get("reason") in {"DECLARED_SIZE_LIMIT", "STREAM_SIZE_LIMIT"}:
            raise AcquisitionTooLargeError("Browser attachment exceeds the byte limit")
        if not isinstance(fetched.get("bodyBase64"), str):
            return None
        final = validate_browser_network_url(fetched["url"])
        if not _official_link(source_page, final):
            raise SupplementBrowserError("attachment_redirect_host_not_covered")
        body = base64.b64decode(fetched["bodyBase64"], validate=True)
        if len(body) > max_bytes:
            raise AcquisitionTooLargeError("Browser attachment exceeds the byte limit")
        if b"%PDF-" not in body[:1024]:
            return None
        return _resource_from_bytes(
            candidate=FullTextCandidate(doi=self.doi, url=url, provenance=()),
            final_url=final,
            status=fetched.get("status"),
            content_type="application/pdf",
            body=body,
            output_dir=output_dir,
        )
