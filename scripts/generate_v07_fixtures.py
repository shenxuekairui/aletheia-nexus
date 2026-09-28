"""Generate the deterministic, self-authored public v0.7 PDF fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pypdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks" / "v07_fixtures"
FIXED_TIME = "2026-09-28T00:00:00+00:00"


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(
    path: Path,
    pages: list[list[tuple[float, float, float, str]]],
    *,
    title: str,
    image_pages: set[int] | None = None,
) -> None:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for page_index, entries in enumerate(pages):
        page = writer.add_blank_page(width=612, height=792)
        resources = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        commands = []
        if image_pages and page_index in image_pages:
            image = DecodedStreamObject()
            image.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(2),
                    NameObject("/Height"): NumberObject(2),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            image.set_data(bytes([20, 80, 160] * 4))
            image_ref = writer._add_object(image)
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Im1"): image_ref}
            )
            commands.append("q 160 0 0 80 54 320 cm /Im1 Do Q")
        page[NameObject("/Resources")] = resources
        for x, y, size, text in entries:
            commands.append(
                f"BT /F1 {size:g} Tf 1 0 0 1 {x:g} {y:g} Tm "
                f"({_escape_pdf_text(text)}) Tj ET"
            )
        stream = DecodedStreamObject()
        stream.set_data(("\n".join(commands) + "\n").encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata(
        {
            "/Title": title,
            "/Author": "Aletheia Nexus contributors",
            "/Subject": "Apache-2.0 self-authored parser fixture",
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar(path: Path, doi: str, *, role: str = "ARTICLE") -> Path:
    payload = {
        "schema": "aletheia-nexus/acquisition-record/v1",
        "acquired_at": FIXED_TIME,
        "status": "VERIFIED",
        "target": {"doi": doi, "expected_title": None},
        "retrieval": {"sha256": _sha256(path)},
        "pdf_validation": {
            "valid_pdf": True,
            "page_count": len(PdfReader(path).pages),
        },
        "identity_validation": {
            "status": "MATCH",
            "document_role": role,
        },
    }
    target = path.with_suffix(".acquisition.json")
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    native = FIXTURES / "native_article.pdf"
    columns = FIXTURES / "two_column_article.pdf"
    sparse = FIXTURES / "sparse_scan.pdf"
    supplement = FIXTURES / "article_supplement.pdf"

    _write_pdf(
        native,
        [
            [
                (54, 744, 18, "A Self-Authored Study of Traceable Parsing"),
                (54, 718, 10, "DOI: 10.5555/an.v07.native"),
                (54, 680, 14, "Abstract"),
                (
                    54,
                    660,
                    10,
                    "We test citations [1], unresolved links [2], and uncertainty.",
                ),
                (54, 620, 14, "1 Introduction"),
                (
                    54,
                    600,
                    10,
                    "Source-linked blocks let a reader return to the exact PDF page.",
                ),
                (54, 560, 14, "2 Methods"),
                (54, 540, 10, "The score is defined as S = correct / total."),
                (
                    54,
                    500,
                    10,
                    "Table 1. Evaluation counts for the deterministic fixture.",
                ),
                (54, 480, 10, "Metric"),
                (190, 480, 10, "Correct"),
                (330, 480, 10, "Total"),
                (54, 464, 10, "Anchors"),
                (190, 464, 10, "4"),
                (330, 464, 10, "4"),
                (54, 424, 10, "Figure 1. Flow from verified bytes to anchored blocks."),
            ],
            [
                (54, 744, 14, "3 Results"),
                (54, 722, 10, "The baseline preserves every selected source span [1]."),
                (54, 680, 14, "4 Conclusion"),
                (
                    54,
                    658,
                    10,
                    "Parsing is not a claim that scientific conclusions are true.",
                ),
                (54, 610, 14, "References"),
                (54, 588, 10, "[1] A. Author. Reproducible fixture design. 2026."),
            ],
        ],
        title="A Self-Authored Study of Traceable Parsing",
        image_pages={0},
    )
    _write_pdf(
        columns,
        [
            [
                (54, 744, 18, "Two-Column Reading Order Fixture"),
                (54, 714, 10, "DOI: 10.5555/an.v07.columns"),
                (54, 680, 14, "1 Introduction"),
                (54, 658, 10, "Left column first line."),
                (54, 640, 10, "Left column second line."),
                (54, 600, 14, "2 Methods"),
                (54, 578, 10, "Left column method detail."),
                (320, 680, 14, "3 Results"),
                (320, 658, 10, "Right column first line."),
                (320, 640, 10, "Right column second line."),
                (320, 600, 14, "4 Conclusion"),
                (320, 578, 10, "Right column conclusion detail."),
            ]
        ],
        title="Two-Column Reading Order Fixture",
    )
    _write_pdf(
        sparse,
        [[]],
        title="Synthetic Scanned Page Without Native Text",
    )
    _write_pdf(
        supplement,
        [
            [
                (54, 744, 18, "Supporting Information"),
                (54, 710, 10, "Additional data only."),
            ]
        ],
        title="Supporting Information",
    )

    entries = []
    for identifier, path, doi, expected, role in (
        ("native", native, "10.5555/an.v07.native", "PASS", "ARTICLE"),
        ("two-column", columns, "10.5555/an.v07.columns", "PASS", "ARTICLE"),
        ("sparse", sparse, "10.5555/an.v07.sparse", "PASS", "ARTICLE"),
        (
            "supplement-rejection",
            supplement,
            "10.5555/an.v07.supplement",
            "DOCUMENT_NOT_ARTICLE",
            "SUPPLEMENT",
        ),
    ):
        sidecar = _sidecar(path, doi, role=role)
        gold_name = f"{identifier}.gold.json" if expected == "PASS" else None
        gold_path = FIXTURES / gold_name if gold_name else None
        if gold_path is not None and not gold_path.is_file():
            raise FileNotFoundError(f"missing gold annotation: {gold_path}")
        entries.append(
            {
                "id": identifier,
                "pdf": path.name,
                "sidecar": sidecar.name,
                "doi": doi,
                "pdf_sha256": _sha256(path),
                "sidecar_sha256": _sha256(sidecar),
                "expected_gate": expected,
                "gold": gold_name,
                "gold_sha256": _sha256(gold_path) if gold_path else None,
            }
        )
    manifest = {
        "schema": "aletheia-nexus/parser-fixture-manifest/v1",
        "generator": {
            "script": "scripts/generate_v07_fixtures.py",
            "format_version": 1,
            "pypdf_version": pypdf.__version__,
        },
        "license": "Apache-2.0",
        "provenance": (
            "Self-authored deterministic PDFs generated by "
            "scripts/generate_v07_fixtures.py; redistribution permitted under "
            "the repository Apache-2.0 license. No publisher content is included."
        ),
        "entries": entries,
    }
    (FIXTURES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(entries)} fixtures in {FIXTURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
