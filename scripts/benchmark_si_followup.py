import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aletheia_nexus.content.gate import sha256_file, validate_parser_input
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.supplements import acquire_supplements

parser = argparse.ArgumentParser(
    description="Post-hoc SI byte-limit and reuse diagnostics, separate from first-pass scores."
)
parser.add_argument("--root", required=True, type=Path)
args = parser.parse_args()
ROOT = args.root.resolve()
manifest_path = ROOT / "manifest.json"
if not manifest_path.exists():
    manifest_path = ROOT / "run" / "manifest.json"
manifest = json.loads(manifest_path.read_text("utf-8"))
raw = ROOT / "run/cases"
cases = {c["id"]: c for c in manifest["cases"]}
results = {
    p.parent.name: json.loads(p.read_text("utf-8")) for p in raw.glob("*/result.json")
}
assert len(results) == len(cases), "Wait for the frozen primary run to finish"
byte_cases = []
for case in cases:
    path = raw / case / "integrated-si.json"
    if not path.exists():
        continue
    payload = json.loads(path.read_text("utf-8"))
    if any(
        x.get("error")
        in {"AcquisitionTooLargeError", "figshare_file_exceeds_byte_limit"}
        for x in [*payload.get("items", []), *payload.get("errors", [])]
    ):
        byte_cases.append(case)
formats = set(
    f["suffix"]
    for r in results.values()
    if r.get("integrated_si_status") == "COMPLETED"
    for f in r.get("integrated_files", [])
)
uncovered = set(formats)
reuse = []
while uncovered:
    eligible = [
        r
        for r in results.values()
        if r.get("integrated_si_status") == "COMPLETED" and r["id"] not in reuse
    ]
    best = max(
        eligible,
        key=lambda r: (
            len(uncovered & {f["suffix"] for f in r.get("integrated_files", [])}),
            len(r.get("integrated_files", [])),
            r["id"],
        ),
    )
    covered = uncovered & {f["suffix"] for f in best.get("integrated_files", [])}
    if not covered:
        break
    reuse.append(best["id"])
    uncovered -= covered
selection = {
    "limits_100MiB": byte_cases,
    "reuse_cases": reuse,
    "reuse_format_targets": sorted(formats),
    "selection_scope": "Post-hoc diagnostic/regression subset; not a new holdout and not merged into primary scores",
}
(ROOT / "followup-selection.json").write_text(
    json.dumps(selection, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(selection), flush=True)


def main_path(case):
    report = raw / case / "main-report.json"
    if report.exists():
        return Path(json.loads(report.read_text("utf-8"))["items"][0]["pdf"])
    paths = list((raw / case / "integrated").glob("*.pdf"))
    assert len(paths) == 1
    return paths[0]


def one(job):
    mode, case = job
    out = ROOT / "followup" / mode / case
    if (out / "summary.json").exists():
        return json.loads((out / "summary.json").read_text("utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    source = validate_parser_input(main_path(case))
    original = (source.pdf_sha256, source.sidecar_sha256)
    library = None
    main = source
    if mode == "100MiB":
        library = LibraryService(out / "library")
        imported = library.import_pdf(source.pdf_path)
        main = validate_parser_input(imported["pdf_path"])
    started = time.monotonic()
    result = acquire_supplements(
        main.pdf_path,
        library=library,
        timeout=20,
        max_files=20,
        max_bytes=(100 if mode == "100MiB" else 16) * 1024**2,
    )
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files = []
    for item in result["items"]:
        if item["status"] not in {"SAVED", "REUSED"}:
            continue
        p = Path(item["path"])
        receipt = json.loads(Path(item["source_record"]).read_text("utf-8"))
        files.append(
            {
                "suffix": p.suffix,
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
                "role": item["role"],
                "status": item["status"],
                "checks_ok": sha256_file(p) == receipt["sha256"] == item["sha256"]
                and receipt["parent"]["doi"] == main.doi
                and receipt["parent"]["pdf_sha256"] == main.pdf_sha256,
            }
        )
    summary = {
        "id": case,
        "mode": mode,
        "status": result["status"],
        "items": files,
        "failed_errors": [
            i.get("error")
            for i in [*result["items"], *result.get("errors", [])]
            if i.get("error")
        ],
        "source_unchanged": original
        == (sha256_file(source.pdf_path), sha256_file(source.sidecar_path)),
        "wall_seconds": round(time.monotonic() - started, 2),
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "id": case,
                "mode": mode,
                "status": result["status"],
                "saved": len(files),
                "reused": sum(f["status"] == "REUSED" for f in files),
                "over_16MiB": sum(f["size_bytes"] > 16 * 1024**2 for f in files),
            }
        ),
        flush=True,
    )
    return summary


jobs = [("100MiB", c) for c in byte_cases] + [("reuse", c) for c in reuse]
with ThreadPoolExecutor(max_workers=2) as pool:
    rows = list(pool.map(one, jobs))
(ROOT / "followup-summary.json").write_text(
    json.dumps({"selection": selection, "cases": rows}, ensure_ascii=False, indent=2)
    + "\n",
    encoding="utf-8",
)
