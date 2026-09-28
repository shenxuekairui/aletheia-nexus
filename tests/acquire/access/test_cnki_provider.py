import hashlib
import json
from pathlib import Path

from pypdf import PdfWriter

from aletheia_nexus.acquire.access import cnki_provider, service
from aletheia_nexus.acquire.access.artifact import finalize_access_resource
from aletheia_nexus.acquire.access.cnki_provider import (
    CNKIProvider,
    _captcha_visible,
    _metadata_for_query,
    _pdf_control,
    _ScholarlyMetadataParser,
    _wait_for_manual_captcha,
)
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    ChallengeKind,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.access.provider_registry import (
    applicable_browser_providers,
    registered_browser_providers,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    TitleSource,
)
from aletheia_nexus.acquire.metadata.exceptions import UnsupportedAgencyError
from aletheia_nexus.core.models import PaperMetadata


def _metadata(*, title="中文论文标题", authors=("张三",)):
    return PaperMetadata(
        doi="10.1000/cnki-target",
        title=title,
        authors=authors,
        journal=None,
        issn=(),
        published_date=None,
        year=None,
        publisher=None,
        work_type=None,
        volume=None,
        issue=None,
        pages=None,
        url=None,
    )


class _EmptyLocator:
    def count(self):
        return 0


class _Element:
    def __init__(self, *, text="", href="", visible=True, click=None):
        self.text = text
        self.href = href
        self.visible = visible
        self.value = None
        self._click = click

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def nth(self, index):
        assert index == 0
        return self

    def is_visible(self):
        return self.visible

    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        return self.href if name == "href" else None

    def fill(self, value):
        self.value = value

    def click(self):
        if self._click is not None:
            self._click()


class _Rows:
    def __init__(self, row):
        self.row = row

    def count(self):
        return 1

    def nth(self, index):
        assert index == 0
        return self.row


class _Row:
    def __init__(self, link):
        self.link = link

    def locator(self, selector):
        return self.link

    def inner_text(self):
        return f"{self.link.text} 张三"


class _Download:
    url = "https://kns.cnki.net/download/article.pdf"

    def save_as(self, path):
        Path(path).write_bytes(b"%PDF-1.7\nCNKI test")


class _EventInfo:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DetailPage:
    url = "https://kns.cnki.net/kcms2/article/abstract?v=public"

    def __init__(self):
        self.closed = False
        self.pdf = _Element(text="PDF下载", href="/download/article.pdf")

    def locator(self, selector):
        if selector == "a#pdfDown":
            return self.pdf
        return _EmptyLocator()

    def wait_for_load_state(self, state):
        assert state == "domcontentloaded"

    def expect_download(self, **kwargs):
        return _EventInfo(_Download())

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class _SearchPage:
    url = "https://kns.cnki.net/kns8s/"

    def __init__(self, title):
        self.search = _Element()
        self.button = _Element()
        self.link = _Element(text=title, href="/kcms2/article/abstract?v=public")
        self.rows = _Rows(_Row(self.link))

    def locator(self, selector):
        if selector == "#txt_SearchText":
            return self.search
        if selector == ".search-btn":
            return self.button
        if selector == ".result-table-list tbody tr":
            return self.rows
        return _EmptyLocator()

    def goto(self, url, **kwargs):
        self.url = url

    def wait_for_selector(self, selector, **kwargs):
        assert selector == ".result-table-list tbody tr"

    def is_closed(self):
        return False


class _Context:
    def __init__(self, detail_page):
        self.detail_page = detail_page

    def expect_page(self, **kwargs):
        return _EventInfo(self.detail_page)


def test_cnki_is_registered_after_general_public_acquisition_layers():
    providers = registered_browser_providers()

    assert [provider.name for provider in providers] == ["cnki"]
    assert providers[0].priority > 0


def test_cnki_defaults_to_chinese_titles_and_can_be_explicitly_broadened():
    chinese = _metadata()
    english = _metadata(title="An English Article")

    assert len(
        applicable_browser_providers(
            doi=chinese.doi,
            metadata=chinese,
            expected_title=None,
            config=BrowserAccessConfig(),
        )
    ) == 1
    assert (
        applicable_browser_providers(
            doi=english.doi,
            metadata=english,
            expected_title=None,
            config=BrowserAccessConfig(),
        )
        == ()
    )
    assert len(
        applicable_browser_providers(
            doi=english.doi,
            metadata=english,
            expected_title=None,
            config=BrowserAccessConfig(cnki_search_all_titles=True),
        )
    ) == 1


def test_cnki_doi_markers_trigger_provider_without_resolved_metadata():
    assert len(
        applicable_browser_providers(
            doi="10.13822/j.cnki.hxsj.2024.0476",
            metadata=None,
            expected_title=None,
            config=BrowserAccessConfig(),
        )
    ) == 1
    assert len(
        applicable_browser_providers(
            doi="10.7503/cjcu20250333",
            metadata=None,
            expected_title=None,
            config=BrowserAccessConfig(),
        )
    ) == 1


def test_cnki_metadata_parser_reads_chndoi_title_and_authors():
    parser = _ScholarlyMetadataParser()
    parser.feed(
        """
        <table>
          <tr><td><label>题名：</label>银修饰铜纳米阵列用于电催化还原CO_2</td></tr>
          <tr><td><label>作者：</label>乔华建;李天治;安赛</td></tr>
        </table>
        """
    )

    assert parser.result() == (
        "银修饰铜纳米阵列用于电催化还原CO_2",
        ("乔华建", "李天治", "安赛"),
    )


def test_cnki_resolves_missing_title_from_existing_metadata_before_network():
    title, authors, resolved = _metadata_for_query(
        "10.1000/cnki-target",
        metadata=_metadata(),
        expected_title=None,
        metadata_mailto=None,
    )

    assert title == "中文论文标题"
    assert authors == ("张三",)
    assert resolved is not None


def test_cnki_resolves_cnki_agency_metadata_from_chndoi(monkeypatch):
    def unsupported(*args, **kwargs):
        raise UnsupportedAgencyError("cnki")

    class Response:
        status_code = 200
        text = """
        <table>
          <tr><td><label>题名：</label>可控设计的Co-N/C电催化剂</td></tr>
          <tr><td><label>作者：</label>胡鹏;张琪婧</td></tr>
        </table>
        """

    monkeypatch.setattr(cnki_provider, "get_metadata", unsupported)
    monkeypatch.setattr(cnki_provider.httpx, "get", lambda *args, **kwargs: Response())

    title, authors, resolved = _metadata_for_query(
        "10.13822/j.cnki.hxsj.2023.0605",
        metadata=None,
        expected_title=None,
        metadata_mailto=None,
    )

    assert title == "可控设计的Co-N/C电催化剂"
    assert authors == ("胡鹏", "张琪婧")
    assert resolved is None


def test_cnki_pdf_control_excludes_caj_link():
    caj = _Element(text="CAJ下载", href="/download/file.caj")
    pdf = _Element(text="PDF下载", href="/download/file.pdf")

    class Page:
        def locator(self, selector):
            if selector == "a#pdfDown":
                return caj
            if selector == "a:has-text('PDF下载')":
                return pdf
            return _EmptyLocator()

    assert _pdf_control(Page()) is pdf


def test_cnki_captcha_uses_human_handoff_callback_without_solving():
    callbacks = []

    class CaptchaLocator(_Element):
        def __init__(self):
            super().__init__()
            self.checks = 0

        def is_visible(self):
            self.checks += 1
            return self.checks == 1

    captcha = CaptchaLocator()

    class Page:
        url = "https://kns.cnki.net/kns8s/verify"

        def locator(self, selector):
            if selector == ".geetest_slider_button":
                return captcha
            return _EmptyLocator()

        def is_closed(self):
            return False

        def wait_for_timeout(self, value):
            raise AssertionError("already-cleared CAPTCHA should not need polling")

    cleared, used, report = _wait_for_manual_captcha(
        Page(),
        config=BrowserAccessConfig(
            interaction_callback=lambda challenge, url: callbacks.append(
                (challenge, url)
            )
        ),
    )

    assert cleared is True
    assert used is True
    assert report is not None and report.kind == ChallengeKind.CAPTCHA
    assert len(callbacks) == 1


def test_cnki_recognizes_server_side_verify_redirect_before_widget_renders():
    class Page:
        url = (
            "https://kns.cnki.net/verify/home?captchaType=blockPuzzle&returnUrl=x"
        )

        def locator(self, selector):
            return _EmptyLocator()

    assert _captcha_visible(Page()) is True


def test_cnki_fetch_uses_popup_pdf_download_hash_and_shared_finalizer(
    monkeypatch, tmp_path
):
    title = "中文论文标题"
    page = _SearchPage(title)
    detail = _DetailPage()
    captured = {}

    def finalize(**kwargs):
        resource = kwargs["resource"]
        captured.update(kwargs)
        assert resource.sha256 == hashlib.sha256(
            b"%PDF-1.7\nCNKI test"
        ).hexdigest()
        return AcquisitionResult(
            candidate=kwargs["candidate"],
            status=AcquisitionStatus.VERIFIED,
            retrieved=resource,
            file_path=tmp_path / "verified.pdf",
        )

    monkeypatch.setattr(cnki_provider, "finalize_access_resource", finalize)

    attempt = CNKIProvider().fetch(
        doi="10.1000/cnki-target",
        context=_Context(detail),
        page=page,
        output_dir=tmp_path,
        config=BrowserAccessConfig(),
        metadata=_metadata(title=title),
    )

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert page.search.value == title
    assert attempt.file_attempts[0].method == "cnki_pdf_download"
    assert captured["transport"] == "cnki_authenticated_browser"
    assert captured["access_details"]["fetcher"] == "CNKIProvider"
    assert captured["access_details"]["access_method"] == (
        "playwright_institution_auth"
    )
    assert detail.closed is True


def test_maximized_acquisition_uses_cnki_after_public_routes_before_generic_browser(
    monkeypatch, tmp_path
):
    metadata = _metadata()
    source = FullTextCandidate(
        doi=metadata.doi,
        url="https://kns.cnki.net/kns8s/",
        provenance=(),
    )
    base = MultiRouteAcquisitionResult(
        doi=metadata.doi,
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(
            doi=metadata.doi,
            candidates=(),
            providers=(),
        ),
        metadata=metadata,
        expected_title=metadata.title,
        title_source=TitleSource.METADATA,
    )
    verified = AcquisitionResult(
        candidate=source,
        status=AcquisitionStatus.VERIFIED,
        file_path=tmp_path / "cnki.pdf",
    )
    # BrowserAccessAttempt.result is derived from file_attempts, so represent the
    # verified resource using the production BrowserFileAttempt contract.
    provider_attempt = BrowserAccessAttempt(
        source_candidate=source,
        final_url=source.url,
        status=BrowserAttemptStatus.VERIFIED,
        file_attempts=(BrowserFileAttempt(candidate=source, result=verified),),
    )

    monkeypatch.setattr(service, "acquire_full_text", lambda *args, **kwargs: base)
    monkeypatch.setattr(
        service,
        "acquire_with_browser_provider",
        lambda provider, **kwargs: provider_attempt,
    )
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("generic browser routes must not run after CNKI verification")
        ),
    )

    result = service.acquire_full_text_maximized(
        metadata.doi,
        output_dir=tmp_path,
        browser_config=BrowserAccessConfig(),
        auto_official_api=False,
    )

    assert result.status == MaximizedAcquisitionStatus.VERIFIED
    assert result.verified_result is verified
    assert result.browser_attempts == (provider_attempt,)


def test_cnki_artifact_records_hash_source_and_access_method(tmp_path):
    title = "中文论文标题"
    temporary = tmp_path / "cnki.part"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    with temporary.open("wb") as handle:
        writer.write(handle)
    body = temporary.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    candidate = FullTextCandidate(
        doi="10.1000/cnki-target",
        url="https://kns.cnki.net/download/article.pdf",
        provenance=(DiscoveryProvider.CNKI,),
        url_type=CandidateUrlType.PDF,
    )

    result = finalize_access_resource(
        candidate=candidate,
        resource=RetrievedResource(
            requested_url="https://kns.cnki.net/kcms2/article/abstract?v=public",
            final_url=candidate.url,
            http_status=200,
            content_type="application/pdf",
            size_bytes=len(body),
            sha256=digest,
            local_path=temporary,
        ),
        output_dir=tmp_path / "out",
        expected_title=title,
        keep_unverified=False,
        transport="cnki_authenticated_browser",
        access_details={
            "provider": "cnki",
            "fetcher": "CNKIProvider",
            "source_page_url": (
                "https://kns.cnki.net/kcms2/article/abstract?v=public"
            ),
            "access_method": "playwright_institution_auth",
        },
    )

    assert result.status == AcquisitionStatus.VERIFIED
    payload = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert payload["retrieval"]["sha256"] == digest
    assert payload["candidate"]["provenance"] == ["cnki"]
    assert payload["transport"] == "cnki_authenticated_browser"
    assert payload["access"]["fetcher"] == "CNKIProvider"
    assert payload["access"]["access_method"] == "playwright_institution_auth"
