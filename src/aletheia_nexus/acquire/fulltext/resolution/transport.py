import time
from urllib.parse import urljoin

import httpx

from aletheia_nexus.acquire.fulltext.exceptions import (
    AcquisitionNetworkError,
    AcquisitionRedirectError,
    AcquisitionTooLargeError,
)
from aletheia_nexus.acquire.fulltext.http import (
    REDIRECT_STATUSES,
    build_user_agent,
    raise_for_http_status,
    validate_http_limits,
)
from aletheia_nexus.acquire.fulltext.models import RedirectHop
from aletheia_nexus.acquire.fulltext.resolution.models import RetrievedPage
from aletheia_nexus.acquire.fulltext.safety import validate_safe_url

DEFAULT_PAGE_TIMEOUT = 30.0
DEFAULT_MAX_PAGE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_PAGE_REDIRECTS = 8
_READ_CHUNK_BYTES = 64 * 1024
_PDF_SNIFF_BYTES = 8192


def _looks_like_pdf(prefix: bytes) -> bool:
    return b"%PDF-" in prefix[:1024]


def _decode_page(body: bytes, response: httpx.Response) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _is_definitely_textual(content_type: str) -> bool:
    lowered = content_type.lower()
    return "html" in lowered or "xhtml" in lowered or lowered.startswith("text/")


def retrieve_page(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_PAGE_BYTES,
    timeout: float = DEFAULT_PAGE_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_PAGE_REDIRECTS,
    client: httpx.Client | None = None,
) -> RetrievedPage:
    """Safely retrieve a bounded page route while preserving redirect evidence.

    If a route unexpectedly resolves directly to a real PDF, only a small bounded
    prefix is consumed. The final URL is then returned as a direct-file derivation
    signal rather than downloading the PDF twice inside the resolution layer.
    """

    validate_http_limits(
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

                    if status_code in REDIRECT_STATUSES:
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

                    raise_for_http_status(status_code, current_url)

                    content_type = response.headers.get("Content-Type") or ""
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = None
                        if (
                            declared_size is not None
                            and declared_size > max_bytes
                            and _is_definitely_textual(content_type)
                        ):
                            raise AcquisitionTooLargeError(
                                "Declared page size exceeds configured maximum"
                            )

                    chunks: list[bytes] = []
                    bytes_read = 0
                    prefix = bytearray()

                    for chunk in response.iter_bytes(chunk_size=_READ_CHUNK_BYTES):
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
                    allowed_text = not content_type or _is_definitely_textual(
                        content_type
                    )
                    if not allowed_text:
                        return RetrievedPage(
                            requested_url=requested_url,
                            final_url=current_url,
                            http_status=status_code,
                            content_type=content_type or None,
                            text=None,
                            size_bytes=len(body),
                            redirects=tuple(redirects),
                            elapsed_seconds=time.perf_counter() - started_at,
                        )

                    return RetrievedPage(
                        requested_url=requested_url,
                        final_url=current_url,
                        http_status=status_code,
                        content_type=content_type or None,
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
