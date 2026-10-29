"""Optional independent typed fields in one document-level bookkeeping record."""

from copy import deepcopy

from .contracts import PROMPT, digest, response_schema, validate
from .provider import decode_response, project_response, raw_response_value

VERSION = "field-independent/1"
INSTRUCTION = (
    "Read exactly this configured field independently from the supplied original source. "
    "Preserve its complete description, objects, conditions, qualifications and uncertainty. "
    "Return one document-level record with the supplied bookkeeping ID. It does not assert "
    "that the paper contains one experiment. No other field answers are supplied or rewritten. "
    "Return no steps or extra claims. The program copies this typed field unchanged."
)


def strategy_identity(task: dict) -> dict:
    if task.get("extraction_strategy") != "field_independent":
        return {}
    return {
        "extraction_strategy": "field_independent",
        "field_independent_version": VERSION,
        "field_independent_prompt_sha256": digest([PROMPT, INSTRUCTION]),
    }


def document_record(package: dict) -> dict:
    owners = [
        d for d in package["documents"] if d["source"]["document_role"] != "SUPPLEMENT"
    ]
    if len(owners) != 1:
        raise ValueError(
            "field_independent requires one main source per material family"
        )
    source = owners[0]
    return {
        "id": source["id"],
        "subject": source["source"]["title"] or source["id"],
        "stage": "document",
        "fields": {},
        "steps": [],
    }


def field_stage(task: dict, package: dict, request: dict, definition: dict) -> tuple:
    partial = deepcopy(task)
    partial["fields"] = [deepcopy(definition)]
    schema = response_schema(partial)
    records = schema["properties"]["records"]
    records.update(minItems=1, maxItems=1)
    row = records["items"]
    row["properties"] = {
        k: v for k, v in row["properties"].items() if k in {"id", "fields"}
    }
    row["required"] = ["id", "fields"]
    record = document_record(package)
    row["properties"]["id"] = {"type": "string", "enum": [record["id"]]}
    scoped = deepcopy(request)
    scoped["fields"] = [deepcopy(definition)]
    scoped["record_context"] = [{"id": record["id"], "scope": "document"}]
    scoped["instruction"] = scoped.get("instruction", "") + "\n" + INSTRUCTION
    return partial, schema, scoped


def assemble_field(response: dict, package: dict) -> dict:
    record = document_record(package)
    rows = response["records"]
    if len(rows) != 1 or rows[0]["id"] != record["id"]:
        raise ValueError("field_independent record identity mismatch")
    record["fields"] = deepcopy(rows[0]["fields"])
    return {**deepcopy(response), "records": [record]}


def narrow_response(response: dict) -> dict:
    return {
        **deepcopy(response),
        "records": [
            {"id": r["id"], "fields": deepcopy(r["fields"])}
            for r in response["records"]
        ],
    }


def check_stage_cache(cached: dict, schema: dict, package: dict) -> None:
    payload = {k: v for k, v in cached.items() if k != "field_artifact_id"}
    if cached.get("field_artifact_id") != "an:field-stage:sha256:" + digest(payload):
        raise ValueError("field stage identity mismatch")
    wire = cached["field_wire_response"]
    validate(wire, schema, "field_stage")
    if dict(project_response(cached["field_raw_response"], schema)) != wire:
        raise ValueError("field raw response mismatch")
    proof = cached.get("field_final_metadata")
    if proof:
        if proof["schema"] != schema or proof["targets"]:
            raise ValueError("field projection contract mismatch")
        replayed = decode_response(proof["raw_text"], schema)
        if (
            getattr(replayed, "metadata", None) != proof
            or dict(replayed) != wire
            or raw_response_value(replayed) != cached["field_raw_response"]
        ):
            raise ValueError("field projection does not replay")
    if assemble_field(wire, package) != cached["result"]["response"]:
        raise ValueError("field response was rewritten")


def merge_fields(responses: list[dict], task: dict, package: dict) -> dict:
    record = document_record(package)
    if len(responses) != len(task["fields"]):
        raise ValueError(
            "Do not deliver unexecuted fields as scientific missing values"
        )
    for definition, response in zip(task["fields"], responses):
        fields = response["records"][0]["fields"]
        if set(fields) != {definition["id"]}:
            raise ValueError("unexpected independent field")
        record["fields"].update(deepcopy(fields))
    return {
        "records": [record],
        "claims": [],
        "issues": [deepcopy(i) for r in responses for i in r["issues"]],
        "requests": [deepcopy(i) for r in responses for i in r["requests"]],
    }
