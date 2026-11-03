"""Freeze metadata-closed papers before any article/SI retrieval attempts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

from aletheia_nexus.acquire.fulltext.resolution.parser import parse_html
from aletheia_nexus.core.identifiers.doi import normalize_doi

GROUPS = [
    ("Elsevier", "10.1016"),
    ("ACS", "10.1021"),
    ("RSC", "10.1039"),
    ("Wiley", "10.1002"),
    ("Springer", "10.1007"),
    ("Nature", "10.1038"),
    ("Science", "10.1126"),
    ("OUP", "10.1093"),
    ("Cambridge", "10.1017"),
    ("Taylor_Francis", "10.1080"),
    ("SAGE", "10.1177"),
    ("BMJ", "10.1136"),
    ("IEEE", "10.1109"),
    ("IOP", "10.1088"),
    ("AIP", "10.1063"),
    ("APS", "10.1103"),
    ("Royal_Society", "10.1098"),
    ("Karger", "10.1159"),
    ("Biologists", "10.1242"),
    ("PNAS", "10.1073"),
]
SEED = "AN-SI-CLOSED-20261103-v1"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample(name, prefix, output, reuse):
    directory = output / "sampling"
    directory.mkdir(parents=True, exist_ok=True)
    query = {
        "filter": "type:journal-article,from-pub-date:2021-01-01,until-pub-date:2026-06-30",
        "rows": 40,
        "sort": "published",
        "order": "desc",
        "select": "DOI,title,publisher,container-title,published,type,license,link,relation",
    }
    evidence = {"publisher_stratum": name, "prefix": prefix, "query": query}
    requests = []

    def fetch(client, url, params, filename):
        target = directory / filename
        prior = reuse / "sampling" / filename if reuse else None
        if prior and prior.exists():
            raw = prior.read_bytes()
            target.write_bytes(raw)
            requests.append(
                {
                    "file": filename,
                    "reused_metadata_from": str(prior),
                    "sha256": sha(prior),
                }
            )
            return json.loads(raw)
        for attempt in range(1, 4):
            try:
                response = client.get(url, params=params)
                requests.append(
                    {
                        "file": filename,
                        "attempt": attempt,
                        "http_status": response.status_code,
                    }
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                target.write_bytes(response.content)
                return response.json()
            except (httpx.RequestError, httpx.HTTPStatusError):
                if attempt == 3:
                    raise
                time.sleep(attempt)
        raise RuntimeError("metadata attempts exhausted")

    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            path = directory / (name + "-crossref.json")
            crossref = fetch(
                client,
                f"https://api.crossref.org/prefixes/{prefix}/works",
                query,
                path.name,
            )["message"]["items"]
            evidence["crossref_sha256"] = sha(path)
            evidence["crossref_returned"] = len(crossref)
            candidates = {}
            for item in crossref:
                doi = normalize_doi(item.get("DOI", ""))
                titles = item.get("title") or []
                title = parse_html(titles[0]).visible_text.strip() if titles else ""
                if (
                    not doi.startswith(prefix + "/")
                    or not title
                    or re.search(
                        r"\b(?:correction|corrigendum|erratum|retraction|obituary)\b",
                        title,
                        re.I,
                    )
                ):
                    continue
                candidates[doi] = (item, title)
            mapped, snapshots, ambiguous = {}, [], set()
            dois = sorted(candidates)
            for index in range(0, len(dois), 20):
                batch = dois[index : index + 20]
                params = {
                    "filter": "doi:" + "|".join("https://doi.org/" + d for d in batch),
                    "select": "id,doi,title,open_access,primary_location,locations,type,publication_year",
                    "per-page": 100,
                }
                path = directory / f"{name}-openalex-{index // 20}.json"
                data = fetch(
                    client, "https://api.openalex.org/works", params, path.name
                )
                snapshots.append(
                    {"file": path.name, "sha256": sha(path), "queried_dois": batch}
                )
                for item in data["results"]:
                    doi = normalize_doi(item.get("doi", ""))
                    if doi in candidates:
                        if doi in mapped:
                            ambiguous.add(doi)
                        mapped[doi] = item
        eligible = []
        for doi, work in mapped.items():
            if doi in ambiguous or work.get("type") not in {"article", "review"}:
                continue
            access = work.get("open_access") or {}
            if access.get("is_oa") is not False or access.get("oa_status") != "closed":
                continue
            item, title = candidates[doi]
            eligible.append(
                {
                    "doi": doi,
                    "title": title,
                    "publisher_stratum": name,
                    "cohort": "metadata_closed",
                    "pmcid": None,
                    "journal": (item.get("container-title") or [""])[0],
                    "crossref_publisher": item.get("publisher"),
                    "crossref_published": item.get("published"),
                    "openalex_id": work["id"],
                    "open_access_snapshot": access,
                    "primary_location_is_oa": (work.get("primary_location") or {}).get(
                        "is_oa"
                    ),
                    "sampling_raw": "sampling/" + name + "-crossref.json",
                    "selection_key": hashlib.sha256(
                        (SEED + ":" + doi).encode()
                    ).hexdigest(),
                }
            )
        eligible.sort(key=lambda item: item["selection_key"])
        selected, journals = [], set()
        for different_journal in [True, False]:
            for item in eligible:
                if len(selected) >= 3:
                    break
                if item in selected or (
                    different_journal and item["journal"] in journals
                ):
                    continue
                selected.append(item)
                journals.add(item["journal"])
        evidence.update(
            status="SAMPLED",
            classified=len(mapped),
            eligible_closed=len(eligible),
            selected_dois=[item["doi"] for item in selected],
            openalex=snapshots,
            ambiguous_dois=sorted(ambiguous),
            requests=requests,
        )
        return selected, evidence
    except Exception as exc:
        evidence.update(
            status="SAMPLING_FAILED", error_type=type(exc).__name__, requests=requests
        )
        return [], evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reuse-sampling", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [
            pool.submit(sample, name, prefix, output, args.reuse_sampling)
            for name, prefix in GROUPS
        ]
        results = []
        for (name, _), job in zip(GROUPS, jobs, strict=True):
            selected, evidence = job.result()
            results.append((selected, evidence))
            print(
                json.dumps(
                    {
                        "group": name,
                        "selected": len(selected),
                        "status": evidence["status"],
                    }
                ),
                flush=True,
            )
    cases = []
    for selected, _ in results:
        for item in selected:
            item["id"] = f"{len(cases) + 1:03d}-" + item["publisher_stratum"]
            cases.append(item)
    repo = Path(__file__).resolve().parents[1]
    previous = json.loads(
        (
            repo / "benchmarks/si_publishers_20261103/native-current-manifest.json"
        ).read_text("utf-8")
    )
    controls = [
        item
        for item in previous["cases"]
        if item["id"] in {"002-ACS", "004-Wiley", "040-Taylor_Francis", "073-eLife"}
    ]
    for index, control in enumerate(controls, 1):
        cases.append(
            {
                **control,
                "id": f"C{index:02d}-" + control["publisher_stratum"],
                "cohort": "known_OA_regression_control",
            }
        )
    manifest = {
        "schema": "aletheia-nexus/si-closed-corpus/v1",
        "seed": SEED,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "measurement_scope": "native_only",
        "groups": GROUPS,
        "sampling_protocol": "First 40 Crossref journal articles per DOI prefix, published 2021-01-01 through 2026-06-30, published-descending; exclude correction/retraction/obituary titles; unambiguous OpenAlex DOI match with type article/review and is_oa=false plus oa_status=closed; SHA-256 seeded order, distinct journals preferred; take up to three without article/SI outcome filtering. Metadata classification is not an entitlement audit or SI-positive gold.",
        "independent_probe": "Public SI discovery/delivery without a main PDF; no fabricated parent, registration or pipeline-success claim. Existing native discovery and validation helpers only. Authorized routes not tested.",
        "limits": {
            "request_timeout_seconds": 20,
            "case_timeout_seconds": 420,
            "main_timeout_seconds": 200,
            "probe_timeout_seconds": 200,
            "max_si_files": 20,
            "si_max_bytes": 100 * 1024**2,
            "workers": 4,
            "disk_budget_bytes": 5 * 1024**3,
        },
        "cases": cases,
    }
    write(output / "manifest.json", manifest)
    write(
        output / "sampling-evidence.json",
        {
            "manifest_sha256": sha(output / "manifest.json"),
            "sampler_sha256": sha(Path(__file__)),
            "before_article_or_SI_delivery": True,
            "groups": [e for _, e in results],
        },
    )
    print(
        json.dumps(
            {
                "frozen_cases": len(cases),
                "closed": len(cases) - len(controls),
                "controls": len(controls),
                "manifest_sha256": sha(output / "manifest.json"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
