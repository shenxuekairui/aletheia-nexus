import hashlib
import re
import shutil
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from aletheia_nexus.acquire.access.artifact import finalize_browser_resource
from aletheia_nexus.acquire.access.browser_engine.downloads import (
    CdpDownloadCapture as _CdpDownloadCapture,
)
from aletheia_nexus.acquire.access.browser_engine.downloads import (
    LocalBrowserDownload as _LocalBrowserDownload,
)
from aletheia_nexus.acquire.access.browser_engine.viewer import (
    select_pdf_viewer_target,
    trigger_embedded_pdf_frame_fetch,
    trigger_pdf_viewer_same_origin_fetch,
)
from aletheia_nexus.acquire.access.browser_engine.viewer import (
    trigger_pdf_viewer_save as _trigger_pdf_viewer_save,
)
from aletheia_nexus.acquire.access.challenge import classify_access_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.access.publisher_adapters import adapter_for_url
from aletheia_nexus.acquire.access.publisher_routes import canonical_pdf_route
from aletheia_nexus.acquire.access.security import (
    redact_url_for_record,
    validate_browser_network_url,
)
from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    RedirectHop,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.resolution.derivation import derive_pdf_candidates
from aletheia_nexus.acquire.fulltext.resolution.identity import validate_page_identity
from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.acquire.fulltext.urls import normalize_derived_url

_BROWSER_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SEMANTIC_PDF_CONTROL = re.compile(
    r"(?:download|view|read|open)?\s*(?:full[- ]?text\s*)?(?:article\s*)?pdf",
    re.IGNORECASE,
)
_SEMANTIC_INSTITUTION_CONTROL = re.compile(
    r"(?:access|sign\s*in|log\s*in).{0,50}(?:institution|organization|organisation)"
    r"|access\s+through.{0,50}(?:university|academy|college|library)"
    r"|(?:institutional|organization|organisation).{0,50}(?:access|sign\s*in|login)"
    r"|carsi|shibboleth|openathens|中国科技云通行证|统一身份认证|机构(?:登录|认证|访问)",
    re.IGNORECASE,
)
_INTERACTIVE_CONTROL_SELECTOR = "a, button, [role='button'], [role='link']"
_MODAL_SELECTORS = (".js-react-modal", "dialog, [role='dialog']")
_MODAL_DISMISS_LABELS = frozenset(
    {
        "cancel",
        "close",
        "close button",
        "close dialog",
        "close modal",
        "close window",
        "dismiss",
        "maybe later",
        "no thanks",
        "not now",
    }
)


def _page_snapshot(page) -> tuple[str, str, str, str]:
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        url = page.url
    except Exception:
        url = ""
    try:
        visible_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        visible_text = ""

    # Access state is often exposed only through a control's accessible name or
    # title. Include a bounded
    # projection of those labels in challenge classification without recording
    # form values, cookies, page scripts, or credentials.
    try:
        control_labels = page.evaluate(
            """
            () => Array.from(document.querySelectorAll(
              'a, button, [role="button"], [role="link"]'
            )).slice(0, 200).flatMap((element) => [
              element.innerText || '',
              element.getAttribute('title') || '',
              element.getAttribute('aria-label') || ''
            ]).filter(Boolean).join(' ')
            """
        )
        if isinstance(control_labels, str) and control_labels:
            visible_text = f"{visible_text}\n{control_labels}"
    except Exception:
        pass

    try:
        html = page.content()
    except Exception:
        html = ""
    return title, url, visible_text, html


def _report_for_page(page) -> ChallengeReport:
    title, url, visible_text, html = _page_snapshot(page)
    report = classify_access_challenge(
        title=title,
        url=url,
        visible_text=visible_text,
        html=html,
    )
    return adapter_for_url(url).refine_page_challenge(page, report)


def _wait_for_ieee_article_controls(page) -> None:
    """Compatibility wrapper; article hydration belongs to the adapter."""

    adapter_for_url(str(page.url)).prepare_article_controls(page)


def _append_report(
    history: list[ChallengeReport],
    report: ChallengeReport,
) -> None:
    if not history or history[-1] != report:
        history.append(report)


def _wait_until_challenge_changes(
    page,
    *,
    initial: ChallengeReport,
    seconds: float | None,
    poll_interval: float,
    history: list[ChallengeReport],
) -> ChallengeReport:
    report = initial
    if seconds is not None and seconds <= 0:
        return report
    deadline = None if seconds is None else time.monotonic() + seconds
    while deadline is None or time.monotonic() < deadline:
        try:
            if page.is_closed():
                return report
            wait_seconds = poll_interval
            if deadline is not None:
                wait_seconds = min(
                    poll_interval,
                    max(deadline - time.monotonic(), 0.01),
                )
            page.wait_for_timeout(wait_seconds * 1000)
            report = _report_for_page(page)
        except Exception:
            # A user may close a stuck CAPTCHA/authentication tab or the browser
            # may invalidate the target while Playwright is polling. Preserve the
            # last confirmed challenge instead of replacing useful access state
            # with a generic TargetClosedError at the DOI level.
            return report

        _append_report(history, report)
        if report.kind in {
            ChallengeKind.NONE,
            ChallengeKind.ENTITLEMENT,
            ChallengeKind.ACCESS_DENIED,
        }:
            return report
    return report


def _resolve_page_challenge(
    page,
    *,
    config: BrowserAccessConfig,
) -> tuple[ChallengeReport, tuple[ChallengeReport, ...], bool]:
    """Allow normal browser JS first, then bounded human-in-the-loop recovery."""

    history: list[ChallengeReport] = []
    report = _report_for_page(page)
    _append_report(history, report)

    if report.kind == ChallengeKind.NONE:
        return report, tuple(history), False

    # Browser-native challenges frequently disappear after JavaScript/cookies run.
    report = _wait_until_challenge_changes(
        page,
        initial=report,
        seconds=config.auto_challenge_grace,
        poll_interval=config.poll_interval,
        history=history,
    )
    if report.kind == ChallengeKind.NONE:
        return report, tuple(history), False

    # A hard entitlement/access-denied page is not a prompt to circumvent controls.
    if report.kind in {ChallengeKind.ENTITLEMENT, ChallengeKind.ACCESS_DENIED}:
        return report, tuple(history), False

    if not config.interactive or (
        not config.wait_for_interaction and config.interaction_timeout <= 0
    ):
        return report, tuple(history), False

    # The visible persistent browser is the handoff surface. The user may complete
    # legitimate SSO, MFA, CAPTCHA or other account verification. AN never records
    # credentials or challenge answers; it only observes when the page becomes usable.
    if config.interaction_callback is not None:
        callback_url = redact_url_for_record(page.url) or ""
        config.interaction_callback(report, callback_url)
    report = _wait_until_challenge_changes(
        page,
        initial=report,
        seconds=None if config.wait_for_interaction else config.interaction_timeout,
        poll_interval=config.poll_interval,
        history=history,
    )
    return report, tuple(history), True


def _candidate_for_url(parent: FullTextCandidate, url: str) -> FullTextCandidate:
    normalized = normalize_derived_url(url, base_url=parent.url)
    if normalized is None:
        raise ValueError(f"Browser exposed an unusable HTTP(S) URL: {url!r}")
    safe_url = validate_browser_network_url(normalized)
    return replace(
        parent,
        url=safe_url,
        url_type=CandidateUrlType.PDF,
        host_type=refine_host_type(normalized, parent.host_type),
    )


def _dedupe_candidates(
    candidates: list[FullTextCandidate],
    *,
    limit: int,
) -> tuple[FullTextCandidate, ...]:
    seen: set[str] = set()
    output: list[FullTextCandidate] = []
    for candidate in candidates:
        key = candidate.url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
        if len(output) >= limit:
            break
    return tuple(output)


def _resource_from_bytes(
    *,
    candidate: FullTextCandidate,
    final_url: str,
    status: int,
    content_type: str | None,
    body: bytes,
    output_dir: str | Path,
    redirects: tuple[RedirectHop, ...] = (),
) -> RetrievedResource:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".an-browser-{uuid4().hex}.part"
    temporary.write_bytes(body)
    return RetrievedResource(
        requested_url=candidate.url,
        final_url=final_url,
        http_status=status,
        content_type=content_type,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        local_path=temporary,
        redirects=redirects,
    )


def _safe_context_get(
    context,
    *,
    url: str,
    request_kwargs: dict[str, object],
    max_redirects: int = 10,
) -> tuple[object, tuple[RedirectHop, ...]]:
    """GET through the shared browser cookie jar with safe manual redirects."""

    current = validate_browser_network_url(url)
    redirects: list[RedirectHop] = []

    for _ in range(max_redirects + 1):
        response = context.request.get(
            current,
            max_redirects=0,
            **request_kwargs,
        )
        if response.status not in _BROWSER_REDIRECT_STATUSES:
            return response, tuple(redirects)

        location = response.headers.get("location")
        if not location:
            return response, tuple(redirects)

        next_url = normalize_derived_url(location, base_url=current)
        if next_url is None:
            response.dispose()
            raise ValueError(f"Redirect exposed an unusable URL: {location!r}")
        try:
            safe_next = validate_browser_network_url(next_url)
        except Exception:
            response.dispose()
            raise
        redirects.append(
            RedirectHop(
                from_url=current,
                status_code=response.status,
                location=location,
                to_url=safe_next,
            )
        )
        response.dispose()
        current = safe_next

    raise RuntimeError(
        f"Browser-authenticated request exceeded {max_redirects} redirects"
    )


def _challenge_from_non_pdf_response(response, body: bytes) -> ChallengeReport:
    content_type = (response.headers.get("content-type") or "").lower()
    if "html" not in content_type and b"<html" not in body[:4096].lower():
        return ChallengeReport(kind=ChallengeKind.NONE)
    text = body[:500_000].decode("utf-8", errors="ignore")
    parsed = parse_html(text)
    report = classify_access_challenge(
        title=parsed.title or "",
        url=response.url,
        visible_text=parsed.visible_text,
        html=text,
    )
    return adapter_for_url(response.url).refine_non_pdf_challenge(
        urlsplit(response.url), parsed.visible_text, report
    )


def _safe_referer(source_page_url: str, target_url: str) -> str | None:
    """Return a privacy-preserving Referer for an authenticated PDF request.

    Query strings on SSO/article URLs can contain short-lived credentials.
    Preserve the page path only for same-origin requests; cross-origin requests
    receive origin-only referrer information.
    """

    try:
        source = urlsplit(validate_browser_network_url(source_page_url))
        target = urlsplit(validate_browser_network_url(target_url))
    except (TypeError, ValueError):
        return None

    source_port = source.port or (443 if source.scheme == "https" else 80)
    target_port = target.port or (443 if target.scheme == "https" else 80)
    same_origin = (
        source.scheme == target.scheme
        and source.hostname == target.hostname
        and source_port == target_port
    )

    if same_origin:
        return urlunsplit(
            (
                source.scheme,
                source.netloc,
                source.path or "/",
                "",
                "",
            )
        )
    return urlunsplit((source.scheme, source.netloc, "/", "", ""))


def _request_pdf_candidate(
    context,
    *,
    candidate: FullTextCandidate,
    source_page_url: str | None,
    output_dir: str | Path,
    expected_title: str | None,
    config: BrowserAccessConfig,
) -> tuple[BrowserFileAttempt, ChallengeReport | None]:
    try:
        request_kwargs: dict[str, object] = {
            "timeout": config.request_timeout * 1000,
            "fail_on_status_code": False,
        }
        if source_page_url:
            referer = _safe_referer(source_page_url, candidate.url)
            if referer is not None:
                request_kwargs["headers"] = {"Referer": referer}
        response, redirects = _safe_context_get(
            context,
            url=candidate.url,
            request_kwargs=request_kwargs,
            max_redirects=config.max_request_redirects,
        )
    except Exception as exc:
        return (
            BrowserFileAttempt(
                candidate=candidate,
                source_page_url=source_page_url,
                error=type(exc).__name__,
            ),
            None,
        )

    resource: RetrievedResource | None = None
    try:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > config.max_bytes:
                    return (
                        BrowserFileAttempt(
                            candidate=candidate,
                            source_page_url=source_page_url,
                            error=(
                                "Browser-authenticated response exceeds max_bytes "
                                f"({content_length} > {config.max_bytes})"
                            ),
                        ),
                        None,
                    )
            except ValueError:
                pass

        body = response.body()
        if len(body) > config.max_bytes:
            return (
                BrowserFileAttempt(
                    candidate=candidate,
                    source_page_url=source_page_url,
                    error=(
                        "Browser-authenticated response exceeded max_bytes after "
                        f"download ({len(body)} > {config.max_bytes})"
                    ),
                ),
                None,
            )

        content_type = response.headers.get("content-type")
        pdf_like = b"%PDF-" in body[:1024] or "pdf" in (content_type or "").lower()
        if not pdf_like:
            challenge = _challenge_from_non_pdf_response(response, body)
            return (
                BrowserFileAttempt(
                    candidate=candidate,
                    source_page_url=source_page_url,
                    error=f"Authenticated route returned non-PDF HTTP {response.status}",
                ),
                challenge if challenge.kind != ChallengeKind.NONE else None,
            )

        resource = _resource_from_bytes(
            candidate=candidate,
            final_url=response.url,
            status=response.status,
            content_type=content_type,
            body=body,
            output_dir=output_dir,
            redirects=redirects,
        )
        result = finalize_browser_resource(
            candidate=candidate,
            resource=resource,
            output_dir=output_dir,
            expected_title=expected_title,
            keep_unverified=config.keep_unverified,
            profile_name=config.profile_name,
            source_page_url=source_page_url,
            access_evidence=(
                "Retrieved through Playwright BrowserContext.request",
                "Request shared the persistent browser context cookie jar",
            ),
        )
        return (
            BrowserFileAttempt(
                candidate=candidate,
                result=result,
                source_page_url=source_page_url,
            ),
            None,
        )
    except Exception as exc:
        if resource is not None and resource.local_path is not None:
            resource.local_path.unlink(missing_ok=True)
        return (
            BrowserFileAttempt(
                candidate=candidate,
                source_page_url=source_page_url,
                error=type(exc).__name__,
            ),
            None,
        )
    finally:
        try:
            response.dispose()
        except Exception:
            pass


def _browser_response_to_file_attempt(
    response,
    *,
    parent: FullTextCandidate,
    source_page_url: str | None,
    output_dir: str | Path,
    expected_title: str | None,
    config: BrowserAccessConfig,
) -> BrowserFileAttempt:
    """Validate PDF bytes already returned by the real browser request."""

    resource: RetrievedResource | None = None
    try:
        candidate = _candidate_for_url(parent, response.url)
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > config.max_bytes:
                    return BrowserFileAttempt(
                        candidate=candidate,
                        source_page_url=source_page_url,
                        method="browser_response",
                        error=(
                            "Browser PDF response exceeds max_bytes "
                            f"({content_length} > {config.max_bytes})"
                        ),
                    )
            except ValueError:
                pass

        body = response.body()
        if len(body) > config.max_bytes:
            return BrowserFileAttempt(
                candidate=candidate,
                source_page_url=source_page_url,
                method="browser_response",
                error=(
                    "Browser PDF response exceeded max_bytes "
                    f"({len(body)} > {config.max_bytes})"
                ),
            )

        content_type = response.headers.get("content-type")
        if b"%PDF-" not in body[:1024] and "pdf" not in (content_type or "").lower():
            return BrowserFileAttempt(
                candidate=candidate,
                source_page_url=source_page_url,
                method="browser_response",
                error="Browser response was not PDF-like",
            )

        resource = _resource_from_bytes(
            candidate=candidate,
            final_url=response.url,
            status=response.status,
            content_type=content_type,
            body=body,
            output_dir=output_dir,
        )
        result = finalize_browser_resource(
            candidate=candidate,
            resource=resource,
            output_dir=output_dir,
            expected_title=expected_title,
            keep_unverified=config.keep_unverified,
            profile_name=config.profile_name,
            source_page_url=source_page_url,
            access_evidence=(
                "Captured bytes from an authenticated browser network response",
            ),
        )
        return BrowserFileAttempt(
            candidate=candidate,
            result=result,
            source_page_url=source_page_url,
            method="browser_response",
        )
    except Exception as exc:
        if resource is not None and resource.local_path is not None:
            resource.local_path.unlink(missing_ok=True)
        try:
            candidate = _candidate_for_url(parent, response.url)
        except Exception:
            candidate = replace(
                parent,
                url=getattr(response, "url", parent.url),
                url_type=CandidateUrlType.PDF,
            )
        return BrowserFileAttempt(
            candidate=candidate,
            source_page_url=source_page_url,
            method="browser_response",
            error=type(exc).__name__,
        )


def _download_to_file_attempt(
    download,
    *,
    parent: FullTextCandidate,
    source_page_url: str | None,
    output_dir: str | Path,
    expected_title: str | None,
    config: BrowserAccessConfig,
) -> BrowserFileAttempt:
    download_url = str(getattr(download, "url", "") or "")
    browser_local_url = False
    try:
        candidate = _candidate_for_url(parent, download_url)
        resource_url = download_url
    except ValueError:
        # Browser-generated downloads frequently use blob: URLs. The downloaded
        # bytes are still valuable; retain the HTTP(S) parent route as provenance
        # and let scientific file validation decide whether the artifact is valid.
        candidate = replace(parent, url=parent.url, url_type=CandidateUrlType.PDF)
        resource_url = source_page_url or parent.url
        browser_local_url = True

    temporary: Path | None = None
    try:
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".an-browser-download-{uuid4().hex}.part"
        save_as = getattr(download, "save_as", None)
        if callable(save_as):
            # save_as waits for completion and copies from Chromium before its
            # temporary download is reclaimed. This is more reliable for CDP-
            # attached Edge/Chrome than reading download.path() afterward.
            save_as(str(temporary))
        else:
            source = Path(download.path())
            shutil.copyfile(source, temporary)

        size = temporary.stat().st_size
        if size > config.max_bytes:
            temporary.unlink(missing_ok=True)
            return BrowserFileAttempt(
                candidate=candidate,
                source_page_url=source_page_url,
                method="browser_download",
                error=f"Browser download exceeds max_bytes ({size} > {config.max_bytes})",
            )

        body_hash = hashlib.sha256()
        with temporary.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                body_hash.update(chunk)
        resource = RetrievedResource(
            requested_url=candidate.url,
            final_url=resource_url,
            http_status=200,
            content_type="application/pdf",
            size_bytes=size,
            sha256=body_hash.hexdigest(),
            local_path=temporary,
        )
        evidence = ["Captured a browser download event"]
        if browser_local_url:
            evidence.append(
                "Browser-local download URL was replaced by the parent HTTP(S) route "
                "for provenance"
            )
        result = finalize_browser_resource(
            candidate=candidate,
            resource=resource,
            output_dir=output_dir,
            expected_title=expected_title,
            keep_unverified=config.keep_unverified,
            profile_name=config.profile_name,
            source_page_url=source_page_url,
            access_evidence=tuple(evidence),
        )
        return BrowserFileAttempt(
            candidate=candidate,
            result=result,
            source_page_url=source_page_url,
            method="browser_download",
        )
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        return BrowserFileAttempt(
            candidate=candidate,
            source_page_url=source_page_url,
            method="browser_download",
            error=type(exc).__name__,
        )


def _trigger_pdf_viewer_same_origin_fetch(page, *, max_bytes: int) -> bool:
    return trigger_pdf_viewer_same_origin_fetch(
        page, max_bytes=max_bytes, validate_url=validate_browser_network_url
    )


def _trigger_embedded_pdf_frame_fetch(
    page, *, max_bytes: int
) -> tuple[str, bytes] | None:
    return trigger_embedded_pdf_frame_fetch(
        page, max_bytes=max_bytes, validate_url=validate_browser_network_url
    )


def _select_pdf_viewer_target(
    targets: list[dict[str, object]],
    *,
    doi: str,
    expected_title: str | None,
    page_title: str | None,
    page_url: str,
) -> dict[str, object] | None:
    """Compatibility wrapper for the browser engine's viewer selector."""

    return select_pdf_viewer_target(
        targets,
        doi=doi,
        expected_title=expected_title,
        page_title=page_title,
        page_url=page_url,
    )


def _runtime_publisher_pdf_candidate(
    parent: FullTextCandidate,
    page_url: str,
) -> FullTextCandidate | None:
    """Derive a stable PDF route revealed only after browser navigation."""

    route = canonical_pdf_route(parent.doi, page_url)
    if route is None:
        return None
    url, source_name = route
    return replace(
        _candidate_for_url(parent, url),
        source_name=source_name,
    )


def _control_semantics(item) -> str:
    """Return bounded user-facing semantics for one interactive browser control."""

    values: list[str] = []
    try:
        values.append(item.inner_text())
    except Exception:
        pass

    getter = getattr(item, "get_attribute", None)
    if callable(getter):
        for attribute in ("aria-label", "title", "href"):
            try:
                value = getter(attribute)
            except Exception:
                value = None
            if value:
                values.append(str(value))

    return " ".join(" ".join(value.split()) for value in values if value).strip()[:1000]


def _control_is_inside_modal(item) -> bool:
    try:
        return bool(
            item.evaluate(
                "el => Boolean(el.closest('dialog, [role=\"dialog\"], .js-react-modal'))"
            )
        )
    except Exception:
        return False


def _click_semantic_pdf_control_once(page) -> bool:
    try:
        locator = page.locator(_INTERACTIVE_CONTROL_SELECTOR)
        count = min(locator.count(), 120)
    except Exception:
        return False

    choices: list[tuple[int, int, object]] = []
    for index in range(count):
        item = locator.nth(index)
        text = _control_semantics(item)
        lowered = text.lower()
        if (
            not text
            or _control_is_inside_modal(item)
            or not _SEMANTIC_PDF_CONTROL.search(text)
            or any(
                marker in lowered
                for marker in (
                    "supporting",
                    "supplement",
                    "source data",
                    "peer review",
                    "reporting summary",
                )
            )
        ):
            continue

        score = 0
        if "download" in lowered:
            score += 100
        if "pdf" in lowered:
            score += 20
        if "view" in lowered or "open" in lowered or "read" in lowered:
            score += 10
        choices.append((score, index, item))

    for _, _, item in sorted(choices, key=lambda value: (-value[0], value[1])):
        try:
            item.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def _dismiss_blocking_modal(page) -> bool:
    """Dismiss one visible modal only through an explicit, unambiguous control."""

    for modal_selector in _MODAL_SELECTORS:
        try:
            modals = page.locator(modal_selector)
            modal_count = min(modals.count(), 8)
        except Exception:
            continue

        for modal_index in range(modal_count):
            modal = modals.nth(modal_index)
            try:
                controls = modal.locator(_INTERACTIVE_CONTROL_SELECTOR)
                control_count = min(controls.count(), 40)
            except Exception:
                continue

            for control_index in range(control_count):
                control = controls.nth(control_index)
                try:
                    if not control.is_visible():
                        continue
                except Exception:
                    pass
                labels: list[str] = []
                try:
                    labels.append(control.inner_text())
                except Exception:
                    pass
                getter = getattr(control, "get_attribute", None)
                if callable(getter):
                    for attribute in ("aria-label", "title"):
                        try:
                            value = getter(attribute)
                        except Exception:
                            value = None
                        if value:
                            labels.append(str(value))
                normalized = {
                    " ".join(label.split()).strip().casefold()
                    for label in labels
                    if label and label.strip()
                }
                if not normalized.intersection(_MODAL_DISMISS_LABELS):
                    continue
                try:
                    control.click(timeout=5000)
                    return True
                except Exception:
                    continue
    return False


def _click_semantic_pdf_control(page) -> bool:
    """Click one main-article PDF control, safely clearing an incidental modal."""

    if _click_semantic_pdf_control_once(page):
        return True
    if not _dismiss_blocking_modal(page):
        return False
    try:
        page.wait_for_timeout(350)
    except Exception:
        pass
    return _click_semantic_pdf_control_once(page)


def _click_semantic_institution_control(page) -> bool:
    """Click one explicit institutional-access control as a late fallback."""

    try:
        if adapter_for_url(str(page.url)).click_institution_control(
            page, _control_semantics
        ):
            return True
    except Exception:
        pass

    try:
        locator = page.locator(_INTERACTIVE_CONTROL_SELECTOR)
        count = min(locator.count(), 120)
    except Exception:
        locator = None
        count = 0

    for index in range(count):
        item = locator.nth(index)
        text = _control_semantics(item)
        if not text or not _SEMANTIC_INSTITUTION_CONTROL.search(text):
            continue
        try:
            item.click(timeout=5000)
            return True
        except Exception:
            continue

    # Some modern publisher UIs render the visible access label inside a plain
    # span/div while a React/JavaScript ancestor owns the click behavior. In that
    # case there is no semantic a/button/role node for the first pass to match.
    # Playwright's text locator clicks the rendered text element and lets the
    # browser dispatch/bubble the event normally, without publisher-specific DOM
    # selectors or synthetic credential handling.
    try:
        text_locator = page.get_by_text(_SEMANTIC_INSTITUTION_CONTROL)
        text_count = min(text_locator.count(), 40)
    except Exception:
        return False

    for index in range(text_count):
        item = text_locator.nth(index)
        try:
            text = " ".join(item.inner_text().split())
        except Exception:
            text = ""
        if (
            not text
            or len(text) > 180
            or not _SEMANTIC_INSTITUTION_CONTROL.search(text)
        ):
            continue
        try:
            item.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def _ieee_selected_institution_available(page) -> bool:
    """Compatibility wrapper for the adapter's remembered-institution hook."""

    try:
        return adapter_for_url(str(page.url)).remembered_institution(
            page, _control_semantics
        )
    except Exception:
        pass
    return False


def _resolve_external_auth_page(
    page,
    *,
    source_host: str,
    config: BrowserAccessConfig,
    context=None,
    existing_page_ids: set[int] | None = None,
) -> tuple[ChallengeReport, tuple[ChallengeReport, ...], bool]:
    """Wait for an external IdP to close or return to the publisher.

    IdP transitions often show intermediate pages with no recognizable login
    words. Treating that transient NONE as success causes AN to retry the
    article and bounce the user back to organization selection indefinitely.
    """

    history: list[ChallengeReport] = []
    fallback = ChallengeReport(
        kind=ChallengeKind.SSO,
        evidence=("External institutional authentication page remains open",),
    )

    def observe() -> tuple[ChallengeReport, bool]:
        # Some IdPs leave the original redirect tab open after completing SSO
        # in another tab. A newly opened usable publisher tab is sufficient to
        # retry the article; the normal PDF validation still decides success.
        if context is not None and existing_page_ids is not None:
            try:
                for candidate in context.pages:
                    if candidate is page or id(candidate) in existing_page_ids:
                        continue
                    if candidate.is_closed():
                        continue
                    candidate_host = (urlsplit(candidate.url).hostname or "").lower()
                    if candidate_host != source_host:
                        continue
                    candidate_report = _report_for_page(candidate)
                    if candidate_report.kind == ChallengeKind.NONE:
                        return candidate_report, True
            except Exception:
                pass
        try:
            if page.is_closed():
                return ChallengeReport(kind=ChallengeKind.NONE), True
            current_host = (urlsplit(page.url).hostname or "").lower()
        except Exception:
            return fallback, False
        if not current_host and context is not None:
            # An IdP may finish by leaving its original tab at about:blank and
            # returning the user to a publisher tab that was already open.
            try:
                for candidate in context.pages:
                    if candidate is page or candidate.is_closed():
                        continue
                    candidate_host = (urlsplit(candidate.url).hostname or "").lower()
                    if (
                        candidate_host == source_host
                        and _report_for_page(candidate).kind == ChallengeKind.NONE
                    ):
                        return ChallengeReport(kind=ChallengeKind.NONE), True
            except Exception:
                pass
        report = _report_for_page(page)
        returned = bool(source_host and current_host == source_host)
        if returned:
            return report, report.kind == ChallengeKind.NONE
        if report.kind == ChallengeKind.NONE:
            return fallback, False
        return report, False

    report, completed = observe()
    _append_report(history, report)
    if completed or report.kind in {
        ChallengeKind.ENTITLEMENT,
        ChallengeKind.ACCESS_DENIED,
    }:
        return report, tuple(history), False
    if not config.interactive or (
        not config.wait_for_interaction and config.interaction_timeout <= 0
    ):
        return report, tuple(history), False

    if config.interaction_callback is not None:
        callback_url = redact_url_for_record(getattr(page, "url", "")) or ""
        config.interaction_callback(report, callback_url)

    deadline = (
        None
        if config.wait_for_interaction
        else time.monotonic() + config.interaction_timeout
    )
    while deadline is None or time.monotonic() < deadline:
        wait_seconds = config.poll_interval
        if deadline is not None:
            wait_seconds = min(
                wait_seconds,
                max(deadline - time.monotonic(), 0.01),
            )
        try:
            page.wait_for_timeout(wait_seconds * 1000)
        except Exception:
            try:
                if page.is_closed():
                    cleared = ChallengeReport(kind=ChallengeKind.NONE)
                    _append_report(history, cleared)
                    return cleared, tuple(history), True
            except Exception:
                pass
            return report, tuple(history), True

        report, completed = observe()
        _append_report(history, report)
        if completed or report.kind in {
            ChallengeKind.ENTITLEMENT,
            ChallengeKind.ACCESS_DENIED,
        }:
            return report, tuple(history), True
    return report, tuple(history), True


def _run_institution_handoff(
    context,
    page,
    *,
    config: BrowserAccessConfig,
) -> tuple[bool, tuple[ChallengeReport, ...], bool, ChallengeReport]:
    """Use one explicit institution-access control, then observe legitimate auth."""

    try:
        source_host = (urlsplit(page.url).hostname or "").lower()
    except Exception:
        source_host = ""
    existing_page_ids = {id(open_page) for open_page in context.pages}
    ieee_selected_institution = _ieee_selected_institution_available(page)
    if not _click_semantic_institution_control(page):
        return False, (), False, ChallengeReport(kind=ChallengeKind.NONE)

    try:
        page.wait_for_timeout(5000 if ieee_selected_institution else 1000)
    except Exception:
        pass

    new_pages = [
        popup
        for popup in context.pages
        if id(popup) not in existing_page_ids and popup is not page
    ][:4]
    if ieee_selected_institution and not new_pages:
        try:
            current_host = (urlsplit(page.url).hostname or "").lower()
        except Exception:
            current_host = ""
        if current_host == source_host and _dismiss_blocking_modal(page):
            try:
                page.wait_for_timeout(350)
            except Exception:
                pass
    auth_page = new_pages[-1] if new_pages else page
    preserve_auth_pages = False

    try:
        try:
            auth_page.wait_for_load_state(
                "domcontentloaded",
                timeout=min(config.navigation_timeout, 10.0) * 1000,
            )
        except Exception:
            pass

        try:
            auth_host = (urlsplit(auth_page.url).hostname or "").lower()
        except Exception:
            auth_host = ""
        external_auth_open = auth_page is not page or (
            bool(source_host) and bool(auth_host) and auth_host != source_host
        )
        if external_auth_open:
            report, observed, used = _resolve_external_auth_page(
                auth_page,
                source_host=source_host,
                config=config,
                context=context,
                existing_page_ids=existing_page_ids,
            )
        else:
            report, observed, used = _resolve_page_challenge(
                auth_page,
                config=config,
            )
        auth_page_closed = False
        if auth_page is not page:
            try:
                auth_page_closed = auth_page.is_closed()
            except Exception:
                pass

        if auth_page_closed:
            report = ChallengeReport(kind=ChallengeKind.NONE)
        else:
            # Institutional authentication commonly crosses from a publisher
            # WAYF page to a university or identity-provider domain. Such a
            # page may contain none of our SSO keywords. NONE there means an
            # unknown authentication UI, not that authentication completed.
            if report.kind == ChallengeKind.NONE and external_auth_open:
                report = ChallengeReport(
                    kind=ChallengeKind.SSO,
                    evidence=("Institutional authentication page remains open",),
                )
                observed = (*observed, report)
                used = True

            preserve_auth_pages = report.kind in {
                ChallengeKind.CAPTCHA,
                ChallengeKind.SSO,
            }
        return True, observed, used, report
    finally:
        if not preserve_auth_pages:
            for popup in new_pages:
                try:
                    if not popup.is_closed():
                        popup.close()
                except Exception:
                    pass


def _status_from_challenge(report: ChallengeReport) -> BrowserAttemptStatus:
    if report.kind == ChallengeKind.ENTITLEMENT:
        return BrowserAttemptStatus.ENTITLEMENT_REQUIRED
    if report.kind == ChallengeKind.ACCESS_DENIED:
        return BrowserAttemptStatus.ACCESS_DENIED
    return BrowserAttemptStatus.INTERACTION_REQUIRED


def _install_browser_request_guard(page) -> list[str]:
    """Block obvious local-network HTTP(S) requests made by a browser page."""

    blocked: list[str] = []

    def guard(route) -> None:
        request_url = str(route.request.url)
        if not request_url.lower().startswith(("http://", "https://")):
            route.continue_()
            return
        try:
            validate_browser_network_url(request_url)
        except (TypeError, ValueError):
            safe_url = redact_url_for_record(request_url) or ""
            if safe_url not in blocked:
                blocked.append(safe_url)
            route.abort("blockedbyclient")
            return
        route.continue_()

    page.route("**/*", guard)
    return blocked


def _response_is_pdf_candidate(response) -> bool:
    """Recognize PDF responses even when a publisher uses a generic MIME type."""

    try:
        headers = response.headers
        content_type = (headers.get("content-type") or "").lower()
        disposition = (headers.get("content-disposition") or "").lower()
        path = urlsplit(str(response.url)).path.lower()
        return (
            "application/pdf" in content_type
            or ".pdf" in disposition
            or path.endswith(".pdf")
            or "/pdfdirect/" in path
            or "/doi/pdf/" in path
        )
    except Exception:
        return False


def _process_new_popup_pages(
    context,
    *,
    original_page,
    existing_page_ids: set[int],
    source: FullTextCandidate,
    output_dir: str | Path,
    expected_title: str | None,
    config: BrowserAccessConfig,
    close_pages: bool = True,
) -> tuple[
    list[BrowserFileAttempt],
    list[ChallengeReport],
    bool,
    AcquisitionResult | None,
]:
    """Process a bounded set of pages opened by an explicit PDF control click."""

    file_attempts: list[BrowserFileAttempt] = []
    challenges: list[ChallengeReport] = []
    interaction_used = False
    new_pages = [
        popup
        for popup in context.pages
        if id(popup) not in existing_page_ids and popup is not original_page
    ][:4]

    for popup in new_pages:
        try:
            try:
                popup.wait_for_load_state(
                    "domcontentloaded",
                    timeout=min(config.navigation_timeout, 10.0) * 1000,
                )
            except Exception:
                pass

            report, observed, used = _resolve_page_challenge(
                popup,
                config=config,
            )
            for item in observed:
                _append_report(challenges, item)
            interaction_used = interaction_used or used
            if report.kind != ChallengeKind.NONE:
                continue

            popup_url = str(getattr(popup, "url", "") or "")
            try:
                candidate = _candidate_for_url(source, popup_url)
            except ValueError:
                candidate = None

            if candidate is not None:
                attempt, challenge = _request_pdf_candidate(
                    context,
                    candidate=candidate,
                    source_page_url=popup_url,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=config,
                )
                file_attempts.append(attempt)
                if challenge is not None:
                    _append_report(challenges, challenge)
                if (
                    attempt.result is not None
                    and attempt.result.status == AcquisitionStatus.VERIFIED
                ):
                    return (
                        file_attempts,
                        challenges,
                        interaction_used,
                        attempt.result,
                    )

            # Chromium's built-in PDF plugin can replace Response.body() with a
            # tiny HTML viewer shell while holding the real bytes behind an
            # about:blank application/pdf embed. A same-origin cache fetch
            # makes those entitled bytes observable to the existing context
            # response handler without exporting cookies or signed URLs.
            _trigger_pdf_viewer_same_origin_fetch(
                popup,
                max_bytes=config.max_bytes,
            )

            try:
                html = popup.content()
                parsed = parse_html(html)
                identity = validate_page_identity(
                    target_doi=source.doi,
                    parsed=parsed,
                    expected_title=expected_title,
                )
            except Exception:
                continue

            if identity.status.value == "MISMATCH":
                continue

            try:
                derived = derive_pdf_candidates(
                    parent=source,
                    parsed=parsed,
                    source_page_url=popup_url,
                )
            except Exception:
                derived = ()

            popup_candidates = _dedupe_candidates(
                [item.candidate for item in derived],
                limit=config.max_pdf_candidates,
            )
            for popup_candidate in popup_candidates:
                attempt, challenge = _request_pdf_candidate(
                    context,
                    candidate=popup_candidate,
                    source_page_url=popup_url,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=config,
                )
                file_attempts.append(attempt)
                if challenge is not None:
                    _append_report(challenges, challenge)
                if (
                    attempt.result is not None
                    and attempt.result.status == AcquisitionStatus.VERIFIED
                ):
                    return (
                        file_attempts,
                        challenges,
                        interaction_used,
                        attempt.result,
                    )
        finally:
            if close_pages:
                try:
                    if not popup.is_closed():
                        popup.close()
                except Exception:
                    pass

    return file_attempts, challenges, interaction_used, None


def attempt_browser_route(
    context,
    page,
    *,
    source: FullTextCandidate,
    output_dir: str | Path,
    expected_title: str | None,
    config: BrowserAccessConfig,
    session_blocked_urls: list[str] | None = None,
    session_pdf_responses: list[object] | None = None,
    session_downloads: list[object] | None = None,
    _allow_access_handoff: bool = True,
    _allow_runtime_pdf_handoff: bool = True,
    _navigate_source: bool = True,
    _browser_native_only: bool = False,
) -> BrowserAccessAttempt:
    started_at = time.perf_counter()
    file_attempts: list[BrowserFileAttempt] = []
    challenge_history: list[ChallengeReport] = []
    network_pdf_urls: list[str] = []
    network_pdf_responses: list[object] = []
    network_pdf_response_ids: set[int] = set()
    downloads: list[object] = []
    processed_downloads: set[int] = set()
    browser_response_attempt_count = 0
    interaction_used = False

    blocked_unsafe_urls = (
        session_blocked_urls
        if session_blocked_urls is not None
        else _install_browser_request_guard(page)
    )
    blocked_start = len(blocked_unsafe_urls)
    pdf_cursor = len(session_pdf_responses) if session_pdf_responses is not None else 0
    download_cursor = len(session_downloads) if session_downloads is not None else 0

    def sync_session_events() -> None:
        nonlocal pdf_cursor, download_cursor

        if session_pdf_responses is not None:
            for response in session_pdf_responses[pdf_cursor:]:
                try:
                    url = str(response.url)
                except Exception:
                    continue
                if url not in network_pdf_urls:
                    network_pdf_urls.append(url)
                marker = id(response)
                if marker not in network_pdf_response_ids:
                    network_pdf_response_ids.add(marker)
                    network_pdf_responses.append(response)
            pdf_cursor = len(session_pdf_responses)

        if session_downloads is not None:
            downloads.extend(session_downloads[download_cursor:])
            download_cursor = len(session_downloads)

    def new_blocked_urls() -> tuple[str, ...]:
        return tuple(blocked_unsafe_urls[blocked_start:])

    def process_pending_downloads() -> BrowserFileAttempt | None:
        sync_session_events()
        for download in downloads:
            marker = id(download)
            if marker in processed_downloads:
                continue
            processed_downloads.add(marker)
            attempt = _download_to_file_attempt(
                download,
                parent=source,
                source_page_url=getattr(page, "url", None) or source.url,
                output_dir=output_dir,
                expected_title=expected_title,
                config=config,
            )
            file_attempts.append(attempt)
            if (
                attempt.result is not None
                and attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                return attempt
        return None

    def pending_browser_responses():
        """Yield each live PDF-like response once within the route budget."""

        nonlocal browser_response_attempt_count
        for response in list(network_pdf_responses):
            response_url = getattr(response, "url", "")
            response_id = id(response)
            if not response_url or response_id in seen_browser_response_ids:
                continue
            seen_browser_response_ids.add(response_id)
            if browser_response_attempt_count >= config.max_pdf_candidates:
                continue
            browser_response_attempt_count += 1
            yield response

    def run_institution_handoff_and_retry() -> BrowserAccessAttempt | None:
        nonlocal interaction_used

        if not _allow_access_handoff:
            return None

        (
            access_clicked,
            access_reports,
            access_interaction_used,
            access_final,
        ) = _run_institution_handoff(
            context,
            page,
            config=config,
        )
        if not access_clicked:
            return None

        for report in access_reports:
            _append_report(challenge_history, report)
        interaction_used = interaction_used or access_interaction_used

        if access_final.kind != ChallengeKind.NONE:
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=getattr(page, "url", None) or source.url,
                status=_status_from_challenge(access_final),
                challenge_history=tuple(challenge_history),
                file_attempts=tuple(file_attempts),
                candidates_considered=len(file_attempts),
                interaction_used=interaction_used,
                evidence=access_final.evidence,
                elapsed_seconds=time.perf_counter() - started_at,
            )

        retry = attempt_browser_route(
            context,
            page,
            source=source,
            output_dir=output_dir,
            expected_title=expected_title,
            config=config,
            session_blocked_urls=session_blocked_urls,
            session_pdf_responses=session_pdf_responses,
            session_downloads=session_downloads,
            _allow_access_handoff=False,
            _navigate_source=False,
            _browser_native_only=_browser_native_only,
        )

        merged_history = list(challenge_history)
        for report in retry.challenge_history:
            _append_report(merged_history, report)
        merged_file_attempts = [*file_attempts, *retry.file_attempts]
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=retry.final_url,
            status=retry.status,
            challenge_history=tuple(merged_history),
            file_attempts=tuple(merged_file_attempts),
            candidates_considered=len(merged_file_attempts),
            interaction_used=interaction_used or retry.interaction_used,
            evidence=(
                "Institutional access handoff completed; current browser page resumed",
                *retry.evidence,
            ),
            error=retry.error,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    def on_response(response) -> None:
        try:
            if _response_is_pdf_candidate(response):
                if response.url not in network_pdf_urls:
                    network_pdf_urls.append(response.url)
                marker = id(response)
                if marker in network_pdf_response_ids:
                    return
                network_pdf_response_ids.add(marker)
                network_pdf_responses.append(response)
        except Exception:
            return

    def on_download(download) -> None:
        downloads.append(download)

    if not _browser_native_only:
        page.on("response", on_response)
        page.on("download", on_download)

    # If a persistent session is already authenticated, a direct PDF request can
    # succeed without opening a page at all. External browser handoff deliberately
    # avoids BrowserContext.request because strict WAFs may reject it even when the
    # real tab is already authorized.
    if source.url_type == CandidateUrlType.PDF and not _browser_native_only:
        direct, direct_challenge = _request_pdf_candidate(
            context,
            candidate=source,
            source_page_url=None,
            output_dir=output_dir,
            expected_title=expected_title,
            config=config,
        )
        file_attempts.append(direct)
        if (
            direct.result is not None
            and direct.result.status == AcquisitionStatus.VERIFIED
        ):
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=direct.result.retrieved.final_url
                if direct.result.retrieved
                else source.url,
                status=BrowserAttemptStatus.VERIFIED,
                file_attempts=tuple(file_attempts),
                candidates_considered=1,
                evidence=("Persistent session satisfied direct PDF route",),
                elapsed_seconds=time.perf_counter() - started_at,
            )
        if direct_challenge is not None:
            _append_report(challenge_history, direct_challenge)

    try:
        safe_source_url = validate_browser_network_url(source.url)
    except Exception as exc:
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=None,
            status=BrowserAttemptStatus.UNSAFE_URL,
            challenge_history=tuple(challenge_history),
            file_attempts=tuple(file_attempts),
            candidates_considered=len(file_attempts),
            error=type(exc).__name__,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    # After a successful institutional/human handoff, continue from the page
    # the browser has already reached. Re-navigating the original publisher
    # URL here can discard useful transient state and re-trigger WAF/CAPTCHA.
    navigation_response = None
    if _navigate_source:
        navigation_error: Exception | None = None
        native_download = _CdpDownloadCapture(context, output_dir)
        try:
            navigation_response = page.goto(
                safe_source_url,
                wait_until="domcontentloaded",
                timeout=config.navigation_timeout * 1000,
            )
        except Exception as exc:
            navigation_error = exc

        # Attachment responses can be fully saved by an externally attached
        # Edge instance even when Playwright reports navigation failure or an
        # unusable temporary Download object. Prefer the Browser-domain file,
        # whose completion event is authoritative.
        captured_download = None
        try:
            if native_download.started:
                captured_download = native_download.wait(
                    page,
                    config.request_timeout,
                )
            if captured_download is not None:
                saved_path, download_url = captured_download
                native_attempt = _download_to_file_attempt(
                    _LocalBrowserDownload(saved_path, download_url or safe_source_url),
                    parent=source,
                    source_page_url=getattr(page, "url", None) or source.url,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=config,
                )
                native_attempt = replace(
                    native_attempt,
                    method="cdp_browser_download",
                )
                file_attempts.append(native_attempt)
                if (
                    native_attempt.result is not None
                    and native_attempt.result.status == AcquisitionStatus.VERIFIED
                ):
                    return BrowserAccessAttempt(
                        source_candidate=source,
                        final_url=download_url or safe_source_url,
                        status=BrowserAttemptStatus.VERIFIED,
                        file_attempts=tuple(file_attempts),
                        candidates_considered=len(file_attempts),
                        evidence=("Captured a completed native Chromium download",),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )
        finally:
            native_download.close()

        if navigation_error is not None:
            blocked_now = new_blocked_urls()
            if blocked_now:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=getattr(page, "url", None),
                    status=BrowserAttemptStatus.UNSAFE_URL,
                    challenge_history=tuple(challenge_history),
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    evidence=tuple(
                        f"Blocked unsafe browser request: {url}" for url in blocked_now
                    ),
                    error="Browser navigation attempted an unsafe local-network URL",
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            # A direct PDF navigation can become a browser download; allow a short
            # event flush before deciding the route truly failed. Context-level
            # capture also sees downloads created by a popup/new tab.
            page.wait_for_timeout(500)
            verified_download = process_pending_downloads()
            if verified_download is not None:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=source.url,
                    status=BrowserAttemptStatus.VERIFIED,
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    evidence=("Direct browser navigation produced a download",),
                    elapsed_seconds=time.perf_counter() - started_at,
                )
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=getattr(page, "url", None),
                status=BrowserAttemptStatus.NAVIGATION_ERROR,
                challenge_history=tuple(challenge_history),
                file_attempts=tuple(file_attempts),
                candidates_considered=len(file_attempts),
                error=type(navigation_error).__name__,
                elapsed_seconds=time.perf_counter() - started_at,
            )

    try:
        validate_browser_network_url(page.url)
    except (TypeError, ValueError) as exc:
        safe_final = redact_url_for_record(getattr(page, "url", None))
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=safe_final,
            status=BrowserAttemptStatus.UNSAFE_URL,
            challenge_history=tuple(challenge_history),
            file_attempts=tuple(file_attempts),
            candidates_considered=len(file_attempts),
            evidence=("Browser navigation ended at an unsafe network target",),
            error=type(exc).__name__,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    initial_report = _report_for_page(page)
    if initial_report.kind == ChallengeKind.NONE:
        _wait_for_ieee_article_controls(page)
        initial_report = _report_for_page(page)
    _append_report(challenge_history, initial_report)
    if initial_report.kind == ChallengeKind.SSO:
        handoff_result = run_institution_handoff_and_retry()
        if handoff_result is not None:
            return handoff_result

    final_report, observed, used = _resolve_page_challenge(page, config=config)
    for report in observed:
        _append_report(challenge_history, report)
    interaction_used = interaction_used or used

    if final_report.kind != ChallengeKind.NONE:
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page.url,
            status=_status_from_challenge(final_report),
            challenge_history=tuple(challenge_history),
            file_attempts=tuple(file_attempts),
            candidates_considered=len(file_attempts),
            interaction_used=interaction_used,
            evidence=final_report.evidence,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    sync_session_events()

    try:
        html = page.content()
        parsed = parse_html(html)
        identity = validate_page_identity(
            target_doi=source.doi,
            parsed=parsed,
            expected_title=expected_title,
        )
    except Exception as exc:
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page.url,
            status=BrowserAttemptStatus.ERROR,
            challenge_history=tuple(challenge_history),
            file_attempts=tuple(file_attempts),
            candidates_considered=len(file_attempts),
            interaction_used=interaction_used,
            error=type(exc).__name__,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    if identity.status.value == "MISMATCH":
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=page.url,
            status=BrowserAttemptStatus.PAGE_MISMATCH,
            challenge_history=tuple(challenge_history),
            file_attempts=tuple(file_attempts),
            candidates_considered=len(file_attempts),
            interaction_used=interaction_used,
            evidence=identity.evidence,
            elapsed_seconds=time.perf_counter() - started_at,
        )

    # A DOI resolver can be blocked before v0.5 records its final publisher
    # URL. Once the real browser reaches that page, promote the documented
    # publisher PDF route and navigate it in the same authenticated context.
    runtime_pdf = _runtime_publisher_pdf_candidate(source, page.url)
    if (
        _allow_runtime_pdf_handoff
        and runtime_pdf is not None
        and runtime_pdf.url.split("#", 1)[0] != source.url.split("#", 1)[0]
    ):
        runtime_attempt = attempt_browser_route(
            context,
            page,
            source=runtime_pdf,
            output_dir=output_dir,
            expected_title=expected_title,
            config=config,
            session_blocked_urls=session_blocked_urls,
            session_pdf_responses=session_pdf_responses,
            session_downloads=session_downloads,
            _allow_access_handoff=_allow_access_handoff,
            _allow_runtime_pdf_handoff=False,
            _navigate_source=True,
        )
        merged_history = list(challenge_history)
        for report in runtime_attempt.challenge_history:
            _append_report(merged_history, report)
        merged_file_attempts = [*file_attempts, *runtime_attempt.file_attempts]
        return replace(
            runtime_attempt,
            source_candidate=source,
            challenge_history=tuple(merged_history),
            file_attempts=tuple(merged_file_attempts),
            candidates_considered=len(merged_file_attempts),
            interaction_used=interaction_used or runtime_attempt.interaction_used,
            evidence=(
                "Promoted publisher PDF route after live DOI resolution",
                *runtime_attempt.evidence,
            ),
            elapsed_seconds=time.perf_counter() - started_at,
        )

    # Some publisher viewers (notably Wiley) embed an entitled PDF in a nested
    # same-origin frame while rejecting BrowserContext.request with HTTP 403.
    # Trigger one bounded same-origin cache fetch so the browser-session bytes
    # can be validated without replaying credentials outside the page.
    embedded_pdf = _trigger_embedded_pdf_frame_fetch(
        page,
        max_bytes=config.max_bytes,
    )
    if embedded_pdf is None and (
        source.url_type == CandidateUrlType.PDF
        or "/pdf" in urlsplit(str(page.url or "")).path.casefold()
    ):
        # JavaScript viewers commonly attach their real PDF iframe shortly
        # after DOMContentLoaded. Retry once within a small fixed budget instead
        # of misclassifying an entitled, still-hydrating viewer as exhausted.
        try:
            page.wait_for_timeout(5000)
        except Exception:
            pass
        embedded_pdf = _trigger_embedded_pdf_frame_fetch(
            page,
            max_bytes=config.max_bytes,
        )
    if embedded_pdf is not None:
        embedded_resource: RetrievedResource | None = None
        try:
            embedded_url, embedded_body = embedded_pdf
            embedded_candidate = _candidate_for_url(source, embedded_url)
            embedded_resource = _resource_from_bytes(
                candidate=embedded_candidate,
                final_url=embedded_url,
                status=200,
                content_type="application/pdf",
                body=embedded_body,
                output_dir=output_dir,
            )
            embedded_result = finalize_browser_resource(
                candidate=embedded_candidate,
                resource=embedded_resource,
                output_dir=output_dir,
                expected_title=expected_title,
                keep_unverified=config.keep_unverified,
                profile_name=config.profile_name,
                source_page_url=page.url,
                access_evidence=(
                    "Read entitled PDF bytes from the publisher viewer cache",
                    "Request used the authenticated top-level browser page",
                ),
            )
            file_attempts.append(
                BrowserFileAttempt(
                    candidate=embedded_candidate,
                    result=embedded_result,
                    source_page_url=page.url,
                    method="embedded_browser_fetch",
                )
            )
            if embedded_result.status == AcquisitionStatus.VERIFIED:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=page.url,
                    status=BrowserAttemptStatus.VERIFIED,
                    challenge_history=tuple(challenge_history),
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    interaction_used=interaction_used,
                    evidence=("Verified from the authenticated publisher viewer",),
                    elapsed_seconds=time.perf_counter() - started_at,
                )
        except Exception as exc:
            if (
                embedded_resource is not None
                and embedded_resource.local_path is not None
            ):
                embedded_resource.local_path.unlink(missing_ok=True)
            file_attempts.append(
                BrowserFileAttempt(
                    candidate=source,
                    source_page_url=page.url,
                    method="embedded_browser_fetch",
                    error=type(exc).__name__,
                )
            )
        try:
            page.wait_for_timeout(250)
        except Exception:
            pass
        sync_session_events()

    # Chromium's built-in PDF webview keeps its Save control outside the normal
    # page/frame DOM. In an attached real browser, invoke that native control
    # through its isolated DevTools target and validate the resulting file.
    viewer_save = _trigger_pdf_viewer_save(
        context,
        page,
        doi=source.doi,
        output_dir=output_dir,
        expected_title=expected_title,
        timeout=config.request_timeout,
        max_bytes=config.max_bytes,
    )
    if viewer_save is not None:
        saved_path, staging_dir = viewer_save
        try:
            viewer_attempt = _download_to_file_attempt(
                _LocalBrowserDownload(saved_path, page.url),
                parent=source,
                source_page_url=page.url,
                output_dir=output_dir,
                expected_title=expected_title,
                config=config,
            )
            viewer_attempt = replace(viewer_attempt, method="browser_viewer_save")
            file_attempts.append(viewer_attempt)
            if (
                viewer_attempt.result is not None
                and viewer_attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=page.url,
                    status=BrowserAttemptStatus.VERIFIED,
                    challenge_history=tuple(challenge_history),
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    interaction_used=interaction_used,
                    evidence=(
                        "Verified after automatic save from Chromium PDF viewer",
                    ),
                    elapsed_seconds=time.perf_counter() - started_at,
                )
        finally:
            saved_path.unlink(missing_ok=True)
            try:
                staging_dir.rmdir()
            except OSError:
                pass

    seen_browser_response_ids: set[int] = set()
    for response in pending_browser_responses():
        attempt = _browser_response_to_file_attempt(
            response,
            parent=source,
            source_page_url=page.url,
            output_dir=output_dir,
            expected_title=expected_title,
            config=config,
        )
        file_attempts.append(attempt)
        if (
            attempt.result is not None
            and attempt.result.status == AcquisitionStatus.VERIFIED
        ):
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=page.url,
                status=BrowserAttemptStatus.VERIFIED,
                challenge_history=tuple(challenge_history),
                file_attempts=tuple(file_attempts),
                candidates_considered=len(file_attempts),
                interaction_used=interaction_used,
                evidence=(
                    "Verified directly from authenticated browser response bytes",
                ),
                elapsed_seconds=time.perf_counter() - started_at,
            )

    candidates: list[FullTextCandidate] = []
    if source.url_type == CandidateUrlType.PDF:
        candidates.append(source)

    # DOI resolution may be the first point at which a publisher-specific
    # article identifier becomes available. Re-evaluate the final browser URL
    # so dynamic pages cannot hide a legitimate PDF route from the resolver.
    try:
        runtime_candidate = _runtime_publisher_pdf_candidate(source, page.url)
        if runtime_candidate is not None:
            candidates.append(runtime_candidate)
    except (TypeError, ValueError):
        pass

    try:
        derived = derive_pdf_candidates(
            parent=source,
            parsed=parsed,
            source_page_url=page.url,
        )
        candidates.extend(item.candidate for item in derived)
    except Exception:
        pass

    if navigation_response is not None:
        try:
            content_type = (
                navigation_response.headers.get("content-type") or ""
            ).lower()
            if "application/pdf" in content_type:
                candidates.insert(
                    0, _candidate_for_url(source, navigation_response.url)
                )
        except Exception:
            pass

    for url in network_pdf_urls:
        try:
            candidates.append(_candidate_for_url(source, url))
        except ValueError:
            continue

    candidates = list(_dedupe_candidates(candidates, limit=config.max_pdf_candidates))

    if not _browser_native_only:
        retried_auth_urls: set[str] = set()
        for candidate in candidates:
            attempt, challenge = _request_pdf_candidate(
                context,
                candidate=candidate,
                source_page_url=page.url,
                output_dir=output_dir,
                expected_title=expected_title,
                config=config,
            )
            file_attempts.append(attempt)
            if (
                attempt.result is not None
                and attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=page.url,
                    status=BrowserAttemptStatus.VERIFIED,
                    challenge_history=tuple(challenge_history),
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    interaction_used=interaction_used,
                    evidence=identity.evidence,
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            # Some PDF endpoints perform their own authentication redirect. Surface
            # that endpoint in the browser once, let the legitimate session recover,
            # then retry the exact same concrete file URL at most once.
            if (
                challenge is not None
                and candidate.url not in retried_auth_urls
                and challenge.kind
                in {
                    ChallengeKind.BOT_CHALLENGE,
                    ChallengeKind.CAPTCHA,
                    ChallengeKind.AUTHENTICATION,
                    ChallengeKind.SSO,
                    ChallengeKind.MFA,
                }
            ):
                retried_auth_urls.add(candidate.url)
                _append_report(challenge_history, challenge)
                try:
                    try:
                        page.goto(
                            candidate.url,
                            wait_until="domcontentloaded",
                            timeout=config.navigation_timeout * 1000,
                        )
                    except Exception:
                        # PDF navigations may raise ERR_ABORTED or time out after
                        # the browser has already rendered the access challenge.
                        # Inspect the visible page before abandoning handoff.
                        pass
                    final, observed, used = _resolve_page_challenge(page, config=config)
                    for report in observed:
                        _append_report(challenge_history, report)
                    interaction_used = interaction_used or used
                    if final.kind == ChallengeKind.NONE:
                        retry, retry_challenge = _request_pdf_candidate(
                            context,
                            candidate=candidate,
                            source_page_url=page.url,
                            output_dir=output_dir,
                            expected_title=expected_title,
                            config=config,
                        )
                        file_attempts.append(retry)
                        if retry_challenge is not None:
                            _append_report(challenge_history, retry_challenge)
                        if (
                            retry.result is not None
                            and retry.result.status == AcquisitionStatus.VERIFIED
                        ):
                            return BrowserAccessAttempt(
                                source_candidate=source,
                                final_url=page.url,
                                status=BrowserAttemptStatus.VERIFIED,
                                challenge_history=tuple(challenge_history),
                                file_attempts=tuple(file_attempts),
                                candidates_considered=len(file_attempts),
                                interaction_used=interaction_used,
                                evidence=(
                                    "Authenticated concrete PDF endpoint recovered",
                                ),
                                elapsed_seconds=time.perf_counter() - started_at,
                            )
                except Exception:
                    pass

                verified_download = process_pending_downloads()
                if verified_download is not None:
                    return BrowserAccessAttempt(
                        source_candidate=source,
                        final_url=getattr(page, "url", None) or source.url,
                        status=BrowserAttemptStatus.VERIFIED,
                        challenge_history=tuple(challenge_history),
                        file_attempts=tuple(file_attempts),
                        candidates_considered=len(file_attempts),
                        interaction_used=interaction_used,
                        evidence=("Authenticated PDF navigation produced a download",),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )

    # Last bounded generic fallback: explicit visible article-PDF control whose
    # JavaScript action was not represented by an href in the rendered HTML.
    existing_page_ids = {id(open_page) for open_page in context.pages}
    clicked = _click_semantic_pdf_control(page)
    if clicked:
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass

        # A PDF control may replace the current article page with an HTML
        # viewer whose same-origin iframe owns the real PDF. Popup processing
        # cannot see that navigation, so
        # re-run embedded-frame capture on the current page after the click.
        clicked_embedded_pdf = _trigger_embedded_pdf_frame_fetch(
            page,
            max_bytes=config.max_bytes,
        )
        if clicked_embedded_pdf is None:
            try:
                page.wait_for_timeout(5000)
            except Exception:
                pass
            clicked_embedded_pdf = _trigger_embedded_pdf_frame_fetch(
                page,
                max_bytes=config.max_bytes,
            )
        if clicked_embedded_pdf is not None:
            clicked_resource: RetrievedResource | None = None
            try:
                clicked_url, clicked_body = clicked_embedded_pdf
                clicked_candidate = _candidate_for_url(source, clicked_url)
                clicked_resource = _resource_from_bytes(
                    candidate=clicked_candidate,
                    final_url=clicked_url,
                    status=200,
                    content_type="application/pdf",
                    body=clicked_body,
                    output_dir=output_dir,
                )
                clicked_result = finalize_browser_resource(
                    candidate=clicked_candidate,
                    resource=clicked_resource,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    keep_unverified=config.keep_unverified,
                    profile_name=config.profile_name,
                    source_page_url=page.url,
                    access_evidence=(
                        "Read entitled PDF bytes from the post-click publisher viewer",
                        "Request used the authenticated top-level browser page",
                    ),
                )
                clicked_attempt = BrowserFileAttempt(
                    candidate=clicked_candidate,
                    result=clicked_result,
                    source_page_url=page.url,
                    method="embedded_browser_fetch",
                )
                file_attempts.append(clicked_attempt)
                if clicked_result.status == AcquisitionStatus.VERIFIED:
                    return BrowserAccessAttempt(
                        source_candidate=source,
                        final_url=page.url,
                        status=BrowserAttemptStatus.VERIFIED,
                        challenge_history=tuple(challenge_history),
                        file_attempts=tuple(file_attempts),
                        candidates_considered=len(file_attempts),
                        interaction_used=interaction_used,
                        evidence=("Verified from the post-click publisher PDF viewer",),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )
            except Exception as exc:
                if clicked_resource is not None and clicked_resource.local_path:
                    clicked_resource.local_path.unlink(missing_ok=True)
                file_attempts.append(
                    BrowserFileAttempt(
                        candidate=source,
                        source_page_url=page.url,
                        method="embedded_browser_fetch",
                        error=type(exc).__name__,
                    )
                )

        # Read context-captured PDF bytes before popup processing closes any
        # newly opened page. Real Chromium may invalidate Response.body() after
        # the owning popup is closed even though the response event was observed.
        sync_session_events()
        for response in pending_browser_responses():
            attempt = _browser_response_to_file_attempt(
                response,
                parent=source,
                source_page_url=page.url,
                output_dir=output_dir,
                expected_title=expected_title,
                config=config,
            )
            file_attempts.append(attempt)
            if (
                attempt.result is not None
                and attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=page.url,
                    status=BrowserAttemptStatus.VERIFIED,
                    challenge_history=tuple(challenge_history),
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    interaction_used=interaction_used,
                    evidence=("PDF control yielded live browser response bytes",),
                    elapsed_seconds=time.perf_counter() - started_at,
                )

        (
            popup_attempts,
            popup_challenges,
            popup_interaction_used,
            popup_verified,
        ) = _process_new_popup_pages(
            context,
            original_page=page,
            existing_page_ids=existing_page_ids,
            source=source,
            output_dir=output_dir,
            expected_title=expected_title,
            config=config,
            close_pages=False,
        )
        file_attempts.extend(popup_attempts)
        for report in popup_challenges:
            _append_report(challenge_history, report)
        interaction_used = interaction_used or popup_interaction_used
        sync_session_events()
        popup_pages = [
            popup
            for popup in context.pages
            if id(popup) not in existing_page_ids and popup is not page
        ][:4]
        response_verified: AcquisitionResult | None = None
        try:
            # Challenge-cleared PDF responses may arrive while popup processing
            # is in progress. Consume their bodies while the owning target is
            # still alive; closing first makes Playwright raise TargetClosedError.
            for response in pending_browser_responses():
                attempt = _browser_response_to_file_attempt(
                    response,
                    parent=source,
                    source_page_url=page.url,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=config,
                )
                file_attempts.append(attempt)
                if (
                    attempt.result is not None
                    and attempt.result.status == AcquisitionStatus.VERIFIED
                ):
                    response_verified = attempt.result
                    break
        finally:
            for popup in popup_pages:
                try:
                    if not popup.is_closed():
                        popup.close()
                except Exception:
                    pass

        if response_verified is not None:
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=page.url,
                status=BrowserAttemptStatus.VERIFIED,
                challenge_history=tuple(challenge_history),
                file_attempts=tuple(file_attempts),
                candidates_considered=len(file_attempts),
                interaction_used=interaction_used,
                evidence=("PDF popup yielded live browser response bytes",),
                elapsed_seconds=time.perf_counter() - started_at,
            )
        if popup_verified is not None:
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=page.url,
                status=BrowserAttemptStatus.VERIFIED,
                challenge_history=tuple(challenge_history),
                file_attempts=tuple(file_attempts),
                candidates_considered=len(file_attempts),
                interaction_used=interaction_used,
                evidence=("New browser tab yielded a verified article PDF",),
                elapsed_seconds=time.perf_counter() - started_at,
            )

        final, observed, used = _resolve_page_challenge(page, config=config)
        for report in observed:
            _append_report(challenge_history, report)
        interaction_used = interaction_used or used
        if final.kind == ChallengeKind.NONE:
            for response in pending_browser_responses():
                attempt = _browser_response_to_file_attempt(
                    response,
                    parent=source,
                    source_page_url=page.url,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=config,
                )
                file_attempts.append(attempt)
                if (
                    attempt.result is not None
                    and attempt.result.status == AcquisitionStatus.VERIFIED
                ):
                    return BrowserAccessAttempt(
                        source_candidate=source,
                        final_url=page.url,
                        status=BrowserAttemptStatus.VERIFIED,
                        challenge_history=tuple(challenge_history),
                        file_attempts=tuple(file_attempts),
                        candidates_considered=len(file_attempts),
                        interaction_used=interaction_used,
                        evidence=("PDF control produced a verified browser response",),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )

            verified_download = process_pending_downloads()
            if verified_download is not None:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=page.url,
                    status=BrowserAttemptStatus.VERIFIED,
                    challenge_history=tuple(challenge_history),
                    file_attempts=tuple(file_attempts),
                    candidates_considered=len(file_attempts),
                    interaction_used=interaction_used,
                    evidence=("Explicit article-PDF browser control produced a file",),
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            post_click: list[FullTextCandidate] = []
            for url in network_pdf_urls:
                try:
                    post_click.append(_candidate_for_url(source, url))
                except ValueError:
                    continue
            for candidate in _dedupe_candidates(
                post_click,
                limit=config.max_pdf_candidates,
            ):
                # A Chromium PDF popup may emit a response/download event whose
                # body is no longer readable after the viewer takes ownership.
                # Such failed captures must not suppress the bounded
                # cookie-sharing request fallback for the same URL.
                attempt, challenge = _request_pdf_candidate(
                    context,
                    candidate=candidate,
                    source_page_url=page.url,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=config,
                )
                file_attempts.append(attempt)
                if challenge is not None:
                    _append_report(challenge_history, challenge)
                if (
                    attempt.result is not None
                    and attempt.result.status == AcquisitionStatus.VERIFIED
                ):
                    return BrowserAccessAttempt(
                        source_candidate=source,
                        final_url=page.url,
                        status=BrowserAttemptStatus.VERIFIED,
                        challenge_history=tuple(challenge_history),
                        file_attempts=tuple(file_attempts),
                        candidates_considered=len(file_attempts),
                        interaction_used=interaction_used,
                        evidence=(
                            "Network response after PDF control yielded verified file",
                        ),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )

    handoff_result = run_institution_handoff_and_retry()
    if handoff_result is not None:
        return handoff_result

    any_retrieved = any(
        attempt.result is not None
        and attempt.result.status != AcquisitionStatus.INVALID_PDF
        for attempt in file_attempts
    )
    any_file_work = bool(file_attempts)
    status = (
        BrowserAttemptStatus.RETRIEVED_UNVERIFIED
        if any_retrieved
        else BrowserAttemptStatus.RETRIEVAL_FAILED
        if any_file_work
        else BrowserAttemptStatus.NO_FILE_CANDIDATES
    )
    return BrowserAccessAttempt(
        source_candidate=source,
        final_url=page.url,
        status=status,
        challenge_history=tuple(challenge_history),
        file_attempts=tuple(file_attempts),
        candidates_considered=len(file_attempts),
        interaction_used=interaction_used,
        evidence=identity.evidence,
        elapsed_seconds=time.perf_counter() - started_at,
    )
