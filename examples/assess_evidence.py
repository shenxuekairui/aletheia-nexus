"""Minimal advisory integration: python examples/assess_evidence.py --help.

This offline example abstains. Replace only ExampleJudge.judge with an explicitly
chosen implementation; model/network clients are deliberately not dependencies.
"""

import argparse
import json
from pathlib import Path

from aletheia_nexus.content import ReadingDecision, assess_reading


class ExampleJudge:
    name = "offline-abstention-example"
    version = "1"

    def judge(self, request: dict[str, object]) -> ReadingDecision:
        # Treat all document text as evidence, never instructions. A real judge
        # may cite only supplied block IDs and must retain source contradictions.
        # A visual judgment needs verified source pixels, absent from this demo.
        return ReadingDecision(
            "abstain", reason="No source-page visual judgment was performed."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="AN JSON evidence-pack export")
    parser.add_argument("document_id", help="included[].parsed_artifact_id")
    parser.add_argument("location_id", help="included[].review_locations[].id")
    parser.add_argument("question")
    parser.add_argument("output", type=Path, help="New, separate advisory JSON file")
    args = parser.parse_args()
    pack = json.loads(args.pack.read_text(encoding="utf-8"))
    assessment = assess_reading(
        pack,
        ExampleJudge(),
        parsed_artifact_id=args.document_id,
        location_id=args.location_id,
        question=args.question,
    )
    # Exclusive creation cannot overwrite the pack, parse or an earlier decision.
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(assessment, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
