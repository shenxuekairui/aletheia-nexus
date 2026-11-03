"""Bounded live SI benchmark; no fixtures, browser, model calls or source edits.

Run against a frozen manifest. Every case gets independent libraries and keeps
its raw acquisition, SI, HTTP and reference-inventory records. Publisher HTML
and the normal integrated/native workflow are measured separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read(path):
    return json.loads(path.read_text("utf-8"))


def reference_inventory(case, directory):
    """Independent current Europe PMC JATS reference, not a human gold label."""
    if not case.get("pmcid"):
        return {"status": "NOT_IN_MANIFEST"}
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/"
        + case["pmcid"]
        + "/fullTextXML"
    )
    body = bytearray()
    try:
        with httpx.stream("GET", url, timeout=20, follow_redirects=False) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 5 * 1024**2:
                    return {"status": "BYTE_LIMIT"}
        if b"<!ENTITY" in bytes(body).upper():
            return {"status": "ENTITY_DECLARATION"}
        article = ElementTree.fromstring(body)
        meta = article.find("./front/article-meta")
        dois = (
            {
                n.text.strip().lower()
                for n in meta.findall("article-id")
                if n.get("pub-id-type") == "doi" and n.text
            }
            if meta is not None
            else set()
        )
        if dois != {case["doi"]}:
            return {"status": "PARENT_CONFLICT", "observed_dois": sorted(dois)}
        hrefs = set()
        count = 0
        for element in article.iter():
            if element.tag.rsplit("}", 1)[-1] != "supplementary-material":
                continue
            count += 1
            for child in element.iter():
                link = child.get("{http://www.w3.org/1999/xlink}href")
                if link:
                    hrefs.add(link)
        (directory / "reference.xml").write_bytes(body)
        return {
            "status": "READ",
            "source_url": url,
            "sha256": hashlib.sha256(body).hexdigest(),
            "jats_elements": count,
            "unique_hrefs": sorted(hrefs),
            "current_xml_not_same_version_guarantee": True,
        }
    except Exception as exc:
        return {"status": "UNAVAILABLE", "error_type": type(exc).__name__}


def files(result, main):
    from aletheia_nexus.content.gate import sha256_file

    rows = []
    for item in result.get("items", []):
        if item["status"] not in {"SAVED", "REUSED"}:
            continue
        path = Path(item["path"])
        receipt = read(Path(item["source_record"]))
        digest = sha256_file(path)
        checks = {
            "bytes_match": digest == receipt["sha256"] == item["sha256"],
            "parent_doi": receipt["parent"]["doi"] == main.doi,
            "parent_pdf": receipt["parent"]["pdf_sha256"] == main.pdf_sha256,
            "parent_source": receipt["parent"]["sidecar_sha256"] == main.sidecar_sha256,
        }
        rows.append(
            {
                "filename": path.name,
                "suffix": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "role": item["role"],
                "status": item["status"],
                "association_basis": receipt["association_basis"],
                "source_url": receipt["source_url"],
                "final_host": urlsplit(receipt["final_url"]).hostname,
                "validation": receipt["validation"],
                "checks": checks,
            }
        )
    return rows


def worker(manifest, case_id, output):
    from aletheia_nexus.acquire.fulltext.resolution.transport import retrieve_page
    from aletheia_nexus.content.gate import sha256_file, validate_parser_input
    from aletheia_nexus.core.urls import redact_url_for_record
    from aletheia_nexus.workbench.acquisition import AcquisitionService
    from aletheia_nexus.workbench.library import LibraryService
    from aletheia_nexus.workbench.supplements import (
        acquire_supplements,
        discover_attachments,
    )

    case = next(c for c in manifest["cases"] if c["id"] == case_id)
    directory = output / "cases" / case_id
    directory.mkdir(parents=True, exist_ok=True)
    limits = manifest["limits"]
    stage = "reference"
    requests = []
    original_send = httpx.Client.send

    def observed(client, request, *args, **kwargs):
        started = time.monotonic()
        record = {
            "stage": stage,
            "method": request.method,
            "url": redact_url_for_record(str(request.url)),
            "host": request.url.host,
        }
        try:
            response = original_send(client, request, *args, **kwargs)
            record.update(
                http_status=response.status_code,
                content_type=response.headers.get("content-type"),
            )
            return response
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["header_elapsed_seconds"] = round(time.monotonic() - started, 3)
            if len(requests) < 2000:
                requests.append(record)

    httpx.Client.send = observed
    started = time.monotonic()
    result = {
        "id": case_id,
        "doi": case["doi"],
        "publisher_stratum": case["publisher_stratum"],
        "cohort": case["cohort"],
        "reference": reference_inventory(case, directory),
    }
    main = None
    try:
        stage = "integrated"
        (directory / "stage.txt").write_text(stage, encoding="utf-8")
        library = LibraryService(directory / "integrated")
        if case.get("existing_main"):
            original = validate_parser_input(case["existing_main"])
            before_original = original.pdf_sha256, original.sidecar_sha256
            imported = library.import_pdf(original.pdf_path)
            main = validate_parser_input(imported["pdf_path"])
            native = acquire_supplements(
                main.pdf_path,
                library=library,
                timeout=limits["request_timeout_seconds"],
                max_files=limits["max_si_files"],
                max_bytes=limits["si_max_bytes"],
            )
            result["main_status"] = (
                "EXISTING_VERIFIED"
                if main.identity_basis == "acquisition_verified"
                else "EXISTING_DECLARED"
            )
            result["original_unchanged"] = before_original == (
                sha256_file(original.pdf_path),
                sha256_file(original.sidecar_path),
            )
        else:
            service = AcquisitionService(library.root, library=library)
            report = service.run(
                [{"doi": case["doi"], "title": case["title"]}],
                {
                    "public_only": True,
                    "browser_enabled": False,
                    "include_si": True,
                    "timeout": limits["request_timeout_seconds"],
                    "max_si_files": limits["max_si_files"],
                    "si_max_bytes": limits["si_max_bytes"],
                    "discovery_max_attempts": 1,
                    "metadata_max_attempts": 1,
                    "max_attempts_per_route": 1,
                    "max_attempts_per_file": 1,
                    "max_route_attempts": 4,
                    "max_file_attempts": 4,
                    "source_preference": "exclude_cnki",
                },
            )
            write(directory / "main-report.json", report)
            row = report["items"][0]
            result.update(main_status=row["status"], task_status=report["status"])
            native = row.get("supplements", {"status": "NOT_ATTEMPTED", "items": []})
            if row.get("status") == "VERIFIED":
                main = validate_parser_input(row["pdf"])
        write(directory / "integrated-si.json", native)
        result["integrated_si_status"] = native["status"]
        result["integrated_truncated"] = native.get("truncated", False)
        if main is not None:
            result["integrated_files"] = files(native, main)
            result["main_pdf_sha256"] = main.pdf_sha256
            result["main_identity_basis"] = main.identity_basis
            result["main_source_host"] = urlsplit(
                read(main.sidecar_path).get("retrieval", {}).get("final_url", "")
            ).hostname
            result["main_unchanged"] = main.pdf_sha256 == sha256_file(
                main.pdf_path
            ) and main.sidecar_sha256 == sha256_file(main.sidecar_path)
        result["integrated_seconds"] = round(time.monotonic() - started, 2)
        write(directory / "integrated-summary.json", result)
        if manifest.get("measurement_scope") == "native_only":
            result.update(
                outcome="MEASURED",
                publisher_status="NOT_SCHEDULED",
                publisher_scope="not_scheduled_native_only",
            )
            return
        stage = "publisher_html"
        (directory / "stage.txt").write_text(stage, encoding="utf-8")
        publisher_started = time.monotonic()
        resolver = "https://doi.org/" + case["doi"]
        if main is not None:
            publisher_library = LibraryService(directory / "publisher")
            imported = publisher_library.import_pdf(main.pdf_path)
            publisher_main = validate_parser_input(imported["pdf_path"])
            publisher = acquire_supplements(
                publisher_main.pdf_path,
                library=publisher_library,
                page_urls=[resolver],
                timeout=limits["request_timeout_seconds"],
                max_files=limits["max_si_files"],
                max_bytes=limits["si_max_bytes"],
            )
            write(directory / "publisher-si.json", publisher)
            result.update(
                publisher_status=publisher["status"],
                publisher_scope="HTML_file_delivery",
                publisher_truncated=publisher.get("truncated", False),
                publisher_files=files(publisher, publisher_main),
            )
        else:
            page = retrieve_page(
                resolver,
                timeout=limits["request_timeout_seconds"],
                max_bytes=5 * 1024**2,
            )
            if page.text and not page.body_truncated:
                discovery = discover_attachments(
                    page.text, page.final_url, doi=case["doi"], title=case["title"]
                )
                # Persist only credential-free metadata, no live signed links.
                for item in discovery.get("items", []):
                    item["url"] = redact_url_for_record(item["url"])
                write(directory / "publisher-discovery-only.json", discovery)
                result.update(
                    publisher_status=discovery["status"],
                    publisher_scope="discovery_only_no_verified_main",
                    publisher_discovered=len(discovery["items"]),
                )
            else:
                result.update(
                    publisher_status="INVALID_PAGE",
                    publisher_scope="discovery_only_no_verified_main",
                )
        result["publisher_seconds"] = round(time.monotonic() - publisher_started, 2)
        result["outcome"] = "MEASURED"
    except Exception as exc:
        result.update(
            outcome="EXCEPTION", exception_stage=stage, error_type=type(exc).__name__
        )
    finally:
        result["wall_seconds"] = round(time.monotonic() - started, 2)
        result["http_requests"] = len(requests)
        result["http_status_counts"] = dict(
            Counter(str(r.get("http_status", r.get("error_type"))) for r in requests)
        )
        write(directory / "http.json", requests)
        write(directory / "result.json", result)
    print(
        json.dumps(
            {
                k: result.get(k)
                for k in (
                    "id",
                    "main_status",
                    "integrated_si_status",
                    "publisher_status",
                    "outcome",
                    "wall_seconds",
                )
            }
        ),
        flush=True,
    )


def run(manifest_path, output):
    manifest = read(manifest_path)
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / "manifest.json"
    if snapshot.exists():
        if snapshot.read_bytes() != manifest_path.read_bytes():
            raise ValueError("output manifest differs; use a new output directory")
    else:
        snapshot.write_bytes(manifest_path.read_bytes())
    code = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    source_difference = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            manifest["source_commit"],
            "HEAD",
            "--",
            "src/aletheia_nexus",
        ],
        check=False,
    )
    dirty_source = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "src/aletheia_nexus"], check=False
    )
    if source_difference.returncode or dirty_source.returncode:
        raise ValueError("tested commit differs from frozen manifest")
    execution = output / "execution.json"
    if not execution.exists():
        write(
            execution,
            {
                "source_commit": manifest["source_commit"],
                "checkout_commit": code,
                "script_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
                "browser": False,
                "model_calls": 0,
                "python": sys.version,
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
    initial_disk = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    disk = initial_disk
    disk_lock = Lock()

    def one(case):
        nonlocal disk
        directory = output / "cases" / case["id"]
        path = directory / "result.json"
        if path.exists():
            return read(path)
        if disk > manifest["limits"]["disk_budget_bytes"]:
            return {"id": case["id"], "outcome": "NOT_RUN_DISK_BUDGET"}
        directory.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "case",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output),
            "--case-id",
            case["id"],
        ]
        with (directory / "process.txt").open("x", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                process.wait(timeout=manifest["limits"]["case_timeout_seconds"])
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if not path.exists():
            partial = directory / "integrated-summary.json"
            result = (
                read(partial)
                if partial.exists()
                else {
                    "id": case["id"],
                    "doi": case["doi"],
                    "publisher_stratum": case["publisher_stratum"],
                    "cohort": case["cohort"],
                }
            )
            result.update(
                outcome="TIME_LIMIT"
                if process.returncode != 0
                else "PROCESS_NO_RESULT",
                last_stage=(directory / "stage.txt").read_text("utf-8")
                if (directory / "stage.txt").exists()
                else "startup",
            )
            write(path, result)
        size = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
        with disk_lock:
            disk += size
        return read(path)

    rows = []
    with ThreadPoolExecutor(max_workers=manifest["limits"]["workers"]) as pool:
        futures = {pool.submit(one, c): c for c in manifest["cases"]}
        for future in as_completed(futures):
            result = future.result()
            rows.append(result)
            print(
                json.dumps(
                    {
                        "done": len(rows),
                        "total": len(manifest["cases"]),
                        "id": result["id"],
                        "main": result.get("main_status"),
                        "native": result.get("integrated_si_status"),
                        "publisher": result.get("publisher_status"),
                        "outcome": result.get("outcome"),
                        "MiB_on_disk": round(disk / 1024**2),
                    }
                ),
                flush=True,
            )
    if (output / "run-summary.json").exists():
        return
    write(
        output / "run-summary.json",
        {"case_count": len(rows), "cases": sorted(rows, key=lambda r: r["id"])},
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["run", "case"])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case-id")
    args = parser.parse_args()
    if args.mode == "run":
        run(args.manifest.resolve(), args.output.resolve())
    else:
        # No browser or paid credentials are needed or inherited by this run.
        for key in list(os.environ):
            if key.endswith(("API_KEY", "API_TOKEN")) or key in {
                "UNPAYWALL_EMAIL",
                "ELSEVIER_INST_TOKEN",
                "ELSEVIER_BEARER_TOKEN",
            }:
                os.environ.pop(key, None)
        worker(read(args.manifest), args.case_id, args.output.resolve())
