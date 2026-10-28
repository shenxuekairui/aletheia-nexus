"""Use an explicitly allowed AN session for verified-page SI delivery.

No cookies are copied to another HTTP stack. Existing article tabs are only
observed; a native download, when needed, uses a temporary owned tab. A missing
or challenged article remains a visible unsupported handoff rather than an
attempt to solve a challenge or navigate the user's authentication tab.
"""

from __future__ import annotations

import base64
import re
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

from aletheia_nexus.acquire.access.browser_engine.downloads import CdpDownloadCapture
from aletheia_nexus.acquire.access.browser_engine.observation import bounded_read
from aletheia_nexus.acquire.access.browser_engine.viewer import _PDF_FETCH_SCRIPT
from aletheia_nexus.acquire.access.browser_route import _resource_from_bytes
from aletheia_nexus.acquire.access.security import validate_browser_network_url
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionTooLargeError
from aletheia_nexus.acquire.fulltext.resolution.identity import validate_page_identity
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.core.urls import redact_url_for_record


class SupplementBrowserError(ValueError):
    pass


def _root_request_url(request):
    while request.redirected_from is not None:
        request = request.redirected_from
    return str(httpx.URL(request.url))


class SupplementBrowserTransport:
    def __init__(self, session, *, doi, title=None):
        self.session, self.doi, self.title = session, doi, title
        self.pages = {}
        self.diagnostics = []

    def page_fetch(self, url, *, timeout=30.0, max_bytes=5 * 1024 * 1024):
        from .supplements import _OFFICIAL_GROUPS, _official_link, _under

        # Passing this session is an explicit caller decision. Ordinary startup
        # reuses the named profile under its existing lease; never infer CDP.
        context = self.session._ensure_started()
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
        for page in pages:
            if time.monotonic() >= deadline:
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
                validate_browser_network_url(str(page.url))
                html = bounded_read(
                    page,
                    "content",
                    timeout=min(max(0.01, deadline - time.monotonic()), 5.0),
                )
                if len(html.encode("utf-8")) > max_bytes:
                    continue
                identity = validate_page_identity(
                    target_doi=self.doi,
                    parsed=parse_html(html),
                    expected_title=self.title,
                )
                if identity.metadata_dois != (self.doi,) or not identity.doi_match:
                    continue
                self.pages[str(page.url)] = page
                self.pages[redact_url_for_record(str(page.url))] = page
                self.pages[url] = page
                return SimpleNamespace(
                    requested_url=url,
                    final_url=str(page.url),
                    text=html,
                    size_bytes=len(html.encode("utf-8")),
                    http_status=None,
                    body_truncated=False,
                    transport="browser_existing_DOM",
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
        raise SupplementBrowserError("browser_parent_page_not_available")

    def file_fetch(
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
                    },
                    timeout=timeout + 2,
                )
            finally:
                source.unroute("**/*", safe_fetch)
            if blocked:
                raise SupplementBrowserError("unsafe_attachment_redirect")
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
                    status=None,
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
        frame_session = None

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

        page.route("**/*", guard)
        if capture.active:
            capture.session.on("Browser.downloadWillBegin", begun)
            capture.session.on("Browser.downloadProgress", progress)
        try:
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
                if not frame.get("parentId") and isinstance(frame.get("id"), str):
                    owned_frames.add(frame["id"])

            frame_session.on("Page.frameNavigated", navigated)
            try:
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout * 1000,
                    referer=source_page.split("?", 1)[0].split("#", 1)[0],
                )
            except Exception:
                # Native attachment navigation commonly reports download-started.
                # Only a correlated completed transfer below is accepted.
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if blocked:
                    raise SupplementBrowserError("unsafe_attachment_redirect")
                if too_large:
                    raise AcquisitionTooLargeError(
                        "Browser attachment exceeds the byte limit"
                    )
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
            if not page.is_closed():
                page.close()
