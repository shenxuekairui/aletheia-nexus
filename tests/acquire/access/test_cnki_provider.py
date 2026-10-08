import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
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
from aletheia_nexus.acquire.access.cnki_runtime import (
    CNKIFileCapture,
    CNKIGate,
    CNKIInteractionRequired,
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
    def __init__(self, *, text="", href="", visible=True, click=None, content=None):
        self.text = text
        self.href = href
        self.visible = visible
        self.value = None
        self._click = click
        self.content = content

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

    def inner_text(self, **kwargs):
        return self.text

    def get_attribute(self, name):
        return (
            self.href if name == "href" else self.content if name == "content" else None
        )

    def fill(self, value):
        self.value = value

    def click(self):
        if self._click is not None:
            self._click()


class _Rows:
    def __init__(self, row):
        self.rows = row if isinstance(row, list) else [row]

    def count(self):
        return len(self.rows)

    def nth(self, index):
        return self.rows[index]


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


class _Events:
    def on(self, event, handler):
        if not hasattr(self, "listeners"):
            self.listeners = {}
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.listeners[event].remove(handler)

    def emit(self, event, value):
        for handler in getattr(self, "listeners", {}).get(event, ()):
            handler(value)


class _DetailPage(_Events):
    url = "https://kns.cnki.net/kcms2/article/abstract?v=public"

    def __init__(self):
        self.closed = False
        self.pdf = _Element(
            text="PDF下载",
            href="/download/article.pdf",
            click=lambda: self.emit("download", _Download()),
        )

    def locator(self, selector):
        if selector == "a#pdfDown":
            return self.pdf
        return _EmptyLocator()

    def wait_for_load_state(self, state):
        assert state == "domcontentloaded"

    def expect_download(self, **kwargs):
        return _EventInfo(_Download())

    def wait_for_timeout(self, value):
        if hasattr(self, "on_poll"):
            self.on_poll()

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class _SearchPage(_Events):
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
        if selector == cnki_provider._RESULT_ROW_SELECTOR:
            return self.rows
        return _EmptyLocator()

    def goto(self, url, **kwargs):
        self.url = url

    def wait_for_selector(self, selector, **kwargs):
        assert selector == ".result-table-list tbody tr"

    def is_closed(self):
        return False


class _Context(_Events):
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

    assert (
        len(
            applicable_browser_providers(
                doi=chinese.doi,
                metadata=chinese,
                expected_title=None,
                config=BrowserAccessConfig(),
            )
        )
        == 1
    )
    assert (
        applicable_browser_providers(
            doi=english.doi,
            metadata=english,
            expected_title=None,
            config=BrowserAccessConfig(),
        )
        == ()
    )
    assert (
        len(
            applicable_browser_providers(
                doi=english.doi,
                metadata=english,
                expected_title=None,
                config=BrowserAccessConfig(cnki_search_all_titles=True),
            )
        )
        == 1
    )


def test_cnki_doi_markers_trigger_provider_without_resolved_metadata():
    assert (
        len(
            applicable_browser_providers(
                doi="10.13822/j.cnki.hxsj.2024.0476",
                metadata=None,
                expected_title=None,
                config=BrowserAccessConfig(),
            )
        )
        == 1
    )
    assert (
        len(
            applicable_browser_providers(
                doi="10.7503/cjcu20250333",
                metadata=None,
                expected_title=None,
                config=BrowserAccessConfig(),
            )
        )
        == 1
    )


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
        url = "https://kns.cnki.net/verify/home?captchaType=blockPuzzle&returnUrl=x"

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
        assert resource.sha256 == hashlib.sha256(b"%PDF-1.7\nCNKI test").hexdigest()
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
            AssertionError(
                "generic browser routes must not run after CNKI verification"
            )
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
            "source_page_url": ("https://kns.cnki.net/kcms2/article/abstract?v=public"),
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


def _valid_pdf(title="中文论文标题", *, doi=None):
    from io import BytesIO

    buffer = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if doi:
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            }
        )
        contents = DecodedStreamObject()
        contents.set_data(f"BT /F1 12 Tf 50 700 Td ({doi}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(contents)
    writer.add_metadata({"/Title": title})
    writer.write(buffer)
    return buffer.getvalue()


def _response(page, *, body=None, url="https://kns.cnki.net/article.pdf"):
    return SimpleNamespace(
        frame=SimpleNamespace(page=page),
        headers={"content-type": "application/pdf"},
        status=200,
        url=url,
        body=lambda: body if body is not None else _valid_pdf(),
    )


def _fetch(
    page, detail, tmp_path, *, context=None, config=None, doi="10.1000/cnki-target"
):
    return CNKIProvider().fetch(
        doi=doi,
        context=context or _Context(detail),
        page=page,
        output_dir=tmp_path,
        config=config or BrowserAccessConfig(),
        metadata=_metadata(),
    )


def test_cnki_inline_pdf_response_passes_real_identity_and_provenance(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("response", _response(detail))

    attempt = _fetch(_SearchPage("中文论文标题"), detail, tmp_path, context=context)

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert attempt.file_attempts[0].method == "cnki_pdf_response"
    record = json.loads(attempt.result.sidecar_path.read_text(encoding="utf-8"))
    assert record["retrieval"]["sha256"] == hashlib.sha256(_valid_pdf()).hexdigest()
    assert record["access"]["matched_result_title"] == "中文论文标题"
    assert record["access"]["download_method"] == "cnki_pdf_response"
    assert not list((tmp_path / "_browser-downloads").glob("*.part"))
    assert not any(context.listeners.values())


def test_cnki_popup_download_is_captured_and_popup_closed_after_save(tmp_path):
    detail = _DetailPage()
    popup = _DetailPage()
    popup.opener = lambda: detail
    context = _Context(detail)

    class Download(_Download):
        def save_as(self, path):
            assert not popup.closed
            Path(path).write_bytes(_valid_pdf())

    def click():
        context.emit("page", popup)
        popup.emit("download", Download())

    detail.pdf._click = click
    attempt = _fetch(_SearchPage("中文论文标题"), detail, tmp_path, context=context)

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert popup.closed and detail.closed


def test_cnki_capture_ignores_other_tabs_and_caj_responses():
    detail, other = _DetailPage(), _DetailPage()
    context = _Context(detail)
    capture = CNKIFileCapture(context, detail, 100_000)
    context.emit("response", _response(other))
    caj = _response(detail, url="https://kns.cnki.net/article.caj")
    context.emit("response", caj)
    assert capture.next_file() is None
    capture.close()
    assert not any(context.listeners.values())


def test_cnki_pdf_response_size_limit_cleans_up_and_reports_failure(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("response", _response(detail))
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(max_bytes=20),
    )

    assert attempt.status == BrowserAttemptStatus.RETRIEVAL_FAILED
    assert not list(tmp_path.rglob("*.part"))


def test_cnki_continues_to_next_result_after_conflicting_detail_doi(tmp_path):
    search = _SearchPage("中文论文标题")
    other_link = _Element(text="中文论文标题", href="/kcms2/article/abstract?id=second")
    search.rows = _Rows([_Row(search.link), _Row(other_link)])

    class Conflict(_DetailPage):
        def locator(self, selector):
            if selector == "meta[name='citation_doi']":
                return _Element(content="10.1000/unrelated")
            return super().locator(selector)

    first, second = Conflict(), _DetailPage()

    class Context(_Context):
        def __init__(self):
            self.queue = [first, second]

        def expect_page(self, **kwargs):
            return _EventInfo(self.queue.pop(0))

    context = Context()
    second.pdf._click = lambda: context.emit("response", _response(second))
    first.pdf._click = lambda: pytest.fail("conflicting DOI must not download")

    attempt = _fetch(search, second, tmp_path, context=context)

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert attempt.candidates_considered == 2
    assert "detail DOI mismatch" in attempt.evidence
    assert first.closed and second.closed


def test_cnki_title_typography_matching_handles_subscripts_and_fullwidth():
    page = _SearchPage("银修饰铜纳米阵列用于电催化还原ＣＯ₂")
    assert (
        cnki_provider._best_result_link(
            page, title="银修饰铜纳米阵列用于电催化还原CO_2", authors=(), limit=5
        )
        is page.link
    )


def test_cnki_metadata_label_preserves_nested_formula_and_inline_authors():
    parser = _ScholarlyMetadataParser()
    parser.feed(
        "<td>题名：银修饰铜纳米阵列用于电催化还原CO<sub>2</sub></td>"
        "<td>作者：<a>张三</a>;<a>李四</a></td>"
    )
    title, authors = parser.result()
    assert cnki_provider._normalized_title(title) == "银修饰铜纳米阵列用于电催化还原co2"
    assert authors == ("张三", "李四")


def test_cnki_keeps_english_metadata_if_chinese_fallback_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        cnki_provider,
        "_metadata_from_chinese_sources",
        lambda *args, **kwargs: (None, ()),
    )
    title, _, _ = _metadata_for_query(
        "10.7503/cjcu20250333",
        metadata=_metadata(title="An English Article"),
        expected_title=None,
        metadata_mailto=None,
    )
    assert title == "An English Article"


def test_author_overlap_does_not_rescue_an_unrelated_title():
    assert (
        cnki_provider._best_result_link(
            _SearchPage("完全无关的研究"),
            title="中文论文标题",
            authors=("张三",),
            limit=5,
        )
        is None
    )


def test_cnki_same_tab_navigation_does_not_click_result_twice(tmp_path):
    page = _SearchPage("中文论文标题")
    detail = _DetailPage()
    clicks = []

    def click():
        clicks.append(True)
        page.url = detail.url
        page.locator = detail.locator

    page.link._click = click

    class NoPopup(_EventInfo):
        def __exit__(self, *args):
            raise TimeoutError()

    class Context(_Context):
        def expect_page(self, **kwargs):
            return NoPopup(None)

    context = Context(detail)
    page.wait_for_load_state = detail.wait_for_load_state
    page.wait_for_timeout = detail.wait_for_timeout
    detail.pdf._click = lambda: context.emit("response", _response(page))
    attempt = _fetch(page, detail, tmp_path, context=context)

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert len(clicks) == 1


def test_cnki_post_click_captcha_hands_off_popup_and_leaves_it_open(tmp_path):
    detail, popup = _DetailPage(), _DetailPage()
    popup.url = "https://kns.cnki.net/verify/home?captchaType=blockPuzzle"
    popup.opener = lambda: detail
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("page", popup)
    callbacks = []
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(
            interactive=False,
            interaction_callback=lambda report, url: callbacks.append((report, url)),
        ),
    )

    assert attempt.status == BrowserAttemptStatus.INTERACTION_REQUIRED
    assert callbacks[0][0].kind == ChallengeKind.CAPTCHA
    assert "blockPuzzle" not in callbacks[0][1]
    assert not popup.closed
    assert not any(context.listeners.values())


def test_cnki_manual_completion_resumes_post_click_download(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    clicks = []

    def click():
        clicks.append(True)
        if len(clicks) == 1:
            detail.url = "https://kns.cnki.net/verify/home?captchaType=blockPuzzle"
        else:
            context.emit("response", _response(detail))

    def human_completes_challenge():
        detail.url = "https://kns.cnki.net/kcms2/article/abstract?v=public"

    detail.pdf._click = click
    detail.on_poll = human_completes_challenge
    callbacks = []
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(
            interaction_callback=lambda *args: callbacks.append(args)
        ),
    )

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert attempt.interaction_used
    assert len(callbacks) == 1 and len(clicks) == 2


def test_cnki_real_login_form_hands_off_but_navbar_login_does_not():
    class Login(_DetailPage):
        def __init__(self, form):
            super().__init__()
            self.form = form

        def locator(self, selector):
            if selector == "body":
                return _Element(text="机构登录 请先登录")
            if selector == "input[type='password']" and self.form:
                return _Element()
            return super().locator(selector)

    gate = CNKIGate(BrowserAccessConfig(interactive=False))
    assert gate.check(Login(False)) is False
    with pytest.raises(CNKIInteractionRequired) as exc:
        gate.check(Login(True))
    assert exc.value.report.kind in {ChallengeKind.SSO, ChallengeKind.AUTHENTICATION}


def test_title_only_resolves_article_doi_and_preserves_target_title(tmp_path):
    class Detail(_DetailPage):
        def locator(self, selector):
            if selector == "meta[name='citation_doi']":
                return _Element(content="10.1000/title-discovered")
            return super().locator(selector)

    detail = Detail()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("response", _response(detail))
    attempt = _fetch(
        _SearchPage("中文论文标题"), detail, tmp_path, context=context, doi=""
    )

    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert attempt.source_candidate.doi == "10.1000/title-discovered"
    payload = json.loads(attempt.result.sidecar_path.read_text(encoding="utf-8"))
    assert payload["target"]["expected_title"] == "中文论文标题"


def test_title_only_never_invents_doi_when_article_has_none(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("response", _response(detail))
    attempt = _fetch(
        _SearchPage("中文论文标题"), detail, tmp_path, context=context, doi=""
    )

    assert attempt.status != BrowserAttemptStatus.VERIFIED
    assert not attempt.source_candidate.doi
    assert not list(tmp_path.rglob("*.part"))


def test_title_only_resolves_unique_doi_from_real_pdf_first_page(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    body = _valid_pdf(doi="10.1000/title-in-pdf")
    detail.pdf._click = lambda: context.emit("response", _response(detail, body=body))
    attempt = _fetch(
        _SearchPage("中文论文标题"), detail, tmp_path, context=context, doi=""
    )
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert attempt.source_candidate.doi == "10.1000/title-in-pdf"
    assert attempt.result.identity_validation.doi_match


def test_title_only_rejects_ambiguous_pdf_dois(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    body = _valid_pdf(doi="10.1000/one 10.1000/two")
    detail.pdf._click = lambda: context.emit("response", _response(detail, body=body))
    attempt = _fetch(
        _SearchPage("中文论文标题"), detail, tmp_path, context=context, doi=""
    )
    assert attempt.status == BrowserAttemptStatus.RETRIEVAL_FAILED
    assert not attempt.source_candidate.doi
    assert not list(tmp_path.rglob("*.part"))


def test_cnki_invalid_pdf_download_is_failure_instead_of_unverified_pdf(tmp_path):
    detail = _DetailPage()

    class Download(_Download):
        def save_as(self, path):
            Path(path).write_bytes(b"<html>login page</html>")

    detail.pdf._click = lambda: detail.emit("download", Download())
    attempt = _fetch(_SearchPage("中文论文标题"), detail, tmp_path)
    assert attempt.status == BrowserAttemptStatus.RETRIEVAL_FAILED
    assert attempt.result.status == AcquisitionStatus.INVALID_PDF
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize(
    "origin,verified",
    [
        ("https://kns.cnki.net", True),
        ("https://other.example", False),
    ],
)
def test_blob_download_requires_the_article_origin(tmp_path, origin, verified):
    detail = _DetailPage()

    class Download(_Download):
        url = f"blob:{origin}/generated-pdf"

        def save_as(self, path):
            Path(path).write_bytes(_valid_pdf())

    detail.pdf._click = lambda: detail.emit("download", Download())
    attempt = _fetch(_SearchPage("中文论文标题"), detail, tmp_path)
    assert (attempt.status == BrowserAttemptStatus.VERIFIED) is verified
    assert not list(tmp_path.rglob("*.part"))


def test_unverified_first_pdf_does_not_prevent_second_result_verification(tmp_path):
    search = _SearchPage("中文论文标题")
    second_link = _Element(
        text="中文论文标题", href="/kcms2/article/abstract?id=second"
    )
    search.rows = _Rows([_Row(search.link), _Row(second_link)])
    first, second = _DetailPage(), _DetailPage()

    class Context(_Context):
        def __init__(self):
            self.queue = [first, second]

        def expect_page(self, **kwargs):
            return _EventInfo(self.queue.pop(0))

    context = Context()
    first.pdf._click = lambda: context.emit(
        "response", _response(first, body=_valid_pdf("另一篇研究论文"))
    )
    second.pdf._click = lambda: context.emit("response", _response(second))
    result = _fetch(search, second, tmp_path, context=context)
    assert result.status == BrowserAttemptStatus.VERIFIED
    assert len(result.file_attempts) == 2
    assert result.file_attempts[0].result.file_path is None
    assert result.result is result.file_attempts[1].result


def test_cnki_login_iframe_is_detected_without_matching_body_words():
    page = _DetailPage()
    frame = SimpleNamespace(
        frame_element=lambda: _Element(),
        locator=lambda selector: (
            _Element() if selector == "input[type='password']" else _EmptyLocator()
        ),
    )
    page.frames = [frame]
    with pytest.raises(CNKIInteractionRequired) as exc:
        CNKIGate(BrowserAccessConfig(interactive=False)).check(page)
    assert exc.value.report.kind == ChallengeKind.AUTHENTICATION


def test_chndoi_error_document_title_is_not_used_as_paper_metadata(monkeypatch):
    monkeypatch.setattr(
        cnki_provider.httpx,
        "get",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=200, text="<title>系统繁忙 - 中国知网</title>"
        ),
    )
    assert cnki_provider._metadata_from_chinese_sources(
        "10.13822/j.cnki.hxsj.2024.0476", mailto=None
    ) == (None, ())


def test_cnki_direct_api_passes_title_and_authors_to_reusable_session(tmp_path):
    from aletheia_nexus.acquire.access import acquire_cnki_pdf

    class Session:
        def acquire_provider(self, provider, **kwargs):
            assert provider.authors == ("张三",)
            assert kwargs["doi"] == ""
            assert kwargs["expected_title"] == "中文论文标题"
            return "acquired"

    assert (
        acquire_cnki_pdf(
            title="中文论文标题",
            authors=("张三",),
            output_dir=tmp_path,
            browser_session=Session(),
        )
        == "acquired"
    )
    with pytest.raises(ValueError):
        acquire_cnki_pdf(output_dir=tmp_path)
    with pytest.raises(ValueError):
        acquire_cnki_pdf(title=" ", output_dir=tmp_path)


def test_cnki_closed_target_restarts_once_with_same_session_config(
    monkeypatch, tmp_path
):
    from aletheia_nexus.acquire.access import BrowserSession

    session = BrowserSession(BrowserAccessConfig(profile_root=tmp_path))
    contexts = []
    restarts = []

    def context():
        contexts.append(True)
        return SimpleNamespace(new_page=_DetailPage)

    monkeypatch.setattr(session, "_ensure_started", context)
    monkeypatch.setattr(session, "close", lambda: restarts.append(True))
    provider = CNKIProvider()
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return BrowserAccessAttempt(
            source_candidate=cnki_provider._source_candidate(kwargs["doi"]),
            final_url=None,
            status=BrowserAttemptStatus.ERROR
            if len(calls) == 1
            else BrowserAttemptStatus.NO_FILE_CANDIDATES,
            evidence=("CNKI browser target closed",) if len(calls) == 1 else (),
        )

    monkeypatch.setattr(provider, "fetch", fetch)
    result = session.acquire_provider(provider, doi="10.1000/test", output_dir=tmp_path)
    assert result.status == BrowserAttemptStatus.NO_FILE_CANDIDATES
    assert len(calls) == 2 and len(restarts) == 1
    assert calls[0]["config"] is calls[1]["config"]
