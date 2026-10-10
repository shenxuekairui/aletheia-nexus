"""Resumable sequential batch orchestration for the v0.6 access layer."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from aletheia_nexus.acquire.access.browser import BrowserSession
from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    MaximizedAcquisitionResult,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.access.publisher_routes import is_ieee_doi
from aletheia_nexus.acquire.access.service import acquire_full_text_maximized
from aletheia_nexus.acquire.fulltext.storage import organized_output
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.organization import destination
from aletheia_nexus.core.paper_request import PaperRequest

_CHECKPOINT_SCHEMA = "aletheia-nexus/access-batch-checkpoint/v1"


def _organization(value):
    return (
        value
        if isinstance(value, PaperRequest)
        and (value.folder or value.filename or value.tags)
        else None
    )


def _acquire_item(value, *, output_dir, **kwargs):
    request = value if isinstance(value, PaperRequest) else None
    directory = destination(output_dir, request.folder) if request else output_dir
    with organized_output(request):
        return acquire_full_text_maximized(value, output_dir=directory, **kwargs)


class BatchItemStatus(StrEnum):
    """Stable outcome for one input in a maximized-acquisition batch."""

    VERIFIED = "VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"
    RETRIEVED_UNVERIFIED = "RETRIEVED_UNVERIFIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INTERACTION_REQUIRED = "INTERACTION_REQUIRED"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    UNSAFE_URL = "UNSAFE_URL"
    EXHAUSTED = "EXHAUSTED"
    ERROR = "ERROR"
    INVALID_DOI = "INVALID_DOI"
    RUNNER_ERROR = "RUNNER_ERROR"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True, slots=True)
class BatchAcquisitionItem:
    """One ordered batch item, including resume and retry evidence."""

    input_value: object
    doi: str | None
    status: BatchItemStatus
    result: MaximizedAcquisitionResult | None = None
    verified_path: Path | None = None
    resumed: bool = False
    attempts: int = 0
    error: str | None = None
    elapsed_seconds: float = 0.0
    request_key: str | None = None


@dataclass(frozen=True, slots=True)
class BatchAcquisitionResult:
    """Complete outcome for a sequential, resumable acquisition batch."""

    items: tuple[BatchAcquisitionItem, ...]
    checkpoint_path: Path | None = None
    halted_for_interaction: bool = False
    elapsed_seconds: float = 0.0

    @property
    def status_counts(self) -> dict[str, int]:
        return dict(Counter(item.status.value for item in self.items))

    @property
    def verified_count(self) -> int:
        return sum(item.status == BatchItemStatus.VERIFIED for item in self.items)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_checkpoint(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid batch checkpoint: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _CHECKPOINT_SCHEMA:
        raise ValueError("Unsupported batch checkpoint schema")
    records = payload.get("records")
    if not isinstance(records, dict):
        raise ValueError("Batch checkpoint records must be an object")
    return {
        key: value
        for key, value in records.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _write_checkpoint(
    path: Path,
    records: Mapping[str, Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    payload = {
        "schema": _CHECKPOINT_SCHEMA,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _verified_checkpoint_item(
    input_value: object,
    doi: str | None,
    record: Mapping[str, object] | None,
    request_key: str | None = None,
) -> BatchAcquisitionItem | None:
    if not record or record.get("status") != BatchItemStatus.VERIFIED.value:
        return None
    raw_path = record.get("verified_path")
    sha256 = record.get("sha256")
    if not isinstance(raw_path, str) or not isinstance(sha256, str):
        return None
    path = Path(raw_path)
    if not path.is_file():
        return None
    try:
        if _sha256_file(path) != sha256:
            return None
        sidecar = path.with_suffix(".acquisition.json")
        if not sidecar.is_file() or _sha256_file(sidecar) != record.get(
            "sidecar_sha256"
        ):
            return None
    except OSError:
        return None
    return BatchAcquisitionItem(
        input_value=input_value,
        doi=doi,
        status=BatchItemStatus.VERIFIED,
        verified_path=path,
        resumed=True,
        request_key=request_key,
    )


def _checkpoint_record(
    item: BatchAcquisitionItem, previous: Mapping[str, object] | None = None
) -> dict[str, object]:
    record: dict[str, object] = {
        "doi": item.doi,
        "status": item.status.value,
        "attempts": item.attempts,
        "elapsed_seconds": item.elapsed_seconds,
        "verified_path": None,
        "sha256": None,
    }
    if item.status == BatchItemStatus.VERIFIED and item.verified_path is not None:
        path = item.verified_path.resolve()
        record["verified_path"] = str(path)
        resource = (
            item.result.verified_result.retrieved
            if item.result and item.result.verified_result
            else None
        )
        record["sha256"] = (
            resource.sha256 if resource is not None else _sha256_file(path)
        )
        sidecar = path.with_suffix(".acquisition.json")
        record["sidecar_sha256"] = _sha256_file(sidecar) if sidecar.is_file() else None
    history = (previous or {}).get("attempt_history", [])
    record["attempt_history"] = [
        *(history if isinstance(history, list) else []),
        {"status": item.status.value, "at": datetime.now(timezone.utc).isoformat()},
    ]
    record["resume_stage"] = (
        "ACCESS_CHECK" if item.status == BatchItemStatus.INTERACTION_REQUIRED else None
    )
    return record


def _normalize_titles(
    expected_titles: Mapping[str, str] | None,
) -> dict[str, str]:
    if expected_titles is None:
        return {}
    if not isinstance(expected_titles, Mapping):
        raise TypeError("expected_titles must be a DOI-to-title mapping or None")
    normalized: dict[str, str] = {}
    for raw_doi, title in expected_titles.items():
        doi = normalize_doi(raw_doi)
        if not isinstance(title, str) or not title.strip():
            raise ValueError("expected title values must be non-empty strings")
        normalized[doi] = title.strip()
    return normalized


def acquire_full_text_batch_maximized(
    values: Iterable[object],
    *,
    output_dir: str | Path,
    expected_titles: Mapping[str, str] | None = None,
    local_pdfs: Mapping[str, str | Path] | None = None,
    manual_file_callback: Callable[[str], str | Path | None] | None = None,
    browser_config: BrowserAccessConfig | None = None,
    browser_session: BrowserSession | None = None,
    checkpoint_path: str | Path | None = None,
    resume: bool = True,
    deduplicate: bool = True,
    stop_on_interaction: bool = False,
    max_item_attempts: int = 1,
    retry_backoff: float = 1.0,
    progress_callback: Callable[[BatchAcquisitionItem, int, int], None] | None = None,
    **acquisition_options: object,
) -> BatchAcquisitionResult:
    """Acquire DOI strings or PaperRequests with one reusable browser session.

    Work is deliberately sequential because publisher login/challenge state is shared.
    A checkpoint records no credentials, cookies, URLs, or exception messages. Resume
    trusts only VERIFIED files that still exist and match their recorded SHA-256.
    Non-success outcomes are attempted again on the next run so a newly completed
    login, refreshed institutional session, or corrected entitlement can recover them.
    An unresolved interactive challenge ends that item, as in the installed CLI;
    callers can use ``stop_on_interaction=True`` to defer remaining items.
    """

    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise TypeError(
            "acquire_full_text_batch_maximized() expects an iterable of DOI values"
        )
    if browser_config is not None and not isinstance(
        browser_config, BrowserAccessConfig
    ):
        raise TypeError("browser_config must be a BrowserAccessConfig or None")
    if browser_session is not None and not isinstance(browser_session, BrowserSession):
        raise TypeError("browser_session must be a BrowserSession or None")
    if browser_config is not None and browser_session is not None:
        raise ValueError("browser_config and browser_session are mutually exclusive")
    for name, value in (
        ("resume", resume),
        ("deduplicate", deduplicate),
        ("stop_on_interaction", stop_on_interaction),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name} must be a boolean")
    if (
        not isinstance(max_item_attempts, int)
        or isinstance(max_item_attempts, bool)
        or max_item_attempts < 1
    ):
        raise ValueError("max_item_attempts must be a positive integer")
    if (
        not isinstance(retry_backoff, (int, float))
        or isinstance(retry_backoff, bool)
        or retry_backoff < 0
    ):
        raise ValueError("retry_backoff must be a non-negative number")
    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    if manual_file_callback is not None and not callable(manual_file_callback):
        raise TypeError("manual_file_callback must be callable or None")
    if local_pdfs is not None and not isinstance(local_pdfs, Mapping):
        raise TypeError("local_pdfs must be a DOI-to-path mapping or None")
    if "expected_title" in acquisition_options:
        raise ValueError(
            "Use expected_titles={doi: title} for batch-specific expected titles"
        )
    if "local_pdf_path" in acquisition_options:
        raise ValueError("Use local_pdfs={doi: path} for batch-specific local PDFs")

    titles = _normalize_titles(expected_titles)
    local_files = {
        (
            doi
            if isinstance(doi, str) and doi.startswith("citation:")
            else normalize_doi(doi)
        ): Path(path)
        for doi, path in (local_pdfs or {}).items()
    }
    checkpoint = Path(checkpoint_path) if checkpoint_path is not None else None
    checkpoint_records = (
        _load_checkpoint(checkpoint) if checkpoint is not None and resume else {}
    )
    raw_values = list(values)
    prepared: list[tuple[object, str | None, str | None, str | None]] = []
    seen: set[str] = set()
    for value in raw_values:
        try:
            doi = value.doi if isinstance(value, PaperRequest) else normalize_doi(value)
            key = (
                value.batch_key
                if isinstance(value, PaperRequest)
                else (
                    PaperRequest(doi=doi, title=titles[doi]).key
                    if doi in titles
                    else doi
                )
            )
        except (TypeError, ValueError) as exc:
            prepared.append((value, None, None, str(exc)))
            continue
        if deduplicate and key in seen:
            continue
        seen.add(key)
        prepared.append((value, doi, key, None))

    started_at = time.perf_counter()
    items: list[BatchAcquisitionItem] = []
    halted = False
    owned_session = browser_session is None
    session = browser_session or BrowserSession(browser_config)
    session_scope = session if owned_session else nullcontext(session)

    with session_scope:
        for index, (input_value, doi, key, input_error) in enumerate(prepared, start=1):
            if halted:
                item = BatchAcquisitionItem(
                    input_value=input_value,
                    doi=doi,
                    status=BatchItemStatus.DEFERRED,
                    error="Deferred after an unresolved interactive access challenge",
                )
                items.append(item)
                if progress_callback is not None:
                    progress_callback(item, index, len(prepared))
                continue

            item_started_at = time.perf_counter()
            if input_error is not None:
                item = BatchAcquisitionItem(
                    input_value=input_value,
                    doi=None,
                    status=BatchItemStatus.INVALID_DOI,
                    error=input_error,
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )
                items.append(item)
                if progress_callback is not None:
                    progress_callback(item, index, len(prepared))
                continue

            resumed_item = _verified_checkpoint_item(
                input_value,
                doi or checkpoint_records.get(key, {}).get("doi"),
                checkpoint_records.get(key),
                request_key=key,
            )
            organization = _organization(input_value)
            if organization is not None:
                expected_directory = destination(output_dir, organization.folder)
                if (
                    resumed_item is not None
                    and resumed_item.verified_path.resolve().parent
                    != expected_directory
                ):
                    resumed_item = None
            if resumed_item is not None:
                items.append(resumed_item)
                if progress_callback is not None:
                    progress_callback(resumed_item, index, len(prepared))
                continue

            result: MaximizedAcquisitionResult | None = None
            runner_error: str | None = None
            attempts = 0
            for attempt_number in range(1, max_item_attempts + 1):
                attempts = attempt_number
                try:
                    result = _acquire_item(
                        input_value if isinstance(input_value, PaperRequest) else doi,
                        output_dir=output_dir,
                        browser_session=session,
                        expected_title=titles.get(doi),
                        local_pdf_path=local_files.get(key) or local_files.get(doi),
                        **acquisition_options,
                    )
                    if (
                        result.status == MaximizedAcquisitionStatus.INTERACTION_REQUIRED
                        and doi is not None
                        and is_ieee_doi(doi)
                        and doi not in local_files
                        and manual_file_callback is not None
                    ):
                        chosen = manual_file_callback(doi)
                        if chosen:
                            result = _acquire_item(
                                input_value
                                if isinstance(input_value, PaperRequest)
                                else doi,
                                output_dir=output_dir,
                                browser_session=session,
                                expected_title=titles.get(doi),
                                local_pdf_path=Path(chosen),
                                **acquisition_options,
                            )
                except Exception as exc:
                    # Persist only the exception type. Messages can contain signed URLs,
                    # headers, local profile paths, or provider response fragments.
                    runner_error = type(exc).__name__
                    result = None
                retryable = (
                    result is None or result.status == MaximizedAcquisitionStatus.ERROR
                )
                if result is not None and any(
                    attempt.download_started for attempt in result.browser_attempts
                ):
                    retryable = False
                if not retryable or attempt_number == max_item_attempts:
                    break
                if retry_backoff:
                    time.sleep(float(retry_backoff) * (2 ** (attempt_number - 1)))

            if result is None:
                item = BatchAcquisitionItem(
                    input_value=input_value,
                    doi=doi,
                    status=BatchItemStatus.RUNNER_ERROR,
                    request_key=key,
                    attempts=attempts,
                    error=runner_error,
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )
            else:
                item = BatchAcquisitionItem(
                    input_value=input_value,
                    doi=result.doi or doi,
                    status=BatchItemStatus(result.status.value),
                    request_key=key,
                    result=result,
                    verified_path=result.verified_path,
                    attempts=attempts,
                    elapsed_seconds=time.perf_counter() - item_started_at,
                )

            items.append(item)
            checkpoint_records[key] = _checkpoint_record(
                item, checkpoint_records.get(key)
            )
            if checkpoint is not None:
                _write_checkpoint(checkpoint, checkpoint_records)
            if progress_callback is not None:
                progress_callback(item, index, len(prepared))

            if (
                stop_on_interaction
                and item.status == BatchItemStatus.INTERACTION_REQUIRED
            ):
                halted = True

        # A login for an earlier paper may have completed while later papers
        # ran. Revisit only retained challenges that visibly cleared; never
        # blindly repeat an unchanged login or entitlement boundary.
        if not halted and session.config.interactive:
            for index, item in enumerate(items):
                if (
                    item.status != BatchItemStatus.INTERACTION_REQUIRED
                    or item.doi is None
                ):
                    continue
                if not session.interaction_ready(item.doi):
                    continue
                try:
                    recovered = _acquire_item(
                        item.input_value
                        if isinstance(item.input_value, PaperRequest)
                        else item.doi,
                        output_dir=output_dir,
                        browser_session=session,
                        expected_title=titles.get(item.doi),
                        local_pdf_path=local_files.get(item.request_key)
                        or local_files.get(item.doi),
                        **acquisition_options,
                    )
                except Exception:
                    # Preserve the original result if the recovery runner fails.
                    continue
                fresh = BatchAcquisitionItem(
                    input_value=item.input_value,
                    doi=recovered.doi or item.doi,
                    request_key=item.request_key,
                    status=BatchItemStatus(recovered.status.value),
                    result=recovered,
                    verified_path=recovered.verified_path,
                    attempts=item.attempts + 1,
                    elapsed_seconds=item.elapsed_seconds + recovered.elapsed_seconds,
                )
                items[index] = fresh
                key = item.request_key or item.doi
                checkpoint_records[key] = _checkpoint_record(
                    fresh, checkpoint_records.get(key)
                )
                if checkpoint is not None:
                    _write_checkpoint(checkpoint, checkpoint_records)
                if progress_callback is not None:
                    progress_callback(fresh, index + 1, len(prepared))

    return BatchAcquisitionResult(
        items=tuple(items),
        checkpoint_path=checkpoint,
        halted_for_interaction=halted,
        elapsed_seconds=time.perf_counter() - started_at,
    )
