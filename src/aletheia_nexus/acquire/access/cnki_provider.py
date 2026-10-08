import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit
from uuid import uuid4

import httpx

from aletheia_nexus.acquire.access.artifact import finalize_access_resource
from aletheia_nexus.acquire.access.base_provider import BaseBrowserProvider
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
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
    RetrievedResource,
)
from aletheia_nexus.acquire.fulltext.validation import inspect_pdf
from aletheia_nexus.acquire.metadata.exceptions import MetadataError
from aletheia_nexus.acquire.metadata.resolver import get_metadata
from aletheia_nexus.acquire.metadata.transport import build_user_agent
from aletheia_nexus.core.identifiers.doi import extract_dois, normalize_doi
from aletheia_nexus.core.models import PaperMetadata

CNKI_SEARCH_URL = "https://kns.cnki.net/kns8s/"

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SPACE_RE = re.compile(r"\s+")
_SEARCH_INPUT_SELECTORS = (
    "#txt_SearchText",
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


def _ranked_results(page, *, title: str, authors: tuple[str, ...], limit: int):
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
            # Authors rank plausible titles; they cannot make an unrelated title
            # cross the retrieval threshold. PDF identity remains authoritative.
            if score < 0.60:
                continue
            row_text = _normalized_title(row.inner_text())
            if author_tokens and any(token in row_text for token in author_tokens):
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
            ranked.append(_RankedResult(link, observed_title, url, score))
        except Exception:
            continue
    return tuple(sorted(ranked, key=lambda item: item.score, reverse=True))


def _best_result_link(page, *, title: str, authors: tuple[str, ...], limit: int):
    results = _ranked_results(page, title=title, authors=authors, limit=limit)
    return results[0].link if results else None


def _detail_dois(page) -> tuple[str, ...]:
    observed_dois = []
    for selector in (
        "meta[name='citation_doi']",
        "meta[name='dc.Identifier' i]",
        "meta[name='DC.Identifier.DOI' i]",
    ):
        locator = page.locator(selector)
        for index in range(min(locator.count(), 10)):
            value = locator.nth(index).get_attribute("content") or ""
            observed_dois.extend(extract_dois(value))
    return tuple(dict.fromkeys(observed_dois))


def _detail_identity(page, *, doi: str, title: str) -> tuple[bool, str]:
    """Reject contradictory detail metadata before spending an entitlement."""
    observed_dois = _detail_dois(page)
    observed_title = None
    for selector in ("meta[name='citation_title']", ".wx-tit h1", "h1"):
        locator = page.locator(selector)
        if locator.count():
            observed_title = locator.first.get_attribute("content")
            if not observed_title:
                observed_title = locator.first.inner_text()
            if observed_title:
                break
    if observed_dois and doi:
        matches = doi in observed_dois
        return matches, "detail DOI matched" if matches else "detail DOI mismatch"
    if observed_title:
        score = SequenceMatcher(
            None, _normalized_title(title), _normalized_title(observed_title)
        ).ratio()
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
        pdf_button.click()
        deadline = time.monotonic() + config.navigation_timeout
        retries = 0
        retry_after_handoff = False
        while True:
            downloaded = capture.next_file()
            if downloaded is not None:
                completed = True
                return downloaded, capture
            live_pages = [item for item in capture.pages if not item.is_closed()]
            if not live_pages:
                raise CNKITargetClosed()
            cleared = False
            for target in live_pages:
                cleared = gate.check(target) or cleared
            if cleared:
                retry_after_handoff = True
                deadline = time.monotonic() + config.navigation_timeout
                # Verification may resume the download itself. Pump events and
                # check capture before any bounded re-click of the PDF control.
                live_pages[-1].wait_for_timeout(100)
                downloaded = capture.next_file()
                if downloaded is not None:
                    completed = True
                    return downloaded, capture
            if retry_after_handoff and retries < 1 and not page.is_closed():
                control = _pdf_control(page)
                if control is not None:
                    retries += 1
                    retry_after_handoff = False
                    control.click()
            if time.monotonic() >= deadline:
                raise CNKIStageTimeout("PDF retrieval")
            live_pages[-1].wait_for_timeout(
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
):
    staging_dir = Path(output_dir) / "_browser-downloads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temporary = staging_dir / f".an-cnki-{uuid4().hex}.part"
    try:
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
            method = "cnki_pdf_response"
        else:
            filename = str(getattr(downloaded, "suggested_filename", "") or "")
            if filename.casefold().endswith(".caj"):
                raise CNKIFileError("CNKI returned CAJ instead of PDF")
            downloaded.save_as(temporary)
            method = "cnki_pdf_download"
        size = temporary.stat().st_size
        if size > config.max_bytes:
            raise CNKIFileError("CNKI PDF exceeds max_bytes")
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if not doi:
            inspection = inspect_pdf(temporary)
            observed_dois = tuple(
                dict.fromkeys(extract_dois(inspection.first_page_text))
            )
            if len(observed_dois) != 1:
                raise CNKIFileError(
                    "Title-only CNKI acquisition needs a unique article DOI"
                )
            doi = observed_dois[0]
            doi_origin = "pdf_first_page_unique_doi"
        candidate = _source_candidate(doi, resource_url, url_type=CandidateUrlType.PDF)
        resource = RetrievedResource(
            requested_url=detail_url,
            final_url=resource_url,
            http_status=getattr(downloaded, "status", 200),
            content_type=getattr(downloaded, "content_type", "application/pdf"),
            size_bytes=size,
            sha256=digest.hexdigest(),
            local_path=temporary,
            elapsed_seconds=time.perf_counter() - started_at,
        )
        result = finalize_access_resource(
            candidate=candidate,
            resource=resource,
            output_dir=output_dir,
            expected_title=title,
            keep_unverified=config.keep_unverified,
            transport="cnki_authenticated_browser",
            access_details={
                "provider": "cnki",
                "fetcher": "CNKIProvider",
                "source_page_url": detail_url,
                "access_method": "playwright_institution_auth",
                "query_method": "title_with_optional_author_ranking",
                "matched_result_title": matched_title,
                "result_match_score": round(match_score, 4),
                "download_method": method,
                "search_title": title,
                "doi_resolution_method": doi_origin,
            },
            access_evidence=(
                "CNKI result selected by title/author metadata",
                "Explicit PDF download control used; CAJ links excluded",
            ),
        )
        return BrowserFileAttempt(
            candidate=candidate,
            result=result,
            source_page_url=redact_url_for_record(detail_url),
            method=method,
        )
    finally:
        temporary.unlink(missing_ok=True)


class CNKIProvider(BaseBrowserProvider):
    """Acquire CNKI PDFs with a caller-owned, institution-authenticated browser."""

    name = "cnki"
    priority = 900

    def __init__(self, *, authors: tuple[str, ...] = ()):
        if not isinstance(authors, tuple) or any(
            not isinstance(author, str) for author in authors
        ):
            raise TypeError("authors must be a tuple of strings")
        self.authors = authors

    def is_applicable(
        self,
        *,
        doi: str,
        metadata: PaperMetadata | None,
        expected_title: str | None,
        config: BrowserAccessConfig,
    ) -> bool:
        if not config.cnki_enabled:
            return False
        if config.cnki_search_all_titles:
            return True
        metadata_title = metadata.title if metadata is not None else None
        metadata_journal = metadata.journal if metadata is not None else None
        normalized_doi = doi.casefold()
        return (
            _contains_chinese(expected_title)
            or _contains_chinese(metadata_title)
            or _contains_chinese(metadata_journal)
            or ".cnki." in normalized_doi
            or normalized_doi.startswith("10.7503/cjcu")
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
            )

        try:
            title, authors, _ = _metadata_for_query(
                normalized_doi,
                metadata=metadata,
                expected_title=expected_title,
                metadata_mailto=metadata_mailto,
            )
            authors = self.authors or authors
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

            search_input, search_button = gate.wait(page, search_controls, stage=stage)
            search_input.fill(title)
            search_button.click()
            stage = "search results"

            def result_state():
                rows = page.locator(_RESULT_ROW_SELECTOR)
                for index in range(min(rows.count(), config.cnki_max_results)):
                    links = rows.nth(index).locator(_RESULT_LINK_SELECTOR)
                    if links.count() and links.first.inner_text().strip():
                        return "results"
                if _first_visible(page, _NO_RESULTS_SELECTORS) is not None:
                    return "empty"
                return None

            search_retries = 0

            def resume_search():
                nonlocal search_retries
                if search_retries or result_state():
                    return
                controls = gate.wait(page, search_controls, stage="search controls")
                if controls:
                    search_retries += 1
                    controls[0].fill(title)
                    controls[1].click()

            state = gate.wait(page, result_state, stage=stage, on_resume=resume_search)
            results = (
                ()
                if state == "empty"
                else _ranked_results(
                    page, title=title, authors=authors, limit=config.cnki_max_results
                )
            )
            if not results:
                evidence.append("CNKI returned no sufficiently close title match")
                return attempt(BrowserAttemptStatus.NO_FILE_CANDIDATES)

            search_url = page.url
            failures = []
            for selected in results:
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
                    gate.check(detail_page)
                    stage = "detail identity"
                    matches, identity_evidence = _detail_identity(
                        detail_page, doi=normalized_doi, title=title
                    )
                    evidence.append(identity_evidence)
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
                        failures.append(BrowserAttemptStatus.ENTITLEMENT_REQUIRED)
                        evidence.append("CNKI exposed no visible PDF download control")
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
                            evidence.append("CNKI exposes CAJ only; no PDF downloaded")
                            continue
                    stage = "PDF retrieval"
                    matches, detail_evidence = _detail_identity(
                        detail_page, doi=normalized_doi, title=title
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
                    downloaded, capture = _capture_download(
                        context, detail_page, pdf_button, gate=gate, config=config
                    )
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
                        )
                    finally:
                        capture.close()
                    files.append(file_attempt)
                    if not normalized_doi:
                        source = _source_candidate(file_attempt.candidate.doi)
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
                        and detail_page is not preserve_page
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
        except CNKIStageTimeout:
            return attempt(
                BrowserAttemptStatus.NAVIGATION_ERROR,
                error=f"CNKI timed out at {stage}",
            )
        except Exception as exc:
            if isinstance(exc, CNKITargetClosed) or type(exc).__name__ == (
                "TargetClosedError"
            ):
                evidence.append("CNKI browser target closed")
            return attempt(
                BrowserAttemptStatus.ERROR,
                error=f"CNKI provider failed at {stage}: {type(exc).__name__}",
            )
        finally:
            if detail_page is not None and detail_page is not page:
                try:
                    if detail_page is not preserve_page and not detail_page.is_closed():
                        detail_page.close()
                except Exception:
                    pass
