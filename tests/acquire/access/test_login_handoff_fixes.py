from dataclasses import replace
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser_route, service
from aletheia_nexus.acquire.access.challenge import classify_access_challenge
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    ChallengeKind,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryResult,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
)


class Page:
    url = "https://publisher.example/article"
    closed = False

    def title(self):
        return "Article"

    def content(self):
        return "<main>Article abstract</main>"

    def locator(self, selector):
        assert selector == "body"
        return SimpleNamespace(inner_text=lambda **kw: "Article abstract")

    def is_closed(self):
        return self.closed

    def wait_for_timeout(self, milliseconds):
        pass


def test_ineffective_institution_click_does_not_claim_login_success():
    page = Page()
    report, history, used = browser_route._resolve_external_auth_page(
        page,
        source_host="publisher.example",
        origin_url=page.url,
        config=BrowserAccessConfig(interactive=False),
    )
    assert report.kind == ChallengeKind.NONE
    assert browser_route._HANDOFF_NOT_STARTED in report.evidence
    assert not used
    assert history[-1] == report


@pytest.mark.parametrize("pdf_already_present", [False, True])
def test_ineffective_click_never_requests_login_on_unchanged_article(
    pdf_already_present,
):
    page = Page()
    notices = []

    def user_cancels(report, url):
        notices.append(report.kind)
        page.closed = True

    _, _, used = browser_route._resolve_external_auth_page(
        page,
        source_host="publisher.example",
        origin_url=page.url,
        origin_pdf_control=pdf_already_present,
        config=BrowserAccessConfig(
            wait_for_interaction=True, interaction_callback=user_cancels
        ),
    )
    assert not used and not notices
    assert not page.closed


@pytest.mark.parametrize(
    "path,expected",
    [("/au/login", ChallengeKind.AUTHENTICATION), ("/article", ChallengeKind.NONE)],
)
def test_empty_title_authentication_method_selector(path, expected):
    report = classify_access_challenge(
        title="",
        url="https://repository.example" + path,
        visible_text="Scegli il metodo di autenticazione: Autenticazione Esterna Autenticazione IRIS",
    )
    assert report.kind == expected


@pytest.mark.parametrize("visible", [True, False])
def test_only_visible_embedded_login_is_a_challenge(visible):
    page = Page()
    frame = Page()
    frame.url = "https://idp.example/login"
    frame.title = lambda: "Choose your institution"
    frame.locator = lambda selector: SimpleNamespace(
        inner_text=lambda **kw: "Choose your institution"
    )
    frame.frame_element = lambda: SimpleNamespace(is_visible=lambda: visible)
    page.frames = [page, frame]
    assert browser_route._report_for_page(page).kind == (
        ChallengeKind.SSO if visible else ChallengeKind.NONE
    )


def test_repository_authentication_is_recorded_without_requesting_credentials():
    page = Page()
    page.url = "https://repository.example/au/login"
    page.title = lambda: ""
    page.locator = lambda selector: SimpleNamespace(
        inner_text=lambda **kw: (
            "Scegli il metodo di autenticazione: Autenticazione IRIS"
        )
    )
    notices = []
    report, _, used = browser_route._resolve_page_challenge(
        page,
        config=BrowserAccessConfig(
            wait_for_interaction=True,
            interaction_callback=lambda *args: notices.append(args),
        ),
        return_host="repository.example",
        allow_authentication=False,
    )
    assert report.kind == ChallengeKind.AUTHENTICATION
    assert not used and not notices


def test_publisher_browser_route_precedes_repository_pdf_login():
    publisher = FullTextCandidate(
        doi="10.1000/test",
        url="https://publisher.example/article",
        provenance=(),
        host_type=HostType.PUBLISHER,
    )
    repository = replace(
        publisher,
        url="https://repository.example/file.pdf",
        host_type=HostType.REPOSITORY,
        url_type=CandidateUrlType.PDF,
    )
    base = MultiRouteAcquisitionResult(
        doi=publisher.doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(
            doi=publisher.doi, candidates=(repository, publisher), providers=()
        ),
    )
    routes = service.browser_recovery_routes(base, limit=10)
    assert routes.index(publisher) < routes.index(repository)
    attempt = BrowserAccessAttempt(
        source_candidate=repository,
        final_url="https://repository.example/login",
        status=BrowserAttemptStatus.AUTH_REQUIRED,
    )
    status, message = service._final_status_from_browser(base, [attempt])
    assert status == MaximizedAcquisitionStatus.AUTH_REQUIRED
    assert "repository" in message.lower()
