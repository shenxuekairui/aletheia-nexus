import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from aletheia_nexus.acquire.access.browser_route import attempt_browser_route
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserRecoveryResult,
)
from aletheia_nexus.acquire.access.security import (
    redact_url_for_record,
    validate_browser_network_url,
)
from aletheia_nexus.acquire.discovery.hosts import refine_host_type
from aletheia_nexus.acquire.discovery.models import CandidateUrlType, FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionResult, AcquisitionStatus
from aletheia_nexus.core.identifiers.doi import normalize_doi

_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BrowserCapabilityUnavailable(RuntimeError):
    """Raised when the optional browser capability cannot be started."""


@dataclass(slots=True)
class _CapturedBrowserResponse:
    """Stable PDF response bytes captured while the real browser target is alive."""

    url: str
    status: int
    headers: dict[str, str]
    _body: bytes

    def body(self) -> bytes:
        return self._body


def _validate_config(config: BrowserAccessConfig) -> None:
    if not isinstance(config, BrowserAccessConfig):
        raise TypeError("config must be a BrowserAccessConfig")
    if not isinstance(config.profile_name, str):
        raise TypeError("profile_name must be a string")
    if not _PROFILE_RE.fullmatch(config.profile_name) or config.profile_name in {
        ".",
        "..",
    }:
        raise ValueError(
            "profile_name must be 1-64 safe characters and may not be '.' or '..'"
        )
    for name in (
        "headless",
        "interactive",
        "wait_for_interaction",
        "keep_unverified",
        "cdp_resume_existing_page",
        "use_system_proxy",
    ):
        if not isinstance(getattr(config, name), bool):
            raise TypeError(f"{name} must be a bool")
    if config.channel is not None:
        if not isinstance(config.channel, str):
            raise TypeError("channel must be a string or None")
        if not config.channel.strip():
            raise ValueError("channel must not be blank")
    if config.cdp_endpoint is not None:
        if not isinstance(config.cdp_endpoint, str):
            raise TypeError("cdp_endpoint must be a string or None")
        endpoint = config.cdp_endpoint.strip()
        if not endpoint:
            raise ValueError("cdp_endpoint must not be blank")
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("cdp_endpoint must use http or https")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("cdp_endpoint must point to a loopback browser endpoint")
        if parsed.username or parsed.password:
            raise ValueError("cdp_endpoint must not contain credentials")
    if config.interaction_callback is not None and not callable(
        config.interaction_callback
    ):
        raise TypeError("interaction_callback must be callable or None")
    if config.headless and config.interactive:
        raise ValueError("headless browser mode cannot use interactive human handoff")
    for name in (
        "navigation_timeout",
        "request_timeout",
        "poll_interval",
    ):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{name} must be a positive number")
    for name in ("auto_challenge_grace", "interaction_timeout"):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"{name} must be a non-negative number")
    for name in ("max_source_routes", "max_pdf_candidates"):
        value = getattr(config, name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if (
        not isinstance(config.max_request_redirects, int)
        or isinstance(config.max_request_redirects, bool)
        or config.max_request_redirects < 0
    ):
        raise ValueError("max_request_redirects must be a non-negative integer")
    if (
        not isinstance(config.max_bytes, int)
        or isinstance(config.max_bytes, bool)
        or config.max_bytes < 1
    ):
        raise ValueError("max_bytes must be a positive integer")


def browser_profile_dir(config: BrowserAccessConfig) -> Path:
    """Return the dedicated persistent browser profile directory."""

    _validate_config(config)
    root = (
        Path(config.profile_root).expanduser()
        if config.profile_root is not None
        else Path.home() / ".aletheia-nexus" / "browser-profiles"
    )
    return root / config.profile_name


def _install_context_request_guard(context) -> list[str]:
    """Protect every page/popup in the persistent context from local-network URLs."""

    blocked: list[str] = []
    if not hasattr(context, "route"):
        return blocked

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

    context.route("**/*", guard)
    return blocked


def _install_context_event_capture(
    context,
    *,
    pdf_responses: list[object],
    downloads: list[object],
    snapshot_pdf_responses: bool = False,
    max_bytes: int | None = None,
) -> None:
    """Capture PDF responses and downloads from every page, including popups."""

    if not hasattr(context, "on"):
        return

    def on_response(response) -> None:
        try:
            headers = dict(response.headers)
            content_type = (headers.get("content-type") or "").lower()
            disposition = (headers.get("content-disposition") or "").lower()
            path = urlsplit(str(response.url)).path.lower()
            if not (
                "application/pdf" in content_type
                or ".pdf" in disposition
                or path.endswith(".pdf")
                or "/pdfdirect/" in path
                or "/doi/pdf/" in path
            ):
                return

            if not snapshot_pdf_responses:
                pdf_responses.append(response)
                return

            content_length = headers.get("content-length")
            if content_length and max_bytes is not None:
                try:
                    if int(content_length) > max_bytes:
                        return
                except ValueError:
                    pass

            body = response.body()
            if max_bytes is not None and len(body) > max_bytes:
                return

            pdf_responses.append(
                _CapturedBrowserResponse(
                    url=str(response.url),
                    status=int(response.status),
                    headers=headers,
                    _body=body,
                )
            )
        except Exception:
            return

    def attach_page(page) -> None:
        try:
            page.on("download", downloads.append)
        except Exception:
            return

    context.on("response", on_response)
    context.on("page", attach_page)
    for page in getattr(context, "pages", ()):
        attach_page(page)


def _normalized_page_title(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(str(value).casefold().split())


def _attached_page_is_pdf(url: str) -> bool:
    try:
        return urlsplit(url).path.lower().endswith(".pdf")
    except ValueError:
        return False


def _attached_page_has_expired_signature(url: str) -> bool:
    """Detect an expired AWS-style signed URL without retaining its secrets."""

    try:
        query = parse_qs(urlsplit(url).query)
        raw_date = query.get("X-Amz-Date", [None])[0]
        raw_expires = query.get("X-Amz-Expires", [None])[0]
        if raw_date is None or raw_expires is None:
            return False
        issued_at = datetime.strptime(raw_date, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        expires = float(raw_expires)
        if expires < 0:
            return True
        return datetime.now(timezone.utc) >= issued_at + timedelta(seconds=expires)
    except (TypeError, ValueError, OverflowError):
        return False


def _preferred_document_tokens(preferred_url: str) -> tuple[str, ...]:
    """Return conservative identifier tokens usable for PDF-tab correlation."""

    try:
        suffix = urlsplit(preferred_url).path.rstrip("/").rsplit("/", 1)[-1]
    except ValueError:
        return ()
    compact = re.sub(r"[^a-z0-9]", "", suffix.casefold())
    if not compact:
        return ()
    tokens = [compact]
    # ACS article filenames abbreviate the journal but preserve article codes,
    # e.g. acsnano.5c01551 -> nn5c01551.pdf. The code is specific enough to
    # distinguish an article without guessing a publisher URL.
    tail = re.search(r"\d+[a-z]\d{4,}$", compact)
    if tail is not None and tail.group(0) != compact:
        tokens.append(tail.group(0))
    return tuple(tokens)


def _select_attached_page(
    context,
    *,
    preferred_url: str,
    expected_title: str | None = None,
    minimum_score: int = 0,
):
    """Choose the best existing web page from an attached real browser."""

    preferred_host = urlsplit(preferred_url).hostname
    preferred_document_url = preferred_url.split("#", 1)[0]
    preferred_path = urlsplit(preferred_url).path.lower()
    preferred_tokens = _preferred_document_tokens(preferred_url)
    preferred_is_pdf_route = _attached_page_is_pdf(preferred_url) or (
        "/doi/pdf/" in preferred_path or preferred_path.endswith("/pdf")
    )
    pages = list(getattr(context, "pages", ()) or ())
    expected = _normalized_page_title(expected_title)
    ranked: list[tuple[int, int, object]] = []
    for index, page in enumerate(pages):
        try:
            if page.is_closed():
                continue
            url = str(page.url or "")
        except Exception:
            continue
        if not url.lower().startswith(("http://", "https://")):
            continue
        score = 0
        if preferred_is_pdf_route and url.split("#", 1)[0] == preferred_document_url:
            score += 500
        try:
            if preferred_host and urlsplit(url).hostname == preferred_host:
                score += 100
        except ValueError:
            pass

        pdf_page = _attached_page_is_pdf(url)
        if pdf_page:
            score += 150
            if _attached_page_has_expired_signature(url):
                score -= 700

        compact_url = re.sub(r"[^a-z0-9]", "", url.casefold())
        if any(len(token) >= 6 and token in compact_url for token in preferred_tokens):
            score += 450

        if expected:
            try:
                observed = _normalized_page_title(page.title())
            except Exception:
                observed = ""
            if observed:
                similarity = SequenceMatcher(None, expected, observed).ratio()
                if similarity >= 0.92:
                    score += 300
                    if pdf_page:
                        score += 100

        # Later pages win exact ties. This follows the normal handoff workflow,
        # where the researcher leaves the most recently opened target tab active.
        ranked.append((score, index, page))

    if not ranked:
        return None
    winner = max(ranked, key=lambda item: (item[0], item[1]))
    if winner[0] < minimum_score:
        return None
    return winner[2]


def _source_for_attached_page(
    routes: list[FullTextCandidate],
    *,
    page_url: str,
) -> FullTextCandidate:
    """Represent the user's current browser tab as the authoritative handoff route."""

    safe_url = validate_browser_network_url(page_url)
    page_host = (urlsplit(safe_url).hostname or "").lower()
    parent = routes[0]
    for route in routes:
        route_host = (urlsplit(route.url).hostname or "").lower()
        if page_host and route_host == page_host:
            parent = route
            break

    url_type = (
        CandidateUrlType.PDF
        if _attached_page_is_pdf(safe_url)
        else CandidateUrlType.LANDING_PAGE
    )
    return replace(
        parent,
        url=safe_url,
        url_type=url_type,
        host_type=refine_host_type(safe_url, parent.host_type),
        source_name="External browser current page",
    )


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserCapabilityUnavailable(
            "Browser acquisition requires the optional 'browser' dependency. "
            "Install with: python -m pip install -e '.[browser]'"
        ) from exc
    return sync_playwright


def _normalize_routes(
    *,
    doi: str,
    routes: tuple[FullTextCandidate, ...] | list[FullTextCandidate],
    limit: int,
) -> tuple[str, list[FullTextCandidate], list[BrowserAccessAttempt]]:
    normalized_doi = normalize_doi(doi)
    normalized_routes: list[FullTextCandidate] = []
    preflight_attempts: list[BrowserAccessAttempt] = []
    seen: set[str] = set()

    for route in routes:
        if not isinstance(route, FullTextCandidate):
            raise TypeError("routes must contain FullTextCandidate values")
        if normalize_doi(route.doi) != normalized_doi:
            raise ValueError("all browser routes must belong to the requested DOI")

        raw_key = route.url.strip().split("#", 1)[0]
        if raw_key in seen:
            continue
        if len(seen) >= limit:
            break
        seen.add(raw_key)

        try:
            safe_url = validate_browser_network_url(route.url)
        except (TypeError, ValueError) as exc:
            preflight_attempts.append(
                BrowserAccessAttempt(
                    source_candidate=route,
                    final_url=None,
                    status=BrowserAttemptStatus.UNSAFE_URL,
                    error=type(exc).__name__,
                )
            )
            continue
        route = FullTextCandidate(
            doi=route.doi,
            url=safe_url,
            provenance=route.provenance,
            url_type=route.url_type,
            access_type=route.access_type,
            version=route.version,
            host_type=route.host_type,
            license=route.license,
            source_name=route.source_name,
            is_best=route.is_best,
        )
        normalized_routes.append(route)

    return normalized_doi, normalized_routes, preflight_attempts


class BrowserSession:
    """Reusable persistent browser context for one sequential acquisition batch.

    The session starts lazily on the first browser recovery. Keeping it alive
    across DOI-level acquisitions preserves session cookies and temporary
    institutional/challenge state that may disappear when a browser closes.
    The object is intentionally sequential; callers should not share one session
    across concurrent acquisition tasks.
    """

    def __init__(self, config: BrowserAccessConfig | None = None) -> None:
        self.config = config or BrowserAccessConfig()
        _validate_config(self.config)
        self.profile_dir = browser_profile_dir(self.config)
        self._manager = None
        self._context = None
        self._attached_browser = None
        self._attached_external = False
        self._blocked_unsafe_urls: list[str] = []
        self._pdf_responses: list[object] = []
        self._downloads: list[object] = []

    @property
    def active(self) -> bool:
        return self._context is not None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _ensure_started(self):
        if self._context is not None:
            return self._context

        self.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.profile_dir.chmod(0o700)
        except OSError:
            # Windows and some mounted filesystems may not implement POSIX modes.
            pass

        sync_playwright = _load_playwright()
        manager = sync_playwright()
        try:
            playwright = manager.__enter__()
        except Exception as exc:
            raise BrowserCapabilityUnavailable(
                f"Playwright could not start: {type(exc).__name__}"
            ) from exc

        if self.config.cdp_endpoint is not None:
            try:
                browser = playwright.chromium.connect_over_cdp(
                    self.config.cdp_endpoint.strip(),
                    timeout=self.config.navigation_timeout * 1000,
                )
                contexts = list(browser.contexts)
                if not contexts:
                    raise RuntimeError("attached browser exposed no BrowserContext")
                context = contexts[0]
            except Exception as exc:
                manager.__exit__(type(exc), exc, exc.__traceback__)
                raise BrowserCapabilityUnavailable(
                    "Could not attach to the external browser CDP endpoint. "
                    f"Error type: {type(exc).__name__}"
                ) from exc

            context.set_default_timeout(self.config.navigation_timeout * 1000)
            _install_context_event_capture(
                context,
                pdf_responses=self._pdf_responses,
                downloads=self._downloads,
                snapshot_pdf_responses=True,
                max_bytes=self.config.max_bytes,
            )
            self._manager = manager
            self._context = context
            self._attached_browser = browser
            self._attached_external = True
            return context

        launch_kwargs: dict[str, object] = {
            "headless": self.config.headless,
            "accept_downloads": True,
            "service_workers": "allow",
            # Keep the historical direct-connection default. Opting in to the
            # system proxy only affects this dedicated browser process; it does
            # not change OS settings or the user's everyday browser profile.
            "args": [] if self.config.use_system_proxy else ["--no-proxy-server"],
        }
        if self.config.channel:
            launch_kwargs["channel"] = self.config.channel

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                **launch_kwargs,
            )
        except Exception as exc:
            manager.__exit__(type(exc), exc, exc.__traceback__)
            raise BrowserCapabilityUnavailable(
                "Playwright browser could not start. Install a browser with "
                "'python -m playwright install chromium' or configure an "
                f"available channel. Error type: {type(exc).__name__}"
            ) from exc

        context.set_default_timeout(self.config.navigation_timeout * 1000)
        self._blocked_unsafe_urls = _install_context_request_guard(context)
        _install_context_event_capture(
            context,
            pdf_responses=self._pdf_responses,
            downloads=self._downloads,
            max_bytes=self.config.max_bytes,
        )
        self._manager = manager
        self._context = context
        return context

    def close(self) -> None:
        context = self._context
        manager = self._manager
        attached_external = self._attached_external
        self._context = None
        self._manager = None
        self._attached_browser = None
        self._attached_external = False
        self._blocked_unsafe_urls = []
        self._pdf_responses = []
        self._downloads = []

        if context is not None and not attached_external:
            try:
                context.close()
            finally:
                if manager is not None:
                    manager.__exit__(None, None, None)
        elif manager is not None:
            # In CDP attach mode, disconnect Playwright without closing the
            # user-controlled external browser or its tabs.
            manager.__exit__(None, None, None)

    def acquire(
        self,
        *,
        doi: str,
        routes: tuple[FullTextCandidate, ...] | list[FullTextCandidate],
        output_dir: str | Path,
        expected_title: str | None = None,
    ) -> BrowserRecoveryResult:
        """Recover one DOI while preserving this session for later DOI calls."""

        if expected_title is not None and not isinstance(expected_title, str):
            raise TypeError("expected_title must be a string or None")

        normalized_doi, normalized_routes, preflight_attempts = _normalize_routes(
            doi=doi,
            routes=routes,
            limit=self.config.max_source_routes,
        )
        started_at = time.perf_counter()
        attempts: list[BrowserAccessAttempt] = list(preflight_attempts)
        if not normalized_routes:
            return BrowserRecoveryResult(
                doi=normalized_doi,
                attempts=tuple(attempts),
                profile_dir=self.profile_dir,
                elapsed_seconds=time.perf_counter() - started_at,
            )

        context = self._ensure_started()
        verified: AcquisitionResult | None = None

        attached_page = None
        if self._attached_external:
            attached_page = _select_attached_page(
                context,
                preferred_url=normalized_routes[0].url,
                expected_title=expected_title,
                # Automatic batch navigation may leave a challenge tab open.
                # Resume it only when its title strongly matches this paper;
                # never fall back to an arbitrary browser tab.
                minimum_score=(0 if self.config.cdp_resume_existing_page else 300),
            )

        if self._attached_external and (
            self.config.cdp_resume_existing_page or attached_page is not None
        ):
            page = attached_page
            if page is None:
                attempts.append(
                    BrowserAccessAttempt(
                        source_candidate=normalized_routes[0],
                        final_url=None,
                        status=BrowserAttemptStatus.BROWSER_UNAVAILABLE,
                        error="External browser has no open HTTP(S) page to resume",
                    )
                )
                return BrowserRecoveryResult(
                    doi=normalized_doi,
                    attempts=tuple(attempts),
                    profile_dir=self.profile_dir,
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            try:
                source = _source_for_attached_page(
                    normalized_routes,
                    page_url=page.url,
                )
            except (TypeError, ValueError) as exc:
                attempts.append(
                    BrowserAccessAttempt(
                        source_candidate=normalized_routes[0],
                        final_url=redact_url_for_record(getattr(page, "url", None)),
                        status=BrowserAttemptStatus.UNSAFE_URL,
                        error=type(exc).__name__,
                    )
                )
                return BrowserRecoveryResult(
                    doi=normalized_doi,
                    attempts=tuple(attempts),
                    profile_dir=self.profile_dir,
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            self._pdf_responses.clear()
            self._downloads.clear()
            attempt = attempt_browser_route(
                context,
                page,
                source=source,
                output_dir=output_dir,
                expected_title=expected_title,
                config=self.config,
                session_blocked_urls=None,
                session_pdf_responses=self._pdf_responses,
                session_downloads=self._downloads,
                _navigate_source=False,
                _browser_native_only=True,
            )
            attempts.append(attempt)
            if (
                attempt.result is not None
                and attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                verified = attempt.result

            self._pdf_responses.clear()
            self._downloads.clear()
            return BrowserRecoveryResult(
                doi=normalized_doi,
                attempts=tuple(attempts),
                verified_result=verified,
                profile_dir=self.profile_dir,
                elapsed_seconds=time.perf_counter() - started_at,
            )

        for source in normalized_routes:
            # Context-wide handlers append into these reusable lists. Clear them
            # per route so a long batch preserves authentication state without
            # retaining response/download objects from earlier papers.
            self._blocked_unsafe_urls.clear()
            self._pdf_responses.clear()
            self._downloads.clear()

            page = context.new_page()
            attempt = None
            try:
                attempt = attempt_browser_route(
                    context,
                    page,
                    source=source,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=self.config,
                    session_blocked_urls=self._blocked_unsafe_urls,
                    session_pdf_responses=self._pdf_responses,
                    session_downloads=self._downloads,
                )
            finally:
                preserve_interaction_page = (
                    self._attached_external
                    and attempt is not None
                    and attempt.status == BrowserAttemptStatus.INTERACTION_REQUIRED
                )
                if not preserve_interaction_page and not page.is_closed():
                    page.close()
                self._blocked_unsafe_urls.clear()
                self._pdf_responses.clear()
                self._downloads.clear()

            attempts.append(attempt)
            if (
                attempt.result is not None
                and attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                verified = attempt.result
                break

            # An unresolved interactive challenge is a terminal state for this
            # recovery pass. Continuing through alternate resolver/publisher
            # routes after the user has closed or abandoned the challenge can
            # repeat the same prompt and may operate on an invalidated context.
            if attempt.status == BrowserAttemptStatus.INTERACTION_REQUIRED:
                break

        return BrowserRecoveryResult(
            doi=normalized_doi,
            attempts=tuple(attempts),
            verified_result=verified,
            profile_dir=self.profile_dir,
            elapsed_seconds=time.perf_counter() - started_at,
        )


def acquire_with_browser(
    *,
    doi: str,
    routes: tuple[FullTextCandidate, ...] | list[FullTextCandidate],
    output_dir: str | Path,
    expected_title: str | None = None,
    config: BrowserAccessConfig | None = None,
) -> BrowserRecoveryResult:
    """Recover one DOI with a temporary persistent-browser session wrapper.

    For batch acquisition, use :class:`BrowserSession` directly so the live
    browser context remains open across multiple DOI-level calls.
    """

    with BrowserSession(config) as session:
        return session.acquire(
            doi=doi,
            routes=routes,
            output_dir=output_dir,
            expected_title=expected_title,
        )
