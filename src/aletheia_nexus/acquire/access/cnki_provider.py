import hashlib
import re
import time
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx

from aletheia_nexus.acquire.access.artifact import finalize_access_resource
from aletheia_nexus.acquire.access.base_provider import BaseBrowserProvider
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
from aletheia_nexus.acquire.metadata.exceptions import MetadataError
from aletheia_nexus.acquire.metadata.resolver import get_metadata
from aletheia_nexus.acquire.metadata.transport import build_user_agent
from aletheia_nexus.core.identifiers.doi import normalize_doi
from aletheia_nexus.core.models import PaperMetadata

CNKI_SEARCH_URL = "https://kns.cnki.net/kns8s/"

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SPACE_RE = re.compile(r"\s+")
_CAPTCHA_SELECTORS = (
    ".geetest_slider_button",
    ".geetest_panel",
    "iframe[src*='geetest']",
    "iframe[src*='captcha']",
    "iframe[title*='验证']",
)
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
_RESULT_ROW_SELECTOR = ".result-table-list tbody tr"
_RESULT_LINK_SELECTOR = "a.fz14, a[href*='/kcms2/article/abstract'], a[href*='/KCMS/detail']"
_PDF_SELECTORS = (
    "a#pdfDown",
    "a:has-text('PDF下载')",
    "a:has-text('PDF 下载')",
    "a[href*='download'][href*='pdf' i]",
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

    def handle_data(self, data: str) -> None:
        value = unescape(data).strip()
        if not value:
            return
        if self._in_title:
            self._document_title.append(value)
        if value in {"题名：", "题名:"}:
            self._pending_label = "title"
            return
        if value in {"作者：", "作者:"}:
            self._pending_label = "authors"
            return
        if self._pending_label == "title":
            self.title = self.title or value
            self._pending_label = None
        elif self._pending_label == "authors":
            self.authors.extend(
                item.strip() for item in re.split(r"[;,；，]", value) if item.strip()
            )
            self._pending_label = None

    def result(self) -> tuple[str | None, tuple[str, ...]]:
        title = self.title
        if title is None and self._document_title:
            candidate = " ".join(self._document_title).strip()
            if candidate and candidate.casefold() not in {
                "doi not found",
                "多重解析地址选择页面",
            }:
                title = candidate
        return title, tuple(dict.fromkeys(self.authors))


def _normalized_title(value: str) -> str:
    return _SPACE_RE.sub(" ", value.casefold()).strip()


def _clean_title(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return _SPACE_RE.sub(" ", value).strip()


def _contains_chinese(value: str | None) -> bool:
    return bool(value and _CJK_RE.search(value))


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                if item.is_visible():
                    return item
            except Exception:
                continue
    return None


def _captcha_visible(page) -> bool:
    try:
        current = urlsplit(str(page.url or ""))
        if (
            current.hostname == "kns.cnki.net"
            and current.path.casefold().startswith("/verify/")
        ) or "captchatype=" in current.query.casefold():
            return True
    except (AttributeError, ValueError):
        pass
    return _first_visible(page, _CAPTCHA_SELECTORS) is not None


def _wait_for_manual_captcha(
    page,
    *,
    config: BrowserAccessConfig,
) -> tuple[bool, bool, ChallengeReport | None]:
    """Wait for user-operated CAPTCHA completion without automating the puzzle."""

    if not _captcha_visible(page):
        return True, False, None

    report = ChallengeReport(
        kind=ChallengeKind.CAPTCHA,
        evidence=("CNKI slider/CAPTCHA control is visible",),
    )
    if config.interaction_callback is not None:
        config.interaction_callback(report, redact_url_for_record(page.url) or "")
    if not config.interactive:
        return False, False, report

    deadline = (
        None
        if config.wait_for_interaction
        else time.monotonic() + config.interaction_timeout
    )
    while _captcha_visible(page):
        if deadline is not None and time.monotonic() >= deadline:
            return False, True, report
        try:
            if page.is_closed():
                return False, True, report
            page.wait_for_timeout(config.poll_interval * 1000)
        except Exception:
            return False, True, report
    return True, True, report


def _metadata_for_query(
    doi: str,
    *,
    metadata: PaperMetadata | None,
    expected_title: str | None,
    metadata_mailto: str | None,
) -> tuple[str, tuple[str, ...], PaperMetadata | None]:
    title = _clean_title(expected_title) if expected_title else None
    resolved = metadata
    if title is None and resolved is not None and resolved.title:
        title = _clean_title(resolved.title) or None
    metadata_error: MetadataError | None = None
    if title is None:
        try:
            resolved = get_metadata(doi, mailto=metadata_mailto)
            title = _clean_title(resolved.title) if resolved.title else None
        except MetadataError as exc:
            metadata_error = exc
    if title is None:
        title, fallback_authors = _metadata_from_chinese_sources(
            doi,
            mailto=metadata_mailto,
        )
        if title:
            return title, fallback_authors, resolved
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
            title, authors = parser.result()
            if title:
                return _clean_title(title), authors
        except (httpx.HTTPError, UnicodeError, ValueError):
            continue
    return None, ()


def _best_result_link(page, *, title: str, authors: tuple[str, ...], limit: int):
    rows = page.locator(_RESULT_ROW_SELECTOR)
    try:
        row_count = min(rows.count(), limit)
    except Exception:
        return None

    expected = _normalized_title(title)
    author_tokens = tuple(
        token
        for author in authors[:3]
        if (token := _normalized_title(author))
    )
    ranked: list[tuple[float, int, object]] = []
    for index in range(row_count):
        row = rows.nth(index)
        links = row.locator(_RESULT_LINK_SELECTOR)
        try:
            if links.count() < 1:
                continue
            link = links.first
            observed = _normalized_title(link.inner_text())
            if not observed:
                continue
            score = SequenceMatcher(None, expected, observed).ratio()
            row_text = _normalized_title(row.inner_text())
            if author_tokens and any(token in row_text for token in author_tokens):
                score += 0.08
            ranked.append((score, -index, link))
        except Exception:
            continue

    if not ranked:
        return None
    best = max(ranked, key=lambda item: (item[0], item[1]))
    return best[2] if best[0] >= 0.60 else None


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
                if "caj" in text or "caj" in href:
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


class CNKIProvider(BaseBrowserProvider):
    """Acquire CNKI PDFs with a caller-owned, institution-authenticated browser."""

    name = "cnki"
    priority = 900

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
        normalized_doi = normalize_doi(doi)
        source = _source_candidate(normalized_doi)
        challenges: list[ChallengeReport] = []
        interaction_used = False
        detail_page = None

        def challenge_gate(target_page) -> bool:
            nonlocal interaction_used
            cleared, used, report = _wait_for_manual_captcha(
                target_page,
                config=config,
            )
            interaction_used = interaction_used or used
            if report is not None and report not in challenges:
                challenges.append(report)
            return cleared

        def interaction_attempt(target_page) -> BrowserAccessAttempt:
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=redact_url_for_record(getattr(target_page, "url", None)),
                status=BrowserAttemptStatus.INTERACTION_REQUIRED,
                challenge_history=tuple(challenges),
                interaction_used=interaction_used,
                evidence=("CNKI CAPTCHA requires manual completion",),
                elapsed_seconds=time.perf_counter() - started_at,
            )

        try:
            title, authors, _ = _metadata_for_query(
                normalized_doi,
                metadata=metadata,
                expected_title=expected_title,
                metadata_mailto=metadata_mailto,
            )
            try:
                page.goto(CNKI_SEARCH_URL, wait_until="domcontentloaded")
            except Exception:
                # CNKI's verification shell can keep network activity alive long
                # enough for navigation to time out. Classify the visible/URL
                # challenge before treating that condition as navigation failure.
                if not challenge_gate(page):
                    return interaction_attempt(page)
                raise
            if not challenge_gate(page):
                return interaction_attempt(page)

            search_input = _first_visible(page, _SEARCH_INPUT_SELECTORS)
            search_button = _first_visible(page, _SEARCH_BUTTON_SELECTORS)
            if search_input is None or search_button is None:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=redact_url_for_record(page.url),
                    status=BrowserAttemptStatus.NAVIGATION_ERROR,
                    challenge_history=tuple(challenges),
                    interaction_used=interaction_used,
                    error="CNKI search controls were not found",
                    elapsed_seconds=time.perf_counter() - started_at,
                )
            search_input.fill(title)
            search_button.click()
            try:
                page.wait_for_selector(_RESULT_ROW_SELECTOR, state="visible")
            except Exception:
                if not challenge_gate(page):
                    return interaction_attempt(page)
                raise
            if not challenge_gate(page):
                return interaction_attempt(page)

            result_link = _best_result_link(
                page,
                title=title,
                authors=authors,
                limit=config.cnki_max_results,
            )
            if result_link is None:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=redact_url_for_record(page.url),
                    status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
                    challenge_history=tuple(challenges),
                    candidates_considered=config.cnki_max_results,
                    interaction_used=interaction_used,
                    evidence=("CNKI returned no sufficiently close title match",),
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            try:
                with context.expect_page(
                    timeout=min(config.navigation_timeout, 10.0) * 1000
                ) as popup_info:
                    result_link.click()
                detail_page = popup_info.value
            except Exception:
                # CNKI normally opens a popup, but some deployments navigate the
                # current page. The identity gate below protects this fallback.
                detail_page = page
            detail_page.wait_for_load_state("domcontentloaded")
            if not challenge_gate(detail_page):
                return interaction_attempt(detail_page)

            pdf_button = _pdf_control(detail_page)
            if pdf_button is None:
                return BrowserAccessAttempt(
                    source_candidate=source,
                    final_url=redact_url_for_record(detail_page.url),
                    status=BrowserAttemptStatus.ENTITLEMENT_REQUIRED,
                    challenge_history=tuple(challenges),
                    candidates_considered=1,
                    interaction_used=interaction_used,
                    evidence=("CNKI exposed no visible PDF download control",),
                    error="PDF format unavailable or institutional entitlement required",
                    elapsed_seconds=time.perf_counter() - started_at,
                )

            with detail_page.expect_download(
                timeout=config.navigation_timeout * 1000
            ) as download_info:
                pdf_button.click()
            download = download_info.value

            staging_dir = Path(output_dir) / "_browser-downloads"
            staging_dir.mkdir(parents=True, exist_ok=True)
            temporary = staging_dir / f".an-cnki-{uuid4().hex}.part"
            try:
                download.save_as(temporary)
                size = temporary.stat().st_size
                if size > config.max_bytes:
                    temporary.unlink(missing_ok=True)
                    return BrowserAccessAttempt(
                        source_candidate=source,
                        final_url=redact_url_for_record(detail_page.url),
                        status=BrowserAttemptStatus.RETRIEVAL_FAILED,
                        challenge_history=tuple(challenges),
                        candidates_considered=1,
                        interaction_used=interaction_used,
                        error=(
                            "CNKI PDF exceeds max_bytes "
                            f"({size} > {config.max_bytes})"
                        ),
                        elapsed_seconds=time.perf_counter() - started_at,
                    )
                digest = hashlib.sha256()
                with temporary.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)

                detail_url = validate_browser_network_url(detail_page.url)
                raw_download_url = str(getattr(download, "url", "") or "")
                try:
                    resource_url = validate_browser_network_url(raw_download_url)
                except (TypeError, ValueError):
                    resource_url = detail_url
                candidate = _source_candidate(
                    normalized_doi,
                    resource_url,
                    url_type=CandidateUrlType.PDF,
                )
                resource = RetrievedResource(
                    requested_url=detail_url,
                    final_url=resource_url,
                    http_status=200,
                    content_type="application/pdf",
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
                        "provider": self.name,
                        "fetcher": type(self).__name__,
                        "source_page_url": detail_url,
                        "access_method": "playwright_institution_auth",
                        "query_method": "title_with_optional_author_ranking",
                    },
                    access_evidence=(
                        "CNKI result selected by title/author metadata",
                        "Explicit PDF download control used; CAJ links excluded",
                    ),
                )
            except Exception:
                temporary.unlink(missing_ok=True)
                raise

            file_attempt = BrowserFileAttempt(
                candidate=candidate,
                result=result,
                source_page_url=redact_url_for_record(detail_url),
                method="cnki_pdf_download",
            )
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=redact_url_for_record(detail_url),
                status=_status_for_result(result),
                challenge_history=tuple(challenges),
                file_attempts=(file_attempt,),
                candidates_considered=1,
                interaction_used=interaction_used,
                evidence=(
                    "CNKI searched by resolved title",
                    "Downloaded through the existing institutional browser session",
                ),
                elapsed_seconds=time.perf_counter() - started_at,
            )
        except Exception as exc:
            return BrowserAccessAttempt(
                source_candidate=source,
                final_url=redact_url_for_record(getattr(detail_page or page, "url", None)),
                status=BrowserAttemptStatus.ERROR,
                challenge_history=tuple(challenges),
                interaction_used=interaction_used,
                error=f"CNKI provider failed: {type(exc).__name__}",
                elapsed_seconds=time.perf_counter() - started_at,
            )
        finally:
            if detail_page is not None and detail_page is not page:
                try:
                    if not detail_page.is_closed() and not _captcha_visible(detail_page):
                        detail_page.close()
                except Exception:
                    pass
