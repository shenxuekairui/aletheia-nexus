"""Measure public native SI independently of access to a closed main paper.

The normal product workflow and the unregistered SI delivery probe are separate
processes/results. No fake main PDF, cookies, browser or paid API is used.
"""

from __future__ import annotations

import argparse
import contextlib
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

import httpx
from benchmark_si_publishers import read, worker, write


def independent(manifest, case_id, output):
    """Exercise the actual DOI-only CLI, recording HTTP without changing it."""
    from aletheia_nexus.core.urls import redact_url_for_record
    from aletheia_nexus.si_cli import main as si_main

    case = next(item for item in manifest["cases"] if item["id"] == case_id)
    directory = output / "independent" / case_id
    directory.mkdir(parents=True, exist_ok=True)
    limits = manifest["limits"]
    requests = []
    original_send = httpx.Client.send

    def observed(client, request, *args, **kwargs):
        record = {
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
            requests.append(record)

    httpx.Client.send = observed
    started = time.monotonic()
    result = {"id": case_id, "doi": case["doi"], "cwd": str(Path.cwd())}
    try:
        with (
            (directory / "cli.json").open("x", encoding="utf-8") as stdout,
            (directory / "stderr.txt").open("x", encoding="utf-8") as stderr,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = si_main(
                [
                    "acquire",
                    case["doi"],
                    "--library",
                    str(directory / "library"),
                    "--max-files",
                    str(limits["max_si_files"]),
                    "--max-bytes",
                    str(limits["si_max_bytes"]),
                    "--timeout",
                    str(limits["request_timeout_seconds"]),
                ]
            )
        result.update(exit_code=code, result=read(directory / "cli.json"))
    finally:
        httpx.Client.send = original_send
        result["wall_seconds"] = round(time.monotonic() - started, 2)
        write(directory / "http.json", requests)
        write(directory / "summary.json", sanitized(result))


def sanitized(value):
    from aletheia_nexus.core.urls import redact_url_for_record

    if isinstance(value, dict):
        return {key: sanitized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return redact_url_for_record(value)
    return value


def probe(manifest, case_id, output):
    from aletheia_nexus.acquire.fulltext.resolution.transport import retrieve_page
    from aletheia_nexus.core.urls import redact_url_for_record
    from aletheia_nexus.workbench.supplement_figshare import discover_acs_attachments
    from aletheia_nexus.workbench.supplement_formats import resolve_extension
    from aletheia_nexus.workbench.supplement_pages import expand_supplement_pages
    from aletheia_nexus.workbench.supplements import (
        _retrieve_official_file,
        _validate_attachment,
        discover_attachments,
    )

    case = next(item for item in manifest["cases"] if item["id"] == case_id)
    directory = output / "probes" / case_id
    directory.mkdir(parents=True, exist_ok=True)
    limits = manifest["limits"]
    requests, files, errors, diagnostics = [], [], [], []
    original_send = httpx.Client.send

    def observed(client, request, *args, **kwargs):
        record = {
            "method": request.method,
            "url": redact_url_for_record(str(request.url)),
            "host": request.url.host,
        }
        started = time.monotonic()
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
            record["header_seconds"] = round(time.monotonic() - started, 3)
            requests.append(record)

    httpx.Client.send = observed
    started = time.monotonic()
    result = {
        "id": case_id,
        "doi": case["doi"],
        "publisher_stratum": case["publisher_stratum"],
        "cohort": case["cohort"],
        "registered": False,
        "main_pdf_supplied": False,
        "scope": "Public native discovery/delivery only; not a product acquisition success or complete-SI gold.",
    }
    try:
        discovery = discover_acs_attachments(
            doi=case["doi"],
            title=case["title"],
            timeout=limits["request_timeout_seconds"],
            max_bytes=limits["si_max_bytes"],
        )
        candidates = list(discovery.get("items", []))
        errors.extend(discovery.get("errors", []))
        diagnostics.extend(discovery.get("diagnostics", []))
        write(directory / "native-manifest.json", sanitized(discovery))
        if candidates:
            result["route"] = "official_ACS_Figshare"
        else:
            result["route"] = "official_DOI_article_page"
            resolver = "https://doi.org/" + case["doi"]
            page = retrieve_page(
                resolver,
                timeout=limits["request_timeout_seconds"],
                max_bytes=5 * 1024**2,
            )
            result["article_page"] = redact_url_for_record(page.final_url)
            if not page.text or page.body_truncated:
                result["page_status"] = "INVALID_PAGE"
                raise ValueError("invalid_or_truncated_article_page")
            (directory / "article.html").write_text(page.text, encoding="utf-8")
            discovery = discover_attachments(
                page.text, page.final_url, doi=case["doi"], title=case["title"]
            )
            result["page_status"] = discovery["status"]
            write(directory / "page-discovery.json", sanitized(discovery))
            expanded = expand_supplement_pages(
                discovery,
                fetch=retrieve_page,
                doi=case["doi"],
                title=case["title"],
                timeout=limits["request_timeout_seconds"],
            )
            candidates = [
                {**item, "page": item.get("page") or page.final_url}
                for item in expanded["items"]
            ]
            errors.extend(expanded["errors"])
            diagnostics.extend(expanded["diagnostics"])
            result["truncated"] = expanded["truncated"]
        result["discovered"] = len(candidates)
        if len(candidates) > limits["max_si_files"]:
            result["truncated"] = True
        for index, item in enumerate(candidates[: limits["max_si_files"]], 1):
            row = {
                "role": item["role"],
                "source_url": redact_url_for_record(item["url"]),
                "source_url_sha256": hashlib.sha256(item["url"].encode()).hexdigest(),
                "parent_doi": case["doi"],
                "registered": False,
            }
            resource = None
            try:
                resource = _retrieve_official_file(
                    item["url"],
                    source_page=item["page"],
                    attachment=item,
                    output_dir=directory / "files",
                    max_bytes=limits["si_max_bytes"],
                    timeout=limits["request_timeout_seconds"],
                )
                if (
                    item.get("expected_size") is not None
                    and resource.size_bytes != item["expected_size"]
                ):
                    raise ValueError("manifest_size_mismatch")
                with resource.local_path.open("rb") as stream:
                    md5 = hashlib.file_digest(stream, "md5").hexdigest()
                if item.get("expected_md5") and md5 != item["expected_md5"]:
                    raise ValueError("manifest_md5_mismatch")
                extension = resolve_extension(
                    resource.local_path, item["extension"], resource.content_type
                )
                validation = _validate_attachment(resource.local_path, extension)
                download_sha256 = resource.sha256
                final_url = redact_url_for_record(resource.final_url)
                target = directory / "files" / (f"{index:02d}" + extension)
                if target.exists():
                    raise ValueError("probe_destination_exists")
                resource.local_path.replace(target)
                resource = None
                with target.open("rb") as stream:
                    sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
                if sha256 != download_sha256:
                    raise ValueError("saved_bytes_differ_from_transport")
                row.update(
                    status="DELIVERED_UNREGISTERED",
                    path=str(target),
                    suffix=extension,
                    sha256=sha256,
                    md5=md5,
                    size_bytes=target.stat().st_size,
                    association_basis=item.get(
                        "association_basis",
                        "DOI_confirmed_official_article_page_explicit_link",
                    ),
                    evidence=sanitized(item.get("evidence", {})),
                    validation=validation,
                    declared_extension=item["extension"],
                    manifest_md5_checked=bool(item.get("expected_md5")),
                    bytes_match_transport=True,
                    final_url=final_url,
                )
            except Exception as exc:
                row.update(status="FAILED", error_type=type(exc).__name__)
            finally:
                if resource is not None:
                    resource.local_path.unlink(missing_ok=True)
            write(directory / f"file-{index:02d}.json", row)
            files.append(row)
        delivered = [
            item for item in files if item["status"] == "DELIVERED_UNREGISTERED"
        ]
        result["status"] = (
            "PARTIAL_DELIVERY"
            if delivered
            and (errors or result.get("truncated") or len(delivered) < len(candidates))
            else "FILES_DELIVERED"
            if delivered
            else "FILE_DELIVERY_FAILED"
            if candidates
            else result.get("page_status", "NO_EXPLICIT_FILES")
        )
    except Exception as exc:
        result.update(status="PROBE_FAILED", error_type=type(exc).__name__)
    finally:
        httpx.Client.send = original_send
        result.update(
            files=files,
            errors=errors,
            diagnostics=diagnostics,
            wall_seconds=round(time.monotonic() - started, 2),
            any_SI_delivered=any(
                item["status"] == "DELIVERED_UNREGISTERED"
                and item["role"] == "SUPPLEMENT"
                for item in files
            ),
        )
        write(directory / "http.json", requests)
        write(directory / "summary.json", sanitized(result))


def run(manifest_path, output):
    manifest = read(manifest_path)
    for args in [
        [
            "git",
            "diff",
            "--quiet",
            manifest["source_commit"],
            "HEAD",
            "--",
            "src/aletheia_nexus",
        ],
        ["git", "diff", "--quiet", "HEAD", "--", "src/aletheia_nexus"],
    ]:
        if subprocess.run(args, check=False).returncode:
            raise ValueError("product source differs from frozen manifest")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        if (output / "manifest.json").read_bytes() != manifest_path.read_bytes():
            raise ValueError("manifest changed; use a new output directory")
    else:
        (output / "manifest.json").write_bytes(manifest_path.read_bytes())
        write(
            output / "execution.json",
            {
                "source_commit": manifest["source_commit"],
                "checkout_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], text=True
                ).strip(),
                "manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
                "script_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                "integrated_worker_sha256": hashlib.sha256(
                    Path(__file__).with_name("benchmark_si_publishers.py").read_bytes()
                ).hexdigest(),
                "browser": False,
                "model_calls": 0,
                "credentials": False,
                "python": sys.version,
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
    disk = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    lock = Lock()

    def one(case):
        nonlocal disk
        destination = output / "cases" / case["id"] / "result.json"
        if destination.exists():
            return read(destination)
        with lock:
            over_budget = disk > manifest["limits"]["disk_budget_bytes"]
        result = {
            "id": case["id"],
            "doi": case["doi"],
            "publisher_stratum": case["publisher_stratum"],
            "cohort": case["cohort"],
        }
        if over_budget:
            result["status"] = "NOT_RUN_DISK_BUDGET"
        else:
            modes = (
                ["si"]
                if manifest["measurement_scope"] == "standalone_si"
                else ["probe", "main"]
            )
            for mode in modes:
                log = output / "logs" / (case["id"] + "-" + mode + ".txt")
                log.parent.mkdir(exist_ok=True)
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    mode,
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output),
                    "--case-id",
                    case["id"],
                ]
                with log.open("x", encoding="utf-8") as stream:
                    process = subprocess.Popen(
                        command,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        cwd=os.path.join(os.environ["SystemRoot"], "System32")
                        if mode == "si" and os.name == "nt"
                        else None,
                    )
                    try:
                        process.wait(
                            timeout=manifest["limits"][mode + "_timeout_seconds"]
                        )
                        result[mode + "_process"] = (
                            "FINISHED" if process.returncode == 0 else "PROCESS_ERROR"
                        )
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        result[mode + "_process"] = "TIME_LIMIT"
                path = (
                    output / "independent" / case["id"] / "summary.json"
                    if mode == "si"
                    else output / "probes" / case["id"] / "summary.json"
                    if mode == "probe"
                    else output / "native/cases" / case["id"] / "result.json"
                )
                if path.exists():
                    result[mode] = read(path)
            result["status"] = "MEASURED"
        write(destination, result)
        with lock:
            disk += sum(
                p.stat().st_size
                for directory in [
                    output / "probes" / case["id"],
                    output / "native/cases" / case["id"],
                    output / "independent" / case["id"],
                ]
                for p in directory.rglob("*")
                if p.is_file()
            )
        return result

    rows = []
    with ThreadPoolExecutor(max_workers=manifest["limits"]["workers"]) as pool:
        jobs = [pool.submit(one, case) for case in manifest["cases"]]
        for job in as_completed(jobs):
            row = job.result()
            rows.append(row)
            print(
                json.dumps(
                    {
                        "done": len(rows),
                        "total": len(jobs),
                        "id": row["id"],
                        "main": row.get("main", {}).get("main_status"),
                        "probe": row.get("probe", {}).get("status"),
                        "SI_delivered": row.get("probe", {}).get(
                            "any_SI_delivered", False
                        ),
                        "independent": row.get("si", {})
                        .get("result", {})
                        .get("status"),
                    }
                ),
                flush=True,
            )
    if not (output / "summary.json").exists():
        write(
            output / "summary.json",
            {
                "source_commit": manifest["source_commit"],
                "n": len(rows),
                "statuses": dict(Counter(row["status"] for row in rows)),
                "cases": sorted(rows, key=lambda row: row["id"]),
            },
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["run", "main", "probe", "si"])
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case-id")
    args = parser.parse_args()
    if args.mode == "run":
        run(args.manifest.resolve(), args.output.resolve())
    else:
        for key in list(os.environ):
            if key.endswith(("API_KEY", "API_TOKEN")) or key in {
                "UNPAYWALL_EMAIL",
                "ELSEVIER_INST_TOKEN",
                "ELSEVIER_BEARER_TOKEN",
            }:
                os.environ.pop(key, None)
        if args.mode == "main":
            worker(read(args.manifest), args.case_id, args.output / "native")
        elif args.mode == "si":
            independent(read(args.manifest), args.case_id, args.output)
        else:
            probe(read(args.manifest), args.case_id, args.output)
