import re
import time
from pathlib import Path

from aletheia_nexus.acquire.access.browser_route import attempt_browser_route
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserRecoveryResult,
)
from aletheia_nexus.acquire.access.security import validate_browser_network_url
from aletheia_nexus.acquire.discovery.models import FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionResult, AcquisitionStatus
from aletheia_nexus.core.identifiers.doi import normalize_doi

_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BrowserCapabilityUnavailable(RuntimeError):
    """Raised when the optional browser capability cannot be started."""


def _validate_config(config: BrowserAccessConfig) -> None:
    if not isinstance(config, BrowserAccessConfig):
        raise TypeError("config must be a BrowserAccessConfig")
    if not _PROFILE_RE.fullmatch(config.profile_name) or config.profile_name in {
        ".",
        "..",
    }:
        raise ValueError(
            "profile_name must be 1-64 safe characters and may not be '.' or '..'"
        )
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
        try:
            safe_url = validate_browser_network_url(route.url)
        except (TypeError, ValueError) as exc:
            preflight_attempts.append(
                BrowserAccessAttempt(
                    source_candidate=route,
                    final_url=None,
                    status=BrowserAttemptStatus.UNSAFE_URL,
                    error=f"{type(exc).__name__}: {exc}",
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
        key = route.url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        normalized_routes.append(route)
        if len(normalized_routes) >= limit:
            break

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
                f"Playwright could not start: {type(exc).__name__}: {exc}"
            ) from exc

        launch_kwargs: dict[str, object] = {
            "headless": self.config.headless,
            "accept_downloads": True,
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
                f"available channel. Original error: {type(exc).__name__}: {exc}"
            ) from exc

        context.set_default_timeout(self.config.navigation_timeout * 1000)
        self._manager = manager
        self._context = context
        return context

    def close(self) -> None:
        context = self._context
        manager = self._manager
        self._context = None
        self._manager = None

        if context is not None:
            try:
                context.close()
            finally:
                if manager is not None:
                    manager.__exit__(None, None, None)
        elif manager is not None:
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

        for source in normalized_routes:
            page = context.new_page()
            try:
                attempt = attempt_browser_route(
                    context,
                    page,
                    source=source,
                    output_dir=output_dir,
                    expected_title=expected_title,
                    config=self.config,
                )
            finally:
                if not page.is_closed():
                    page.close()

            attempts.append(attempt)
            if (
                attempt.result is not None
                and attempt.result.status == AcquisitionStatus.VERIFIED
            ):
                verified = attempt.result
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
