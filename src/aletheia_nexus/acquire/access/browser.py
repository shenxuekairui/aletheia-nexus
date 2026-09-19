import re
import time
from pathlib import Path

from aletheia_nexus.acquire.access.browser_route import attempt_browser_route
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserRecoveryResult,
)
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


def acquire_with_browser(
    *,
    doi: str,
    routes: tuple[FullTextCandidate, ...] | list[FullTextCandidate],
    output_dir: str | Path,
    expected_title: str | None = None,
    config: BrowserAccessConfig | None = None,
) -> BrowserRecoveryResult:
    """Recover blocked/authenticated routes with one persistent browser session.

    A dedicated profile is reused across calls so legitimate institutional/account
    authentication can persist. Each source route gets a fresh page inside the same
    browser context: session state is shared while page events remain isolated.
    """

    normalized_doi = normalize_doi(doi)
    config = config or BrowserAccessConfig()
    _validate_config(config)
    if expected_title is not None and not isinstance(expected_title, str):
        raise TypeError("expected_title must be a string or None")

    normalized_routes: list[FullTextCandidate] = []
    seen: set[str] = set()
    for route in routes:
        if not isinstance(route, FullTextCandidate):
            raise TypeError("routes must contain FullTextCandidate values")
        if normalize_doi(route.doi) != normalized_doi:
            raise ValueError("all browser routes must belong to the requested DOI")
        key = route.url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        normalized_routes.append(route)
        if len(normalized_routes) >= config.max_source_routes:
            break

    started_at = time.perf_counter()
    profile = browser_profile_dir(config)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        profile.chmod(0o700)
    except OSError:
        # Windows and some mounted filesystems may not implement POSIX modes.
        pass

    sync_playwright = _load_playwright()
    attempts: list[BrowserAccessAttempt] = []
    verified: AcquisitionResult | None = None

    with sync_playwright() as playwright:
        launch_kwargs: dict[str, object] = {
            "headless": config.headless,
            "accept_downloads": True,
        }
        if config.channel:
            launch_kwargs["channel"] = config.channel

        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=profile,
                **launch_kwargs,
            )
        except Exception as exc:
            raise BrowserCapabilityUnavailable(
                "Playwright browser could not start. Install a browser with "
                "'python -m playwright install chromium' or configure an "
                f"available channel. Original error: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            context.set_default_timeout(config.navigation_timeout * 1000)
            for source in normalized_routes:
                page = context.new_page()
                try:
                    attempt = attempt_browser_route(
                        context,
                        page,
                        source=source,
                        output_dir=output_dir,
                        expected_title=expected_title,
                        config=config,
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
        finally:
            context.close()

    return BrowserRecoveryResult(
        doi=normalized_doi,
        attempts=tuple(attempts),
        verified_result=verified,
        profile_dir=profile,
        elapsed_seconds=time.perf_counter() - started_at,
    )
