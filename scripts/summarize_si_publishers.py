import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

parser = argparse.ArgumentParser(
    description="Audit saved SI benchmark bytes and summarize frozen cohort outcomes."
)
parser.add_argument("--root", required=True, type=Path)
args = parser.parse_args()
ROOT = args.root.resolve()
RUN = ROOT / "run"
manifest_path = ROOT / "manifest.json"
if not manifest_path.exists():
    manifest_path = RUN / "manifest.json"
manifest = json.loads(manifest_path.read_text("utf-8"))
cases = []
feed_errors = []
integrity_errors = []
reference_differences = []
all_requests = []
for item in manifest["cases"]:
    directory = RUN / "cases" / item["id"]
    if not (directory / "result.json").exists():
        continue
    result = json.loads((directory / "result.json").read_text("utf-8"))
    xml = directory / "reference.xml"
    main_hrefs = set()
    subarticle_hrefs = set()
    if xml.exists():
        article = ElementTree.fromstring(xml.read_bytes())
        parents = {child: parent for parent in article.iter() for child in parent}
        for node in article.iter():
            if node.tag.rsplit("}", 1)[-1] != "supplementary-material":
                continue
            parent = parents.get(node)
            subarticle = False
            while parent is not None:
                if parent.tag.rsplit("}", 1)[-1] in {
                    "sub-article",
                    "response",
                    "ref-list",
                }:
                    subarticle = True
                parent = parents.get(parent)
            hrefs = {
                child.get("{http://www.w3.org/1999/xlink}href")
                for child in node.iter()
                if child.get("{http://www.w3.org/1999/xlink}href")
            }
            (subarticle_hrefs if subarticle else main_hrefs).update(hrefs)
    result["reference_scope_audit"] = {
        "main_article_hrefs": sorted(main_hrefs),
        "subarticle_hrefs": sorted(subarticle_hrefs),
        "subarticle_only_hrefs": sorted(subarticle_hrefs - main_hrefs),
        "note": "Current reference XML; main-article scope excludes sub-articles, responses and cited-reference trees. Metadata HAS_SUPPL is not main-SI gold.",
    }
    for key in ["integrated_files", "publisher_files"]:
        mode = "integrated" if key == "integrated_files" else "publisher"
        for f in result.get(key, []):
            p = directory / mode / "SI" / f["filename"]
            with p.open("rb") as h:
                digest = hashlib.file_digest(h, "sha256").hexdigest()
            if digest != f["sha256"] or not all(f["checks"].values()):
                integrity_errors.append(
                    {"case": item["id"], "mode": mode, "filename": f["filename"]}
                )
            if f["suffix"] in [".xml", ".txt"]:
                with p.open("rb") as h:
                    prefix = h.read(65536)
                if re.search(
                    rb'<(?:rss\b|feed\b[^>]*xmlns=["\x27]http://www.w3.org/2005/Atom)|http://purl.org/rss/1\.0/',
                    prefix,
                    re.I,
                ):
                    feed_errors.append(
                        {
                            "case": item["id"],
                            "doi": item["doi"],
                            "mode": mode,
                            "filename": f["filename"],
                            "role": f["role"],
                            "sha256": digest,
                            "source_url": f["source_url"],
                            "evidence": "RSS/Atom root in saved attachment bytes",
                        }
                    )
    ref = result.get("reference", {})
    if (
        result.get("integrated_si_status") == "COMPLETED"
        and ref.get("status") == "READ"
        and len(main_hrefs) > len(result.get("integrated_files", []))
    ):
        reference_differences.append(
            {
                "case": item["id"],
                "reference_hrefs": len(main_hrefs),
                "saved": len(result.get("integrated_files", [])),
                "note": "Current Europe PMC XML is not a same-version or manual-gold guarantee",
            }
        )
    requests = (
        json.loads((directory / "http.json").read_text("utf-8"))
        if (directory / "http.json").exists()
        else []
    )
    all_requests.extend(requests)
    result["http_stage_status_counts"] = {
        stage: dict(
            Counter(
                str(r.get("http_status", r.get("error_type")))
                for r in requests
                if r["stage"] == stage
            )
        )
        for stage in ["reference", "integrated", "publisher_html"]
    }
    result["publisher_was_attempted"] = any(
        r["stage"] == "publisher_html" for r in requests
    )
    result["integrated_any_SI"] = any(
        f["role"] == "SUPPLEMENT" for f in result.get("integrated_files", [])
    )
    result["publisher_any_SI"] = any(
        f["role"] == "SUPPLEMENT" for f in result.get("publisher_files", [])
    )
    cases.append(result)


def metrics(rows):
    return {
        "n": len(rows),
        "main_verified": sum(
            r.get("main_status") in ["VERIFIED", "EXISTING_VERIFIED"] for r in rows
        ),
        "main_statuses": dict(
            Counter(r.get("main_status", "UNRECORDED") for r in rows)
        ),
        "integrated_SI_papers": sum(r["integrated_any_SI"] for r in rows),
        "integrated_completed": sum(
            r.get("integrated_si_status") == "COMPLETED" for r in rows
        ),
        "integrated_statuses": dict(
            Counter(r.get("integrated_si_status", "UNRECORDED") for r in rows)
        ),
        "integrated_files": sum(len(r.get("integrated_files", [])) for r in rows),
        "integrated_formats": dict(
            Counter(f["suffix"] for r in rows for f in r.get("integrated_files", []))
        ),
        "integrated_roles": dict(
            Counter(f["role"] for r in rows for f in r.get("integrated_files", []))
        ),
        "publisher_attempted": sum(r["publisher_was_attempted"] for r in rows),
        "publisher_file_delivery_scope": sum(
            r.get("publisher_scope") == "HTML_file_delivery" for r in rows
        ),
        "publisher_SI_papers": sum(r["publisher_any_SI"] for r in rows),
        "publisher_completed": sum(
            r.get("publisher_status") == "COMPLETED" for r in rows
        ),
        "publisher_statuses": dict(
            Counter(r.get("publisher_status", "UNRECORDED") for r in rows)
        ),
        "publisher_files": sum(len(r.get("publisher_files", [])) for r in rows),
        "publisher_formats": dict(
            Counter(f["suffix"] for r in rows for f in r.get("publisher_files", []))
        ),
        "publisher_roles": dict(
            Counter(f["role"] for r in rows for f in r.get("publisher_files", []))
        ),
        "reference_statuses": dict(
            Counter(r.get("reference", {}).get("status", "UNRECORDED") for r in rows)
        ),
        "outcomes": dict(Counter(r.get("outcome", "UNRECORDED") for r in rows)),
    }


summary = {
    "schema": "aletheia-nexus/si-scale-observations/v1",
    "source_commit": manifest["source_commit"],
    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    "planned": len(manifest["cases"]),
    "completed_cases": len(cases),
    "limits": manifest["limits"],
    "all": metrics(cases),
    "cohorts": {
        cohort: metrics([r for r in cases if r["cohort"] == cohort])
        for cohort in dict.fromkeys(r["cohort"] for r in cases)
    },
    "positive_by_publisher": {
        name: metrics(
            [
                r
                for r in cases
                if r["publisher_stratum"] == name
                and r["cohort"] == "metadata_SI_positive"
            ]
        )
        for name, _ in manifest["groups"]
    },
    "integrity_errors": integrity_errors,
    "misclassified_feeds": feed_errors,
    "reference_count_differences": reference_differences,
    "http_statuses": dict(
        Counter(str(r.get("http_status", r.get("error_type"))) for r in all_requests)
    ),
    "http_requests": len(all_requests),
    "cases": cases,
}
(ROOT / "summary-final.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
with (ROOT / "cases-final.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    columns = [
        "id",
        "doi",
        "publisher_stratum",
        "cohort",
        "main_status",
        "integrated_si_status",
        "integrated_any_SI",
        "publisher_status",
        "publisher_any_SI",
        "outcome",
        "wall_seconds",
    ]
    writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(cases)
print(
    json.dumps(
        {
            "completed": len(cases),
            "all": summary["all"],
            "cohorts": summary["cohorts"],
            "integrity_errors": integrity_errors,
            "misclassified_feed_count": len(feed_errors),
            "reference_count_differences": reference_differences,
        },
        ensure_ascii=True,
    ),
    flush=True,
)
