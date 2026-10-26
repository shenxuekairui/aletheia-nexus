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
from .provider import (
    CallBudget,
    DeepSeekProvider,
    ProcessingError,
    ProjectedResponse,
    Provider,
    project_response,
)
from .results import (
    assign_record_ids,
    export_prepared,
    export_results,
    make_result,
    verify_result,
)
from .review import (
    REVIEW_VERSION,
    apply_revision,
    review_batches,
    review_schema,
    revision_mode,
    revision_schema,
    validate_review,
)


def write_json(path: Path, value: dict, *, overwrite: bool = False) -> None:
    write_ai_export(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        overwrite=overwrite,
    )


def _request(
    task: dict,
    package: dict,
    previous: dict | None = None,
    previous_package: dict | None = None,
    *,
    phase: str = "document_extraction",
) -> dict:
    request = {
        "phase": phase,
        "objective": task["objective"],
        "type": task["type"],
        "fields": task["fields"],
        "rules": task["rules"],
        "material": model_material(package),
    }
    if "include_steps" in task:
        request["include_steps"] = task["include_steps"]
    if phase == "cross_document_synthesis":
        request["instruction"] = (
            "Compare these extractions; cite original evidence. Preserve contradictions and gaps."
        )
    elif "include_claims" in task:
        request["include_claims"] = task["include_claims"]
        if phase == "document_extraction" and not task["include_claims"]:
            request["instruction"] = (
                "Put scientific content in the configured fields and requested steps; "
                "return claims: []. Keep necessary issues and material requests."
            )
    if previous is not None:
        if previous_package is None:
            raise ValueError("supplement requires its previous material package")
        by_id = {d["id"]: d for d in previous_package["documents"]}
        coverage = []
        for document in package["documents"]:
            sid = document["id"]
            text_pages = {b["page"] for b in document["blocks"]}
            before = {b["page"] for b in by_id[sid]["blocks"]}
            image_pages = {
                i["page"] for i in package["images"] if i["source_id"] == sid
            }
            prior_images = {
                i["page"] for i in previous_package["images"] if i["source_id"] == sid
            }
            coverage.append(
                {
                    "source_id": sid,
                    "current_text_pages": sorted(text_pages),
                    "added_text_pages": sorted(text_pages - before),
                    "current_image_pages": sorted(image_pages),
                    "added_image_pages": sorted(image_pages - prior_images),
                    "omitted_pages": document["omitted_pages"],
                }
            )
        # Keep the old answer on disk and for failure recovery, not as an anchor
        # for the new extraction. Requested pages are questions, never evidence.
        request["evidence_update"] = {
            "previous_package_id": previous_package["artifact_id"],
            "requested_context": deepcopy(previous["requests"]),
            "current_coverage": coverage,
        }
    return request


def _within_input_budget(task: dict, request: dict) -> None:
    if (
        len(json.dumps(request, ensure_ascii=False))
        > task["budget"]["max_input_characters"]
    ):
        raise ProcessingError("input_budget_exceeded")


def _save_response_metadata(
    response: dict, request: dict, schema: dict, path: Path, row: dict
) -> dict:
    # Mock/alternate providers use exactly the same projection as the HTTP adapter.
    if not isinstance(response, ProjectedResponse):
        response = project_response(response, schema, request.get("targets"))
    if isinstance(response, ProjectedResponse):
        write_json(path, response.metadata)
        row.setdefault("response_metadata", []).append(
            {"file": path.name, "sha256": digest(response.metadata)}
        )
    return dict(response)


def _metadata_cache(row: dict, run_dir: Path) -> dict:
    return {
        "response_metadata": row.get("response_metadata", []),
        "metadata_artifacts": {
            item["file"]: json.loads((run_dir / item["file"]).read_text("utf-8"))
            for item in row.get("response_metadata", [])
        },
    }


def _verify_metadata_cache(cached: dict) -> None:
    for item in cached.get("response_metadata", []):
        if Path(item["file"]).name != item["file"]:
            raise ValueError("invalid metadata artifact name")
        proof = cached["metadata_artifacts"][item["file"]]
        if digest(proof) != item["sha256"]:
            raise ValueError("response metadata changed")
        replay = project_response(
            json.loads(proof["raw_text"]),
            proof["schema"],
            proof["targets"],
            raw_text=proof["raw_text"],
        )
        if not isinstance(replay, ProjectedResponse) or replay.metadata != proof:
            raise ValueError("response metadata does not replay")


def _restore_metadata_files(cached: dict, run_dir: Path, row: dict) -> None:
    if cached.get("response_metadata"):
        row["response_metadata"] = cached["response_metadata"]
        for item in row["response_metadata"]:
            write_json(
                run_dir / item["file"], cached["metadata_artifacts"][item["file"]]
            )


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
    output_schema: dict | None = None,
    assemble: Callable[[dict], dict] | None = None,
) -> dict:
    """One evidence-based repair; format/location checks never certify scientific truth."""
    repairable = {
        "invalid_model_output",
        "invalid_citation",
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
    }
    original_request = request
    for repair in range(task["budget"]["max_repair_rounds"] + 1):
        response = None
        raw_response = None
        _within_input_budget(task, request)
        suffix = "" if repair == 0 else f".repair{repair}"
        try:
            schema = output_schema or response_schema(task, comparison=comparison)
            response = provider.generate(
                request,
                schema,
                images,
                budget,
                task["budget"]["max_output_tokens"],
            )
            raw_response = (
                json.loads(response.metadata["raw_text"])
                if isinstance(response, ProjectedResponse)
                else response
            )
            write_json(run_dir / f"{prefix}.candidate{suffix}.json", raw_response)
            response = _save_response_metadata(
                response,
                request,
                schema,
                run_dir / f"{prefix}.metadata{suffix}.json",
                row,
            )
            if assemble is not None:
                response = assemble(response)
            try:
                make_result(
                    task, package, provider.identity, response, comparison=comparison
                )
            except ProcessingError as error:
                if error.code != "invalid_record_identity":
                    raise
                # The response schema has already been checked. Row names are
                # bookkeeping; do not buy another extraction to make them unique.
                adjusted, changes = assign_record_ids(response)
                if not changes:
                    raise
                make_result(
                    task, package, provider.identity, adjusted, comparison=comparison
                )
                row.setdefault("record_id_adjustments", []).append(
                    {"candidate_sha256": digest(response), "changes": changes}
                )
                response = adjusted
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
                if isinstance(exc, ValueError):
                    raise ProcessingError(code, diagnostic) from None
                raise
            row.setdefault("output_repairs", []).append(
                {"input": prefix, "error": code, "attempt": repair + 1}
            )
            request = {
                **original_request,
                "validation_feedback": {"code": code, **diagnostic},
            }
            if raw_response is not None:
                request["unvalidated_candidate"] = raw_response
    raise ProcessingError("invalid_model_output")


def _review_candidate(
    task: dict,
    package: dict,
    candidate: dict,
    images: list,
    provider: Provider,
    budget: CallBudget,
    run_dir: Path,
    prefix: str,
    row: dict,
) -> tuple[dict, dict]:
    """Retain the last valid candidate if any bounded review/revision fails."""
    artifacts = {}

    def save(name: str, value: dict) -> None:
        artifacts[name] = deepcopy(value)
        write_json(run_dir / name, value)

    for index in range(task["budget"]["max_review_rounds"]):
        stem = f"{prefix}.review{index + 1}"
        save(f"{stem}.input.json", candidate)
        trace = {"round": index + 1, "version": REVIEW_VERSION, "status": "RUNNING"}
        row.setdefault("model_reviews", []).append(trace)
        budget.checkpoint()
        try:
            review = {"checks": [], "issues": [], "requests": []}
            batches = review_batches(
                candidate, include_steps=task.get("include_steps", True)
            )
            for batch, (targets, view) in enumerate(batches):
                original_request = {
                    **_request(task, package, phase="evidence_review"),
                    "candidate": view,
                    "targets": targets,
                }
                request = original_request
                for repair in range(task["budget"]["max_repair_rounds"] + 1):
                    _within_input_budget(task, request)
                    part = None
                    batch_stem = f"{stem}.batch{batch + 1}.attempt{repair + 1}"
                    try:
                        part = provider.generate(
                            request,
                            review_schema(),
                            images,
                            budget,
                            task["budget"]["max_output_tokens"],
                        )
                        save(
                            f"{batch_stem}.json",
                            json.loads(part.metadata["raw_text"])
                            if isinstance(part, ProjectedResponse)
                            else part,
                        )
                        part = _save_response_metadata(
                            part,
                            request,
                            review_schema(),
                            run_dir / f"{batch_stem}.metadata.json",
                            row,
                        )
                        validate_review(part, candidate, task, package, targets=targets)
                        break
                    except (ProcessingError, ValueError) as exc:
                        code = (
                            exc.code
                            if isinstance(exc, ProcessingError)
                            else "invalid_model_output"
                        )
                        diagnostic = (
                            (exc.diagnostics or {})
                            if isinstance(exc, ProcessingError)
                            else {"validation": str(exc)}
                        )
                        save(
                            f"{batch_stem}.rejected.json", {"code": code, **diagnostic}
                        )
                        if (
                            code
                            not in {
                                "invalid_model_output",
                                "invalid_citation",
                                "incomplete_model_review",
                                "empty_model_review",
                            }
                            or repair == task["budget"]["max_repair_rounds"]
                        ):
                            raise
                        request = {
                            **original_request,
                            "validation_feedback": {"code": code, **diagnostic},
                        }
                        if part is not None:
                            request["unvalidated_candidate"] = part
                for key in review:
                    review[key].extend(part[key])
            save(f"{stem}.feedback.json", review)
            validate_review(review, candidate, task, package)
            mode = revision_mode(review, candidate)
            trace["revision_mode"] = mode
            revised = candidate
            if mode != "unchanged":
                revision_request = {
                    **_request(task, package, phase="document_revision"),
                    "revision_mode": mode,
                    "base_candidate_sha256": digest(candidate),
                    "candidate": candidate,
                    "evidence_review": review,
                }
                patch = None

                def assemble(replacements: dict) -> dict:
                    nonlocal patch
                    patch = deepcopy(replacements)
                    return apply_revision(candidate, replacements, task, review)

                revised = _generate_checked(
                    task,
                    package,
                    revision_request,
                    images,
                    provider,
                    budget,
                    run_dir,
                    stem,
                    row,
                    output_schema=revision_schema(task, candidate, review)
                    if mode == "targeted"
                    else None,
                    assemble=assemble if mode == "targeted" else None,
                )
                if mode == "targeted":
                    save(f"{stem}.patch.json", patch)
                    trace["patch_sha256"] = digest(patch)
            # Feedback remains in the hash-bound history. Resolved advice must
            # not be reintroduced as an outstanding problem in the new result.
            save(f"{stem}.output.json", revised)
            trace.update(
                status="COMPLETED",
                input_sha256=digest(candidate),
                review_sha256=digest(review),
                output_sha256=digest(revised),
                scientific_support="not-verified",
            )
            candidate = revised
        except (ProcessingError, ValueError) as exc:
            trace.update(
                status="FAILED",
                error=exc.code
                if isinstance(exc, ProcessingError)
                else "invalid_model_review",
            )
            save(f"{stem}.failure.json", trace)
            row["review_status"] = trace["error"]
            break
        finally:
            budget.checkpoint()
    return candidate, artifacts


def _restore_cache(
    path: Path, task: dict, sources: list[Source], initial: dict, provider: dict
) -> dict | None:
    if not path.is_file():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        _verify_metadata_cache(cached)
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
        reviews = cached.get("model_reviews", [])
        if len(reviews) != task["budget"]["max_review_rounds"]:
            return None
        artifacts = cached.get("review_artifacts", {})
        if any(Path(name).name != name for name in artifacts):
            return None
        last_output = None
        for trace in reviews:
            if trace["status"] != "COMPLETED" or trace["version"] != REVIEW_VERSION:
                return None
            triple = {}
            for suffix, checksum in (
                ("input", "input_sha256"),
                ("feedback", "review_sha256"),
                ("output", "output_sha256"),
            ):
                matches = [
                    v
                    for name, v in artifacts.items()
                    if name.endswith(f".review{trace['round']}.{suffix}.json")
                ]
                if len(matches) != 1 or digest(matches[0]) != trace[checksum]:
                    return None
                triple[suffix] = matches[0]
            if last_output is not None and triple["input"] != last_output:
                return None
            validate_review(triple["feedback"], triple["input"], task, parent)
            mode = revision_mode(triple["feedback"], triple["input"])
            if trace.get("revision_mode") != mode:
                return None
            if mode == "unchanged" and triple["input"] != triple["output"]:
                return None
            if mode == "targeted":
                patches = [
                    value
                    for name, value in artifacts.items()
                    if name.endswith(f".review{trace['round']}.patch.json")
                ]
                if len(patches) != 1 or digest(patches[0]) != trace.get("patch_sha256"):
                    return None
                if (
                    apply_revision(
                        triple["input"], patches[0], task, triple["feedback"]
                    )
                    != triple["output"]
                ):
                    return None
            last_output = triple["output"]
        if reviews and last_output != result["response"]:
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
                        "request": _request(task, initial),
                        "schema": response_schema(task),
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
                    _restore_metadata_files(cached, run_dir, row)
                    if cached.get("record_id_adjustments"):
                        row["record_id_adjustments"] = cached["record_id_adjustments"]
                    if cached.get("supplement_status"):
                        row["supplement_status"] = cached["supplement_status"]
                    if cached.get("model_reviews"):
                        row["model_reviews"] = cached["model_reviews"]
                        for name, artifact in cached["review_artifacts"].items():
                            if Path(name).name != name:
                                raise ValueError("invalid review artifact name")
                            write_json(run_dir / name, artifact)
                else:
                    additions = {}
                    previous = None
                    previous_package = None
                    previous_images = None
                    for round_number in range(
                        task["budget"]["max_supplement_rounds"] + 1
                    ):
                        for source in sources:
                            source.verify()
                        request = _request(task, package, previous, previous_package)
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
                            images = previous_images
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
                        needs_input = any(not r["pages"] for r in response["requests"])
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
                                "needs_input"
                                if not changed and needs_input
                                else "no_new_material"
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
                        previous_images = images
                        package, images = next_package, next_images
                        packages.append(package)
                        for img in images:
                            _save_image(run_dir, img)
                        write_json(
                            run_dir / f"{owner_id}.package.{round_number + 1}.json",
                            package,
                        )
                        previous = response
                    review_artifacts = {}
                    if task["budget"]["max_review_rounds"]:
                        response, review_artifacts = _review_candidate(
                            task,
                            package,
                            response,
                            images,
                            provider,
                            budget,
                            run_dir,
                            owner_id,
                            row,
                        )
                        if not row.get("review_status") and row.get(
                            "supplement_status"
                        ) in {None, "no_new_material", "needs_input"}:
                            # Review can introduce requests after the reading loop.
                            # Cache only requests that cannot add new supplied pages.
                            covered_pages = {
                                d["id"]: set(d["pages_requested"])
                                for d in package["documents"]
                            }
                            if task["mode"] == "hybrid":
                                covered_pages = {
                                    sid: {
                                        image["page"]
                                        for image in package["images"]
                                        if image["source_id"] == sid
                                    }
                                    for sid in covered_pages
                                }
                            if not response["requests"] or any(
                                set(request["pages"])
                                - covered_pages[request["source_id"]]
                                for request in response["requests"]
                            ):
                                row.pop("supplement_status", None)
                            else:
                                row["supplement_status"] = (
                                    "needs_input"
                                    if any(not r["pages"] for r in response["requests"])
                                    else "no_new_material"
                                )
                    for source in sources:
                        source.verify()
                    result = make_result(task, package, provider_identity, response)
                    row["reused"] = False
                    # Already supplied pages and requests awaiting user material
                    # are stable partial results; resume must not charge again.
                    # Failures after adding material still retry on the next run.
                    if not row.get("review_status") and (
                        not response["requests"]
                        or row.get("supplement_status")
                        in {"no_new_material", "needs_input"}
                    ):
                        write_json(
                            cache,
                            {
                                "result": result,
                                "packages": packages,
                                "supplement_status": row.get("supplement_status"),
                                "model_reviews": row.get("model_reviews", []),
                                "review_artifacts": review_artifacts,
                                "record_id_adjustments": row.get(
                                    "record_id_adjustments", []
                                ),
                                **_metadata_cache(row, run_dir),
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
                        if response.get("requests")
                        or response["issues"]
                        or row.get("review_status")
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
        request = _request(task, package, phase="cross_document_synthesis")
        request["extractions"] = [r["response"] for r in results]
        _within_input_budget(task, request)
        key = digest(
            {
                "task": task,
                "package": package,
                "provider": provider_identity,
                "request": request,
                "schema": response_schema(task, comparison=True),
            }
        )
        cached_path = cache_dir / ("comparison-" + key + ".json")
        cached = None
        if resume and cached_path.is_file():
            try:
                candidate = json.loads(cached_path.read_text("utf-8"))
                # Older comparison caches contain the result directly.
                envelope = candidate if "result" in candidate else {"result": candidate}
                candidate = envelope["result"]
                _verify_metadata_cache(envelope)
                verify_result(candidate)
                if (
                    candidate["package"] == package
                    and candidate["task"] == task
                    and candidate["provider"] == provider_identity
                ):
                    cached = envelope
            except (OSError, ValueError, KeyError, TypeError, ProcessingError):
                pass
        if cached:
            result = cached["result"]
            _restore_metadata_files(cached, run_dir, manifest["comparison"])
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
            write_json(
                cached_path,
                {"result": result, **_metadata_cache(manifest["comparison"], run_dir)},
                overwrite=True,
            )
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
