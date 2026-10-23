"""Run an ordinary AN batch with opt-in detailed timings.

Usage: python scripts/profile_acquisition.py --trace-dir DIR -- acquire INPUT.json
       [the usual AN arguments]. Use a fresh output directory and checkpoint for
       a new measurement; resumed successes do not execute acquisition.
"""

import argparse
import json
import sys
from pathlib import Path

from aletheia_nexus.acquire.access.timing import AcquisitionTimer, install


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if arguments[:1] != ["acquire"]:
        parser.error("Pass the normal AN acquire batch command after --")
    args.trace_dir.mkdir(parents=True, exist_ok=True)
    timer = AcquisitionTimer(args.trace_dir / "timing-events.jsonl")
    try:
        install(timer)
        timer.start_heartbeat()
        from aletheia_nexus.cli import entrypoint

        sys.argv = ["aletheia-nexus", *arguments]
        return entrypoint()
    finally:
        timer.close()
        (args.trace_dir / "timing-summary.json").write_text(
            json.dumps(timer.summary(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
