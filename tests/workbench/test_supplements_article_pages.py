"""Missing official HTML is recovered in owned tabs, never the user's tabs."""

import base64
import hashlib
import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from aletheia_nexus.acquire.access.models import (
    BrowserAccessConfig,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.content.gate import validate_parser_input
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.workbench import supplements, supplements_browser

DOI = "10.1021/ja0659323"
PAGE = "https://pubs.acs.org/jacsat/article/128/51/16414/3525402/Local"
FILE = "https://pubs.acs.org/jacsat/article-supplement/3525402/pdf/ja0659323_si_001/"
RESOLVER = "https://doi.org/" + DOI
HTML = f'<title>Local parent</title><meta name="citation_doi" content="{DOI}"><a href="{FILE}">suppl-mat1</a>'


class Page:
    def __init__(self, context, *, url="about:blank", html="", closed=False):
        self.context, self.url, self.html = context, url, html
        self.closed = closed
        self.routes = []
        self.gotos = []
        self.main_frame = object()

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True

    def route(self, pattern, handler):
        self.routes.append(handler)

    def unroute(self, pattern, handler):
        self.routes.remove(handler)

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.context.navigations.append(url)
        plan = self.context.plans[url]
        self.url, self.html = plan.get("final", url), plan.get("html", HTML)
        self.challenge = plan.get("challenge", ChallengeKind.NONE)
        for target in plan.get("requests", [self.url]):
            request = SimpleNamespace(
                url=target,
                frame=self.main_frame,
                is_navigation_request=lambda: True,
            )
            for guard in self.routes:
                guard(
                    SimpleNamespace(
                        request=request,
                        fallback=lambda: None,
                        abort=lambda _: self.context.blocked.append(target),
                    )
                )
        return SimpleNamespace(
            status=plan.get("status", 200), headers=plan.get("headers", {})
        )


class Context:
    def __init__(self, plans):
        self.plans, self.pages, self.created = plans, [], []
        self.navigations, self.blocked = [], []

    def new_page(self):
        page = Page(self)
        self.created.append(page)
        self.pages.append(page)
        return page


def session(plans):
    context = Context(plans)
    return SimpleNamespace(
        _context=context,
        _ensure_started=lambda: context,
        pump_events=lambda _: None,
        config=BrowserAccessConfig(
            auto_challenge_grace=0,
            interaction_callback=lambda *a: pytest.fail(
                "main callback must not be used for SI"
            ),
            interaction_poll_callback=lambda *a: pytest.fail(
                "main poll must not be used for SI"
            ),
        ),
    )


@pytest.fixture(autouse=True)
def observations(monkeypatch):
    def read(page, operation, *args, **kwargs):
        assert not page.closed
        if operation == "content":
            return page.html
        pytest.fail("unexpected operation: " + operation)

    def resolve(page, *, config):
        assert not config.interactive and not config.wait_for_interaction
        assert config.interaction_callback is config.interaction_poll_callback is None
        return ChallengeReport(page.challenge), (), False

    monkeypatch.setattr(supplements_browser, "bounded_read", read)
    monkeypatch.setattr(supplements_browser, "_resolve_page_challenge", resolve)


@pytest.mark.parametrize("old_main_closed", [False, True])
def test_missing_or_closed_main_page_uses_owned_article_lifecycle(old_main_closed):
    current = session({PAGE: {}})
    unrelated = Page(
        current._context,
        url="https://pubs.acs.org/unrelated",
        html=HTML.replace(DOI, "10.1021/other"),
    )
    current._context.pages.append(unrelated)
    if old_main_closed:
        current._context.pages.append(
            Page(current._context, url=PAGE, html=HTML, closed=True)
        )
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    found = adapter.page_fetch(PAGE)
    owned = current._context.created[0]
    assert found.transport == "browser_owned_article_DOM"
    assert found.text == HTML and not owned.closed
    assert current._context.navigations == [PAGE] and not unrelated.gotos
    assert adapter.pages[PAGE] is owned
    adapter.close()
    assert owned.closed and not unrelated.closed and not unrelated.gotos


@pytest.mark.parametrize(
    "pdf",
    [
        "https://pubs.acs.org/doi/pdf/" + DOI,
        "https://pdf.sciencedirectassets.com/signed/main.pdf?token=not-recorded",
    ],
)
def test_pdf_source_uses_doi_landing_without_requesting_main_pdf(pdf):
    current = session({RESOLVER: {"final": PAGE}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    found = adapter.page_fetch(pdf)
    assert found.final_url == PAGE and current._context.navigations == [RESOLVER]
    adapter.close()


def test_existing_unique_doi_page_needs_no_navigation_and_is_never_closed():
    current = session({})
    existing = Page(current._context, url=PAGE, html=HTML)
    current._context.pages.append(existing)
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    assert adapter.page_fetch(RESOLVER).transport == "browser_existing_DOM"
    adapter.close()
    assert not current._context.created and not existing.closed and not existing.gotos


@pytest.mark.parametrize(
    "html",
    [
        HTML.replace(DOI, "10.1021/other"),
        HTML + '<meta name="citation_doi" content="10.1021/other">',
    ],
)
def test_wrong_or_ambiguous_doi_is_rejected_and_owned_pages_closed(html):
    current = session({PAGE: {"html": html}, RESOLVER: {"final": PAGE, "html": html}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(
        supplements_browser.SupplementBrowserError,
        match="browser_parent_page_not_available",
    ):
        adapter.page_fetch(PAGE)
    assert all(page.closed for page in current._context.created)
    assert not adapter.pages
    assert (
        sum(d.get("identity") == "IDENTITY_NOT_CONFIRMED" for d in adapter.diagnostics)
        == 2
    )


def test_nonofficial_redirect_is_not_adopted_even_when_doi_matches():
    current = session(
        {RESOLVER: {"final": "https://untrusted.example/paper", "html": HTML}}
    )
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError):
        adapter.page_fetch(RESOLVER)
    assert not adapter.pages and current._context.created[0].closed


@pytest.mark.parametrize(
    "challenge",
    [
        ChallengeKind.CAPTCHA,
        ChallengeKind.AUTHENTICATION,
        ChallengeKind.SSO,
        ChallengeKind.MFA,
        ChallengeKind.BOT_CHALLENGE,
    ],
)
def test_article_gate_is_retained_without_calling_main_wait_or_opening_other_routes(
    challenge,
):
    current = session({PAGE: {"challenge": challenge}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(
        supplements_browser.SupplementBrowserError,
        match="attachment_interaction_required",
    ):
        adapter.page_fetch(PAGE)
    adapter.close()
    assert current._context.navigations == [PAGE]
    assert not current._context.created[0].closed and not adapter.pages
    gate = adapter.diagnostics[-1]
    assert (
        gate["stage"] == "si_article_page"
        and gate["page_retained"]
        and gate["needs_manual_check"]
    )


@pytest.mark.parametrize(
    "challenge,code",
    [
        (ChallengeKind.ACCESS_DENIED, "attachment_access_denied"),
        (ChallengeKind.ENTITLEMENT, "attachment_entitlement_required"),
    ],
)
def test_hard_access_boundary_does_not_try_alternate_route(challenge, code):
    current = session({PAGE: {"challenge": challenge}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError, match=code):
        adapter.page_fetch(PAGE)
    assert current._context.created[0].closed and current._context.navigations == [PAGE]


@pytest.mark.parametrize(
    "target", ["http://127.0.0.1/private", "https://pubs.acs.org/doi/pdf/" + DOI]
)
def test_navigation_guards_refuse_ssrf_or_main_pdf_redirect(target):
    current = session({RESOLVER: {"final": PAGE, "requests": [target]}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError):
        adapter.page_fetch(RESOLVER)
    assert current._context.blocked == [target]
    assert not adapter.pages and current._context.created[0].closed


def pdf_bytes(width):
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=100)
    writer.write(buffer)
    return buffer.getvalue()


def test_service_keeps_owned_article_until_attachment_saved_then_releases_it(
    tmp_path, monkeypatch
):
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf_bytes(100))
    register_local_pdf(main, output_dir=tmp_path, doi=DOI, title="Local parent")
    sidecar = validate_parser_input(main).sidecar_path
    before = main.read_bytes(), sidecar.read_bytes()
    current = session({PAGE: {}})

    def blocked(*a, **kw):
        raise RuntimeError("local HTTP fixture failure")

    original_read = supplements_browser.bounded_read
    body = pdf_bytes(120)

    def read(page, operation, *args, **kwargs):
        if operation != "evaluate":
            return original_read(page, operation, *args, **kwargs)
        assert not page.closed and page is current._context.created[0]
        return {
            "url": FILE,
            "bodyBase64": base64.b64encode(body).decode(),
            "status": 200,
        }

    monkeypatch.setattr(supplements_browser, "bounded_read", read)
    monkeypatch.setattr(supplements, "_retrieve_official_file", blocked)
    result = supplements.acquire_supplements(
        main, page_urls=[PAGE], page_fetch=blocked, browser_session=current
    )
    assert result["status"] == "COMPLETED" and result["items"][0]["status"] == "SAVED"
    assert result["items"][0]["sha256"] == hashlib.sha256(body).hexdigest()
    assert current._context.created[0].closed and result["main_status_unchanged"]
    assert (main.read_bytes(), sidecar.read_bytes()) == before


def test_service_exposes_parent_gate_as_si_interaction_without_changing_main(tmp_path):
    main = tmp_path / "main.pdf"
    main.write_bytes(pdf_bytes(100))
    register_local_pdf(main, output_dir=tmp_path, doi=DOI, title="Local parent")
    before = main.read_bytes(), validate_parser_input(main).sidecar_path.read_bytes()
    current = session({PAGE: {"challenge": ChallengeKind.CAPTCHA}})

    def blocked(*a, **kw):
        raise RuntimeError("local HTTP fixture failure")

    result = supplements.acquire_supplements(
        main, page_urls=[PAGE], page_fetch=blocked, browser_session=current
    )
    assert result["status"] == "INTERACTION_REQUIRED" and not result["items"]
    assert result["errors"][-1]["status"] == "INTERACTION_REQUIRED"
    assert not current._context.created[0].closed
    assert not (tmp_path / "SI").exists()
    assert (
        main.read_bytes(),
        validate_parser_input(main).sidecar_path.read_bytes(),
    ) == before


def test_source_page_candidates_exclude_extensionless_main_pdf_routes():
    assert supplements._source_page_candidates(
        {
            "access": {
                "source_page_url": "https://pubs.rsc.org/en/content/articlepdf/2022/cy/example.pdf"
            },
            "candidate": {
                "url": "https://www.sciencedirect.com/science/article/pii/FILE/pdf",
                "host_type": "publisher",
                "url_type": "landing_page",
            },
        },
        DOI,
    ) == [RESOLVER]


def test_official_resolver_refresh_reuses_core_routes_and_final_doi_gate():
    doi = "10.1016/j.elecom.2022.107204"
    resolver = "https://doi.org/" + doi
    wrapper = "https://linkinghub.elsevier.com/retrieve/pii/S1388248122000066"
    article = (
        "https://www.sciencedirect.com/science/article/pii/S1388248122000066?via%3Dihub"
    )
    # Minimal public-page signal only; no real key, IP address or auth state.
    refresh = '<meta http-equiv="refresh" content="2; url=\'/retrieve/articleSelectSinglePerm?Redirect=https%3A%2F%2Fwww.sciencedirect.com%2Fscience%2Farticle%2Fpii%2FS1388248122000066%3Fvia%253Dihub&amp;key=fixture-secret-key\'">'
    current = session(
        {
            resolver: {"final": wrapper, "html": refresh},
            article: {"html": HTML.replace(DOI, doi)},
        }
    )
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=doi)
    found = adapter.page_fetch(resolver)
    assert found.final_url == article
    assert current._context.navigations == [resolver, article]
    assert not current._context.created[-1].closed
    assert current._context.created[0].closed
    assert any(d.get("method") == "REDIRECT_TARGET" for d in adapter.diagnostics)
    assert "fixture-secret-key" not in json.dumps(adapter.diagnostics)
    adapter.close()


@pytest.mark.parametrize(
    "target",
    [
        "https://untrusted.example/article",
        "http://127.0.0.1/article",
        "https://pubs.acs.org/download.pdf",
    ],
)
def test_article_expansion_does_not_follow_foreign_private_or_pdf_targets(target):
    html = f'<link rel="canonical" href="{target}">'
    current = session({RESOLVER: {"final": PAGE, "html": html}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError):
        adapter.page_fetch(RESOLVER)
    assert current._context.navigations == [RESOLVER]


def test_article_route_expansion_rejects_wrong_metadata_before_following_links():
    target = "https://pubs.acs.org/other-article"
    html = (
        HTML.replace(DOI, "10.1021/other") + f'<link rel="canonical" href="{target}">'
    )
    current = session({RESOLVER: {"final": PAGE, "html": html}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError):
        adapter.page_fetch(RESOLVER)
    assert current._context.navigations == [RESOLVER] and not adapter.pages


def test_official_wrapper_cannot_smuggle_nonofficial_embedded_target():
    html = '<meta http-equiv="refresh" content="1; url=/redirect?Redirect=https%3A%2F%2Funtrusted.example%2Farticle">'
    current = session({RESOLVER: {"final": PAGE, "html": html}})
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError):
        adapter.page_fetch(RESOLVER)
    assert current._context.navigations == [RESOLVER]


def test_owned_article_following_respects_global_route_budget_and_closes_rejects():
    targets = [f"https://pubs.acs.org/landing/{index}" for index in range(6)]
    plans = {
        target: {"html": f'<link rel="canonical" href="{targets[index + 1]}">'}
        for index, target in enumerate(targets[:-1])
    }
    current = session(plans)
    current.config = replace(current.config, max_source_routes=3)
    adapter = supplements_browser.SupplementBrowserTransport(current, doi=DOI)
    with pytest.raises(supplements_browser.SupplementBrowserError):
        adapter.page_fetch(targets[0])
    assert current._context.navigations == targets[:3]
    assert all(page.closed for page in current._context.created)
