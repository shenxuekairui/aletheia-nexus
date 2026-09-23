import hashlib
import tempfile
import time
from pathlib import Path
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
from aletheia_nexus.acquire.fulltext.models import RedirectHop, RetrievedResource
from aletheia_nexus.acquire.fulltext.safety import validate_safe_url

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 8


def _new_temp_path(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=".aletheia-",
        suffix=".part",
        dir=output_dir,
        delete=False,
    )
    path = Path(handle.name)
    handle.close()
    return path


def retrieve_to_temp(
    url: str,
    *,
    output_dir: str | Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    client: httpx.Client | None = None,
) -> RetrievedResource:
    """Safely retrieve one external URL into a temporary local file.

    Redirects are handled manually so every target can be safety-checked before
    the next request. The response is streamed and bounded by ``max_bytes``.
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
    temp_path: Path | None = None
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
                        "Accept": "application/pdf,*/*;q=0.8",
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

                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        try:
                            declared_size = int(content_length)
                        except ValueError:
                            declared_size = None
                        if declared_size is not None and declared_size > max_bytes:
                            raise AcquisitionTooLargeError(
                                "Declared response size exceeds configured maximum"
                            )

                    temp_path = _new_temp_path(Path(output_dir))
                    digest = hashlib.sha256()
                    bytes_written = 0

                    try:
                        with temp_path.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                if not chunk:
                                    continue
                                bytes_written += len(chunk)
                                if bytes_written > max_bytes:
                                    raise AcquisitionTooLargeError(
                                        "Downloaded response exceeds configured maximum"
                                    )
                                digest.update(chunk)
                                handle.write(chunk)
                    except Exception:
                        temp_path.unlink(missing_ok=True)
                        temp_path = None
                        raise

                    return RetrievedResource(
                        requested_url=requested_url,
                        final_url=current_url,
                        http_status=status_code,
                        content_type=response.headers.get("Content-Type"),
                        size_bytes=bytes_written,
                        sha256=digest.hexdigest(),
                        local_path=temp_path,
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
