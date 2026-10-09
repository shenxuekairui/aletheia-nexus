import hashlib
import json
from types import SimpleNamespace

import pytest
from pypdf.errors import PdfReadError

from aletheia_nexus.acquire.access import audit, browser, browser_route
from aletheia_nexus.acquire.access.batch import acquire_full_text_batch_maximized
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ChallengeKind,
    ChallengeReport,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.access.publisher_adapters import adapter_for_url
from aletheia_nexus.acquire.access.security import redact_url_for_record
from aletheia_nexus.acquire.discovery.models import FullTextCandidate


def test_completed_pdf_snapshot_does_not_read_body_at_headers():
    handlers = {}
    context = SimpleNamespace(on=lambda name, fn: handlers.update({name: fn}), pages=[])
    timing = {"responseEnd": -1}
    bodies = []
    response = SimpleNamespace(
        url="https://publisher.example/doi/pdf/10.1000/test",
        headers={"content-type": "application/pdf"},
        status=200,
        request=SimpleNamespace(timing=timing),
        body=lambda: bodies.append(True) or b"%PDF-test",
    )
    captured = []
    browser._install_context_event_capture(
        context,
        pdf_responses=captured,
        downloads=[],
        snapshot_pdf_responses=True,
        max_bytes=100,
    )
    handlers["response"](response)
    assert bodies == [] and captured == []
    # Fulfilled/cache responses can lack timing metrics even when the browser
    # has emitted its authoritative completion event.
    handlers["requestfinished"](SimpleNamespace(response=lambda: response))
    assert bodies == [True] and captured[0].body() == b"%PDF-test"


def test_live_unfinished_pdf_response_is_not_read(tmp_path):
    response = SimpleNamespace(
        url="https://publisher.example/a.pdf",
        headers={},
        request=SimpleNamespace(timing={"responseEnd": -1}),
        body=lambda: pytest.fail("must not block waiting for a live body"),
    )
    result = browser_route._browser_response_to_file_attempt(
        response,
        parent=FullTextCandidate(doi="10.1000/test", url=response.url, provenance=()),
        source_page_url=response.url,
        output_dir=tmp_path,
        expected_title="Test",
        config=BrowserAccessConfig(),
    )
    assert result.result is None and "still loading" in result.error


@pytest.mark.parametrize(
    "path",
    [
        "/doi/pdf/10.1126/test",
        "/doi/epdf/10.1002/test",
        "/doi/pdfdirect/10.1002/test",
        "/article.pdf",
        "/article/pdf",
    ],
)
def test_loaded_pdf_route_is_recognized_without_filename(path):
    assert browser._attached_page_is_pdf("https://publisher.example" + path)
    assert not browser._attached_page_is_pdf(
        "https://publisher.example/doi/abs/10.1000/test"
    )


def test_linkinghub_uses_observed_official_pii():
    candidate = FullTextCandidate(
        doi="10.1016/j.desal.2024.118392",
        url="https://linkinghub.elsevier.com/retrieve/pii/S0011916424011032",
        provenance=(),
    )
    _, routes, errors = browser._normalize_routes(
        doi=candidate.doi, routes=[candidate], limit=2
    )
    assert errors == []
    assert (
        routes[0].url
        == "https://www.sciencedirect.com/science/article/pii/S0011916424011032"
    )
    assert (
        adapter_for_url(
            "https://linkinghub.elsevier.com.evil.test/retrieve/pii/S0011916424011032"
        ).name
        == "generic"
    )


def test_loaded_viewer_failure_falls_back_without_closing_user_tab(
    monkeypatch, tmp_path
):
    from test_browser_session import _AttachedContext, _AttachedManager, _AttachedPage

    page = _AttachedPage(
        "https://publisher.example/doi/pdf/10.1000/test", title="article.pdf"
    )
    context = _AttachedContext(page)
    manager = _AttachedManager(context)
    calls = []
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def attempt(ctx, chosen, *, source, **kwargs):
        calls.append((chosen, kwargs.get("_navigate_source", True)))
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)
    with browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path, cdp_endpoint="http://127.0.0.1:9222")
    ) as session:
        session.acquire(
            doi="10.1000/test",
            routes=[
                FullTextCandidate(
                    doi="10.1000/test",
                    url="https://publisher.example/doi/abs/10.1000/test",
                    provenance=(),
                )
            ],
            output_dir=tmp_path,
        )
    assert len(calls) == 2
    assert calls[0] == (page, False) and calls[1][1] is True
    assert page.closed is False and calls[1][0].closed is True


def test_batch_revisits_only_a_cleared_challenge_and_keeps_history(
    monkeypatch, tmp_path
):
    import aletheia_nexus.acquire.access.batch as module

    calls = []
    session = browser.BrowserSession()
    monkeypatch.setattr(session, "interaction_ready", lambda doi: doi == "10.1000/one")

    def acquire(doi, **kwargs):
        calls.append(doi)
        waiting = doi == "10.1000/one" and calls.count(doi) == 1
        return SimpleNamespace(
            status=MaximizedAcquisitionStatus.INTERACTION_REQUIRED
            if waiting
            else MaximizedAcquisitionStatus.EXHAUSTED,
            verified_path=None,
            verified_result=None,
            elapsed_seconds=0,
        )

    monkeypatch.setattr(module, "acquire_full_text_maximized", acquire)
    checkpoint = tmp_path / "checkpoint.json"
    result = acquire_full_text_batch_maximized(
        ["10.1000/one", "10.1000/two"],
        output_dir=tmp_path,
        browser_session=session,
        checkpoint_path=checkpoint,
    )
    assert calls == ["10.1000/one", "10.1000/two", "10.1000/one"]
    assert result.items[0].attempts == 2
    record = json.loads(checkpoint.read_text())["records"]["10.1000/one"]
    assert [x["status"] for x in record["attempt_history"]] == [
        "INTERACTION_REQUIRED",
        "EXHAUSTED",
    ]


def test_hard_entitlement_does_not_click_institution_again(monkeypatch):
    boundary = ChallengeReport(
        kind=ChallengeKind.ENTITLEMENT, evidence=("Target restricted",)
    )
    monkeypatch.setattr(browser_route, "_report_for_page", lambda page: boundary)
    monkeypatch.setattr(
        browser_route,
        "_click_semantic_institution_control",
        lambda page: pytest.fail(
            "must not reselect an institution at an explicit boundary"
        ),
    )
    clicked, _, _, final = browser_route._run_institution_handoff(
        None, object(), config=BrowserAccessConfig()
    )
    assert clicked is False and final == boundary


def test_font_text_audit_warning_preserves_verified_file(monkeypatch, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-synthetic")
    pdf.with_suffix(".acquisition.json").write_text(
        json.dumps(
            {
                "status": "VERIFIED",
                "target": {"doi": "10.1000/test"},
                "retrieval": {"sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
                "identity_validation": {"status": "MATCH", "document_role": "ARTICLE"},
            }
        )
    )

    def broken_text():
        raise PdfReadError("multiple font streams")

    monkeypatch.setattr(
        audit,
        "PdfReader",
        lambda path: SimpleNamespace(pages=[SimpleNamespace(extract_text=broken_text)]),
    )
    result = audit.audit_verified_pdf(pdf, doi="10.1000/test")
    assert result["status"] == "WARNING" and result["warnings"] == ["PdfReadError"]
    success = {"status": "VERIFIED", "verified_path": str(pdf), "audit": result}
    latest = {"status": "INTERACTION_REQUIRED", "verified_path": None}
    merged = audit.summarize_attempt_history([success, latest])
    assert merged["latest_attempt"] == latest and merged["best_verified"] == success
    assert merged["effective_status"] == "VERIFIED" and pdf.exists()


def test_path_session_values_are_redacted():
    url = "https://publisher.example/login;jsessionid=private;other=ok?ticket=secret#token"
    safe = redact_url_for_record(url)
    assert "private" not in safe and "secret" not in safe and "#" not in safe
    assert ";other=ok" in safe


@pytest.mark.parametrize("native_only", [False, True])
def test_post_click_endpoint_challenge_stops_replays(
    monkeypatch, tmp_path, native_only
):
    from test_browser_challenge_flow import _RouteContext, _RoutePage

    from aletheia_nexus.acquire.access.models import BrowserFileAttempt

    page = _RoutePage("https://onlinelibrary.wiley.com/doi/10.1002/example")
    context = _RouteContext(page)
    source = FullTextCandidate(doi="10.1002/example", url=page.url, provenance=())
    responses = []
    requests = []
    clear = ChallengeReport(kind=ChallengeKind.NONE)
    challenge = ChallengeReport(kind=ChallengeKind.CAPTCHA, evidence=("PDF gate",))
    monkeypatch.setattr(browser_route, "_report_for_page", lambda p: clear)
    monkeypatch.setattr(
        browser_route, "_resolve_page_challenge", lambda p, **k: (clear, (), False)
    )
    monkeypatch.setattr(
        browser_route,
        "validate_page_identity",
        lambda **k: SimpleNamespace(status=SimpleNamespace(value="MATCH"), evidence=()),
    )
    monkeypatch.setattr(browser_route, "parse_html", lambda html: object())
    monkeypatch.setattr(browser_route, "derive_pdf_candidates", lambda **k: ())
    monkeypatch.setattr(
        browser_route, "_trigger_embedded_pdf_frame_fetch", lambda *a, **k: None
    )
    monkeypatch.setattr(
        browser_route, "_trigger_pdf_viewer_same_origin_fetch", lambda *a, **k: False
    )
    monkeypatch.setattr(browser_route, "_trigger_pdf_viewer_save", lambda *a, **k: None)
    monkeypatch.setattr(
        browser_route, "_runtime_publisher_pdf_candidate", lambda *a: None
    )
    monkeypatch.setattr(
        browser_route, "_ieee_selected_institution_available", lambda p: False
    )
    monkeypatch.setattr(
        browser_route,
        "_run_institution_handoff",
        lambda *a, **k: (False, (), False, clear),
    )
    monkeypatch.setattr(
        browser_route,
        "_browser_response_to_file_attempt",
        lambda response, **k: BrowserFileAttempt(candidate=source, error="HTML gate"),
    )

    def click(p):
        responses.extend(
            SimpleNamespace(url=f"https://onlinelibrary.wiley.com/{i}.pdf")
            for i in range(2)
        )
        return True

    def request(context, *, candidate, **kwargs):
        requests.append(candidate.url)
        return BrowserFileAttempt(
            candidate=candidate, error="Endpoint challenge"
        ), challenge

    monkeypatch.setattr(browser_route, "_click_semantic_pdf_control", click)
    monkeypatch.setattr(browser_route, "_request_pdf_candidate", request)
    result = browser_route.attempt_browser_route(
        context,
        page,
        source=source,
        output_dir=tmp_path,
        expected_title="Article",
        config=BrowserAccessConfig(),
        session_blocked_urls=[],
        session_pdf_responses=responses,
        session_downloads=[],
        _navigate_source=False,
        _browser_native_only=native_only,
    )
    assert requests == (
        [] if native_only else ["https://onlinelibrary.wiley.com/0.pdf"]
    )
    assert result.status == BrowserAttemptStatus.RETRIEVAL_FAILED
    if not native_only:
        assert page.goto_calls == ["https://onlinelibrary.wiley.com/0.pdf"]
        assert challenge in result.challenge_history
        assert result.challenge_history[-1].kind == ChallengeKind.NONE


@pytest.mark.parametrize(
    ("label", "href", "expected"),
    [
        (
            "Manage Your Institutional Subscription",
            "/action/institutionAccessEntitlements",
            False,
        ),
        (
            "Institutional access",
            "/action/ssostart?redirectUri=%2Faction%2FinstitutionAccessEntitlements",
            False,
        ),
        ("Institutional login for librarians", "/librarian/login", False),
        ("Log in to manage your subscription", "/subscriptions", False),
        (
            "Access through your institution",
            "/action/ssostart?redirectUri=%2Fdoi%2F10.1126%2Fexample",
            True,
        ),
        ("Access via OpenAthens", "/openathens", True),
    ],
)
def test_institution_access_excludes_administration(label, href, expected):
    item = SimpleNamespace(
        get_attribute=lambda name, timeout=0: href if name == "href" else None
    )
    assert browser_route._is_reader_institution_control(item, label) is expected
