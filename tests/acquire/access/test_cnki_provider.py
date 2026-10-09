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

    def evaluate(self, expression):
        return True

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

        def evaluate(self, expression):
            return True

        def wait_for_timeout(self, value):
            # Require two clear observations before resuming, even when the
            # widget disappears immediately after notifying the user.
            pass

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


@pytest.mark.parametrize("title", ["中文论文标题", "An English Article"])
def test_maximized_acquisition_uses_cnki_after_public_routes_before_generic_browser(
    monkeypatch, tmp_path, title
):
    metadata = _metadata(title=title)
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
            candidates=(source,),
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
    assert result.browser_attempts[0].file_attempts == provider_attempt.file_attempts
    assert (
        "CNKI routing decision: observed_cnki_source"
        in result.browser_attempts[0].evidence
    )


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
    assert payload["identity_validation"]["policy"] == "pdf_front_matter/v2"
    assert "declared_dois" in payload["identity_validation"]


def _valid_pdf(title="中文论文标题", *, doi="10.1000/cnki-target", text=""):
    from io import BytesIO

    buffer = BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if doi or text:
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
        content = ("DOI: " + doi if doi else "") + "\n" + text
        commands = " ".join(
            "("
            + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            + ") Tj 0 -16 Td"
            for line in content.splitlines()
        )
        contents.set_data(f"BT /F1 12 Tf 50 700 Td {commands} ET".encode("ascii"))
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


def test_current_kcms2_bibliography_excludes_affiliations_and_reference_dois():
    from aletheia_nexus.acquire.access.cnki_metadata import (
        conflicting_fields,
        detail_bibliography,
    )
    from aletheia_nexus.core.paper_request import PaperRequest

    class Value(_Element):
        def get_attribute(self, name):
            return self.text if name == "value" else super().get_attribute(name)

    class Detail(_DetailPage):
        def locator(self, selector):
            return {
                ".wx-tit h1": _Element(text="膜下滴灌水稻品质性状的相关性及主成分分析"),
                "#authorpart span": _Rows(
                    [_Element(text="朱江艳1"), _Element(text="王圣毅2")]
                ),
                ".author span a": _Rows(
                    [_Element(text="朱江艳"), _Element(text="某研究机构")]
                ),
                ".row li": _Rows(
                    [
                        _Element(text="DOI： 10.14069/j.cnki.32-1769/s.2025.02.003"),
                        _Element(text="参考文献： DOI: 10.1000/other"),
                    ]
                ),
                ".top-tip": _Element(
                    text="大麦与谷类科学 . 2025 ,42 (02) : 15-19 查看该刊数据库收录来源"
                ),
                "#paramdbcode": Value(text="CJFQ"),
                "#param-filename": Value(text="DMKX202502003"),
            }.get(selector, _EmptyLocator())

    observed = detail_bibliography(Detail(), fallback_title="fallback")
    assert observed.authors == ("朱江艳", "王圣毅")
    assert observed.doi == "10.14069/j.cnki.32-1769/s.2025.02.003"
    assert observed.journal == "大麦与谷类科学" and observed.year == 2025
    assert (
        observed.volume == "42" and observed.issue == "02" and observed.pages == "15-19"
    )
    assert observed.cnki_id == "cnki:cjfq:dmkx202502003"
    assert not conflicting_fields(
        PaperRequest(title=observed.title, issue="2"), observed
    )


def test_title_only_ambiguous_results_stop_before_download(tmp_path):
    search = _SearchPage("中文论文标题")
    search.rows = _Rows(
        [_Row(search.link), _Row(_Element(text="中文论文标题", href="/another"))]
    )
    detail = _DetailPage()
    detail.pdf._click = lambda: pytest.fail("Ambiguous candidate must not download")
    attempt = _fetch(search, detail, tmp_path, doi="")
    assert attempt.status == BrowserAttemptStatus.AMBIGUOUS
    assert not attempt.download_started and not attempt.file_attempts


def test_doi_less_local_import_validates_and_never_mutates_original(tmp_path):
    from aletheia_nexus.acquire.access import (
        PaperRequest,
        acquire_full_text_maximized,
        import_local_pdf,
    )

    title = "Accurate scientific document identification without digital identifiers"
    request = PaperRequest(
        title=title, authors=("Alice Chen",), journal="Journal of Testing", year=2024
    )
    body = _valid_pdf(
        title, doi=None, text=title + "\nAlice Chen\nJournal of Testing 2024\nAbstract"
    )
    source = tmp_path / "original.pdf"
    source.write_bytes(body)
    result = import_local_pdf(request, source, output_dir=tmp_path / "saved")
    assert result.status == AcquisitionStatus.VERIFIED and source.read_bytes() == body
    assert not result.candidate.doi and result.candidate.article_id.startswith(
        "bibliographic:"
    )
    sidecar = json.loads(result.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["target"]["doi"] is None
    assert sidecar["target"]["article_id"] == request.article_id
    combined = acquire_full_text_maximized(
        request,
        local_pdf_path=source,
        output_dir=tmp_path / "combined",
        source_preference="exclude_cnki",
    )
    assert combined.status == MaximizedAcquisitionStatus.VERIFIED


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
    assert "CNKI detail bibliographic conflict: doi" in attempt.evidence
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
    detail.pdf._click = lambda: context.emit(
        "response", _response(detail, body=_valid_pdf(doi="10.1000/title-discovered"))
    )
    attempt = _fetch(
        _SearchPage("中文论文标题"), detail, tmp_path, context=context, doi=""
    )

    # Discovering a candidate DOI does not prove it is the requested title.
    assert attempt.status == BrowserAttemptStatus.RETRIEVED_UNVERIFIED
    assert attempt.source_candidate.doi == "10.1000/title-discovered"
    payload = json.loads(attempt.result.sidecar_path.read_text(encoding="utf-8"))
    assert payload["target"]["expected_title"] == "中文论文标题"


def test_title_only_never_invents_doi_when_article_has_none(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit(
        "response", _response(detail, body=_valid_pdf(doi=None))
    )
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
    assert attempt.status == BrowserAttemptStatus.RETRIEVED_UNVERIFIED
    assert attempt.source_candidate.doi == "10.1000/title-in-pdf"
    assert attempt.result.identity_validation.doi_match


def test_title_only_rejects_ambiguous_pdf_dois(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    body = _valid_pdf(doi="10.1000/one\nDOI: 10.1000/two")
    detail.pdf._click = lambda: context.emit("response", _response(detail, body=body))
    attempt = _fetch(
        _SearchPage("中文论文标题"), detail, tmp_path, context=context, doi=""
    )
    assert attempt.status == BrowserAttemptStatus.RETRIEVED_UNVERIFIED
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
        "response",
        _response(first, body=_valid_pdf("另一篇研究论文", doi="10.1000/wrong")),
    )
    second.pdf._click = lambda: context.emit("response", _response(second))
    result = _fetch(search, second, tmp_path, context=context)
    assert result.status == BrowserAttemptStatus.VERIFIED
    assert len(result.file_attempts) == 2
    rejected = result.file_attempts[0].result
    assert rejected.file_path.parent.name == "_unverified"
    assert rejected.sidecar_path.is_file()
    payload = json.loads(rejected.sidecar_path.read_text(encoding="utf-8"))
    assert payload["identity_validation"]["policy"] == "cnki_bibliographic/v3"
    assert result.result is result.file_attempts[1].result


def test_cnki_explicit_source_routes_english_titles_without_global_opt_in():
    metadata = _metadata(title="An English Article")

    def providers(url, enabled=True):
        return applicable_browser_providers(
            doi=metadata.doi,
            metadata=metadata,
            expected_title=metadata.title,
            config=BrowserAccessConfig(cnki_enabled=enabled),
            source_urls=(url,),
        )

    assert providers("https://kns.cnki.net/article")
    assert not providers("https://kns.cnki.net/article", enabled=False)
    assert not providers("https://cnki.net.evil.example/article")
    assert not providers("https://example.org/article")


def test_cnki_review_retention_can_be_disabled(tmp_path):
    detail = _DetailPage()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit(
        "response",
        _response(detail, body=_valid_pdf("另一篇研究论文", doi="10.1000/wrong")),
    )
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(cnki_keep_unverified=False),
    )
    assert attempt.status != BrowserAttemptStatus.VERIFIED
    assert attempt.result.file_path is None
    assert not list(tmp_path.rglob("*.pdf"))


def test_observed_direct_pdf_url_never_invents_or_crosses_origins():
    page = _DetailPage()
    assert (
        cnki_provider._direct_pdf_url(page, _Element(href="/article.pdf"))
        == "https://kns.cnki.net/article.pdf"
    )
    assert (
        cnki_provider._direct_pdf_url(
            page, _Element(href="https://other.example/article.pdf")
        )
        is None
    )
    assert cnki_provider._direct_pdf_url(page, _Element(href="/article.caj")) is None
    assert (
        cnki_provider._direct_pdf_url(page, _Element(href="javascript:download()"))
        is None
    )


def test_cnki_search_control_cold_start_retries_once(monkeypatch, tmp_path):
    original = CNKIGate.wait
    waits = 0

    def wait(gate, page, predicate, **kwargs):
        nonlocal waits
        if kwargs.get("stage") == "search controls":
            waits += 1
            if waits == 1:
                raise cnki_provider.CNKIStageTimeout("search controls")
        return original(gate, page, predicate, **kwargs)

    monkeypatch.setattr(CNKIGate, "wait", wait)
    detail = _DetailPage()
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("response", _response(detail))
    attempt = _fetch(_SearchPage("中文论文标题"), detail, tmp_path, context=context)
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert waits == 2
    assert "CNKI retried initial search-page hydration once" in attempt.evidence


def test_cnki_search_control_retry_is_bounded(monkeypatch, tmp_path):
    waits = 0

    def wait(gate, page, predicate, **kwargs):
        nonlocal waits
        waits += 1
        raise cnki_provider.CNKIStageTimeout("search controls")

    monkeypatch.setattr(CNKIGate, "wait", wait)
    attempt = _fetch(_SearchPage("中文论文标题"), _DetailPage(), tmp_path)
    assert attempt.status == BrowserAttemptStatus.NAVIGATION_ERROR
    assert waits == 2
    assert not attempt.download_started


def test_cnki_prior_manual_gate_prevents_control_reload(monkeypatch, tmp_path):
    waits = 0

    def wait(gate, page, predicate, **kwargs):
        nonlocal waits
        waits += 1
        gate.history.append(cnki_provider.ChallengeReport(ChallengeKind.CAPTCHA))
        raise cnki_provider.CNKIStageTimeout("search controls")

    monkeypatch.setattr(CNKIGate, "wait", wait)
    attempt = _fetch(_SearchPage("中文论文标题"), _DetailPage(), tmp_path)
    assert attempt.status == BrowserAttemptStatus.NAVIGATION_ERROR
    assert waits == 1


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


def test_cnki_formula_query_has_one_bounded_chinese_phrase_fallback():
    title = "Mo-Cu共掺RuO2电催化剂的制备及酸性析氧性能研究"
    assert cnki_provider._search_queries(title) == (
        title,
        "电催化剂的制备及酸性析氧性能研究",
    )
    assert cnki_provider._search_queries(
        "可控设计的Co-N/C电催化剂及其氧还原反应活性"
    ) == ("可控设计的Co-N/C电催化剂及其氧还原反应活性", "电催化剂及其氧还原反应活性")
    assert cnki_provider._search_queries("完整且没有化学式的中文论文标题") == (
        "完整且没有化学式的中文论文标题",
    )


def test_cnki_cross_language_candidate_does_not_mean_identity_match():
    title = "In situ Electrochemical Characterization Techniques for Active Hydrogen"
    page = _SearchPage("电催化硝酸盐还原合成氨过程中活性氢的原位电化学表征技术（英文）")
    results = cnki_provider._ranked_results(page, title=title, authors=(), limit=5)
    assert len(results) == 1 and results[0].cross_language
    detail = _DetailPage()
    detail.locator = lambda selector: (
        _Element(text=page.link.text) if selector == "h1" else _EmptyLocator()
    )
    matches, _ = cnki_provider._detail_identity(detail, doi="10.1000/test", title=title)
    assert not matches


def test_cnki_bilingual_heading_can_match_expected_english_title():
    title = "In situ Electrochemical Characterization Techniques for Active Hydrogen"
    detail = _DetailPage()
    detail.locator = lambda selector: (
        _Element(text="中文标题\n" + title)
        if selector == ".wx-tit"
        else _EmptyLocator()
    )
    matches, evidence = cnki_provider._detail_identity(
        detail, doi="10.1000/test", title=title
    )
    assert matches and evidence == "detail title similarity=1.000"


def test_cnki_search_text_quotes_operators_without_changing_identity_title():
    title = "Mo-Cu共掺RuO2电催化剂的制备及酸性析氧性能研究"
    assert cnki_provider._search_text(title, _Element()) == "'" + title + "'"
    assert cnki_provider._search_text("可控设计的Co-N/C电催化剂", _Element()) == (
        "'可控设计的Co-N/C电催化剂'"
    )
    control = SimpleNamespace(get_attribute=lambda name: "100")
    query = "In situ Electrochemical Characterization Techniques " * 3
    prepared = cnki_provider._search_text(query, control)
    assert len(prepared) <= 100 and query.startswith(prepared)


def test_translated_detail_without_doi_requires_explicit_candidate_flag():
    title = "In situ Electrochemical Characterization Techniques for Active Hydrogen"
    detail = _DetailPage()
    detail.locator = lambda selector: (
        _Element(text="中文论文标题（英文）") if selector == "h1" else _EmptyLocator()
    )
    assert not cnki_provider._detail_identity(detail, doi="10.1000/test", title=title)[
        0
    ]
    assert cnki_provider._detail_identity(
        detail, doi="10.1000/test", title=title, allow_translated_title=True
    ) == (True, "detail translated title; PDF identity required")


def test_translated_detail_flag_never_overrides_conflicting_doi():
    detail = _DetailPage()
    detail.locator = lambda selector: (
        _Element(content="10.9999/other")
        if selector == "meta[name='citation_doi']"
        else _EmptyLocator()
    )
    assert cnki_provider._detail_identity(
        detail,
        doi="10.1000/test",
        title="Specific English article title",
        allow_translated_title=True,
    ) == (False, "detail DOI mismatch")


def test_english_search_does_not_admit_arbitrary_chinese_title():
    page = _SearchPage("另一篇中文文章且没有英文标记")
    assert (
        cnki_provider._ranked_results(
            page,
            title="In situ Electrochemical Characterization Techniques for Active Hydrogen",
            authors=(),
            limit=5,
        )
        == ()
    )


@pytest.mark.parametrize("raise_on_close", [False, True])
def test_cnki_transient_download_popup_does_not_restart_context(raise_on_close):
    detail = _DetailPage()
    context = _Context(detail)

    class Popup(_DetailPage):
        def opener(self):
            return detail

        def wait_for_timeout(self, value):
            raise AssertionError("Do not pump a closing attachment popup")

    popup = Popup()
    detail.pdf._click = lambda: context.emit("page", popup)
    detail.wait_for_timeout = lambda value: popup.emit("download", _Download())

    def check(target):
        if target is popup:
            popup.closed = True
            if raise_on_close:
                raise cnki_provider.CNKITargetClosed()
        return False

    downloaded, capture = cnki_provider._capture_download(
        context,
        detail,
        detail.pdf,
        gate=SimpleNamespace(check=check),
        config=BrowserAccessConfig(navigation_timeout=0.1, poll_interval=0.01),
    )
    assert isinstance(downloaded, _Download)
    capture.close()


def test_cancelled_native_download_recovers_with_same_browser_session(
    monkeypatch, tmp_path
):
    requested = []
    disposed = []
    context = object()
    body = _valid_pdf("中文论文标题")
    response = SimpleNamespace(
        url="https://docdown.cnki.net/article.pdf?ticket=secret",
        status=200,
        headers={"content-type": "application/pdf"},
        body=lambda: body,
        dispose=lambda: disposed.append(True),
    )

    def request(active_context, **kwargs):
        assert active_context is context
        requested.append(kwargs)
        return response, ()

    class Cancelled(_Download):
        def save_as(self, path):
            raise RuntimeError("native transfer was cancelled")

    monkeypatch.setattr(cnki_provider, "_safe_context_get", request)
    config = BrowserAccessConfig(interactive=False)
    result = cnki_provider._finalize_cnki_download(
        Cancelled(),
        doi="10.1000/cnki-target",
        title="中文论文标题",
        detail_url=_DetailPage.url,
        output_dir=tmp_path,
        config=config,
        started_at=cnki_provider.time.perf_counter(),
        matched_title="中文论文标题",
        match_score=1.0,
        doi_origin="caller_doi",
        context=context,
        detail_page=_DetailPage(),
        gate=CNKIGate(config),
    )
    assert result.result.status == AcquisitionStatus.VERIFIED
    assert result.method == "cnki_pdf_context_request_recovery"
    assert len(requested) == 1 and disposed == [True]
    record = json.loads(result.result.sidecar_path.read_text(encoding="utf-8"))
    assert record["access"]["download_method"] == result.method
    assert "secret" not in result.result.sidecar_path.read_text(encoding="utf-8")


def test_recovery_html_login_is_handed_to_human_not_retried(monkeypatch):
    calls = []
    response = SimpleNamespace(
        url="https://login.cnki.net/login/",
        status=200,
        headers={"content-type": "text/html"},
        body=lambda: b"<html><title>Login</title><input type='password'></html>",
        dispose=lambda: None,
    )
    monkeypatch.setattr(
        cnki_provider,
        "_safe_context_get",
        lambda *a, **k: (calls.append(True) or response, ()),
    )
    page = _DetailPage()
    page.goto = lambda url, **kwargs: setattr(page, "url", url)
    original_locator = page.locator
    page.locator = lambda selector: (
        _Element()
        if page.url.startswith("https://login.cnki.net/")
        and selector == "input[type='password']"
        else original_locator(selector)
    )
    config = BrowserAccessConfig(interactive=False)
    with pytest.raises(CNKIInteractionRequired) as exc:
        cnki_provider._recover_pdf_request(
            object(),
            page,
            url="https://docdown.cnki.net/article.pdf",
            detail_url=page.url,
            gate=CNKIGate(config),
            config=config,
        )
    assert exc.value.report.kind == ChallengeKind.AUTHENTICATION
    assert calls == [True]


@pytest.mark.parametrize(
    "headers,body",
    [
        ({"content-length": "101"}, b"%PDF-test"),
        ({"content-disposition": 'attachment; filename="article.caj"'}, b"%PDF-test"),
        ({}, b"not a PDF"),
    ],
)
def test_recovery_rejects_oversize_caj_and_nonpdf(monkeypatch, headers, body):
    disposed = []
    response = SimpleNamespace(
        url="https://docdown.cnki.net/article",
        status=200,
        headers=headers,
        body=lambda: body,
        dispose=lambda: disposed.append(True),
    )
    monkeypatch.setattr(
        cnki_provider, "_safe_context_get", lambda *a, **k: (response, ())
    )
    page = _DetailPage()
    config = BrowserAccessConfig(interactive=False, max_bytes=100)
    with pytest.raises(cnki_provider.CNKIFileError):
        cnki_provider._recover_pdf_request(
            object(),
            page,
            url="https://docdown.cnki.net/article.pdf",
            detail_url=page.url,
            gate=CNKIGate(config),
            config=config,
        )
    assert disposed == [True]


def test_pdf_response_body_can_be_retried_after_transient_read_failure():
    detail = _DetailPage()
    context = _Context(detail)
    capture = CNKIFileCapture(context, detail, 100_000)
    response = _response(detail)
    reads = []

    def body():
        reads.append(True)
        if len(reads) == 1:
            raise RuntimeError("Response is not ready")
        return _valid_pdf()

    response.body = body
    context.emit("response", response)
    assert capture.next_file() is None
    assert capture.next_file().body == _valid_pdf()
    capture.close()


def test_pdf_headers_do_not_block_manual_gate_before_body_finishes():
    detail = _DetailPage()
    context = _Context(detail)
    capture = CNKIFileCapture(context, detail, 100_000)
    response = _response(detail)
    request = object()
    response.request = request
    reads = []
    response.body = lambda: reads.append(True) or _valid_pdf()
    context.emit("response", response)
    assert capture.next_file() is None
    assert not reads
    context.emit("requestfinished", request)
    assert capture.next_file().body == _valid_pdf()
    assert len(reads) == 1
    capture.close()


def test_failed_pdf_response_does_not_read_an_incomplete_body():
    detail = _DetailPage()
    context = _Context(detail)
    capture = CNKIFileCapture(context, detail, 100_000)
    response = _response(detail)
    request = object()
    response.request = request
    response.body = lambda: pytest.fail("Do not read a failed response body")
    context.emit("response", response)
    context.emit("requestfailed", request)
    assert capture.next_file() is None
    capture.close()


def test_manual_popup_can_close_after_verification_without_duplicate_download(tmp_path):
    detail, popup = _DetailPage(), _DetailPage()
    context = _Context(detail)
    popup.url = "https://kns.cnki.net/verify/home?captchaType=blockPuzzle"
    popup.opener = lambda: detail
    clicks = []

    def click():
        clicks.append(True)
        context.emit("page", popup)

    def human_finishes():
        popup.close()
        context.emit("response", _response(detail))

    popup.on_poll = human_finishes
    detail.pdf._click = click
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(poll_interval=0.01),
    )
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert attempt.interaction_used and attempt.download_started
    assert len(clicks) == 1


def test_save_failure_preserves_new_authentication_popup_and_its_opener(tmp_path):
    detail, popup = _DetailPage(), _DetailPage()
    context = _Context(detail)
    popup.url = "https://kns.cnki.net/verify/home?captchaType=blockPuzzle"
    popup.opener = lambda: detail

    class Download(_Download):
        def save_as(self, path):
            context.emit("page", popup)
            raise RuntimeError("Transfer requires authentication")

    detail.pdf._click = lambda: detail.emit("download", Download())
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(interactive=False),
    )
    assert attempt.status == BrowserAttemptStatus.INTERACTION_REQUIRED
    assert not popup.closed and not detail.closed
    assert attempt.download_started
    assert not list(tmp_path.rglob("*.part"))
    assert not any(context.listeners.values())


def test_closed_context_after_pdf_click_is_failure_not_a_safe_restart(tmp_path):
    detail = _DetailPage()
    search = _SearchPage("中文论文标题")
    context = _Context(detail)
    search.closed = False
    search.is_closed = lambda: search.closed

    def close_context():
        detail.close()
        search.closed = True
        context.emit("close", context)

    detail.pdf._click = close_context
    result = _fetch(search, detail, tmp_path, context=context)
    assert result.status == BrowserAttemptStatus.RETRIEVAL_FAILED
    assert result.download_started
    assert "CNKI browser target closed" in result.evidence


def test_browser_session_does_not_restart_after_unsaved_download(monkeypatch, tmp_path):
    from aletheia_nexus.acquire.access import BrowserSession

    session = BrowserSession(BrowserAccessConfig(profile_root=tmp_path))
    context = SimpleNamespace(new_page=_DetailPage)
    monkeypatch.setattr(session, "_ensure_started", lambda: context)
    monkeypatch.setattr(
        session, "close", lambda: pytest.fail("Must not replay download")
    )
    provider = CNKIProvider()
    calls = []

    def fetch(**kwargs):
        calls.append(True)
        return BrowserAccessAttempt(
            source_candidate=cnki_provider._source_candidate("10.1000/test"),
            final_url=None,
            status=BrowserAttemptStatus.ERROR,
            evidence=("CNKI browser target closed",),
            download_started=True,
        )

    monkeypatch.setattr(provider, "fetch", fetch)
    result = session.acquire_provider(provider, doi="10.1000/test", output_dir=tmp_path)
    assert result.download_started and len(calls) == 1


def test_manual_gate_requires_rendered_ready_content_and_two_clear_polls():
    page = _DetailPage()
    page.url = "https://kns.cnki.net/verify/home?captchaType=blockPuzzle"
    page.pdf.visible = False
    page.ready = False
    page.evaluate = lambda expression: page.ready
    polls = []

    def human_and_page_load():
        polls.append(True)
        page.url = _DetailPage.url
        page.ready = len(polls) >= 3

    page.on_poll = human_and_page_load
    gate = CNKIGate(BrowserAccessConfig(poll_interval=0.01))
    assert gate.check(page)
    assert len(polls) >= 4


def test_search_fallback_runs_after_all_detail_candidates_conflict(tmp_path):
    title = "Mo-Cu共掺RuO2电催化剂的制备及酸性析氧性能研究"
    search = _SearchPage(title)
    navigations = []

    def goto(url, **kwargs):
        search.url = url
        navigations.append(url)
        if len(navigations) == 2:
            search.link.href = "/kcms2/article/abstract?id=correct"

    search.goto = goto

    class Conflict(_DetailPage):
        def locator(self, selector):
            if selector == "meta[name='citation_doi']":
                return _Element(content="10.9999/wrong")
            return super().locator(selector)

    first, second = Conflict(), _DetailPage()
    context = _Context(second)
    queue = [first, second]
    context.expect_page = lambda **kwargs: _EventInfo(queue.pop(0))
    first.pdf._click = lambda: pytest.fail("Do not download a conflicting DOI")
    second.pdf._click = lambda: context.emit(
        "response", _response(second, body=_valid_pdf(title))
    )
    attempt = CNKIProvider().fetch(
        doi="10.1000/cnki-target",
        expected_title=title,
        context=context,
        page=search,
        output_dir=tmp_path,
        config=BrowserAccessConfig(),
    )
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert len(navigations) == 2 and attempt.candidates_considered == 2


def test_provenance_records_actual_field_when_title_menu_is_unavailable(tmp_path):
    search, detail = _SearchPage("中文论文标题"), _DetailPage()
    original_locator = search.locator
    field = _Element()
    field.get_attribute = lambda name: "SU" if name == "value" else None
    search.locator = lambda selector: (
        field if selector == "#selectfield" else original_locator(selector)
    )
    context = _Context(detail)
    detail.pdf._click = lambda: context.emit("response", _response(detail))
    attempt = _fetch(search, detail, tmp_path, context=context)
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    record = json.loads(attempt.result.sidecar_path.read_text(encoding="utf-8"))
    assert record["access"]["search_field"] == "SU"


def test_cnki_auto_login_without_password_is_not_a_manual_gate():
    page = _DetailPage()
    original = page.locator
    page.locator = lambda selector: (
        _Element(text="自动登录")
        if selector == "h1:has-text('自动登录')"
        else original(selector)
    )
    assert not CNKIGate(BrowserAccessConfig(interactive=False)).check(page)


def test_direct_cnki_default_keeps_waiting_for_human_authentication(
    monkeypatch, tmp_path
):
    from aletheia_nexus.acquire.access import cnki

    observed = []

    class Session:
        def __init__(self, config):
            observed.append(config)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def acquire_provider(self, *args, **kwargs):
            return "acquired"

    monkeypatch.setattr(cnki, "BrowserSession", Session)
    assert (
        cnki.acquire_cnki_pdf(title="中文论文标题", output_dir=tmp_path) == "acquired"
    )
    assert observed[0].interactive and observed[0].wait_for_interaction


def test_cnki_order_control_downloads_once_without_native_transfer(
    monkeypatch, tmp_path
):
    detail = _DetailPage()
    detail.pdf.href = "https://bar.cnki.net/bar/download/order?id=private"
    detail.pdf._click = lambda: pytest.fail(
        "A successful order request needs no second download"
    )
    context = _Context(detail)
    requested = []
    body = _valid_pdf()
    response = SimpleNamespace(
        status=200,
        url="https://docdown.cnki.net/target.pdf?ticket=private",
        headers={"content-type": "application/pdf"},
        body=lambda: body,
        dispose=lambda: None,
    )

    def request(active_context, **kwargs):
        assert active_context is context
        requested.append(kwargs)
        return response, ()

    monkeypatch.setattr(cnki_provider, "_safe_context_get", request)
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(cnki_context_request=True),
    )
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert len(requested) == 1 and attempt.download_started
    assert requested[0]["url"] == detail.pdf.href
    assert attempt.file_attempts[0].method == "cnki_pdf_control_request"
    record_text = attempt.result.sidecar_path.read_text(encoding="utf-8")
    record = json.loads(record_text)
    assert record["access"]["download_method"] == "cnki_pdf_control_request"
    assert record["retrieval"]["sha256"] == hashlib.sha256(body).hexdigest()
    assert "private" not in record_text


def test_cnki_order_entitlement_gate_never_falls_back_to_native(monkeypatch, tmp_path):
    detail = _DetailPage()
    detail.pdf.href = "https://bar.cnki.net/bar/download/order?id=private"
    detail.goto = lambda url, **kwargs: setattr(detail, "url", url)
    detail.pdf._click = lambda: pytest.fail("Do not retry a permission gate")
    response = SimpleNamespace(
        status=200,
        url=detail.pdf.href,
        headers={"content-type": "text/html"},
        body=lambda: b"<html>Your institution does not have access</html>",
        dispose=lambda: None,
    )
    monkeypatch.setattr(
        cnki_provider, "_safe_context_get", lambda *a, **k: (response, ())
    )
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        config=BrowserAccessConfig(interactive=False, cnki_context_request=True),
    )
    assert attempt.status == BrowserAttemptStatus.ENTITLEMENT_REQUIRED
    assert not detail.closed
    assert not list(tmp_path.rglob("*.part"))


def test_cnki_order_javascript_shell_falls_back_to_single_native_click(
    monkeypatch, tmp_path
):
    detail = _DetailPage()
    detail.pdf.href = "https://bar.cnki.net/bar/download/order?id=private"
    context = _Context(detail)
    response = SimpleNamespace(
        status=200,
        url=detail.pdf.href,
        headers={"content-type": "text/html"},
        body=lambda: b"<html><script>startDownload()</script></html>",
        dispose=lambda: None,
    )
    monkeypatch.setattr(
        cnki_provider, "_safe_context_get", lambda *a, **k: (response, ())
    )
    clicks = []

    def click():
        clicks.append(True)
        context.emit("response", _response(detail))

    detail.pdf._click = click
    attempt = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(cnki_context_request=True),
    )
    assert attempt.status == BrowserAttemptStatus.VERIFIED
    assert len(clicks) == 1
    assert attempt.file_attempts[0].method == "cnki_pdf_response"


@pytest.mark.parametrize(
    "headers,body",
    [
        ({"content-length": "101"}, b"%PDF-test"),
        ({"content-disposition": "attachment; filename=article.caj"}, b"%PDF-test"),
    ],
)
def test_cnki_order_file_policy_failure_never_reclicks_native(
    monkeypatch, tmp_path, headers, body
):
    detail = _DetailPage()
    detail.pdf.href = "https://bar.cnki.net/bar/download/order?id=private"
    detail.pdf._click = lambda: pytest.fail("Do not retry a rejected file")
    response = SimpleNamespace(
        status=200,
        url=detail.pdf.href,
        headers=headers,
        body=lambda: body,
        dispose=lambda: None,
    )
    monkeypatch.setattr(
        cnki_provider, "_safe_context_get", lambda *a, **k: (response, ())
    )
    result = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        config=BrowserAccessConfig(max_bytes=100, cnki_context_request=True),
    )
    assert result.status == BrowserAttemptStatus.RETRIEVAL_FAILED
    assert not list(tmp_path.rglob("*.part"))


def test_cnki_explicit_native_order_control_uses_click_not_api_request(
    monkeypatch, tmp_path
):
    detail = _DetailPage()
    detail.pdf.href = "https://bar.cnki.net/bar/download/order?id=private"
    context = _Context(detail)
    clicks = []

    def click():
        clicks.append(True)
        context.emit("response", _response(detail))

    detail.pdf._click = click
    monkeypatch.setattr(
        cnki_provider,
        "_safe_context_get",
        lambda *a, **k: pytest.fail("Use the browser control"),
    )
    result = _fetch(
        _SearchPage("中文论文标题"),
        detail,
        tmp_path,
        context=context,
        config=BrowserAccessConfig(cnki_context_request=False),
    )
    assert result.status == BrowserAttemptStatus.VERIFIED
    assert len(clicks) == 1
    assert not result.interaction_used
    assert result.file_attempts[0].method == "cnki_pdf_response"


def test_request_login_auto_ip_redirect_retries_without_manual_notice(monkeypatch):
    page = _DetailPage()
    page.goto = lambda url, **kwargs: setattr(page, "url", _DetailPage.url)
    body = _valid_pdf()
    responses = [
        SimpleNamespace(
            url="https://login.cnki.net/login/",
            status=200,
            headers={"content-type": "text/html"},
            body=lambda: b"<html><title>Login</title></html>",
            dispose=lambda: None,
        ),
        SimpleNamespace(
            url="https://docdown.cnki.net/article.pdf",
            status=200,
            headers={"content-type": "application/pdf"},
            body=lambda: body,
            dispose=lambda: None,
        ),
    ]
    requests = []

    def get(*args, **kwargs):
        requests.append(kwargs)
        return responses.pop(0), ()

    monkeypatch.setattr(cnki_provider, "_safe_context_get", get)
    config = BrowserAccessConfig(
        wait_for_interaction=True,
        interaction_callback=lambda *a: pytest.fail("No visible login form"),
    )
    gate = CNKIGate(config)
    result, _ = cnki_provider._recover_pdf_request(
        object(),
        page,
        url="https://docdown.cnki.net/article.pdf",
        detail_url=page.url,
        gate=gate,
        config=config,
    )
    assert result.body == body
    assert len(requests) == 2
    assert not gate.interaction_used and not gate.history


def test_repeated_request_login_without_visible_gate_is_not_manual_auth(monkeypatch):
    page = _DetailPage()
    page.goto = lambda url, **kwargs: setattr(page, "url", _DetailPage.url)
    response = SimpleNamespace(
        url="https://login.cnki.net/login/",
        status=200,
        headers={"content-type": "text/html"},
        body=lambda: b"<html><title>Login</title></html>",
        dispose=lambda: None,
    )
    calls = []
    monkeypatch.setattr(
        cnki_provider,
        "_safe_context_get",
        lambda *a, **k: (calls.append(True) or response, ()),
    )
    config = BrowserAccessConfig(wait_for_interaction=True)
    gate = CNKIGate(config)
    with pytest.raises(
        cnki_provider.CNKIFileError, match="after browser initialization"
    ):
        cnki_provider._recover_pdf_request(
            object(),
            page,
            url="https://docdown.cnki.net/article.pdf",
            detail_url=page.url,
            gate=gate,
            config=config,
        )
    assert len(calls) == 2
    assert not gate.interaction_used


def test_ip_auto_login_transition_waits_without_prompting_for_account():
    from aletheia_nexus.acquire.access.cnki_runtime import challenge_for_page

    page = _DetailPage()
    page.url = "https://login.cnki.net/login/"
    page.title = lambda: "中国知网-登录" if page.url.endswith("/login/") else "论文详情"
    original = page.locator
    page.locator = lambda selector: (
        _Element(text="自动登录")
        if selector == "h1:has-text('自动登录')" and page.url.endswith("/login/")
        else _EmptyLocator()
        if page.url.endswith("/login/")
        else original(selector)
    )
    assert challenge_for_page(page).kind == ChallengeKind.NONE
    polls = []

    def poll():
        polls.append(True)
        page.url = _DetailPage.url

    page.on_poll = poll
    gate = CNKIGate(
        BrowserAccessConfig(
            navigation_timeout=1,
            interaction_callback=lambda *a: pytest.fail(
                "Automatic IP login is not manual auth"
            ),
        )
    )
    gate.wait_ready(page, stage="institutional initialization")
    assert len(polls) >= 2 and not gate.interaction_used


def test_maximized_acquisition_stops_closed_cnki_transfer_before_generic_replay(
    monkeypatch, tmp_path
):
    attempt = BrowserAccessAttempt(
        source_candidate=cnki_provider._source_candidate("10.1000/target"),
        final_url=None,
        status=BrowserAttemptStatus.RETRIEVAL_FAILED,
        download_started=True,
        evidence=("CNKI browser target closed",),
    )
    base = MultiRouteAcquisitionResult(
        doi="10.1000/target",
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=DiscoveryResult(doi="10.1000/target", candidates=(), providers=()),
        expected_title="Target Article",
    )
    monkeypatch.setattr(service, "acquire_full_text", lambda *a, **k: base)
    monkeypatch.setattr(
        service,
        "applicable_browser_providers",
        lambda **k: (SimpleNamespace(name="cnki"),),
    )
    monkeypatch.setattr(
        service, "acquire_with_browser_provider", lambda *a, **k: attempt
    )
    monkeypatch.setattr(
        service,
        "acquire_with_browser",
        lambda **k: pytest.fail("Do not replay a closed CNKI transfer"),
    )
    result = service.acquire_full_text_maximized(
        "10.1000/target",
        output_dir=tmp_path,
        auto_official_api=False,
    )
    assert result.browser_attempts == (attempt,)
    assert result.status != MaximizedAcquisitionStatus.VERIFIED
