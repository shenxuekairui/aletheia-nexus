"""Check the committed 20-paper acquisition corpus against its raw input."""

import json
from pathlib import Path


def main() -> None:
    corpus_dir = Path(__file__).resolve().parents[1] / "benchmarks"
    raw = json.loads(
        (corpus_dir / "user_20260923_20_with_titles.json").read_text(encoding="utf-8")
    )
    frozen = json.loads(
        (corpus_dir / "user_20260923_20_frozen.json").read_text(encoding="utf-8")
    )
    original_dois = (
        (corpus_dir / "user_20260923_20.txt").read_text(encoding="utf-8").splitlines()
    )

    if not all(isinstance(items, list) and len(items) == 20 for items in (raw, frozen)):
        raise ValueError("Both 20-paper JSON corpora must have exactly 20 rows")
    if len(original_dois) != 20:
        raise ValueError("Original DOI list must have exactly 20 rows")

    seen: set[str] = set()
    for index, (raw_item, item, original_doi) in enumerate(
        zip(raw, frozen, original_dois, strict=True), start=1
    ):
        raw_doi = raw_item if isinstance(raw_item, str) else raw_item.get("doi")
        if not isinstance(item, dict) or item.get("doi") != raw_doi:
            raise ValueError(f"Frozen DOI differs from raw input at row {index}")
        doi = item["doi"]
        if doi != original_doi:
            raise ValueError(f"Frozen DOI differs from original list at row {index}")
        if doi.casefold() in seen:
            raise ValueError(f"Duplicate frozen DOI at row {index}")
        seen.add(doi.casefold())
        if not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("title", "publisher")
        ):
            raise ValueError(f"Missing title or publisher at row {index}")
        year = item.get("year")
        if type(year) is not int or not 1900 <= year <= 2100:
            raise ValueError(f"Invalid publication year at row {index}")
        if isinstance(raw_item, dict) and item["title"] != raw_item.get("title"):
            raise ValueError(f"Explicit raw title differs at row {index}")

    print("Frozen benchmark: 20 unique ordered DOIs with fixed titles/metadata")


if __name__ == "__main__":
    main()
