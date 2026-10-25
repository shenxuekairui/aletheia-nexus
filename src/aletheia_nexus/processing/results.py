"""Resolvable references are necessary evidence, never proof of scientific support."""

from __future__ import annotations

import csv
import html
import io
import json
from copy import deepcopy
from pathlib import Path

from aletheia_nexus.content.export import write_ai_export
from aletheia_nexus.content.gate import sha256_file

from .contracts import digest, export_formats, response_schema, validate
from .provider import ProcessingError

RESULT_SCHEMA = "aletheia-nexus/extraction-result/v1"
FIELD_STATUS = {
    "reported": "原文报告",
    "normalized": "规范化",
    "not_reported": "材料中未报告",
    "ambiguous": "有歧义",
    "unconfirmed": "未确认",
}
NATURE_LABELS = {
    "reported": "直接报告",
    "author_interpretation": "作者解释",
    "ai_synthesis": "AI 归纳",
}


def _quotation(text: str) -> str:
    # Only presentation ligatures and whitespace are equivalent here. Do not use
    # NFKC: it collapses scientifically distinct superscripts/subscripts and units.
    return " ".join(
        text.translate(
            str.maketrans(
                {
                    "ﬀ": "ff",
                    "ﬁ": "fi",
                    "ﬂ": "fl",
                    "ﬃ": "ffi",
                    "ﬄ": "ffl",
                    "ﬅ": "st",
                    "ﬆ": "st",
                }
            )
        ).split()
    )


def check_response(
    response: dict, task: dict, package: dict, *, comparison: bool = False
) -> dict:
    validate(response, response_schema(task, comparison=comparison), "response")
    if (
        not response.get("records")
        and not response["claims"]
        and not response["issues"]
        and not response.get("requests")
    ):
        raise ProcessingError("empty_result_without_explanation")
    documents = {d["id"]: d for d in package["documents"]}
    image_pages = {(i["source_id"], i["page"]) for i in package["images"]}
    locations = []

    citation_errors = {}

    def matching_locations(citation: dict) -> list[dict]:
        """Offer bounded exact-quote locations, never silently repair a citation.

        Only the same supplied document is searched. A matching quote says nothing
        about support for the claim; the existing repair must still reassess it.
        """
        document = documents.get(citation["source_id"])
        quotation = _quotation(citation["quote"])
        if document is None or not quotation:
            return []
        matches = []
        for block in document["blocks"]:
            if block["page"] not in document["pages_requested"]:
                continue
            if quotation in _quotation(block["text"]):
                matches.append(
                    {
                        "source_id": citation["source_id"],
                        "block_id": block["id"],
                        "page": block["page"],
                    }
                )
                if len(matches) == 3:
                    break
        return matches

    def locate_citation(citation: dict) -> bool:
        review = False
        document = documents.get(citation["source_id"])
        if document is None or citation["page"] not in document["pages_requested"]:
            raise ProcessingError("invalid_citation")
        if not citation["quote"].strip():
            raise ProcessingError("missing_source_reading")
        block = next(
            (b for b in document["blocks"] if b["id"] == citation["block_id"]), None
        )
        reading = "parsed"
        if citation["block_id"] is None:
            if (citation["source_id"], citation["page"]) not in image_pages:
                raise ProcessingError("image_not_supplied")
            review = True
            reading = "visual-unverified"
        elif block is None or block["page"] != citation["page"]:
            raise ProcessingError("invalid_citation")
        else:
            quotation = _quotation(citation["quote"])
            if quotation not in _quotation(block["text"]):
                correction = next(
                    (
                        c
                        for c in document["corrections"]
                        if c["block_id"] == block["id"]
                        and quotation in _quotation(c["replacement"])
                    ),
                    None,
                )
                if not correction:
                    raise ProcessingError(
                        "quotation_not_in_source",
                        {
                            "citation": citation,
                            "source_block_excerpt": block["text"][:4000],
                            "validation": "Use a contiguous quotation from this block, or cite the correct supplied block. Do not join text from different blocks.",
                        },
                    )
                reading = "human-correction-overlay"
                review = True
            review |= bool(block.get("uncertain"))
        locations.append(
            {
                **citation,
                "source_artifact_id": document["source"]["artifact_id"],
                "parsed_artifact_id": document["parsed_artifact_id"],
                "pdf_sha256": document["source"]["pdf_sha256"],
                "bbox": block["evidence"]["bbox"] if block else None,
                "reading": reading,
                "support": "not-verified",
            }
        )
        return review

    def citations(items: list[dict], *, required: bool = True) -> bool:
        if required and not items:
            raise ProcessingError("missing_citation")
        review = False
        for citation in items:
            try:
                review |= locate_citation(citation)
            except ProcessingError as exc:
                key = digest(citation)
                if key in citation_errors:
                    continue
                citation_errors[key] = {
                    "code": exc.code,
                    "citation": citation,
                    **(exc.diagnostics or {}),
                }
                if exc.code in {"invalid_citation", "quotation_not_in_source"}:
                    citation_errors[key]["exact_quote_locations"] = matching_locations(
                        citation
                    )
        return review

    states = {}
    seen = set()
    for record in response.get("records", []):
        if (
            not record["id"].strip()
            or record["id"] in seen
            or not record["subject"].strip()
            or not record["stage"].strip()
        ):
            raise ProcessingError("invalid_record_identity")
        seen.add(record["id"])
        steps = record["steps"]
        step_ids = {s["id"] for s in steps}
        if (
            len(step_ids) != len(steps)
            or "" in step_ids
            or [s["order"] for s in steps] != list(range(1, len(steps) + 1))
        ):
            raise ProcessingError("invalid_step_order")
        review = False
        insufficient = False
        for step in steps:
            if not step["description"].strip():
                raise ProcessingError("empty_step")
            review |= citations(step["citations"]) or step["nature"] != "reported"
        definitions = {f["id"]: f for f in task["fields"]}
        for field_id, field in record["fields"].items():
            if not set(field["step_ids"]) <= step_ids:
                raise ProcessingError(
                    "invalid_step_reference",
                    {
                        "record_id": record["id"],
                        "field_id": field_id,
                        "unknown_step_ids": sorted(set(field["step_ids"]) - step_ids),
                        "available_step_ids": sorted(step_ids),
                        "validation": (
                            "Use only IDs of steps in this record where the field "
                            "actually applies. Use [] when no corresponding step "
                            "is reported; do not invent steps to satisfy validation."
                        ),
                    },
                )
            if field["status"] == "not_reported":
                if (
                    field["value"] is not None
                    or field["raw_value"] is not None
                    or field["unit"] is not None
                ):
                    raise ProcessingError(
                        "invented_missing_value",
                        {
                            "record_id": record["id"],
                            "field_id": field_id,
                            "validation": (
                                "For status not_reported, value, raw_value and unit "
                                "must all be JSON null. Put missing-information "
                                "explanations in context. If the source reports a "
                                "qualitative condition, preserve it with its citation "
                                "and an appropriate status instead."
                            ),
                        },
                    )
                insufficient = True
                citations(field["citations"], required=False)
            else:
                review |= citations(field["citations"])
                needs_raw = field["status"] == "normalized" or definitions[field_id][
                    "type"
                ] in {"number", "integer", "boolean"}
                if field["status"] in {"reported", "normalized"} and (
                    field["value"] is None or (needs_raw and not field["raw_value"])
                ):
                    raise ProcessingError("missing_original_value")
                if field["status"] in {"reported", "normalized"} and (
                    isinstance(field["value"], str)
                    and not field["value"].strip()
                    or isinstance(field["value"], list)
                    and not field["value"]
                ):
                    raise ProcessingError("empty_reported_value")
                review |= field["status"] != "reported" or field["nature"] != "reported"
            if field["status"] == "normalized" and not field["context"].strip():
                raise ProcessingError("normalization_requires_explanation")
        states[record["id"]] = (
            "evidence_insufficient"
            if insufficient
            else "review_required"
            if review
            else "source_located"
        )
    for claim in response["claims"]:
        if not claim["text"].strip():
            raise ProcessingError("empty_claim")
        citations(claim["citations"])
    for issue in response["issues"]:
        source = documents.get(issue["source_id"])
        if source is None or (
            issue["page"] is not None
            and not 1 <= issue["page"] <= source["source"]["page_count"]
        ):
            raise ProcessingError("invalid_issue_location")
    for request in response.get("requests", []):
        source = documents.get(request["source_id"])
        if (
            source is None
            or not request["reason"].strip()
            or not request["pages"]
            or any(
                not 1 <= p <= source["source"]["page_count"] for p in request["pages"]
            )
        ):
            raise ProcessingError("invalid_supplement_request")
    if citation_errors:
        errors = list(citation_errors.values())
        raise ProcessingError(
            errors[0]["code"],
            {
                "errors": errors,
                "validation": "Fix all listed citation errors against supplied evidence; retain original scientific meanings. exact_quote_locations lists up to three literal matches in the same supplied document, not proof that they support the claim. Reassess context before citing. Do not invent evidence.",
            },
        )
    if any(i["kind"] == "conflict" for i in response["issues"]):
        states = {key: "conflict" for key in states}
    return {
        "record_states": states,
        "citations": locations,
        "scientific_support": "not-verified",
        "absence_scope": "supplied_material_only",
    }


def seal_result(result: dict) -> dict:
    result.pop("artifact_id", None)
    result["artifact_id"] = "an:extraction:sha256:" + digest(result)
    return result


def make_result(
    task: dict,
    package: dict,
    provider: dict,
    response: dict,
    *,
    comparison: bool = False,
) -> dict:
    validation = check_response(response, task, package, comparison=comparison)
    return seal_result(
        {
            "schema": RESULT_SCHEMA,
            "task": deepcopy(task),
            "package": deepcopy(package),
            "provider": provider,
            "response": response,
            "validation": validation,
            "comparison": comparison,
            "history": [],
        }
    )


def verify_result(result: dict) -> None:
    payload = {k: v for k, v in result.items() if k != "artifact_id"}
    if result.get("schema") != RESULT_SCHEMA or result.get(
        "artifact_id"
    ) != "an:extraction:sha256:" + digest(payload):
        raise ValueError("result identity mismatch")
    if _review_validation(result) != result["validation"]:
        raise ValueError("result validation mismatch")


def _review_validation(result: dict) -> dict:
    checked = check_response(
        result["response"],
        result["task"],
        result["package"],
        comparison=result["comparison"],
    )
    for revision in result["history"]:
        if not all(
            revision.get(k) for k in ("author", "at", "reason", "parent_result_id")
        ):
            raise ValueError("invalid human revision history")
        if "claim_index" in revision:
            index = revision["claim_index"]
            if type(index) is not int or not 0 <= index < len(
                result["response"]["claims"]
            ):
                raise ValueError("revision references a missing claim")
            checked.setdefault("claim_states", {})[str(index)] = (
                "human_confirmed" if revision["confirm"] else "review_required"
            )
            continue
        key = revision["record_id"]
        if key not in checked["record_states"]:
            raise ValueError("revision references a missing record")
        if revision["confirm"]:
            checked["record_states"][key] = "human_confirmed"
        else:
            checked["record_states"][key] = check_response(
                result["response"],
                result["task"],
                result["package"],
                comparison=result["comparison"],
            )["record_states"][key]
    return checked


def revise_result(result: dict, revision: dict) -> dict:
    """An explicit human revision creates a child artifact, never modifies its parent."""
    verify_result(result)
    target = "claim_index" if "claim_index" in revision else "record_id"
    required = {target, "replacement", "author", "at", "reason", "confirm"}
    if (
        set(revision) != required
        or any(
            not isinstance(revision[k], str) or not revision[k].strip()
            for k in ("author", "at", "reason")
        )
        or type(revision["confirm"]) is not bool
        or not isinstance(revision["replacement"], dict)
    ):
        raise ValueError(
            "revision requires record_id or claim_index, replacement, author, at, reason and confirm"
        )
    updated = deepcopy(result)
    if target == "claim_index":
        items = updated["response"]["claims"]
        index = revision["claim_index"]
        if type(index) is not int or not 0 <= index < len(items):
            raise ValueError("revision must identify an existing claim")
    else:
        items = updated["response"].get("records", [])
        index = next(
            (i for i, r in enumerate(items) if r["id"] == revision["record_id"]), None
        )
        if index is None or revision["replacement"].get("id") != revision["record_id"]:
            raise ValueError("revision must identify an existing record")
    before = deepcopy(items[index])
    items[index] = deepcopy(revision["replacement"])
    updated["history"].append(
        {
            **deepcopy(revision),
            "before": before,
            "parent_result_id": result["artifact_id"],
        }
    )
    # Replay explicit reviews so edits revoke only their own confirmation and keep
    # unchanged records/claims confirmed. AI never supplies this history.
    updated["validation"] = _review_validation(updated)
    return seal_result(updated)


def _text(value: object) -> str:
    if value is None:
        return "未报告 / 待核对"
    if isinstance(value, list):
        return "; ".join(map(str, value))
    return str(value)


def _md(value: object) -> str:
    # Evidence/model prose is literal text. Only the exporter creates active
    # links, so a paper or model cannot embed remote images in a local report.
    text = _text(value).replace("\\", "\\\\")
    for character in "`*_[]()!#|~":
        text = text.replace(character, "\\" + character)
    return html.escape(text).replace("\n", "<br>")


def _csv(value: object) -> str:
    text = _text(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def export_results(
    results: list[dict], task: dict, output: Path, *, sources: dict | None = None
) -> list[str]:
    formats = export_formats(task)
    sources = sources or {}
    identities = {}
    for result in results:
        verify_result(result)
        for document in result["package"]["documents"]:
            sid = document["id"]
            identity = document["source"]["pdf_sha256"]
            if sid in identities and identities[sid] != identity:
                raise ValueError("same source ID refers to incompatible PDF versions")
            identities[sid] = identity
            pdf = document.get("locators", {}).get("pdf")
            if pdf:
                sources.setdefault(document["id"], pdf)
    valid_links = {}
    for sid, pdf in sources.items():
        try:
            if sha256_file(Path(pdf)) == identities.get(sid):
                valid_links[sid] = pdf
        except OSError:
            pass
    field_ids = [f["id"] for f in task["fields"]]
    lines = [
        "# 文献整理结果",
        "",
        _md(task["objective"]),
        "",
        "结果为 AI 派生资料；引用定位不等于科学支持已核实。未报告仅指所提供材料范围。",
        "",
    ]
    csv_stream = io.StringIO(newline="")
    writer = csv.writer(csv_stream)
    writer.writerow(
        ["record_id", "subject", "stage"]
        + [
            f"{fid}.{key}"
            for fid in field_ids
            for key in ("value", "raw_value", "unit", "status")
        ]
        + ["result_id", "sources"]
    )
    jsonl = []
    claim_jsonl = []
    reference_numbers = {}
    references = []

    def refs(citations: list) -> str:
        numbers = []
        for citation in citations:
            key = digest(citation)
            if key not in reference_numbers:
                reference_numbers[key] = len(references) + 1
                references.append(citation)
            numbers.append(f"[{reference_numbers[key]}]")
        return " ".join(numbers)

    for result in results:
        verify_result(result)
        provenance = {
            "result_id": result["artifact_id"],
            "package_id": result["package"]["artifact_id"],
            "provider": result["provider"],
            "source_documents": [
                {
                    "id": d["id"],
                    "source": d["source"],
                    "parsed_artifact_id": d["parsed_artifact_id"],
                }
                for d in result["package"]["documents"]
            ],
        }
        for record in result["response"].get("records", []):
            lines.extend(
                [
                    f"## {_md(record['subject'])} · {_md(record['stage'])}",
                    "",
                    "| 字段 | 值 | 单位 | 原始读法 | 性质 / 状态 / 来源 |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            row = [record["id"], record["subject"], record["stage"]]
            record_citations = []
            for definition in task["fields"]:
                field = record["fields"][definition["id"]]
                references_text = refs(field["citations"])
                lines.append(
                    f"| {_md(definition.get('label', definition['id']))} | {_md(field['value'])} | {_md(field['unit'] or '')} | {_md(field['raw_value'] or ('见引用' if field['value'] is not None else None))} | {NATURE_LABELS[field['nature']]} / {FIELD_STATUS[field['status']]} {references_text} |"
                )
                row.extend([field[k] for k in ("value", "raw_value", "unit", "status")])
                record_citations.extend(field["citations"])
            writer.writerow(
                [_csv(v) for v in row]
                + [
                    result["artifact_id"],
                    _csv(json.dumps(record_citations, ensure_ascii=False)),
                ]
            )
            lines.append("")
            for step in record["steps"]:
                lines.append(
                    f"{step['order']}. {_md(step['description'])} ({NATURE_LABELS[step['nature']]}) {refs(step['citations'])}"
                )
            lines.append("")
            jsonl.append(
                json.dumps(
                    {
                        "schema": "aletheia-nexus/research-record/v1",
                        **record,
                        **provenance,
                        "state": result["validation"]["record_states"][record["id"]],
                    },
                    ensure_ascii=False,
                )
            )
        for index, claim in enumerate(result["response"]["claims"]):
            claim_jsonl.append(
                json.dumps(
                    {
                        "schema": "aletheia-nexus/research-claim/v1",
                        "claim_index": index,
                        **claim,
                        **provenance,
                        "state": result["validation"]
                        .get("claim_states", {})
                        .get(str(index), "review_required"),
                    },
                    ensure_ascii=False,
                )
            )
            lines.extend(
                [
                    f"- {_md(claim['text'])} ({NATURE_LABELS[claim['nature']]}) {refs(claim['citations'])}",
                    "",
                ]
            )
        issues = result["response"]["issues"]
        if issues:
            lines.extend(
                [f"<details><summary>待核对事项（{len(issues)}）</summary>", ""]
            )
            for issue in issues:
                lines.extend([f"- {_md(issue['detail'])}", ""])
            lines.extend(["</details>", ""])
    if references:
        lines.extend(["## 原文入口", ""])
    for number, citation in enumerate(references, 1):
        sid = citation["source_id"]
        label = f"{sid} PDF p.{citation['page']}"
        link = (
            f"[{label}]({Path(valid_links[sid]).resolve().as_uri()}#page={citation['page']})"
            if sid in valid_links
            else label + "（本地原文件不可用或已变化；请按结果中的哈希定位）"
        )
        lines.append(f"[{number}] {link}：{_md(citation['quote'])}")
    outputs = []
    for format_name, name, payload in (
        ("markdown", "report.md", "\n".join(lines) + "\n"),
        ("csv", "table.csv", "\ufeff" + csv_stream.getvalue()),
        ("jsonl", "records.jsonl", "\n".join(jsonl) + ("\n" if jsonl else "")),
    ):
        if format_name in formats:
            write_ai_export(output / name, payload)
            outputs.append(name)
    if "jsonl" in formats and claim_jsonl:
        write_ai_export(output / "claims.jsonl", "\n".join(claim_jsonl) + "\n")
        outputs.append("claims.jsonl")
    return outputs


def export_prepared(packages: list[dict], task: dict, output: Path) -> None:
    """Readable local material; no empty AI report pretending extraction occurred."""
    lines = [
        "# 本地文献材料",
        "",
        _md(task["objective"]),
        "",
        "已准备以下原文材料；未调用远程 AI，尚未执行字段提取。",
        "",
    ]
    for package in packages:
        for document in package["documents"]:
            pdf = Path(document["locators"]["pdf"]).as_uri()
            lines.extend(
                [
                    f"## {_md(document['source']['title'] or document['id'])}",
                    "",
                    f"[打开 PDF]({pdf}) · 所选页：{document['pages_requested']}",
                    "",
                ]
            )
            for block in document["blocks"]:
                lines.extend(
                    [
                        _md(block["text"]),
                        "",
                        f"[PDF p.{block['page']}]({pdf}#page={block['page']})",
                        "",
                    ]
                )
            for note in document["notes"]:
                lines.extend(["用户备注：" + _md(note), ""])
            for correction in document["corrections"]:
                lines.extend(
                    [
                        "人工读法修订：" + _md(correction["replacement"]),
                        "依据：" + _md(correction["reason"]),
                        "",
                    ]
                )
    write_ai_export(output / "report.md", "\n".join(lines) + "\n")
