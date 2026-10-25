"""Sequential, checkpointed extraction with bounded material repair."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from aletheia_nexus.content.export import write_ai_export

from .contracts import digest, response_schema, validate_task
from .materials import Source, build_package, load_source, model_material
from .provider import CallBudget, DeepSeekProvider, ProcessingError, Provider
from .results import export_prepared, export_results, make_result, verify_result


def write_json(path: Path, value: dict, *, overwrite: bool = False) -> None:
    write_ai_export(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        overwrite=overwrite,
    )


def _request(task: dict, package: dict, previous: dict | None = None) -> dict:
    request = {
        "phase": "document_extraction",
        "objective": task["objective"],
        "type": task["type"],
        "fields": task["fields"],
        "rules": task["rules"],
        "material": model_material(package),
    }
    if previous is not None:
        request["previous_candidate"] = previous
    return request


def _within_input_budget(task: dict, request: dict) -> None:
    if (
        len(json.dumps(request, ensure_ascii=False))
        > task["budget"]["max_input_characters"]
    ):
        raise ProcessingError("input_budget_exceeded")


def _generate_checked(
    task: dict,
    package: dict,
    request: dict,
    images: list,
    provider: Provider,
    budget: CallBudget,
    run_dir: Path,
    prefix: str,
    row: dict,
    *,
    comparison: bool = False,
) -> dict:
    """One evidence-based repair; format/location checks never certify scientific truth."""
    repairable = {
        "invalid_model_output",
        "quotation_not_in_source",
        "invalid_citation",
        "missing_citation",
        "missing_source_reading",
        "missing_original_value",
        "empty_reported_value",
        "invalid_record_identity",
        "invalid_step_order",
        "invalid_step_reference",
        "invented_missing_value",
        "normalization_requires_explanation",
        "empty_result_without_explanation",
        "invalid_issue_location",
        "invalid_supplement_request",
        "image_not_supplied",
    }
    original_request = request
    for repair in range(task["budget"]["max_repair_rounds"] + 1):
        response = None
        _within_input_budget(task, request)
        suffix = "" if repair == 0 else f".repair{repair}"
        try:
            response = provider.generate(
                request,
                response_schema(task, comparison=comparison),
                images,
                budget,
                task["budget"]["max_output_tokens"],
            )
            write_json(run_dir / f"{prefix}.candidate{suffix}.json", response)
            make_result(
                task, package, provider.identity, response, comparison=comparison
            )
            return response
        except (ProcessingError, ValueError) as exc:
            code = (
                exc.code if isinstance(exc, ProcessingError) else "invalid_model_output"
            )
            diagnostic = (
                exc.diagnostics
                if isinstance(exc, ProcessingError)
                else {"validation": str(exc)}
            ) or {}
            write_json(
                run_dir / f"{prefix}.rejected{suffix}.json",
                {
                    "code": code,
                    "unvalidated": True,
                    **diagnostic,
                },
            )
            if code not in repairable or repair == task["budget"]["max_repair_rounds"]:
                raise
            row.setdefault("output_repairs", []).append(
                {"input": prefix, "error": code, "attempt": repair + 1}
            )
            request = {
                **original_request,
                "validation_feedback": {"code": code, **diagnostic},
            }
            if response is not None:
                request["unvalidated_candidate"] = response
    raise ProcessingError("invalid_model_output")


def _restore_cache(
    path: Path, task: dict, sources: list[Source], initial: dict, provider: dict
) -> dict | None:
    if not path.is_file():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        result = cached["result"]
        verify_result(result)
        if (
            result["provider"] != provider
            or result["task"] != task
            or result["history"]
        ):
            return None
        chain = cached["packages"]
        if not chain or chain[0] != initial:
            return None
        parent = initial
        restored_images = []
        for package in chain[1:]:
            rebuilt, images = build_package(
                task,
                sources,
                additions=package["additions"],
                parent_id=parent["artifact_id"],
                reason=package["reason"],
            )
            if package != rebuilt:
                return None
            parent = rebuilt
            restored_images.extend(images)
        if parent != result["package"]:
            return None
        for source in sources:
            source.verify()
        cached["_restored_images"] = restored_images
        return cached
    except (ValueError, OSError, KeyError, TypeError, ProcessingError):
        return None


def run_task(
    payload: dict,
    *,
    base_dir: str | Path,
    output_dir: str | Path,
    allow_remote: bool = False,
    provider: Provider | None = None,
    resume: bool = True,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    task = validate_task(payload)
    base = Path(base_dir).resolve()
    output = Path(output_dir).resolve()
    remote = task["mode"] != "local"
    if remote and (not task["allow_remote"] or not allow_remote):
        raise ProcessingError("remote_disabled")
    if remote and provider is None:
        if "model" not in task:
            raise ProcessingError("model_configuration_required")
        provider = DeepSeekProvider(task["model"], enabled=True)
    provider_identity = deepcopy(provider.identity) if remote else {"provider": "local"}
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    cache_dir = output / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    budget = CallBudget(task["budget"]["max_calls"], task["budget"].get("max_cost"))
    rows = [{"id": d["id"], "status": "PENDING"} for d in task["documents"]]
    manifest = {
        "schema": "aletheia-nexus/research-run/v1",
        "run_id": run_id,
        "task_fingerprint": digest(task),
        "provider": provider_identity,
        "task_file": "task.json",
        "mode": task["mode"],
        "items": rows,
        "calls": budget.calls,
        "status": "RUNNING",
        "outputs": [],
        "run_directory": str(run_dir),
        "interrupted": False,
    }
    write_json(run_dir / "task.json", task)

    def checkpoint() -> None:
        manifest["usage"] = {
            "http_attempts": len(budget.calls),
            "currency": task.get("model", {}).get("currency", "CNY"),
            "input_tokens": sum(
                (c.get("usage") or {}).get("input_tokens", 0) for c in budget.calls
            ),
            "output_tokens": sum(
                (c.get("usage") or {}).get("output_tokens", 0) for c in budget.calls
            ),
            "estimated_cost": sum(
                c["estimated_cost"]
                for c in budget.calls
                if c.get("estimated_cost") is not None
            ),
            "unknown_usage_calls": sum(c.get("usage") is None for c in budget.calls),
            "unknown_cost_calls": sum(
                c.get("estimated_cost") is None for c in budget.calls
            ),
            "elapsed_seconds": sum(c.get("elapsed_seconds", 0) for c in budget.calls),
        }
        write_json(run_dir / "manifest.json", manifest, overwrite=True)

    budget.checkpoint = checkpoint
    checkpoint()
    loaded = []
    results = []
    prepared = []
    row_by_id = {r["id"]: r for r in rows}
    try:
        for config in task["documents"]:
            try:
                source = load_source(config, base, task["mode"])
                loaded.append(source)
                row_by_id[config["id"]].update(
                    {
                        "source": source.identity,
                        "pdf": str(source.pdf),
                        "artifact": str(source.artifact.path)
                        if source.artifact
                        else None,
                    }
                )
            except (OSError, ValueError, RuntimeError) as exc:
                row_by_id[config["id"]].update(
                    {
                        "status": "FAILED",
                        "error": exc.code
                        if isinstance(exc, ProcessingError)
                        else "source_unavailable_or_invalid",
                    }
                )
                checkpoint()
        mains = {
            s.identity["pdf_sha256"]: s
            for s in loaded
            if s.identity["document_role"] == "ARTICLE"
        }
        groups = {}
        for source in loaded:
            parent = mains.get((source.identity.get("parent") or {}).get("pdf_sha256"))
            owner = parent or source
            groups.setdefault(owner.config["id"], []).append(source)
            if owner is not source:
                row_by_id[source.config["id"]].update(
                    {"status": "ATTACHED", "group": owner.config["id"]}
                )
        for owner_id, sources in groups.items():
            row = row_by_id[owner_id]
            row["status"] = "RUNNING"
            checkpoint()
            try:
                initial, images = build_package(task, sources)
                packages = [initial]
                package = initial
                for img in images:
                    _save_image(run_dir, img)
                write_json(run_dir / f"{owner_id}.package.0.json", initial)
                if not remote:
                    prepared.append(initial)
                    row.update(
                        {"status": "PREPARED", "package": f"{owner_id}.package.0.json"}
                    )
                    continue
                key = digest(
                    {
                        "task": task,
                        "material": initial["artifact_id"],
                        "provider": provider_identity,
                    }
                )
                cache = cache_dir / (key + ".json")
                cached = (
                    _restore_cache(cache, task, sources, initial, provider_identity)
                    if resume
                    else None
                )
                if cached:
                    result = cached["result"]
                    packages = cached["packages"]
                    for img in cached["_restored_images"]:
                        _save_image(run_dir, img)
                    row["reused"] = True
                    if cached.get("supplement_status"):
                        row["supplement_status"] = cached["supplement_status"]
                else:
                    additions = {}
                    previous = None
                    previous_package = None
                    for round_number in range(
                        task["budget"]["max_supplement_rounds"] + 1
                    ):
                        for source in sources:
                            source.verify()
                        request = _request(task, package, previous)
                        try:
                            response = _generate_checked(
                                task,
                                package,
                                request,
                                images,
                                provider,
                                budget,
                                run_dir,
                                f"{owner_id}.{round_number}",
                                row,
                            )
                        except (ProcessingError, ValueError) as exc:
                            if previous is None:
                                raise
                            response, package = previous, previous_package
                            row["supplement_status"] = (
                                exc.code
                                if isinstance(exc, ProcessingError)
                                else "invalid_model_output"
                            )
                            break
                        checkpoint()
                        if not response["requests"]:
                            break
                        changed = False
                        next_additions = deepcopy(additions)
                        by_id = {d["id"]: d for d in package["documents"]}
                        for supplement in response["requests"]:
                            sid = supplement["source_id"]
                            wanted = set(supplement["pages"])
                            covered = set(by_id[sid]["pages_requested"])
                            if task["mode"] == "hybrid":
                                covered = {
                                    i["page"]
                                    for i in package["images"]
                                    if i["source_id"] == sid
                                }
                            changed |= bool(wanted - covered)
                            next_additions[sid] = sorted(
                                set(next_additions.get(sid, [])) | wanted
                            )
                        if (
                            not changed
                            or round_number == task["budget"]["max_supplement_rounds"]
                        ):
                            row["supplement_status"] = (
                                "no_new_material"
                                if not changed
                                else "round_budget_exhausted"
                            )
                            break
                        try:
                            next_package, next_images = build_package(
                                task,
                                sources,
                                additions=next_additions,
                                parent_id=package["artifact_id"],
                                reason="; ".join(
                                    r["reason"] for r in response["requests"]
                                ),
                            )
                        except ProcessingError as exc:
                            row["supplement_status"] = exc.code
                            break
                        additions = next_additions
                        previous_package = package
                        package, images = next_package, next_images
                        packages.append(package)
                        for img in images:
                            _save_image(run_dir, img)
                        write_json(
                            run_dir / f"{owner_id}.package.{round_number + 1}.json",
                            package,
                        )
                        previous = response
                    for source in sources:
                        source.verify()
                    result = make_result(task, package, provider_identity, response)
                    row["reused"] = False
                    # A repeated request for already supplied material is a stable
                    # partial result, not a reason to charge again on every resume.
                    # Failures after adding material still retry on the next run.
                    if (
                        not response["requests"]
                        or row.get("supplement_status") == "no_new_material"
                    ):
                        write_json(
                            cache,
                            {
                                "result": result,
                                "packages": packages,
                                "supplement_status": row.get("supplement_status"),
                            },
                            overwrite=True,
                        )
                for index, item in enumerate(packages):
                    target = run_dir / f"{owner_id}.package.{index}.json"
                    if not target.exists():
                        write_json(target, item)
                result_file = f"{owner_id}.result.json"
                write_json(run_dir / result_file, result)
                results.append(result)
                response = result["response"]
                row.update(
                    {
                        "status": "PARTIAL"
                        if response.get("requests") or response["issues"]
                        else "COMPLETED",
                        "result": result_file,
                        "result_id": result["artifact_id"],
                        "record_count": len(response.get("records", [])),
                        "package_id": result["package"]["artifact_id"],
                    }
                )
            except (OSError, ValueError, RuntimeError) as exc:
                row.update(
                    {
                        "status": "FAILED",
                        "error": exc.code
                        if isinstance(exc, ProcessingError)
                        else "processing_or_validation_failed",
                    }
                )
            finally:
                checkpoint()
            if progress:
                progress(deepcopy(row))
        if remote and task["synthesize"] and len(results) > 1:
            _compare(
                task,
                results,
                provider,
                provider_identity,
                budget,
                run_dir,
                manifest,
                cache_dir=cache_dir,
                resume=resume,
                sources=loaded,
            )
        if remote:
            manifest["outputs"] = export_results(
                results, task, run_dir, sources={s.config["id"]: s.pdf for s in loaded}
            ) + ["task.json"]
        else:
            export_prepared(prepared, task, run_dir)
            manifest["outputs"] = ["report.md", "task.json"] + [
                r["package"] for r in rows if "package" in r
            ]
        statuses = {r["status"] for r in rows} - {"ATTACHED"}
        manifest["status"] = (
            "PREPARED"
            if not remote and statuses == {"PREPARED"}
            else "COMPLETED"
            if statuses == {"COMPLETED"}
            and manifest.get("comparison", {}).get("status", "COMPLETED") == "COMPLETED"
            else "PARTIAL"
            if results or "PREPARED" in statuses
            else "FAILED"
        )
        checkpoint()
        return manifest
    except KeyboardInterrupt:
        manifest.update({"status": "INTERRUPTED", "interrupted": True})
        checkpoint()
        raise
    except Exception:
        manifest["status"] = "FAILED"
        checkpoint()
        raise


def _save_image(directory: Path, image: dict) -> None:
    target = directory / (image["sha256"] + ".png")
    if not target.exists():
        with target.open("xb") as handle:
            handle.write(image["bytes"])


def _compare(
    task: dict,
    results: list[dict],
    provider: Provider,
    provider_identity: dict,
    budget: CallBudget,
    run_dir: Path,
    manifest: dict,
    *,
    cache_dir: Path,
    resume: bool,
    sources: list[Source],
) -> None:
    package = {
        "schema": "aletheia-nexus/comparison-package/v1",
        "builder_version": 2,
        "documents": [d for r in results for d in r["package"]["documents"]],
        "images": [i for r in results for i in r["package"]["images"]],
        "input_result_ids": [r["artifact_id"] for r in results],
    }
    package["artifact_id"] = "an:comparison-package:sha256:" + digest(package)
    manifest["comparison"] = {
        "status": "RUNNING",
        "input_result_ids": package["input_result_ids"],
    }
    try:
        source_ids = {d["id"] for d in package["documents"]}
        used_sources = [s for s in sources if s.config["id"] in source_ids]
        for source in used_sources:
            source.verify()
        if len(package["images"]) > task["budget"]["max_images"]:
            raise ProcessingError("image_budget_exceeded")
        images = []
        for descriptor in package["images"]:
            image_path = run_dir / (descriptor["sha256"] + ".png")
            if image_path.stat().st_size > 12_000_000:
                raise ProcessingError("page_image_budget_exceeded")
            data = image_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
                raise ProcessingError("comparison_image_changed")
            images.append({**descriptor, "bytes": data})
        key = digest({"task": task, "package": package, "provider": provider_identity})
        cached_path = cache_dir / ("comparison-" + key + ".json")
        cached = None
        if resume and cached_path.is_file():
            try:
                candidate = json.loads(cached_path.read_text("utf-8"))
                verify_result(candidate)
                if (
                    candidate["package"] == package
                    and candidate["task"] == task
                    and candidate["provider"] == provider_identity
                ):
                    cached = candidate
            except (OSError, ValueError, KeyError, TypeError, ProcessingError):
                pass
        request = _request(task, package)
        request["phase"] = "cross_document_synthesis"
        request["extractions"] = [r["response"] for r in results]
        request["instruction"] = (
            "Compare these extractions; cite original evidence. Preserve contradictions and gaps."
        )
        _within_input_budget(task, request)
        if cached:
            result = cached
        else:
            response = _generate_checked(
                task,
                package,
                request,
                images,
                provider,
                budget,
                run_dir,
                "comparison",
                manifest["comparison"],
                comparison=True,
            )
            result = make_result(
                task, package, provider_identity, response, comparison=True
            )
            for source in used_sources:
                source.verify()
            write_json(cached_path, result, overwrite=True)
        write_json(run_dir / "comparison.result.json", result)
        results.append(result)
        manifest["comparison"].update(
            {
                "status": "PARTIAL" if result["response"]["issues"] else "COMPLETED",
                "result": "comparison.result.json",
                "reused": cached is not None,
            }
        )
    except (OSError, ValueError, RuntimeError) as exc:
        manifest["comparison"].update(
            {
                "status": "FAILED",
                "error": exc.code
                if isinstance(exc, ProcessingError)
                else "comparison_validation_failed",
            }
        )
