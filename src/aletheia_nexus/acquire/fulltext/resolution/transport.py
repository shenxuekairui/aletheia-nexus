import time
from urllib.parse import urljoin

import httpx

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionAccessBlockedError,
    AcquisitionAuthRequiredError,
    AcquisitionNetworkError,
    AcquisitionNotFoundError,
    AcquisitionRateLimitError,
    AcquisitionRedirectError,
    AcquisitionRequestError,
    AcquisitionServiceError,
    AcquisitionTooLargeError,
)
from aletheia_nexus.acquire.fulltext.models import RedirectHop
from aletheia_nexus.acquire.fulltext.safety import validate_safe_url
from aletheia_nexus.acquire.fulltext.transport import build_user_agent
from aletheia_nexus.acquire.fulltext.resolution.models import RetrievedPage

DEFAULT_PAGE_TIMEOUT = 30.0
DEFAULT_MAX_PAGE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_PAGE_REDIRECTS = 8
_PDF_SNIFF_BYTES = 8192
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _validate_limits(*, max_bytes: int, timeout: float, max_redirects: int) -> None:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive number")
    if (
        not isinstance(max_redirects, int)
        or isinstance(max_redirects, bool)
        or max_redirects < 0
    ):
        raise ValueError("max_redirects must be a non-negative integer")


def _map_http_error(status_code: int, context: str) -> None:
    if status_code == 401:
        raise AcquisitionAuthRequiredError(
            f"Authorization is required while requesting {context}"
        )
    if status_code == 403:
        raise AcquisitionAccessBlockedError(
            f"Access was blocked while requesting {context}"
        )
    if status_code == 404:
        raise AcquisitionNotFoundError(f"Resource not found while requesting {context}")
    if status_code == 429:
        raise AcquisitionRateLimitError(
            f"Rate limit exceeded while requesting {context}"
        )
    if 400 <= status_code < 500:
        raise AcquisitionRequestError(
            f"Request failed with HTTP {status_code} while requesting {context}"
        )
    if 500 <= status_code < 600:
        raise AcquisitionServiceError(
            f"Remote service returned HTTP {status_code} while requesting {context}"
        )
    if not 200 <= status_code < 300:
        raise AcquisitionServiceError(
            f"Unexpected HTTP {status_code} while requesting {context}"
        )


def _looks_like_pdf(prefix: bytes) -> bool:
    return b"%PDF-" in prefix[:1024]


def _decode_page(body: bytes, response: httpx.Response) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def retrieve_page(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    timeout: float = DEFAULT_PAGE_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_PAGE_REDIRECTS,
    client: httpx.Client | None = None,
) -> RetrievedPage:
    """Safely retrieve a bounded page route while preserving redirect evidence.

    If a route unexpectedly resolves directly to a real PDF, only a small prefix
    is consumed. The final URL is then returned as a direct-file derivation signal
    rather than downloading the PDF twice inside the resolution layer.
    """

    _validate_limits(
        max_bytes=max_bytes,
        timeout=timeout,
        max_redirects=max_redirects,
    )
    started_at = time.perf_counter()
    requested_url = validate_safe_url(url)
    current_url = requested_url
    redirects: list[RedirectHop] = []
    owns_client = client is None
    active_client = client or httpx.Client(follow_redirects=False)

    try:
        while True:
            try:
                with active_client.stream(
                    "GET",
                    current_url,
                    headers={
                        "User-Agent": build_user_agent(),
                        "Accept": (
                            "text/html,application/xhtml+xml,application/pdf;q=0.9,"
                            "*/*;q=0.5"
                        ),
                    },
                    timeout=timeout,
                    follow_redirects=False,
                ) as response:
                    status_code = response.status_code

                    if status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("Location")
                        if not location:
                            raise AcquisitionRedirectError(
                                f"HTTP {status_code} redirect is missing Location"
                            )
                        if len(redirects) >= max_redirects:
                            raise AcquisitionRedirectError(
                                f"Exceeded maximum redirects ({max_redirects})"
                            )
                        next_url = validate_safe_url(urljoin(current_url, location))
                        redirects.append(
                            RedirectHop(
                                from_url=current_url,
                                status_code=status_code,
                                location=location,
                                to_url=next_url,
                            )
                        )
                        current_url = next_url
                        continue

                    if 300 <= status_code < 400:
                        raise AcquisitionRedirectError(
                            f"Unsupported redirect response HTTP {status_code}"
                        )

                    _map_http_error(status_code, current_url)

                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = None
                        if declared_size is not None and declared_size > max_bytes:
                            content_type = (response.headers.get("Content-Type") or "").lower()
                            if "pdf" not in content_type:
                                raise AcquisitionTooLargeError(
                                    "Declared page size exceeds configured maximum"
                                )

                    chunks: list[bytes] = []
                    bytes_read = 0
                    prefix = bytearray()

                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        bytes_read += len(chunk)
                        if len(prefix) < _PDF_SNIFF_BYTES:
                            remaining = _PDF_SNIFF_BYTES - len(prefix)
                            prefix.extend(chunk[:remaining])

                        if _looks_like_pdf(bytes(prefix)):
                            return RetrievedPage(
                                requested_url=requested_url,
                                final_url=current_url,
                                http_status=status_code,
                                content_type=response.headers.get("Content-Type"),
                                text=None,
                                size_bytes=bytes_read,
                                redirects=tuple(redirects),
                                elapsed_seconds=time.perf_counter() - started_at,
                                is_pdf_response=True,
                                body_truncated=True,
                            )

                        if bytes_read > max_bytes:
                            raise AcquisitionTooLargeError(
                                "Downloaded page exceeds configured maximum"
                            )
                        chunks.append(chunk)

                    body = b"".join(chunks)
                    content_type = response.headers.get("Content-Type")
                    lowered_type = (content_type or "").lower()
                    allowed_text = (
                        not lowered_type
                        or "html" in lowered_type
                        or "xhtml" in lowered_type
                        or lowered_type.startswith("text/")
                    )
                    if not allowed_text:
                        return RetrievedPage(
                            requested_url=requested_url,
                            final_url=current_url,
                            http_status=status_code,
                            content_type=content_type,
                            text=None,
                            size_bytes=len(body),
                            redirects=tuple(redirects),
                            elapsed_seconds=time.perf_counter() - started_at,
                        )

                    return RetrievedPage(
                        requested_url=requested_url,
                        final_url=current_url,
                        http_status=status_code,
                        content_type=content_type,
                        text=_decode_page(body, response),
                        size_bytes=len(body),
                        redirects=tuple(redirects),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )
            except httpx.TimeoutException as exc:
                raise AcquisitionNetworkError(
                    f"Timed out while requesting {current_url}"
                ) from exc
            except httpx.RequestError as exc:
                raise AcquisitionNetworkError(
                    f"Network error while requesting {current_url}"
                ) from exc
    finally:
        if owns_client:
            active_client.close()
