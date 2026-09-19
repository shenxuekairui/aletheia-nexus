import hashlib
import re
import shutil
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from aletheia_nexus.acquire.access.artifact import finalize_browser_resource
from aletheia_nexus.acquire.access.challenge import classify_access_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    ChallengeKind,
    ChallengeReport,
)
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

    try:
        html = page.content()
    except Exception:
        html = ""
    return title, url, visible_text, html


def _report_for_page(page) -> ChallengeReport:
    title, url, visible_text, html = _page_snapshot(page)
    return classify_access_challenge(
        title=title,
        url=url,
        visible_text=visible_text,
        html=html,
    )


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
    seconds: float,
    poll_interval: float,
    history: list[ChallengeReport],
) -> ChallengeReport:
    report = initial
    if seconds <= 0:
        return report
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            return report
        page.wait_for_timeout(
            min(poll_interval, max(deadline - time.monotonic(), 0.01)) * 1000
        )
        report = _report_for_page(page)
        _append_report(history, report)
        if report.kind == ChallengeKind.NONE:
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

    if not config.interactive or config.interaction_timeout <= 0:
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
        seconds=config.interaction_timeout,
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
    return classify_access_challenge(
        title=parsed.title or "",
        url=response.url,
        visible_text=parsed.visible_text,
        html=text,
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
                error=f"{type(exc).__name__}: {exc}",
            ),
            None,
        )

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

    try:
        candidate = _candidate_for_url(parent, response.url)
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
            error=f"{type(exc).__name__}: {exc}",
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

    try:
        source = Path(download.path())
        size = source.stat().st_size
        if size > config.max_bytes:
            return BrowserFileAttempt(
                candidate=candidate,
                source_page_url=source_page_url,
                method="browser_download",
                error=f"Browser download exceeds max_bytes ({size} > {config.max_bytes})",
            )

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".an-browser-download-{uuid4().hex}.part"
        shutil.copyfile(source, temporary)
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
        return BrowserFileAttempt(
            candidate=candidate,
            source_page_url=source_page_url,
            method="browser_download",
            error=f"{type(exc).__name__}: {exc}",
        )


def _click_semantic_pdf_control(page) -> bool:
    """Click at most one explicit article-PDF control as a bounded fallback."""

    locator = page.locator("a, button").filter(has_text=_SEMANTIC_PDF_CONTROL)
    try:
        count = min(locator.count(), 8)
    except Exception:
        return False

    for index in range(count):
        item = locator.nth(index)
        try:
            text = " ".join(item.inner_text().split())
        except Exception:
            continue
        lowered = text.lower()
        if (
            not text
            or len(text) > 100
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
        try:
            item.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


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


def _process_new_popup_pages(
    context,
    *,
    original_page,
    existing_page_ids: set[int],
    source: FullTextCandidate,
    output_dir: str | Path,
    expected_title: str | None,
    config: BrowserAccessConfig,
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
) -> BrowserAccessAttempt:
    started_at = time.perf_counter()
    file_attempts: list[BrowserFileAttempt] = []
    challenge_history: list[ChallengeReport] = []
    network_pdf_urls: list[str] = []
    network_pdf_responses: list[object] = []
    downloads: list[object] = []
    processed_downloads: set[int] = set()
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

    def on_response(response) -> None:
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            if (
                "application/pdf" in content_type
                and response.url not in network_pdf_urls
            ):
                network_pdf_urls.append(response.url)
                network_pdf_responses.append(response)
        except Exception:
            return

    def on_download(download) -> None:
        downloads.append(download)

    page.on("response", on_response)
    page.on("download", on_download)

    # If a persistent session is already authenticated, a direct PDF request can
    # succeed without opening a page at all.
    if source.url_type == CandidateUrlType.PDF:
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
            error=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=time.perf_counter() - started_at,
        )

    try:
        navigation_response = page.goto(
            safe_source_url,
            wait_until="domcontentloaded",
            timeout=config.navigation_timeout * 1000,
        )
    except Exception as exc:
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
            error=f"{type(exc).__name__}: {exc}",
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
            error=f"{type(exc).__name__}: {exc}",
            elapsed_seconds=time.perf_counter() - started_at,
        )

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
            error=f"{type(exc).__name__}: {exc}",
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

    seen_browser_response_urls: set[str] = set()
    for response in list(network_pdf_responses):
        response_url = getattr(response, "url", "")
        if not response_url or response_url in seen_browser_response_urls:
            continue
        seen_browser_response_urls.add(response_url)
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
                page.goto(
                    candidate.url,
                    wait_until="domcontentloaded",
                    timeout=config.navigation_timeout * 1000,
                )
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
                            evidence=("Authenticated concrete PDF endpoint recovered",),
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
        )
        file_attempts.extend(popup_attempts)
        for report in popup_challenges:
            _append_report(challenge_history, report)
        interaction_used = interaction_used or popup_interaction_used
        sync_session_events()
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
            for response in list(network_pdf_responses):
                response_url = getattr(response, "url", "")
                if not response_url or response_url in seen_browser_response_urls:
                    continue
                seen_browser_response_urls.add(response_url)
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
                if any(a.candidate.url == candidate.url for a in file_attempts):
                    continue
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
