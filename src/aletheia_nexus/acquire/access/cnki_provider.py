import hashlib
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

import httpx

from aletheia_nexus.acquire.access.artifact import finalize_access_resource
from aletheia_nexus.acquire.access.base_provider import BaseBrowserProvider
from aletheia_nexus.acquire.access.browser_route import (
    _challenge_from_non_pdf_response,
    _safe_context_get,
    _safe_referer,
)
from aletheia_nexus.acquire.access.cnki_metadata import (
    conflicting_fields,
    detail_bibliography,
    detail_dois,
)
from aletheia_nexus.acquire.access.cnki_routing import cnki_route_reason
from aletheia_nexus.acquire.access.cnki_runtime import (
    CapturedPDF,
    CNKIFileCapture,
    CNKIFileError,
    CNKIGate,
    CNKIInteractionRequired,
    CNKIStageTimeout,
    CNKITargetClosed,
    captcha_visible,
    first_visible,
)
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
    BrowserFileAttempt,
    ChallengeKind,
    ChallengeReport,
)
from aletheia_nexus.acquire.access.security import (
    redact_url_for_record,
    validate_browser_network_url,
)
from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
    HostType,
)
from aletheia_nexus.acquire.fulltext.identity import declared_pdf_dois
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.validation import inspect_pdf
from aletheia_nexus.acquire.metadata.exceptions import MetadataError
from aletheia_nexus.acquire.metadata.resolver import get_metadata
from aletheia_nexus.acquire.metadata.transport import build_user_agent
from aletheia_nexus.core.identifiers.doi import (
    normalize_doi,
)
from aletheia_nexus.core.models import PaperMetadata
from aletheia_nexus.core.paper_request import PaperRequest

CNKI_SEARCH_URL = "https://kns.cnki.net/kns8s/"

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SPACE_RE = re.compile(r"\s+")
_SEARCH_INPUT_SELECTORS = (
    "#txt_SearchText",
    "#txt_search",
    "input.search-input",
    "input[placeholder*='检索']",
)
_SEARCH_BUTTON_SELECTORS = (
    ".search-btn",
    "button.search-btn",
    "input.search-btn",
)
_RESULT_ROW_SELECTOR = ".result-table-list tbody tr, .brief-table tbody tr"
_RESULT_LINK_SELECTOR = (
    "a.fz14, a.fz16, .name a, "
    "a[href*='/kcms2/article/abstract'], a[href*='/KCMS/detail']"
)
_NO_RESULTS_SELECTORS = (".no-result", ".no-results", ".noResult", "#noResult")
_PDF_SELECTORS = (
    "a#pdfDown",
    "a:has-text('PDF下载')",
    "a:has-text('PDF 下载')",
    "a[href*='download'][href*='pdf' i]",
    "button:has-text('PDF下载')",
    "a[title*='PDF' i]",
)


class _ScholarlyMetadataParser(HTMLParser):
    """Extract citation metadata and CHNDOI labelled fields from trusted pages."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.authors: list[str] = []
        self._in_title = False
        self._document_title: list[str] = []
        self._pending_label: str | None = None
        self._label_chunks: list[str] = []

    def _finish_label(self) -> None:
        value = " ".join(self._label_chunks).strip()
        if self._pending_label == "title" and value:
            self.title = self.title or value
        elif self._pending_label == "authors" and value:
            self.authors.extend(
                item.strip() for item in re.split(r"[;,；，]", value) if item.strip()
            )
        self._pending_label = None
        self._label_chunks = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = {str(key).casefold(): value for key, value in attrs}
        if tag.casefold() == "meta":
            name = str(values.get("name") or values.get("property") or "").casefold()
            content = unescape(str(values.get("content") or "")).strip()
            if name in {"citation_title", "dc.title", "og:title"} and content:
                self.title = self.title or content
            elif name in {"citation_author", "dc.creator"} and content:
                self.authors.append(content)
        elif tag.casefold() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._in_title = False
        elif tag.casefold() in {"td", "tr"}:
            self._finish_label()

    def handle_data(self, data: str) -> None:
        value = unescape(data).strip()
        if not value:
            return
        if self._in_title:
            self._document_title.append(value)
        labelled = re.match(r"^(题名|作者)\s*[：:]\s*(.*)$", value)
        if labelled:
            self._finish_label()
            self._pending_label = "title" if labelled[1] == "题名" else "authors"
            if labelled[2]:
                self._label_chunks.append(labelled[2])
            return
        if self._pending_label is not None:
            self._label_chunks.append(value)

    def result(
        self, *, allow_document_title: bool = True
    ) -> tuple[str | None, tuple[str, ...]]:
        self._finish_label()
        title = self.title
        if title is None and allow_document_title and self._document_title:
            candidate = " ".join(self._document_title).strip()
            if candidate and candidate.casefold() not in {
                "doi not found",
                "多重解析地址选择页面",
            }:
                title = candidate
        return title, tuple(dict.fromkeys(self.authors))


def _normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", _clean_title(value)).casefold()
    # Ignore typography (subscripts, punctuation, line breaks), not words.
    return "".join(character for character in value if character.isalnum())


def _clean_title(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return _SPACE_RE.sub(" ", value).strip()


def _contains_chinese(value: str | None) -> bool:
    return bool(value and _CJK_RE.search(value))


def _first_visible(page, selectors: tuple[str, ...]):
    return first_visible(page, selectors)


def _captcha_visible(page) -> bool:
    return captcha_visible(page)


def _wait_for_manual_captcha(
    page,
    *,
    config: BrowserAccessConfig,
) -> tuple[bool, bool, ChallengeReport | None]:
    """Compatibility adapter around the shared CNKI manual-interaction gate."""
    gate = CNKIGate(config)
    try:
        gate.check(page)
    except CNKIInteractionRequired as exc:
        return False, gate.interaction_used, exc.report
    return True, gate.interaction_used, gate.history[0] if gate.history else None


def _metadata_for_query(
    doi: str,
    *,
    metadata: PaperMetadata | None,
    expected_title: str | None,
    metadata_mailto: str | None,
) -> tuple[str, tuple[str, ...], PaperMetadata | None]:
    title = (_clean_title(expected_title) or None) if expected_title else None
    resolved = metadata
    if title is None and resolved is not None and resolved.title:
        title = _clean_title(resolved.title) or None
    metadata_error: MetadataError | None = None
    if title is None:
        try:
            resolved = get_metadata(doi, mailto=metadata_mailto)
            title = (_clean_title(resolved.title) or None) if resolved.title else None
        except MetadataError as exc:
            metadata_error = exc
    if title is None or (
        expected_title is None
        and not _contains_chinese(title)
        and (".cnki." in doi.casefold() or doi.casefold().startswith("10.7503/cjcu"))
    ):
        fallback_title, fallback_authors = _metadata_from_chinese_sources(
            doi,
            mailto=metadata_mailto,
        )
        if fallback_title:
            return fallback_title, fallback_authors, resolved
    if not title:
        raise ValueError("CNKI title search requires resolvable paper metadata") from (
            metadata_error
        )
    return title, resolved.authors if resolved is not None else (), resolved


def _metadata_from_chinese_sources(
    doi: str,
    *,
    mailto: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve Chinese DOI metadata when Crossref/DataCite lack the record."""

    encoded_query = quote(doi, safe="")
    encoded_path = quote(doi, safe="/")
    urls = [
        f"https://www.chndoi.org/Resolution/Handler?doi={encoded_query}",
    ]
    if doi.casefold().startswith("10.7503/cjcu"):
        urls.extend(
            (
                f"https://cjournal.hep.com.cn/0251-0790/CN/{encoded_path}",
                f"http://www.cjcu.jlu.edu.cn/CN/{encoded_path}",
            )
        )

    headers = {"User-Agent": build_user_agent(mailto)}
    for url in urls:
        try:
            response = httpx.get(
                url,
                headers=headers,
                timeout=15.0,
                follow_redirects=True,
            )
            if response.status_code != 200:
                continue
            parser = _ScholarlyMetadataParser()
            parser.feed(response.text[:2_000_000])
            title, authors = parser.result(allow_document_title=False)
            if title:
                return _clean_title(title), authors
        except (httpx.HTTPError, UnicodeError, ValueError):
            continue
    return None, ()


@dataclass(frozen=True)
class _RankedResult:
    link: object
    title: str
    url: str | None
    score: float
    cross_language: bool = False


def _search_queries(title: str) -> tuple[str, ...]:
    """Try one punctuation-free CJK phrase when CNKI tokenizes formulae."""
    phrases = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]{8,}", title)
    phrase = max(phrases, key=len, default="")
    return (title, phrase) if phrase and phrase != title else (title,)


def _search_text(query: str, control) -> str:
    """Quote CNKI operators and respect the input's advertised length limit."""
    quoted = bool(re.search(r"[-+*/'\"]", query))
    raw_limit = control.get_attribute("maxlength")
    limit = int(raw_limit) if raw_limit and raw_limit.isdigit() else None
    if limit and len(query) + (2 if quoted else 0) > limit:
        query = query[: max(0, limit - (2 if quoted else 0))]
        if not _contains_chinese(query) and " " in query:
            query = query.rsplit(" ", 1)[0]
    # Site help explicitly requires ASCII quotes around special operators.
    return "'" + query.replace("'", " ").replace('"', " ") + "'" if quoted else query


def _select_search_field(page, gate, *, name: str) -> bool:
    """Use CNKI's field menu instead of mutating hidden inputs."""
    field = page.locator("#selectfield")
    if not field.count():
        return False
    if field.first.get_attribute("value") == name:
        return True
    trigger = _first_visible(page, (".sort .sort-default",))
    if trigger is None:
        return False
    trigger.click()
    option = gate.wait(
        page,
        lambda: _first_visible(page, (f".sort-list li[data-val='{name}'] a",)),
        stage="title search field",
    )
    option.click()
    gate.wait(
        page,
        lambda: field.first.get_attribute("value") == name,
        stage="title search field",
    )
    return True


def _ranked_results(
    page, *, title: str, authors: tuple[str, ...], limit: int, request=None
):
    rows = page.locator(_RESULT_ROW_SELECTOR)
    expected = _normalized_title(title)
    author_tokens = tuple(
        token for author in authors[:3] if (token := _normalized_title(author))
    )
    ranked = []
    seen = set()
    for index in range(min(rows.count(), limit)):
        row = rows.nth(index)
        links = row.locator(_RESULT_LINK_SELECTOR)
        try:
            if links.count() < 1:
                continue
            link = links.first
            observed_title = _clean_title(link.inner_text())
            observed = _normalized_title(observed_title)
            if not observed:
                continue
            score = SequenceMatcher(None, expected, observed).ratio()
            cross_language = (
                not _contains_chinese(title)
                and len(expected) >= 40
                and _contains_chinese(observed_title)
                and bool(re.search(r"[（(]英文[）)]$", observed_title))
            )
            # Authors rank plausible titles; they cannot make an unrelated title
            # cross the retrieval threshold. PDF identity remains authoritative.
            if score < 0.60 and not cross_language:
                continue
            row_text = _normalized_title(row.inner_text())
            if request is not None:
                for value in (
                    request.journal,
                    str(request.year) if request.year else None,
                ):
                    if value and _normalized_title(value) in row_text:
                        score += 0.12
            if (
                score >= 0.60
                and author_tokens
                and any(token in row_text for token in author_tokens)
            ):
                score += 0.08
            href = (link.get_attribute("href") or "").strip()
            url = None
            if href and not href.lower().startswith(("javascript:", "#")):
                try:
                    url = validate_browser_network_url(urljoin(page.url, href))
                except (TypeError, ValueError):
                    continue
            key = url or observed
            if key in seen:
                continue
            seen.add(key)
            ranked.append(
                _RankedResult(link, observed_title, url, score, cross_language)
            )
        except Exception:
            continue
    return tuple(sorted(ranked, key=lambda item: item.score, reverse=True))


def _best_result_link(page, *, title: str, authors: tuple[str, ...], limit: int):
    results = _ranked_results(page, title=title, authors=authors, limit=limit)
    return results[0].link if results else None


def _detail_dois(page) -> tuple[str, ...]:
    return detail_dois(page)


def _detail_identity(
    page, *, doi: str, title: str, allow_translated_title: bool = False
) -> tuple[bool, str]:
    """Reject contradictory detail metadata before spending an entitlement."""
    observed_dois = _detail_dois(page)
    if len(observed_dois) > 1:
        return False, "detail DOI ambiguous"
    observed_titles = []
    for selector in (
        "meta[name='citation_title']",
        "meta[name='dc.Title' i]",
        ".wx-tit",
        ".en-tit",
        "h1",
    ):
        locator = page.locator(selector)
        if locator.count():
            observed_title = locator.first.get_attribute("content")
            if not observed_title:
                observed_title = locator.first.inner_text()
            if observed_title:
                observed_titles.append(observed_title)
    if observed_dois and doi:
        matches = doi in observed_dois
        return matches, "detail DOI matched" if matches else "detail DOI mismatch"
    if observed_titles:
        expected = _normalized_title(title)
        specific_title = len(expected) >= 40 or (
            len(expected) >= 12 and len(_CJK_RE.findall(expected)) >= 8
        )
        score = max(
            1.0
            if specific_title and expected in _normalized_title(observed)
            else SequenceMatcher(None, expected, _normalized_title(observed)).ratio()
            for observed in observed_titles
        )
        if (
            score < 0.60
            and allow_translated_title
            and not _contains_chinese(title)
            and any(_contains_chinese(observed) for observed in observed_titles)
        ):
            return True, "detail translated title; PDF identity required"
        return score >= 0.60, f"detail title similarity={score:.3f}"
    return True, "detail metadata unavailable; PDF identity required"


def _pdf_control(page):
    """Return a visible PDF control while explicitly excluding CAJ-only links."""

    for selector in _PDF_SELECTORS:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                text = (item.inner_text() or "").casefold()
                href = (item.get_attribute("href") or "").casefold()
                label = (item.get_attribute("title") or "").casefold()
                if "caj" in text or "caj" in href or "caj" in label:
                    continue
                if item.is_visible():
                    return item
            except Exception:
                continue
    return None


def _pdf_order_url(page, control) -> str | None:
    """Use only the observed CNKI order endpoint exposed by its PDF control.

    Fetching this URL through the same context avoids a native attachment
    transfer without inventing endpoints or bypassing institutional access.
    Other controls (including JavaScript/blob links) keep the browser path.
    """
    href = (control.get_attribute("href") or "").strip()
    if not href or href.casefold().startswith(("javascript:", "blob:", "#")):
        return None
    url = validate_browser_network_url(urljoin(page.url, href))
    parts = urlsplit(url)
    if parts.hostname == "bar.cnki.net" and parts.path == "/bar/download/order":
        return url
    return None


def _direct_pdf_url(page, control) -> str | None:
    """Use a same-origin PDF anchor, never invent a file endpoint."""
    href = (control.get_attribute("href") or "").strip()
    if not href or href.casefold().startswith(("javascript:", "blob:", "#")):
        return None
    url = validate_browser_network_url(urljoin(page.url, href))
    target, origin = urlsplit(url), urlsplit(page.url)
    if (target.scheme, target.netloc) == (
        origin.scheme,
        origin.netloc,
    ) and target.path.casefold().endswith(".pdf"):
        return url
    return None


def _source_candidate(
    doi: str,
    url: str = CNKI_SEARCH_URL,
    *,
    url_type: CandidateUrlType = CandidateUrlType.LANDING_PAGE,
) -> FullTextCandidate:
    return FullTextCandidate(
        doi=doi,
        url=url,
        provenance=(DiscoveryProvider.CNKI,),
        url_type=url_type,
        host_type=HostType.INDEX,
        source_name="CNKI authenticated title search",
    )


def _status_for_result(result: AcquisitionResult) -> BrowserAttemptStatus:
    if result.status == AcquisitionStatus.VERIFIED:
        return BrowserAttemptStatus.VERIFIED
    if result.status in {
        AcquisitionStatus.RETRIEVED_UNVERIFIED,
        AcquisitionStatus.MISMATCH,
        AcquisitionStatus.SUPPLEMENT,
    }:
        return BrowserAttemptStatus.RETRIEVED_UNVERIFIED
    return BrowserAttemptStatus.RETRIEVAL_FAILED


def _capture_download(context, page, pdf_button, *, gate, config):
    capture = CNKIFileCapture(context, page, config.max_bytes)
    preserve_page = None
    completed = False
    try:
        gate.download_started = True
        pdf_button.click()
        deadline = time.monotonic() + config.navigation_timeout
        retries = 0
        retry_after_handoff = False
        handoff_grace_deadline = 0.0
        while True:
            if capture.context_closed:
                raise CNKITargetClosed()
            live_pages = [item for item in capture.pages if not item.is_closed()]
            if not live_pages:
                raise CNKITargetClosed()
            cleared = False
            for target in live_pages:
                try:
                    cleared = gate.check(target) or cleared
                except Exception as exc:
                    if (
                        target is not page
                        and not page.is_closed()
                        and (
                            isinstance(exc, CNKITargetClosed)
                            or type(exc).__name__ == "TargetClosedError"
                        )
                    ):
                        # Attachment-only popups can close as the download is
                        # dispatched. This is not a lost browser context.
                        continue
                    raise
            if cleared:
                retry_after_handoff = True
                deadline = time.monotonic() + config.navigation_timeout
                handoff_grace_deadline = time.monotonic() + min(
                    1.0, config.navigation_timeout / 2
                )
                # Verification may resume the download itself. Pump events and
                # check capture before any bounded re-click of the PDF control.
                pump = page if not page.is_closed() else live_pages[0]
                pump.wait_for_timeout(100)
                downloaded = capture.next_file()
                if downloaded is not None:
                    completed = True
                    return downloaded, capture
            downloaded = capture.next_file()
            if downloaded is not None:
                completed = True
                return downloaded, capture
            if (
                retry_after_handoff
                and retries < 1
                and not page.is_closed()
                and not capture.transfer_pending
                and time.monotonic() >= handoff_grace_deadline
            ):
                control = _pdf_control(page)
                if control is not None:
                    retries += 1
                    retry_after_handoff = False
                    control.click()
            if time.monotonic() >= deadline:
                raise CNKIStageTimeout("PDF retrieval")
            # Pump the stable detail page, not a transient attachment popup.
            pump = page if not page.is_closed() else live_pages[0]
            pump.wait_for_timeout(
                min(config.poll_interval, max(0.01, deadline - time.monotonic())) * 1000
            )
    except CNKIInteractionRequired as exc:
        preserve_page = exc.page
        raise
    finally:
        if not completed:
            capture.close(preserve=preserve_page)


def _finalize_cnki_download(
    downloaded,
    *,
    doi,
    title,
    detail_url,
    output_dir,
    config,
    started_at,
    matched_title,
    match_score,
    doi_origin,
    context=None,
    detail_page=None,
    gate=None,
    recovery_page=None,
    capture_pages=(),
    search_query=None,
    search_field=None,
    cross_language_result=False,
    download_method=None,
    request_redirects=(),
    target_identity=None,
    observed_identity=None,
):
    staging_dir = Path(output_dir) / "_browser-downloads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temporary = staging_dir / f".an-cnki-{uuid4().hex}.part"
    try:
        redirects = request_redirects
        raw_url = str(getattr(downloaded, "url", "") or "")
        if raw_url.startswith("blob:"):
            blob_origin = validate_browser_network_url(raw_url[5:])
            if urlsplit(blob_origin)[:2] != urlsplit(detail_url)[:2]:
                raise CNKIFileError("CNKI download has an unexpected blob origin")
            resource_url = detail_url
        else:
            resource_url = validate_browser_network_url(raw_url or detail_url)
        if isinstance(downloaded, CapturedPDF):
            temporary.write_bytes(downloaded.body)
            method = download_method or "cnki_pdf_response"
        else:
            filename = str(getattr(downloaded, "suggested_filename", "") or "")
            if filename.casefold().endswith(".caj"):
                raise CNKIFileError("CNKI returned CAJ instead of PDF")
            try:
                downloaded.save_as(temporary)
                method = "cnki_pdf_download"
            except Exception as exc:
                stable_page = detail_page
                if stable_page is None or stable_page.is_closed():
                    stable_page = recovery_page
                if (
                    context is None
                    or stable_page is None
                    or gate is None
                    or stable_page.is_closed()
                    or raw_url.startswith("blob:")
                ):
                    raise CNKIFileError(
                        "CNKI browser download could not be saved"
                    ) from exc
                for target in capture_pages:
                    if not target.is_closed():
                        gate.check(target)
                recovered, redirects = _recover_pdf_request(
                    context,
                    stable_page,
                    url=resource_url,
                    detail_url=detail_url,
                    gate=gate,
                    config=config,
                )
                temporary.write_bytes(recovered.body)
                resource_url = recovered.url
                downloaded = recovered
                method = "cnki_pdf_context_request_recovery"
        size = temporary.stat().st_size
        if size > config.max_bytes:
            raise CNKIFileError("CNKI PDF exceeds max_bytes")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if not doi:
            inspection = inspect_pdf(temporary)
            observed_dois = declared_pdf_dois(inspection.first_page_text)
            if len(observed_dois) == 1:
                doi = observed_dois[0]
                doi_origin = "pdf_front_matter_declared_doi"
            else:
                doi_origin = "bibliographic_identity"
        candidate = _source_candidate(doi, resource_url, url_type=CandidateUrlType.PDF)
        if target_identity is None:
            target_identity = PaperRequest(doi=doi or None, title=title)
        identity_key = replace(
            target_identity,
            doi=doi or None,
            cnki_id=(
                observed_identity.cnki_id
                if observed_identity
                else target_identity.cnki_id
            ),
        )
        candidate = replace(candidate, article_id=identity_key.article_id)
        resource = RetrievedResource(
            requested_url=detail_url,
            final_url=resource_url,
            http_status=getattr(downloaded, "status", 200),
            content_type=getattr(downloaded, "content_type", "application/pdf"),
            size_bytes=size,
            sha256=digest.hexdigest(),
            local_path=temporary,
            elapsed_seconds=time.perf_counter() - started_at,
            redirects=redirects,
        )
        result = finalize_access_resource(
            candidate=candidate,
            resource=resource,
            output_dir=output_dir,
            expected_title=title,
            keep_unverified=config.keep_unverified or config.cnki_keep_unverified,
            transport="cnki_authenticated_browser",
            access_details={
                "provider": "cnki",
                "validation_policy": "cnki_bibliographic/v3",
                "observed_bibliography": asdict(observed_identity)
                if observed_identity
                else None,
                "fetcher": "CNKIProvider",
                "source_page_url": detail_url,
                "access_method": "playwright_institution_auth",
                "query_method": "title_with_optional_author_ranking",
                "matched_result_title": matched_title,
                "result_match_score": round(match_score, 4),
                "download_method": method,
                "search_title": title,
                "submitted_query": search_query,
                "search_field": search_field,
                "cross_language_result": cross_language_result,
                "doi_resolution_method": doi_origin,
            },
            access_evidence=(
                "CNKI result selected by title/author metadata",
                "Explicit PDF download control used; CAJ links excluded",
            ),
            target_identity=target_identity,
            observed_identity=observed_identity,
        )
        return BrowserFileAttempt(
            candidate=candidate,
            result=result,
            source_page_url=redact_url_for_record(detail_url),
            method=method,
        )
    finally:
        temporary.unlink(missing_ok=True)


def _transport_failure_code(exc: Exception) -> str:
    """Keep actionable transport causes, never raw messages or signed URLs."""
    message = str(exc).casefold()
    for markers, code in (
        (("has been closed", "target closed", "browser closed"), "browser_closed"),
        (("timeout", "timed out", "etimedout"), "timeout"),
        (("econnreset", "connection reset", "socket hang up"), "connection_reset"),
        (("enotfound", "name_not_resolved", "eai_again"), "dns_error"),
        (("certificate", "err_ssl", "tls"), "tls_error"),
        (("econnrefused", "connection_refused"), "connection_refused"),
    ):
        if any(marker in message for marker in markers):
            return code
    return "transport_error"


def _recover_pdf_request(context, page, *, url, detail_url, gate, config):
    """Recover one cancelled browser transfer using its existing cookie jar.

    Only use the URL emitted by the explicit PDF click. Redirects retain the
    shared URL safety checks; HTML authentication is handed back to the user.
    """
    for retry in range(2):
        gate.check(page)
        headers = {}
        referer = _safe_referer(detail_url, url)
        if referer:
            headers["Referer"] = referer
        try:
            response, redirects = _safe_context_get(
                context,
                url=url,
                request_kwargs={
                    "headers": headers,
                    "timeout": config.request_timeout * 1000,
                    "fail_on_status_code": False,
                },
                max_redirects=config.max_request_redirects,
            )
        except Exception as exc:
            raise CNKIFileError(
                "CNKI browser-session download recovery failed: "
                + _transport_failure_code(exc)
            ) from exc
        try:
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > config.max_bytes:
                raise CNKIFileError("CNKI PDF exceeds max_bytes")
            body = response.body()
            if len(body) > config.max_bytes:
                raise CNKIFileError("CNKI PDF exceeds max_bytes")
            disposition = response.headers.get("content-disposition", "").casefold()
            if "caj" in disposition or urlsplit(response.url).path.casefold().endswith(
                ".caj"
            ):
                raise CNKIFileError("CNKI returned CAJ instead of PDF")
            if response.status == 200 and b"%PDF-" in body[:1024]:
                return CapturedPDF(
                    url=validate_browser_network_url(response.url),
                    body=body,
                    status=response.status,
                    content_type=response.headers.get(
                        "content-type", "application/pdf"
                    ),
                ), redirects
            challenge = _challenge_from_non_pdf_response(response, body)
            handoff_url = validate_browser_network_url(response.url)
        finally:
            response.dispose()
        if challenge.kind == ChallengeKind.NONE:
            raise CNKIFileError("CNKI browser-session recovery returned no PDF")
        if challenge.kind in {ChallengeKind.ENTITLEMENT, ChallengeKind.ACCESS_DENIED}:
            # A policy denial is terminal, not an invitation to navigate/retry.
            gate.history.append(challenge)
            raise CNKIInteractionRequired(page, challenge)
        # Show the actual gate; do not solve it or fill any credentials.
        page.goto(
            handoff_url,
            wait_until="domcontentloaded",
            timeout=config.navigation_timeout * 1000,
        )
        # The login endpoint may automatically identify the institutional IP
        # and redirect back without showing any login form. Absence of a gate
        # is not an unresolved authentication. Also wait for hydrated forms;
        # domcontentloaded alone can precede CNKI's session initialization.
        gate.wait_ready(page, stage="download access initialization")
        if retry:
            raise CNKIFileError(
                "CNKI browser-session request still returned an access page "
                "after browser initialization"
            )
    raise CNKIFileError("CNKI browser-session recovery exhausted its retry")


class CNKIProvider(BaseBrowserProvider):
    """Acquire CNKI PDFs with a caller-owned, institution-authenticated browser."""

    name = "cnki"
    priority = 900

    def __init__(
        self, *, authors: tuple[str, ...] = (), request: PaperRequest | None = None
    ):
        if not isinstance(authors, tuple) or any(
            not isinstance(author, str) for author in authors
        ):
            raise TypeError("authors must be a tuple of strings")
        self.authors = authors
        self.request = request

    def is_applicable(
        self,
        *,
        doi: str,
        metadata: PaperMetadata | None,
        expected_title: str | None,
        config: BrowserAccessConfig,
    ) -> bool:
        return (
            cnki_route_reason(
                doi=doi,
                metadata=metadata,
                expected_title=expected_title,
                config=config,
                request=self.request,
            )
            is not None
        )

    def fetch(
        self,
        *,
        doi: str,
        context,
        page,
        output_dir: str | Path,
        config: BrowserAccessConfig,
        metadata: PaperMetadata | None = None,
        expected_title: str | None = None,
        metadata_mailto: str | None = None,
    ) -> BrowserAccessAttempt:
        started_at = time.perf_counter()
        normalized_doi = normalize_doi(doi) if doi else ""
        source = _source_candidate(normalized_doi)
        gate = CNKIGate(config)
        detail_page = None
        preserve_page = None
        files: list[BrowserFileAttempt] = []
        evidence: list[str] = []
        considered = 0
        stage = "metadata"

        def attempt(status, *, target=None, error=None):
            target = target or detail_page or page
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=redact_url_for_record(getattr(target, "url", None)),
                status=status,
                challenge_history=tuple(gate.history),
                file_attempts=tuple(files),
                candidates_considered=considered,
                interaction_used=gate.interaction_used,
                evidence=tuple(evidence),
                error=error,
                elapsed_seconds=time.perf_counter() - started_at,
                download_started=gate.download_started,
            )

        try:
            title, authors, _ = _metadata_for_query(
                normalized_doi,
                metadata=metadata,
                expected_title=expected_title,
                metadata_mailto=metadata_mailto,
            )
            authors = self.authors or authors
            target_identity = self.request or PaperRequest(
                doi=normalized_doi or None,
                title=title,
                authors=self.authors,
            )
            if target_identity.title is None:
                target_identity = replace(target_identity, title=title)
            stage = "search navigation"
            try:
                page.goto(
                    CNKI_SEARCH_URL,
                    wait_until="domcontentloaded",
                    timeout=config.navigation_timeout * 1000,
                )
            except Exception as exc:
                # A verification shell can time out before widgets hydrate.
                if not gate.check(page) and type(exc).__name__ != "TimeoutError":
                    raise
            stage = "search controls"

            def search_controls():
                search_input = _first_visible(page, _SEARCH_INPUT_SELECTORS)
                search_button = _first_visible(page, _SEARCH_BUTTON_SELECTORS)
                return (
                    (search_input, search_button)
                    if (search_input is not None and search_button is not None)
                    else None
                )

            def result_state():
                rows = page.locator(_RESULT_ROW_SELECTOR)
                for index in range(min(rows.count(), config.cnki_max_results)):
                    links = rows.nth(index).locator(_RESULT_LINK_SELECTOR)
                    if links.count() and links.first.inner_text().strip():
                        return "results"
                if _first_visible(page, _NO_RESULTS_SELECTORS) is not None:
                    return "empty"
                return None

            results = ()
            failures = []
            seen_candidates = set()
            seen_records = set()
            control_retry_used = False
            for query_index, query in enumerate(_search_queries(title)):
                if query_index:
                    # Navigate afresh: old visible rows must not satisfy the
                    # next search while the new response is still loading.
                    stage = "search navigation"
                    page.goto(
                        CNKI_SEARCH_URL,
                        wait_until="domcontentloaded",
                        timeout=config.navigation_timeout * 1000,
                    )
                    evidence.append(
                        "CNKI retried a punctuation-free Chinese title phrase"
                    )
                stage = "search controls"
                try:
                    search_input, search_button = gate.wait(
                        page, search_controls, stage=stage
                    )
                except CNKIStageTimeout:
                    # One cold-start hydration retry is safe only before any
                    # entitlement-consuming action and outside manual gates.
                    if control_retry_used or gate.history or gate.download_started:
                        raise
                    control_retry_used = True
                    evidence.append("CNKI retried initial search-page hydration once")
                    page.goto(
                        CNKI_SEARCH_URL,
                        wait_until="domcontentloaded",
                        timeout=config.navigation_timeout * 1000,
                    )
                    search_input, search_button = gate.wait(
                        page, search_controls, stage=stage
                    )
                field_name = "TI" if _contains_chinese(title) else "SU"
                field_selected = _select_search_field(page, gate, name=field_name)
                actual_field = None
                field_control = page.locator("#selectfield")
                if field_control.count():
                    actual_field = field_control.first.get_attribute("value") or None
                if field_selected:
                    evidence.append(
                        "CNKI search field: article title (TI)"
                        if field_name == "TI"
                        else "CNKI search field: subject (SU) for bilingual metadata"
                    )
                submitted_query = _search_text(query, search_input)
                search_input.fill(submitted_query)
                search_button.click()
                stage = "search results"
                search_retries = 0

                def resume_search():
                    nonlocal search_retries
                    if search_retries or result_state():
                        return
                    controls = gate.wait(page, search_controls, stage="search controls")
                    if controls:
                        search_retries += 1
                        controls[0].fill(submitted_query)
                        controls[1].click()

                state = gate.wait(
                    page, result_state, stage=stage, on_resume=resume_search
                )
                results = (
                    ()
                    if state == "empty"
                    else _ranked_results(
                        page,
                        title=title,
                        authors=authors,
                        limit=config.cnki_max_results,
                        request=target_identity,
                    )
                )
                if not results:
                    continue
                if (
                    not normalized_doi
                    and not target_identity.cnki_id
                    and page.locator(_RESULT_ROW_SELECTOR).count()
                    > config.cnki_max_results
                ):
                    evidence.append(
                        "CNKI candidate limit leaves unexamined rows; refine the citation or increase cnki_max_results"
                    )
                    return attempt(BrowserAttemptStatus.AMBIGUOUS)
                if (
                    not normalized_doi
                    and len(results) > 1
                    and results[0].score - results[1].score < 0.05
                ):
                    evidence.append(
                        "Several CNKI candidates have indistinguishable title/author evidence; supply DOI, authors, publication fields or CNKI record ID"
                    )
                    # Do not consume a download to break an unresolved tie.
                    if not target_identity.cnki_id:
                        return attempt(BrowserAttemptStatus.AMBIGUOUS)

                search_url = page.url
                for selected in results:
                    candidate_key = selected.url or _normalized_title(selected.title)
                    if candidate_key in seen_candidates:
                        continue
                    seen_candidates.add(candidate_key)
                    considered += 1
                    detail_page = None
                    try:
                        stage = "detail navigation"
                        if page.url != search_url and selected.url:
                            detail_page = context.new_page()
                            detail_page.goto(
                                selected.url,
                                wait_until="domcontentloaded",
                                timeout=config.navigation_timeout * 1000,
                            )
                        else:
                            try:
                                with context.expect_page(
                                    predicate=lambda opened: opened.opener() is page,
                                    timeout=min(config.navigation_timeout, 1.5) * 1000,
                                ) as popup_info:
                                    selected.link.click()
                                detail_page = popup_info.value
                            except Exception as exc:
                                if type(exc).__name__ != "TimeoutError":
                                    raise
                                # Click exactly once: some CNKI deployments navigate
                                # this tab. Do not repeat the click after popup timeout.
                                detail_page = page
                                if page.url == search_url and selected.url:
                                    detail_page = context.new_page()
                                    detail_page.goto(
                                        selected.url,
                                        wait_until="domcontentloaded",
                                        timeout=config.navigation_timeout * 1000,
                                    )
                        try:
                            detail_page.wait_for_load_state("domcontentloaded")
                        except Exception as exc:
                            if not gate.check(detail_page):
                                raise exc
                        gate.wait_ready(
                            detail_page, stage="detail access initialization"
                        )
                        stage = "detail identity"
                        observed_identity = detail_bibliography(
                            detail_page, fallback_title=selected.title
                        )
                        record_key = observed_identity.cnki_id or observed_identity.doi
                        if record_key and record_key in seen_records:
                            continue
                        if record_key:
                            seen_records.add(record_key)
                        if (
                            target_identity.cnki_id
                            and observed_identity.cnki_id != target_identity.cnki_id
                        ):
                            evidence.append(
                                "Requested CNKI record ID not confirmed on detail page"
                            )
                            failures.append(BrowserAttemptStatus.PAGE_MISMATCH)
                            continue
                        conflicts = conflicting_fields(
                            target_identity, observed_identity
                        )
                        if conflicts:
                            evidence.append(
                                "CNKI detail bibliographic conflict: "
                                + ", ".join(conflicts)
                            )
                            failures.append(BrowserAttemptStatus.PAGE_MISMATCH)
                            continue
                        matches, identity_evidence = _detail_identity(
                            detail_page,
                            doi=normalized_doi,
                            title=title,
                            allow_translated_title=selected.cross_language,
                        )
                        evidence.append(identity_evidence)
                        if selected.cross_language:
                            evidence.append(
                                "CNKI bilingual result requires PDF identity validation"
                            )
                        if not matches:
                            failures.append(BrowserAttemptStatus.PAGE_MISMATCH)
                            continue
                        stage = "PDF controls"

                        def pdf_state():
                            control = _pdf_control(detail_page)
                            if control is not None:
                                return control
                            if (
                                _first_visible(
                                    detail_page, ("a#cajDown", "a:has-text('CAJ下载')")
                                )
                                is not None
                            ):
                                return "caj-only"
                            return None

                        try:
                            pdf_button = gate.wait(detail_page, pdf_state, stage=stage)
                        except CNKIStageTimeout:
                            failures.append(BrowserAttemptStatus.NO_FILE_CANDIDATES)
                            evidence.append(
                                "CNKI exposed no visible PDF download control"
                            )
                            continue
                        if pdf_button == "caj-only":
                            # PDF may hydrate after CAJ; wait a short bounded grace.
                            try:
                                pdf_button = gate.wait(
                                    detail_page,
                                    lambda: _pdf_control(detail_page),
                                    stage=stage,
                                    timeout=min(config.navigation_timeout, 2.0),
                                )
                            except CNKIStageTimeout:
                                failures.append(BrowserAttemptStatus.NO_FILE_CANDIDATES)
                                evidence.append(
                                    "CNKI exposes CAJ only; no PDF downloaded"
                                )
                                continue
                        stage = "PDF retrieval"
                        matches, detail_evidence = _detail_identity(
                            detail_page,
                            doi=normalized_doi,
                            title=title,
                            allow_translated_title=selected.cross_language,
                        )
                        if not matches:
                            evidence.append(detail_evidence)
                            failures.append(BrowserAttemptStatus.PAGE_MISMATCH)
                            continue
                        detail_url = validate_browser_network_url(detail_page.url)
                        detail_dois = _detail_dois(detail_page)
                        article_doi = normalized_doi or (
                            detail_dois[0] if len(detail_dois) == 1 else ""
                        )
                        downloaded = None
                        capture = None
                        request_redirects = ()
                        download_method = None
                        order_url = (
                            _pdf_order_url(detail_page, pdf_button)
                            if config.cnki_context_request
                            else None
                        )
                        if (
                            order_url is None
                            and config.cnki_context_request
                            and getattr(context, "request", None) is not None
                        ):
                            order_url = _direct_pdf_url(detail_page, pdf_button)
                        if order_url is not None:
                            gate.download_started = True
                            try:
                                downloaded, request_redirects = _recover_pdf_request(
                                    context,
                                    detail_page,
                                    url=order_url,
                                    detail_url=detail_url,
                                    gate=gate,
                                    config=config,
                                )
                                download_method = "cnki_pdf_control_request"
                                evidence.append(
                                    "CNKI PDF control fetched in the authenticated context"
                                )
                            except CNKIFileError as exc:
                                # Some order pages need browser JavaScript. Do
                                # not fall back on security/permission, CAJ or
                                # size failures, or retry a terminated context.
                                if (
                                    str(exc)
                                    != "CNKI browser-session recovery returned no PDF"
                                ):
                                    raise
                                if detail_page.is_closed():
                                    raise CNKITargetClosed() from None
                                evidence.append(
                                    "Observed PDF link returned a non-PDF response; trying its browser action"
                                )
                        if downloaded is None:
                            downloaded, capture = _capture_download(
                                context,
                                detail_page,
                                pdf_button,
                                gate=gate,
                                config=config,
                            )
                        handoff_page = None
                        try:
                            file_attempt = _finalize_cnki_download(
                                downloaded,
                                doi=article_doi,
                                title=title,
                                detail_url=detail_url,
                                output_dir=output_dir,
                                config=config,
                                started_at=started_at,
                                matched_title=selected.title,
                                match_score=selected.score,
                                doi_origin=(
                                    "caller_doi"
                                    if normalized_doi
                                    else "cnki_detail_unique_doi"
                                    if article_doi
                                    else "unresolved"
                                ),
                                context=context,
                                detail_page=detail_page,
                                gate=gate,
                                recovery_page=page,
                                capture_pages=capture.pages
                                if capture is not None
                                else (),
                                search_query=submitted_query,
                                search_field=actual_field,
                                cross_language_result=selected.cross_language,
                                download_method=download_method,
                                request_redirects=request_redirects,
                                target_identity=target_identity,
                                observed_identity=observed_identity,
                            )
                        except CNKIInteractionRequired as exc:
                            handoff_page = exc.page
                            raise
                        finally:
                            if capture is not None:
                                capture.close(preserve=handoff_page)
                        files.append(file_attempt)
                        if file_attempt.result is not None:
                            identity = file_attempt.result.identity_validation
                            if identity is not None:
                                evidence.append(
                                    f"CNKI PDF identity: {identity.status.value}; "
                                    f"policy={identity.policy}"
                                )
                                evidence.extend(identity.evidence)
                                if identity.declared_dois:
                                    evidence.append(
                                        "CNKI PDF declared DOI: "
                                        + ", ".join(identity.declared_dois)
                                    )
                        source = replace(
                            _source_candidate(file_attempt.candidate.doi),
                            article_id=file_attempt.candidate.article_id,
                        )
                        if (
                            file_attempt.result is not None
                            and file_attempt.result.status == AcquisitionStatus.VERIFIED
                        ):
                            evidence.append("CNKI PDF passed the shared identity gate")
                            return attempt(BrowserAttemptStatus.VERIFIED)
                        failures.append(
                            _status_for_result(file_attempt.result)
                            if file_attempt.result is not None
                            else BrowserAttemptStatus.RETRIEVAL_FAILED
                        )
                    except CNKIInteractionRequired as exc:
                        preserve_page = exc.page
                        raise
                    except CNKIStageTimeout:
                        failures.append(BrowserAttemptStatus.RETRIEVAL_FAILED)
                        evidence.append(f"CNKI timed out at {stage}; trying next match")
                    except CNKIFileError as exc:
                        failures.append(BrowserAttemptStatus.RETRIEVAL_FAILED)
                        evidence.append(str(exc))
                        if page.is_closed() and detail_page.is_closed():
                            evidence.append("CNKI browser target closed")
                            return attempt(BrowserAttemptStatus.RETRIEVAL_FAILED)
                    except Exception as exc:
                        if isinstance(exc, CNKITargetClosed) or type(exc).__name__ == (
                            "TargetClosedError"
                        ):
                            raise
                        failures.append(BrowserAttemptStatus.RETRIEVAL_FAILED)
                        evidence.append(
                            f"CNKI candidate failed at {stage}: {type(exc).__name__}"
                        )
                    finally:
                        if (
                            detail_page is not None
                            and detail_page is not page
                            and preserve_page is None
                        ):
                            try:
                                if not detail_page.is_closed():
                                    detail_page.close()
                            except Exception:
                                pass
            if BrowserAttemptStatus.RETRIEVED_UNVERIFIED in failures:
                return attempt(BrowserAttemptStatus.RETRIEVED_UNVERIFIED)
            status = (
                BrowserAttemptStatus.RETRIEVAL_FAILED
                if BrowserAttemptStatus.RETRIEVAL_FAILED in failures
                else BrowserAttemptStatus.ENTITLEMENT_REQUIRED
                if BrowserAttemptStatus.ENTITLEMENT_REQUIRED in failures
                else BrowserAttemptStatus.PAGE_MISMATCH
                if BrowserAttemptStatus.PAGE_MISMATCH in failures
                else BrowserAttemptStatus.NO_FILE_CANDIDATES
            )
            return attempt(status)
        except CNKIInteractionRequired as exc:
            preserve_page = exc.page
            evidence.append(f"CNKI requires manual {exc.report.kind.value}")
            status = {
                ChallengeKind.ENTITLEMENT: BrowserAttemptStatus.ENTITLEMENT_REQUIRED,
                ChallengeKind.ACCESS_DENIED: BrowserAttemptStatus.ACCESS_DENIED,
            }.get(exc.report.kind, BrowserAttemptStatus.INTERACTION_REQUIRED)
            return attempt(status, target=exc.page)
        except CNKIStageTimeout as exc:
            return attempt(
                BrowserAttemptStatus.NAVIGATION_ERROR,
                error=f"CNKI timed out at {exc}",
            )
        except Exception as exc:
            if isinstance(exc, CNKITargetClosed) or type(exc).__name__ == (
                "TargetClosedError"
            ):
                evidence.append("CNKI browser target closed")
            return attempt(
                BrowserAttemptStatus.RETRIEVAL_FAILED
                if gate.download_started
                else BrowserAttemptStatus.ERROR,
                error=f"CNKI provider failed at {stage}: {type(exc).__name__}",
            )
        finally:
            if detail_page is not None and detail_page is not page:
                try:
                    if preserve_page is None and not detail_page.is_closed():
                        detail_page.close()
                except Exception:
                    pass
