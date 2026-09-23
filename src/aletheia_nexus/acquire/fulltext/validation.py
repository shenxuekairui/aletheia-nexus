from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from aletheia_nexus.acquire.fulltext.models import PdfValidationReport

_HEADER_SCAN_BYTES = 1024
_DEFAULT_TEXT_PAGES = 3


@dataclass(frozen=True, slots=True)
class PdfInspection:
    """Internal PDF details reused by identity validation."""

    report: PdfValidationReport
    metadata_title: str | None
    extracted_text: str
    first_page_text: str = ""


def _clean_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def inspect_pdf(
    path: str | Path,
    *,
    text_pages: int = _DEFAULT_TEXT_PAGES,
) -> PdfInspection:
    """Validate PDF structure and extract limited identity evidence."""

    file_path = Path(path)
    if (
        not isinstance(text_pages, int)
        or isinstance(text_pages, bool)
        or text_pages < 0
    ):
        raise ValueError("text_pages must be a non-negative integer")

    with file_path.open("rb") as handle:
        header = handle.read(_HEADER_SCAN_BYTES)

    magic_bytes_ok = b"%PDF-" in header
    if not magic_bytes_ok:
        return PdfInspection(
            report=PdfValidationReport(
                valid_pdf=False,
                magic_bytes_ok=False,
                parseable=False,
                page_count=None,
                encrypted=False,
                warning="PDF header marker was not found",
            ),
            metadata_title=None,
            extracted_text="",
        )

    try:
        reader = PdfReader(str(file_path), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        return PdfInspection(
            report=PdfValidationReport(
                valid_pdf=False,
                magic_bytes_ok=True,
                parseable=False,
                page_count=None,
                encrypted=False,
                warning=f"PDF parser rejected the file: {exc}",
            ),
            metadata_title=None,
            extracted_text="",
        )

    encrypted = bool(reader.is_encrypted)
    warning: str | None = None

    if encrypted:
        try:
            unlocked = bool(reader.decrypt(""))
        except (PdfReadError, ValueError, TypeError):
            unlocked = False
        if not unlocked:
            metadata_title = None
            try:
                metadata = reader.metadata
                metadata_title = _clean_text(metadata.title if metadata else None)
            except (PdfReadError, KeyError, TypeError, ValueError):
                pass
            return PdfInspection(
                report=PdfValidationReport(
                    valid_pdf=True,
                    magic_bytes_ok=True,
                    parseable=True,
                    page_count=None,
                    encrypted=True,
                    warning="Encrypted PDF could not be opened without a password",
                ),
                metadata_title=metadata_title,
                extracted_text="",
            )

    try:
        page_count = len(reader.pages)
    except (PdfReadError, KeyError, TypeError, ValueError) as exc:
        return PdfInspection(
            report=PdfValidationReport(
                valid_pdf=False,
                magic_bytes_ok=True,
                parseable=False,
                page_count=None,
                encrypted=encrypted,
                warning=f"Could not read PDF pages: {exc}",
            ),
            metadata_title=None,
            extracted_text="",
        )

    if page_count < 1:
        return PdfInspection(
            report=PdfValidationReport(
                valid_pdf=False,
                magic_bytes_ok=True,
                parseable=True,
                page_count=0,
                encrypted=encrypted,
                warning="PDF contains no pages",
            ),
            metadata_title=None,
            extracted_text="",
        )

    metadata_title = None
    try:
        metadata = reader.metadata
        metadata_title = _clean_text(metadata.title if metadata else None)
    except (PdfReadError, KeyError, TypeError, ValueError):
        warning = "PDF metadata could not be read"

    text_parts: list[str] = []
    first_page_text = ""
    extraction_failed = False
    for page_index, page in enumerate(reader.pages[: min(text_pages, page_count)]):
        try:
            text = page.extract_text()
        except (PdfReadError, KeyError, TypeError, ValueError):
            extraction_failed = True
            continue
        if text:
            if page_index == 0:
                first_page_text = text
            text_parts.append(text)

    if extraction_failed and warning is None:
        warning = "Text extraction failed for one or more inspected pages"

    return PdfInspection(
        report=PdfValidationReport(
            valid_pdf=True,
            magic_bytes_ok=True,
            parseable=True,
            page_count=page_count,
            encrypted=encrypted,
            warning=warning,
        ),
        metadata_title=metadata_title,
        extracted_text="\n".join(text_parts),
        first_page_text=first_page_text,
    )
