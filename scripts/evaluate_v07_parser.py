"""Evaluate the v0.7 baseline parser without network access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia_nexus.content.evaluation import evaluate_manifest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks" / "v07_fixtures" / "manifest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = evaluate_manifest(args.manifest)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    metrics = report["metrics"]
    character_accuracy = metrics.get("character_accuracy", {})
    failed = (
        any(
            value["correct"] != value["total"]
            for key, value in metrics.items()
            if key != "anchored_block_coverage"
            and isinstance(value, dict)
            and {"correct", "total"} <= value.keys()
        )
        or any(
            value != 0
            for key, value in metrics.items()
            if key in {"table_figure_link_omissions", "table_figure_false_associations"}
        )
        or (
            bool(character_accuracy.get("expected_characters"))
            and any(
                character_accuracy.get(key, 0) != 0
                for key in ("deletions", "insertions", "substitutions")
            )
        )
        or any(
            not item.get("status_correct", True)
            or not item.get("warnings_correct", True)
            for item in report["records"]
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
