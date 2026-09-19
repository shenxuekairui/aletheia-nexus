import hashlib
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

import httpx

from aletheia_nexus.acquire.access.artifact import finalize_access_resource
from aletheia_nexus.acquire.access.models import (
    ElsevierAccessAttempt,
    ElsevierAccessConfig,
    ElsevierAccessStatus,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.fulltext.http import REDIRECT_STATUSES, build_user_agent
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionStatus,
    RedirectHop,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.safety import validate_safe_url
from aletheia_nexus.core.identifiers.doi import normalize_doi

_ELSEVIER_API_ROOT = "https://api.elsevier.com/content/article/doi/"


def _validate_config(config: ElsevierAccessConfig) -> None:
    if not isinstance(config, ElsevierAccessConfig):
        raise TypeError("config must be an ElsevierAccessConfig")
    if not isinstance(config.api_key, str) or not config.api_key.strip():
        raise ValueError("Elsevier api_key must be a non-empty string")
    for name in ("inst_token", "bearer_token"):
        value = getattr(config, name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"Elsevier {name} must be a non-empty string or None")
    if (
        isinstance(config.timeout, bool)
        or not isinstance(config.timeout, (int, float))
        or config.timeout <= 0
    ):
        raise ValueError("Elsevier timeout must be a positive number")
    if (
        not isinstance(config.max_bytes, int)
        or isinstance(config.max_bytes, bool)
        or config.max_bytes < 1
    ):
        raise ValueError("Elsevier max_bytes must be a positive integer")
    if not isinstance(config.allow_author_manuscript_fallback, bool):
        raise TypeError("Elsevier allow_author_manuscript_fallback must be a boolean")
    if not isinstance(config.keep_unverified, bool):
        raise TypeError("Elsevier keep_unverified must be a boolean")
    if (
        not isinstance(config.max_redirects, int)
        or isinstance(config.max_redirects, bool)
        or config.max_redirects < 0
    ):
        raise ValueError("Elsevier max_redirects must be a non-negative integer")


def _credential_modes(config: ElsevierAccessConfig) -> tuple[str, ...]:
    modes = ["api_key"]
    if config.inst_token:
        modes.append("institution_token")
    if config.bearer_token:
        modes.append("bearer_token")
    return tuple(modes)


def _headers(config: ElsevierAccessConfig, *, url: str) -> dict[str, str]:
    """Return request headers without leaking Elsevier credentials cross-origin."""

    headers = {
        "Accept": "application/pdf",
        "User-Agent": build_user_agent(),
    }
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    if hostname != "api.elsevier.com":
        return headers

    headers["X-ELS-APIKey"] = config.api_key
    headers["X-ELS-ResourceVersion"] = "new"
    if config.inst_token:
        headers["X-ELS-Insttoken"] = config.inst_token
    if config.bearer_token:
        headers["Authorization"] = f"Bearer {config.bearer_token}"
    return headers


def _candidate(doi: str, endpoint: str) -> FullTextCandidate:
    return FullTextCandidate(
        doi=doi,
        url=endpoint,
        provenance=(),
        url_type=CandidateUrlType.PDF,
        host_type=HostType.PUBLISHER,
        source_name="Elsevier Article Retrieval API",
    )


def _status_for_error_response(response: httpx.Response) -> ElsevierAccessStatus:
    if response.status_code == 401:
        return ElsevierAccessStatus.AUTH_REQUIRED
    if response.status_code == 403:
        try:
            text = response.read()[:65_536].decode("utf-8", errors="ignore").lower()
        except Exception:
            text = ""
        if "entitl" in text or "subscription" in text:
            return ElsevierAccessStatus.ENTITLEMENT_REQUIRED
        return ElsevierAccessStatus.ACCESS_DENIED
    if response.status_code == 404:
        return ElsevierAccessStatus.NOT_FOUND
    if response.status_code == 429:
        return ElsevierAccessStatus.RATE_LIMITED
    if 500 <= response.status_code < 600:
        return ElsevierAccessStatus.SERVICE_ERROR
    return ElsevierAccessStatus.INVALID_RESPONSE


def acquire_elsevier_pdf(
    doi: str,
    *,
    config: ElsevierAccessConfig,
    output_dir: str | Path,
    expected_title: str | None = None,
) -> ElsevierAccessAttempt:
    """Retrieve an entitled ScienceDirect article through Elsevier's official API."""

    _validate_config(config)
    normalized_doi = normalize_doi(doi)
    started_at = time.perf_counter()
    endpoint = _ELSEVIER_API_ROOT + quote(normalized_doi, safe="/")
    if config.allow_author_manuscript_fallback:
        endpoint += "?amsRedirect=true"
    endpoint = validate_safe_url(endpoint)
    candidate = _candidate(normalized_doi, endpoint)
    credential_modes = _credential_modes(config)
    redirects: list[RedirectHop] = []
    current_url = endpoint

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f".an-elsevier-{uuid4().hex}.part"

    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=config.timeout,
        ) as client:
            while True:
                with client.stream(
                    "GET",
                    current_url,
                    headers=_headers(config, url=current_url),
                ) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            return ElsevierAccessAttempt(
                                status=ElsevierAccessStatus.INVALID_RESPONSE,
                                http_status=response.status_code,
                                credential_modes=credential_modes,
                                error="Elsevier API redirect omitted Location",
                                elapsed_seconds=time.perf_counter() - started_at,
                            )
                        if len(redirects) >= config.max_redirects:
                            return ElsevierAccessAttempt(
                                status=ElsevierAccessStatus.INVALID_RESPONSE,
                                http_status=response.status_code,
                                credential_modes=credential_modes,
                                error="Elsevier API exceeded max_redirects",
                                elapsed_seconds=time.perf_counter() - started_at,
                            )
                        next_url = validate_safe_url(
                            urljoin(str(response.url), location)
                        )
                        redirects.append(
                            RedirectHop(
                                from_url=str(response.url),
                                status_code=response.status_code,
                                location=location,
                                to_url=next_url,
                            )
                        )
                        current_url = next_url
                        continue

                    if response.status_code != 200:
                        status = _status_for_error_response(response)
                        return ElsevierAccessAttempt(
                            status=status,
                            http_status=response.status_code,
                            credential_modes=credential_modes,
                            error=f"Elsevier API returned HTTP {response.status_code}",
                            elapsed_seconds=time.perf_counter() - started_at,
                        )

                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > config.max_bytes:
                                return ElsevierAccessAttempt(
                                    status=ElsevierAccessStatus.INVALID_RESPONSE,
                                    http_status=200,
                                    credential_modes=credential_modes,
                                    error=(
                                        "Elsevier API PDF exceeds max_bytes "
                                        f"({content_length} > {config.max_bytes})"
                                    ),
                                    elapsed_seconds=time.perf_counter() - started_at,
                                )
                        except ValueError:
                            pass

                    digest = hashlib.sha256()
                    size = 0
                    first_bytes = bytearray()
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > config.max_bytes:
                                handle.close()
                                temporary.unlink(missing_ok=True)
                                return ElsevierAccessAttempt(
                                    status=ElsevierAccessStatus.INVALID_RESPONSE,
                                    http_status=200,
                                    credential_modes=credential_modes,
                                    error="Elsevier API PDF exceeded max_bytes while streaming",
                                    elapsed_seconds=time.perf_counter() - started_at,
                                )
                            if len(first_bytes) < 1024:
                                first_bytes.extend(chunk[: 1024 - len(first_bytes)])
                            digest.update(chunk)
                            handle.write(chunk)

                    content_type = response.headers.get("content-type")
                    if (
                        b"%PDF-" not in bytes(first_bytes)
                        and "pdf" not in (content_type or "").lower()
                    ):
                        temporary.unlink(missing_ok=True)
                        return ElsevierAccessAttempt(
                            status=ElsevierAccessStatus.INVALID_RESPONSE,
                            http_status=200,
                            credential_modes=credential_modes,
                            error="Elsevier API returned HTTP 200 but not PDF-like content",
                            elapsed_seconds=time.perf_counter() - started_at,
                        )

                    resource = RetrievedResource(
                        requested_url=endpoint,
                        final_url=str(response.url),
                        http_status=response.status_code,
                        content_type=content_type,
                        size_bytes=size,
                        sha256=digest.hexdigest(),
                        local_path=temporary,
                        redirects=tuple(redirects),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )
                    result = finalize_access_resource(
                        candidate=candidate,
                        resource=resource,
                        output_dir=output_dir,
                        expected_title=expected_title,
                        keep_unverified=config.keep_unverified,
                        transport="elsevier_article_retrieval_api",
                        access_details={
                            "provider": "elsevier",
                            "credential_modes": list(credential_modes),
                            "author_manuscript_fallback_enabled": (
                                config.allow_author_manuscript_fallback
                            ),
                        },
                        access_evidence=(
                            "Retrieved through Elsevier Article Retrieval API",
                            "API credentials were supplied only in request headers",
                        ),
                    )
                    status = (
                        ElsevierAccessStatus.VERIFIED
                        if result.status == AcquisitionStatus.VERIFIED
                        else ElsevierAccessStatus.RETRIEVED_UNVERIFIED
                    )
                    return ElsevierAccessAttempt(
                        status=status,
                        result=result,
                        http_status=200,
                        credential_modes=credential_modes,
                        elapsed_seconds=time.perf_counter() - started_at,
                    )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        return ElsevierAccessAttempt(
            status=ElsevierAccessStatus.ERROR,
            credential_modes=credential_modes,
            error=type(exc).__name__,
            elapsed_seconds=time.perf_counter() - started_at,
        )
