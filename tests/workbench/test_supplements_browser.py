"""Session borrowing is explicit, DOI-gated and read-only for existing tabs."""

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import supplements, supplements_browser

DOI = "10.1021/ja0659323"
PAGE = "https://pubs.acs.org/jacsat/article/128/51/16414/3525402/Competitive"
FILE = "https://pubs.acs.org/jacsat/article-supplement/3525402/pdf/ja0659323_si_001/"
HTML = f'<meta name="citation_doi" content="{DOI}"><a href="{FILE}">suppl-mat1</a>'


def fake_session(*pages):
    calls = []
    context = SimpleNamespace(pages=list(pages))
    return SimpleNamespace(
        _ensure_started=lambda: calls.append("start") or context,
        pump_events=lambda seconds: calls.append(("pump", seconds)),
        config=SimpleNamespace(max_source_routes=12),
        _context=context,
        calls=calls,
    )


def page(url=PAGE, html=HTML):
    return SimpleNamespace(url=url, html=html, is_closed=lambda: False)


def test_explicit_session_can_start_normally_and_borrow_only_doi_confirmed_page(
    monkeypatch,
):
    wrong = page(html=HTML.replace(DOI, "10.1021/wrong"))
    actual = page()
    session = fake_session(wrong, actual)
    monkeypatch.setattr(
        supplements_browser, "validate_browser_network_url", lambda url: url
    )
    monkeypatch.setattr(
        supplements_browser, "bounded_read", lambda p, *args, **kw: p.html
    )
    transport = supplements_browser.SupplementBrowserTransport(session, doi=DOI)
    found = transport.page_fetch("https://doi.org/" + DOI)
    assert found.text == HTML and found.http_status is None
    assert session.calls == ["start", ("pump", 0)]
    assert transport.pages[PAGE] is actual


def test_missing_or_ambiguous_open_page_is_diagnostic_without_navigating_any_tab(
    monkeypatch,
):
    session = fake_session(page(html=HTML.replace(DOI, "10.1021/other")))
    monkeypatch.setattr(
        supplements_browser, "validate_browser_network_url", lambda url: url
    )
    monkeypatch.setattr(
        supplements_browser, "bounded_read", lambda p, *args, **kw: p.html
    )
    with pytest.raises(
        supplements_browser.SupplementBrowserError,
        match="browser_parent_page_not_available",
    ):
        supplements_browser.SupplementBrowserTransport(session, doi=DOI).page_fetch(
            PAGE
        )
    assert not hasattr(session._context.pages[0], "goto")


def test_si_preserves_precise_connection_diagnostic_without_observing_or_closing_tabs():
    from aletheia_nexus.acquire.access.browser import BrowserCapabilityUnavailable

    details = {
        "code": "browser_cdp_attach_timeout",
        "stage": "cdp_attach",
        "timeout_seconds": 45,
        "websocket_connected": True,
        "endpoint_reachable": True,
        "page_count": 15,
        "pdf_like_page_count": 2,
        "message": "浏览器连接超时；原有标签保留，检查后可仅补取 SI。",
    }

    def unavailable():
        raise BrowserCapabilityUnavailable(details["message"], diagnostic=details)

    adapter = supplements_browser.SupplementBrowserTransport(
        SimpleNamespace(_ensure_started=unavailable), doi=DOI
    )
    with pytest.raises(BrowserCapabilityUnavailable):
        adapter.page_fetch(PAGE)
    assert adapter.diagnostics == [
        {"status": "BROWSER_CONNECTION_UNAVAILABLE", **details}
    ]
    assert not adapter.pages


def test_existing_tab_inventory_is_not_truncated_by_source_route_budget(monkeypatch):
    wrong = [
        page(
            url=f"https://pubs.acs.org/old/{i}", html=HTML.replace(DOI, "10.1021/other")
        )
        for i in range(15)
    ]
    actual = page()
    session = fake_session(*wrong, actual)
    session.config.max_source_routes = 1
    monkeypatch.setattr(
        supplements_browser, "validate_browser_network_url", lambda url: url
    )
    reads = []

    def read(p, *args, **kwargs):
        reads.append(p.url)
        return p.html

    monkeypatch.setattr(supplements_browser, "bounded_read", read)
    result = supplements_browser.SupplementBrowserTransport(
        session, doi=DOI
    ).page_fetch("https://doi.org/" + DOI)
    assert result.final_url == PAGE
    assert reads[0] == PAGE  # Changed canonical/new tab is preferred over old PDFs.


def test_blocked_http_uses_explicit_session_and_saves_real_si_with_original_source_unchanged(
    tmp_path, monkeypatch
):
    main = tmp_path / "main.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with main.open("wb") as f:
        writer.write(f)
    register_local_pdf(main, output_dir=tmp_path, doi=DOI, title="Parent title")
    main_before, source_before = (
        main.read_bytes(),
        validate_parser_input(main).sidecar_path.read_bytes(),
    )
    si = tmp_path / "si-source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=120, height=100)
    with si.open("wb") as f:
        writer.write(f)

    class Browser:
        diagnostics = []

        def __init__(self, session, **kwargs):
            assert session is explicit

        def page_fetch(self, *args, **kwargs):
            return SimpleNamespace(text=HTML, final_url=PAGE)

        def file_fetch(self, url, *, output_dir, **kwargs):
            target = Path(output_dir) / "browser.part"
            target.write_bytes(si.read_bytes())
            return SimpleNamespace(
                local_path=target,
                final_url=url,
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            )

    explicit = object()
    monkeypatch.setattr(supplements_browser, "SupplementBrowserTransport", Browser)

    def blocked(*args, **kwargs):
        raise RuntimeError("public HTTP blocked")

    monkeypatch.setattr(supplements, "_retrieve_official_file", blocked)
    result = supplements.acquire_supplements(
        main, page_urls=[PAGE], page_fetch=blocked, browser_session=explicit
    )
    assert result["status"] == "COMPLETED" and result["errors"] == []
    assert result["items"][0]["transport"] == "browser_session"
    receipt = json.loads(Path(result["items"][0]["source_record"]).read_text("utf-8"))
    assert receipt["transport"] == "browser_session" and receipt["parent"]["doi"] == DOI
    assert result["diagnostics"][0]["status"] == "PAGE_FAILED"
    assert (
        main.read_bytes(),
        validate_parser_input(main).sidecar_path.read_bytes(),
    ) == (main_before, source_before)


def test_no_session_never_starts_browser_on_blocked_public_sources(
    tmp_path, monkeypatch
):
    main = tmp_path / "main.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with main.open("wb") as f:
        writer.write(f)
    register_local_pdf(main, output_dir=tmp_path, doi=DOI, title="Parent title")
    monkeypatch.setattr(
        supplements_browser,
        "SupplementBrowserTransport",
        lambda *a, **k: pytest.fail("no browser authorization"),
    )

    def blocked(*args, **kwargs):
        raise RuntimeError("public HTTP blocked")

    assert (
        supplements.acquire_supplements(main, page_urls=[PAGE], page_fetch=blocked)[
            "status"
        ]
        == "FAILED"
    )


def test_same_origin_pdf_fetch_reuses_bounded_core_script_without_navigation(
    tmp_path, monkeypatch
):
    source = page()
    routes, removed = [], []
    source.route = lambda pattern, handler: routes.append((pattern, handler))
    source.unroute = lambda pattern, handler: removed.append((pattern, handler))
    transport = supplements_browser.SupplementBrowserTransport(
        fake_session(source), doi=DOI
    )
    transport.pages[PAGE] = source
    body = b"%PDF-fixture bytes"

    def read(p, operation, script, params, **kwargs):
        assert p is source and operation == "evaluate"
        assert script is supplements_browser._PDF_FETCH_SCRIPT
        assert params["maxBytes"] == 100 and params["returnBody"] is True
        return {"url": FILE, "bodyBase64": base64.b64encode(body).decode()}

    monkeypatch.setattr(
        supplements_browser, "validate_browser_network_url", lambda url: url
    )
    monkeypatch.setattr(supplements_browser, "bounded_read", read)
    resource = transport.file_fetch(
        FILE,
        source_page=PAGE,
        extension=".pdf",
        output_dir=tmp_path,
        max_bytes=100,
        timeout=2,
    )
    assert resource.local_path.read_bytes() == body
    assert (
        resource.http_status is None
    )  # No fabricated network status from a DOM fetch.
    assert routes == removed and not hasattr(source, "goto")


def test_fetch_redirect_to_other_host_cannot_be_accepted(tmp_path, monkeypatch):
    source = page()
    source.route = lambda *a: None
    source.unroute = lambda *a: None
    transport = supplements_browser.SupplementBrowserTransport(
        fake_session(source), doi=DOI
    )
    transport.pages[PAGE] = source
    monkeypatch.setattr(
        supplements_browser, "validate_browser_network_url", lambda url: url
    )
    monkeypatch.setattr(
        supplements_browser,
        "bounded_read",
        lambda *a, **k: {
            "url": "https://foreign.example/unrelated.pdf",
            "bodyBase64": base64.b64encode(b"%PDF-fake").decode(),
        },
    )
    with pytest.raises(
        supplements_browser.SupplementBrowserError,
        match="attachment_redirect_host_not_covered",
    ):
        transport.file_fetch(
            FILE,
            source_page=PAGE,
            extension=".pdf",
            output_dir=tmp_path,
            max_bytes=100,
            timeout=2,
        )
    assert list(tmp_path.iterdir()) == []


def test_browser_network_url_normalization_keeps_redirect_guard_bound_before_http(
    tmp_path, monkeypatch
):
    source = page()
    handlers, actions = [], []
    source.route = lambda pattern, handler: handlers.append(handler)
    source.unroute = lambda *args: None
    transport = supplements_browser.SupplementBrowserTransport(
        fake_session(source), doi=DOI
    )
    transport.pages[PAGE] = source

    def read(*args, **kwargs):
        # Browser-internal viewer requests retain the original guard behavior.
        internal = SimpleNamespace(
            url="chrome-extension://fixture/internal", redirected_from=None
        )
        handlers[0](
            SimpleNamespace(
                request=internal, fallback=lambda: actions.append("internal_allowed")
            )
        )
        original = SimpleNamespace(url=FILE, redirected_from=None)
        redirect = SimpleNamespace(
            url="https://uncovered.example/other.pdf", redirected_from=original
        )
        handlers[0](
            SimpleNamespace(
                request=redirect,
                abort=lambda _: actions.append("redirect_blocked"),
                fallback=lambda: pytest.fail("foreign redirect reached HTTP"),
            )
        )
        return None

    monkeypatch.setattr(supplements_browser, "bounded_read", read)
    with pytest.raises(
        supplements_browser.SupplementBrowserError, match="unsafe_attachment_redirect"
    ):
        transport.file_fetch(
            FILE + "#supplementary-section",
            source_page=PAGE,
            extension=".pdf",
            output_dir=tmp_path,
            max_bytes=100,
            timeout=1,
        )
    assert actions == ["internal_allowed", "redirect_blocked"]


@pytest.mark.parametrize(
    "oversized,timed_out,cancel_failures",
    [
        (False, False, 0),
        (True, False, 0),
        (False, True, 0),
        (True, False, 1),
        (True, False, 2),
    ],
)
def test_native_capture_does_not_cancel_or_delete_unrelated_user_transfer(
    tmp_path, monkeypatch, oversized, timed_out, cancel_failures
):
    captures = []
    wanted = "https://pubs.acs.org/explicit-supplement.docx"
    unrelated = wanted  # Same URL in another user tab must remain independent.

    class Cdp:
        def __init__(self):
            self.handlers, self.commands = {}, []
            self.remaining_failures = cancel_failures

        def on(self, event, handler):
            self.handlers[event] = handler

        def send(self, method, params):
            self.commands.append((method, params))
            if method == "Browser.cancelDownload" and self.remaining_failures:
                self.remaining_failures -= 1
                raise RuntimeError("simulated browser cancellation failure")

    class Capture:
        active = True
        _context_params = {}

        def __init__(self, context, directory):
            self.session = Cdp()
            self.staging_dir = Path(directory) / "browser-staging"
            self.staging_dir.mkdir(parents=True)
            self.owned = self.staging_dir / "owned-transfer"
            self.other = self.staging_dir / "other-transfer"
            self.owned.write_bytes(b"downloaded fixture")
            self.other.write_bytes(b"preserve this unrelated user download")
            captures.append(self)

        def wait(self, page, seconds, *, expected_url, expected_guid):
            assert expected_url == wanted
            assert expected_guid == "owned-transfer"
            if timed_out:
                return None
            return self.owned, wanted

        def close(self, *, remove_files):
            assert remove_files is False

    class Page:
        def on(self, *args):
            pass

        def route(self, pattern, handler):
            self.guard = handler

        def goto(self, url, **kwargs):
            request = SimpleNamespace(url=url, redirected_from=None)
            self.guard(SimpleNamespace(request=request, fallback=lambda: None))
            cdp = captures[0].session
            cdp.handlers["Browser.downloadWillBegin"](
                {
                    "url": unrelated,
                    "guid": "other-transfer",
                    "frameId": "unrelated-frame",
                }
            )
            cdp.handlers["Browser.downloadProgress"](
                {"guid": "other-transfer", "totalBytes": 10**9}
            )
            cdp.handlers["Browser.downloadWillBegin"](
                {"url": wanted, "guid": "owned-transfer", "frameId": "owned-frame"}
            )
            cdp.handlers["Browser.downloadProgress"](
                {
                    "guid": "owned-transfer",
                    "totalBytes": 200 if oversized else 18,
                    "state": "inProgress" if oversized or timed_out else "completed",
                }
            )

        def is_closed(self):
            return False

        def close(self):
            pass

    session = fake_session()
    session._context.new_page = Page
    session._context.new_cdp_session = lambda page: SimpleNamespace(
        send=lambda method: {"frameTree": {"frame": {"id": "owned-frame"}}},
        on=lambda *args: None,
        detach=lambda: None,
    )
    monkeypatch.setattr(supplements_browser, "CdpDownloadCapture", Capture)
    monkeypatch.setattr(
        supplements_browser, "validate_browser_network_url", lambda url: url
    )
    adapter = supplements_browser.SupplementBrowserTransport(session, doi=DOI)
    if timed_out:
        with pytest.raises(
            supplements_browser.SupplementBrowserError,
            match="browser_attachment_delivery_not_completed",
        ):
            adapter._native_file(
                wanted, source_page=PAGE, output_dir=tmp_path, max_bytes=100, timeout=0
            )
    elif oversized:
        from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionTooLargeError

        with pytest.raises(AcquisitionTooLargeError):
            adapter._native_file(
                wanted, source_page=PAGE, output_dir=tmp_path, max_bytes=100, timeout=1
            )
    else:
        resource = adapter._native_file(
            wanted, source_page=PAGE, output_dir=tmp_path, max_bytes=100, timeout=1
        )
        assert resource.local_path.read_bytes() == b"downloaded fixture"
    capture = captures[0]
    assert capture.other.read_bytes() == b"preserve this unrelated user download"
    assert capture.owned.exists() is (cancel_failures == 2)
    cancelled = [
        params["guid"]
        for method, params in capture.session.commands
        if method == "Browser.cancelDownload"
    ]
    assert cancelled == (
        ["owned-transfer"] * (2 if cancel_failures else 1)
        if oversized or timed_out
        else []
    )
    if cancel_failures == 2:
        assert (
            adapter.diagnostics[-1]["status"] == "BROWSER_DOWNLOAD_CANCEL_UNCONFIRMED"
        )
        assert adapter.diagnostics[-1]["needs_manual_check"] is True
    else:
        assert not any(
            d["status"] == "BROWSER_DOWNLOAD_CANCEL_UNCONFIRMED"
            for d in adapter.diagnostics
        )


def test_shared_capture_guid_filter_cannot_select_other_tabs_same_url(tmp_path):
    from aletheia_nexus.acquire.access.browser_engine.downloads import (
        CdpDownloadCapture,
        _NativeTransfer,
    )

    wanted = "https://pubs.acs.org/shared-supplement.docx"
    capture = object.__new__(CdpDownloadCapture)
    capture._session = object()
    capture._staging_dir = tmp_path
    capture._transfers = {}
    for guid, body in [("unrelated", b"user tab"), ("owned", b"owned tab")]:
        path = tmp_path / guid
        path.write_bytes(body)
        capture._transfers[guid] = _NativeTransfer(wanted, "completed", path)
    page = SimpleNamespace(wait_for_timeout=lambda *a: pytest.fail("no waiting needed"))
    assert (
        capture.wait(page, 0, expected_url=wanted, expected_guid="owned")[0]
        == tmp_path / "owned"
    )
    assert capture.wait(page, 0, expected_url=wanted, expected_guid="unknown") is None
    # Existing callers without a GUID retain their original behavior.
    assert capture.wait(page, 0, expected_url=wanted)[0] == tmp_path / "unrelated"


@pytest.mark.parametrize("interaction", [False, True])
def test_dom_discovery_tries_public_file_before_browser_and_preserves_real_attachment_gate(
    tmp_path, monkeypatch, interaction
):
    main = tmp_path / "main.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with main.open("wb") as handle:
        writer.write(handle)
    register_local_pdf(main, output_dir=tmp_path, doi=DOI, title="Parent")
    original = main.read_bytes(), validate_parser_input(main).sidecar_path.read_bytes()
    calls = []

    class Browser:
        diagnostics = []

        def __init__(self, *args, **kwargs):
            pass

        def page_fetch(self, *args, **kwargs):
            calls.append("browser_dom")
            return SimpleNamespace(text=HTML, final_url=PAGE)

        def file_fetch(self, url, *, diagnostics, **kwargs):
            calls.append("browser_file")
            diagnostics.append(
                {
                    "status": "NATIVE_ATTACHMENT_PAGE",
                    "challenge": "BOT_CHALLENGE",
                    "page_retained": True,
                    "needs_manual_check": True,
                }
            )
            raise supplements_browser.SupplementBrowserError(
                "attachment_interaction_required"
            )

    def public_file(url, *, output_dir, diagnostics, **kwargs):
        calls.append("public_file")
        diagnostics.append(
            {"status": "HTTP_FILE_RESPONSE", "http_status": 403 if interaction else 200}
        )
        if interaction:
            raise RuntimeError("HTTP blocked")
        path = Path(output_dir) / "public.part"
        writer = PdfWriter()
        writer.add_blank_page(width=120, height=100)
        with path.open("wb") as handle:
            writer.write(handle)
        return SimpleNamespace(
            local_path=path,
            final_url=url,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            http_status=200,
        )

    def blocked_page(*args, **kwargs):
        raise RuntimeError("HTTP page blocked")

    monkeypatch.setattr(supplements_browser, "SupplementBrowserTransport", Browser)
    monkeypatch.setattr(supplements, "_retrieve_official_file", public_file)
    result = supplements.acquire_supplements(
        main, page_urls=[PAGE], page_fetch=blocked_page, browser_session=object()
    )
    assert calls == ["browser_dom", "public_file"] + (
        ["browser_file"] if interaction else []
    )
    if interaction:
        assert (
            result["status"] == result["items"][0]["status"] == "INTERACTION_REQUIRED"
        )
        assert result["items"][0]["error"] == "attachment_interaction_required"
        assert result["items"][0]["diagnostics"][-1]["page_retained"] is True
    else:
        assert result["status"] == "COMPLETED"
        assert result["items"][0]["transport"] == "http"
    assert (
        main.read_bytes(),
        validate_parser_input(main).sidecar_path.read_bytes(),
    ) == original
