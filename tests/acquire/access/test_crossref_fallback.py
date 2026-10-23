from dataclasses import replace

import pytest

from aletheia_nexus.acquire.access import service
from aletheia_nexus.acquire.access.browser import BrowserSession
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    BrowserRecoveryResult,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.discovery import crossref
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryResult,
    FullTextCandidate,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.fulltext.models import AcquisitionResult, AcquisitionStatus
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FileAttempt,
    FileCandidateOrigin,
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
)
from aletheia_nexus.acquire.metadata.crossref import parse_crossref_work
from aletheia_nexus.acquire.metadata.exceptions import MetadataNetworkError

DOI = "10.1000/target"
ORIGINAL = FullTextCandidate(
    DOI, "https://publisher.example/article", (), CandidateUrlType.LANDING_PAGE
)
PDF = "https://cdn.example/resource.pdf"


def metadata():
    return parse_crossref_work(
        {
            "DOI": DOI,
            "title": ["Target Article"],
            "link": [
                {
                    "URL": PDF,
                    "content-type": "application/pdf",
                    "content-version": "vor",
                }
            ],
        }
    )


def base_result(**changes):
    base = MultiRouteAcquisitionResult(
        doi=DOI,
        status=FullTextAcquisitionStatus.NO_CANDIDATES,
        discovery=DiscoveryResult(DOI, (ORIGINAL,), ()),
        expected_title="Target Article",
    )
    return replace(base, **changes)


def attempt(status=BrowserAttemptStatus.NO_FILE_CANDIDATES, **changes):
    return BrowserAccessAttempt(ORIGINAL, ORIGINAL.url, status, **changes)


@pytest.fixture
def harness(monkeypatch, tmp_path):
    calls = []

    def lookup(*args, **kwargs):
        calls.append("lookup")
        return metadata()

    monkeypatch.setattr(crossref, "get_crossref_metadata", lookup)
    monkeypatch.setattr(service, "acquire_full_text", lambda *a, **k: base_result())

    def browser(**options):
        urls = [c.url for c in options["routes"]]
        calls.append(urls)
        if PDF in urls:
            selected = next(c for c in options["routes"] if c.url == PDF)
            verified = AcquisitionResult(
                selected, AcquisitionStatus.VERIFIED, file_path=tmp_path / "article.pdf"
            )
            return BrowserRecoveryResult(DOI, verified_result=verified)
        return BrowserRecoveryResult(DOI, attempts=(attempt(),))

    monkeypatch.setattr(service, "acquire_with_browser", browser)
    return calls


def acquire(tmp_path, **options):
    options.setdefault("browser_config", BrowserAccessConfig(cnki_enabled=False))
    return service.acquire_full_text_maximized(
        DOI, output_dir=tmp_path, auto_official_api=False, **options
    )


def test_original_browser_success_adds_zero_calls(monkeypatch, tmp_path, harness):
    verified = AcquisitionResult(ORIGINAL, AcquisitionStatus.VERIFIED)
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: BrowserRecoveryResult(DOI, verified_result=verified),
    )
    result = acquire(tmp_path)
    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert harness == []


def test_public_success_never_reaches_browser_or_crossref(
    monkeypatch, tmp_path, harness
):
    verified = AcquisitionResult(ORIGINAL, AcquisitionStatus.VERIFIED)
    monkeypatch.setattr(
        service,
        "acquire_full_text",
        lambda *a, **k: base_result(
            status=FullTextAcquisitionStatus.VERIFIED, verified_result=verified
        ),
    )
    assert acquire(tmp_path).status == MaximizedAcquisitionStatus.VERIFIED
    assert harness == []


@pytest.mark.parametrize(
    "status,extra",
    [
        (BrowserAttemptStatus.INTERACTION_REQUIRED, {}),
        (BrowserAttemptStatus.AMBIGUOUS, {}),
        (BrowserAttemptStatus.RETRIEVED_UNVERIFIED, {}),
        (BrowserAttemptStatus.RETRIEVAL_FAILED, {"download_started": True}),
        (
            BrowserAttemptStatus.ENTITLEMENT_REQUIRED,
            {
                "file_attempts": (
                    BrowserFileAttempt(
                        ORIGINAL,
                        AcquisitionResult(
                            ORIGINAL, AcquisitionStatus.RETRIEVED_UNVERIFIED
                        ),
                    ),
                )
            },
        ),
    ],
)
def test_pending_interaction_or_file_is_never_displaced(
    monkeypatch, tmp_path, harness, status, extra
):
    pending = attempt(status, **extra)
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: BrowserRecoveryResult(DOI, attempts=(pending,)),
    )
    result = acquire(tmp_path)
    assert result.browser_attempts == (pending,)
    assert harness == []


def test_failure_fetches_once_then_only_new_candidates(tmp_path, harness):
    result = acquire(tmp_path)
    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert harness[1:] == ["lookup", [PDF]]
    assert ORIGINAL.url in harness[0]
    assert result.base_result.discovery.providers[-1].attempts == 1
    assert result.base_result.metadata.links[0].url == PDF


def test_reuses_existing_metadata_and_caller_browser_session(
    monkeypatch, tmp_path, harness
):
    monkeypatch.setattr(
        service, "acquire_full_text", lambda *a, **k: base_result(metadata=metadata())
    )
    session = BrowserSession(BrowserAccessConfig(cnki_enabled=False))
    monkeypatch.setattr(session, "acquire", service.acquire_with_browser)
    result = service.acquire_full_text_maximized(
        DOI, output_dir=tmp_path, auto_official_api=False, browser_session=session
    )
    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert "lookup" not in harness
    assert harness[-1] == [PDF]
    assert result.base_result.discovery.providers[-1].attempts == 0


@pytest.mark.parametrize(
    "base_changes,options",
    [
        ({"metadata_error": "already failed"}, {}),
        ({}, {"auto_metadata": False}),
        (
            {},
            {
                "browser_config": BrowserAccessConfig(
                    cnki_enabled=False, max_source_routes=1
                )
            },
        ),
    ],
)
def test_no_repeated_or_disabled_lookup_and_no_budget_reset(
    monkeypatch, tmp_path, harness, base_changes, options
):
    monkeypatch.setattr(
        service, "acquire_full_text", lambda *a, **k: base_result(**base_changes)
    )
    assert acquire(tmp_path, **options).status == MaximizedAcquisitionStatus.EXHAUSTED
    assert len(harness) == 1


def test_crossref_unavailable_preserves_original_entitlement(
    monkeypatch, tmp_path, harness
):
    def unavailable(*a, **k):
        harness.append("lookup")
        raise MetadataNetworkError("offline")

    monkeypatch.setattr(crossref, "get_crossref_metadata", unavailable)
    original = attempt(BrowserAttemptStatus.ENTITLEMENT_REQUIRED)
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: BrowserRecoveryResult(DOI, attempts=(original,)),
    )
    result = acquire(tmp_path)
    assert result.status == MaximizedAcquisitionStatus.ENTITLEMENT_REQUIRED
    assert result.browser_attempts == (original,)
    assert harness == ["lookup"]
    assert (
        result.base_result.discovery.providers[-1].status
        == ProviderDiscoveryStatus.NETWORK_ERROR
    )


def test_previously_attempted_pdf_redirect_is_not_retried(
    monkeypatch, tmp_path, harness
):
    monkeypatch.setattr(
        service, "acquire_full_text", lambda *a, **k: base_result(metadata=metadata())
    )
    original = replace(attempt(), final_url=PDF + "#page=1")
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: BrowserRecoveryResult(DOI, attempts=(original,)),
    )
    result = acquire(tmp_path)
    assert result.status == MaximizedAcquisitionStatus.EXHAUSTED
    assert result.base_result.discovery.providers[-1].candidates == ()
    assert harness == []


def test_supplement_uses_remaining_route_budget(monkeypatch, tmp_path, harness):
    record = metadata()
    record = replace(
        record,
        links=tuple(
            replace(record.links[0], url=f"https://cdn.example/{n}.pdf")
            for n in range(8)
        ),
    )
    monkeypatch.setattr(
        service, "acquire_full_text", lambda *a, **k: base_result(metadata=record)
    )
    result = acquire(
        tmp_path,
        browser_config=BrowserAccessConfig(cnki_enabled=False, max_source_routes=2),
    )
    assert result.status == MaximizedAcquisitionStatus.EXHAUSTED
    assert len(harness) == 2
    assert len(harness[1]) == 1  # One of two slots was consumed by the old route.
    assert len(result.base_result.discovery.providers[-1].candidates) == 1


def test_optional_browser_error_keeps_original_access_outcome(
    monkeypatch, tmp_path, harness
):
    calls = []

    def browser(**options):
        calls.append(options["routes"])
        if len(calls) == 2:
            raise RuntimeError("supplementary browser route failed")
        return BrowserRecoveryResult(
            DOI, attempts=(attempt(BrowserAttemptStatus.ENTITLEMENT_REQUIRED),)
        )

    monkeypatch.setattr(service, "acquire_with_browser", browser)
    result = acquire(tmp_path)
    assert result.status == MaximizedAcquisitionStatus.ENTITLEMENT_REQUIRED
    assert result.browser_attempts[-1].error == "Crossref fallback: RuntimeError"
    assert harness == ["lookup"]


def test_retained_public_pdf_prevents_extra_discovery(monkeypatch, tmp_path, harness):
    unverified = AcquisitionResult(ORIGINAL, AcquisitionStatus.RETRIEVED_UNVERIFIED)
    base = base_result(
        file_attempts=(
            FileAttempt(
                ORIGINAL,
                FileCandidateOrigin.DISCOVERY,
                unverified,
            ),
        )
    )
    monkeypatch.setattr(service, "acquire_full_text", lambda *a, **k: base)
    acquire(tmp_path)
    assert len(harness) == 1  # Original browser recovery only.
