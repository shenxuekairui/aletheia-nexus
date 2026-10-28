"""Local source-link recovery does not rewrite science or confirm support."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_workflow import MockProvider, response_for, task_for, write_pdf
from test_workflow import papers as papers

from aletheia_nexus.content import parse_document
from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.content.local import register_local_pdf
from aletheia_nexus.processing.engine import run_task
from aletheia_nexus.processing.results import (
    resolve_citation_source_ids,
    revise_result,
    seal_result,
    verify_result,
)


def test_native_engine_recovers_source_only_and_preserves_raw_cache_export_review(
    tmp_path, papers
):
    original = tmp_path / "supplement.pdf"
    text = "Synthesis lasted 3 h at 150 C. The material was then washed."
    write_pdf(
        original,
        [[(50, 700, 12, line)] for line in ("Supplement title", "Method index", text)],
        title="Self-authored supplement",
    )
    supplement = register_local_pdf(
        original,
        output_dir=tmp_path / "library",
        title="Self-authored supplement",
        role="SUPPLEMENT",
        parent_pdf=papers[0],
    )
    parse_document(supplement)
    hashes = {p: sha256_file(p) for p in (papers[0], original, supplement)}
    task = task_for([papers[0], supplement])
    task["budget"].update(max_calls=1, max_repair_rounds=0, max_review_rounds=0)

    def generate(request):
        response = response_for(request)
        si = next(d for d in request["material"]["documents"] if d["id"] == "paper1")
        block = next(b for b in si["blocks"] if b["page"] == 3)
        citation = {
            "source_id": "paper0",  # Impossible physical page, correct SI page/block/quote.
            "page": 3,
            "block_id": block["id"],
            "quote": block["text"],
        }
        record = response["records"][0]
        record["fields"]["method"].update(
            value=text, raw_value=text, citations=[deepcopy(citation)]
        )
        record["steps"][0].update(description=text, citations=[deepcopy(citation)])
        response["claims"] = [
            {"text": text, "nature": "reported", "citations": [deepcopy(citation)]}
        ]
        return response

    provider = MockProvider(generate)
    output = tmp_path / "out"

    def run():
        return run_task(
            task,
            base_dir=tmp_path,
            output_dir=output,
            allow_remote=True,
            provider=provider,
        )

    first = run()
    row = first["items"][0]
    assert row["status"] == "COMPLETED" and len(provider.requests) == 1
    directory = Path(first["run_directory"])
    raw = json.loads((directory / "paper0.0.candidate.json").read_text("utf-8"))
    result = json.loads((directory / row["result"]).read_text("utf-8"))
    verify_result(result)
    proof = result["citation_source_resolution"]
    assert len(proof["changes"]) == 3
    reversed_response = deepcopy(result["response"])
    for change in proof["changes"]:
        assert change["after"] == {**change["before"], "source_id": "paper1"}
        parent = reversed_response
        for part in change["path"][:-1]:
            parent = parent[part]
        parent[change["path"][-1]] = change["before"]
    assert reversed_response == raw  # Every scientific string/status remains identical.
    assert result["validation"]["record_states"] == {"r1": "review_required"}
    assert result["validation"]["claim_states"] == {"0": "review_required"}
    assert all(
        c["reading"] == "source-identity-unverified" and c["support"] == "not-verified"
        for c in result["validation"]["citations"]
    )
    assert "同页、同块" in (directory / "report.md").read_text("utf-8")
    exported = json.loads((directory / "records.jsonl").read_text("utf-8"))
    assert exported["citation_source_resolution"] == proof
    assert exported["state"] == "review_required"
    cached = run()
    assert cached["items"][0]["reused"] and len(provider.requests) == 1
    cached_result = json.loads(
        (Path(cached["run_directory"]) / cached["items"][0]["result"]).read_text(
            "utf-8"
        )
    )
    assert cached_result == result
    changed = revise_result(
        result,
        {
            "record_id": "r1",
            "replacement": deepcopy(result["response"]["records"][0]),
            "author": "fixture reviewer",
            "at": "2026-10-28T00:00:00Z",
            "reason": "Explicit source review in self-authored fixture",
            "confirm": True,
        },
    )
    verify_result(changed)
    assert changed["validation"]["record_states"]["r1"] == "human_confirmed"
    assert changed["validation"]["claim_states"]["0"] == "review_required"
    changed_claim = revise_result(
        changed,
        {
            "claim_index": 0,
            "replacement": deepcopy(changed["response"]["claims"][0]),
            "author": "fixture assistant",
            "authority": "assistant",
            "at": "2026-10-28T00:01:00Z",
            "reason": "Keep an unconfirmed claim separate from reviewed record",
            "confirm": False,
        },
    )
    verify_result(changed_claim)
    assert changed_claim["validation"]["record_states"]["r1"] == "human_confirmed"
    assert changed_claim["validation"]["claim_states"]["0"] == "review_required"
    tampered = deepcopy(result)
    tampered["citation_source_resolution"]["changes"][0]["reason"] = "unjustified"
    seal_result(tampered)
    with pytest.raises(ValueError, match="does not replay"):
        verify_result(tampered)
    assert {p: sha256_file(p) for p in hashes} == hashes


def test_no_guess_for_real_pages_unknown_sources_missing_identity_or_ambiguous_family():
    source = {
        "document_role": "ARTICLE",
        "pdf_sha256": "hash",
        "article_id": "article",
        "page_count": 1,
    }
    main = {"id": "main", "source": source, "blocks": [], "pages_requested": [1]}
    si = {
        "id": "si",
        "source": {
            "document_role": "SUPPLEMENT",
            "parent": {"pdf_sha256": "hash", "article_id": "article"},
            "page_count": 3,
        },
        "blocks": [{"page": 3, "id": "b1", "text": "Measured 5 m² in the control."}],
        "pages_requested": [3],
    }
    response = {
        "claims": [
            {
                "citations": [
                    {"source_id": "main", "page": 3, "block_id": "b1", "quote": "5 m²"}
                ]
            }
        ]
    }
    package = {"documents": [main, si]}
    valid, changes = resolve_citation_source_ids(response, package)
    assert len(changes) == 1 and valid != response
    cases = []
    for key, value in (("page_count", 3), ("page_count", None)):
        candidate = deepcopy(package)
        candidate["documents"][0]["source"][key] = value
        cases.append((deepcopy(response), candidate))
    missing_identity = deepcopy(package)
    missing_identity["documents"][1]["source"]["parent"]["article_id"] = "different"
    cases.append((deepcopy(response), missing_identity))
    ambiguous = deepcopy(package)
    duplicate = deepcopy(si)
    duplicate["id"] = "si2"
    ambiguous["documents"].append(duplicate)
    cases.append((deepcopy(response), ambiguous))
    for key, value in (
        ("source_id", "unknown"),
        ("block_id", None),
        ("block_id", "wrong"),
        ("quote", "5 m2"),
        ("quote", ""),
        ("page", 2),
    ):
        candidate = deepcopy(response)
        candidate["claims"][0]["citations"][0][key] = value
        cases.append((candidate, deepcopy(package)))
    for candidate, sources in cases:
        untouched = deepcopy((candidate, sources))
        adjusted, changes = resolve_citation_source_ids(candidate, sources)
        assert adjusted == candidate and changes == []
        assert (candidate, sources) == untouched


def adjacent_fixture(
    left="A microﬂuidic",
    right="response was observed.",
    quote="microfluidic response was observed.",
):
    main = {
        "id": "main",
        "source": {
            "document_role": "ARTICLE",
            "pdf_sha256": "hash",
            "article_id": "article",
            "page_count": 1,
        },
        "blocks": [],
        "pages_requested": [1],
    }
    si = {
        "id": "si",
        "source": {
            "document_role": "SUPPLEMENT",
            "page_count": 4,
            "parent": {"pdf_sha256": "hash", "article_id": "article"},
        },
        "blocks": [
            {"page": 3, "id": "b1", "text": left},
            {"page": 3, "id": "b2", "text": right},
        ],
        "pages_requested": [3, 4],
    }
    response = {
        "claims": [
            {
                "text": "Unchanged scientific assertion.",
                "citations": [
                    {"source_id": "main", "page": 3, "block_id": "b1", "quote": quote}
                ],
            }
        ]
    }
    return response, {"documents": [main, si]}


@pytest.mark.parametrize(
    "left,right,quote,mode",
    [
        (
            "A microﬂuidic",
            "response was observed.",
            "microfluidic response was observed.",
            "same_page_adjacent_blocks_whitespace",
        ),
        (
            "An image after continuous-\n",
            "\nflow operation.",
            "continuous-flow operation.",
            "same_page_adjacent_blocks_line_end_hyphen",
        ),
    ],
)
def test_adjacent_source_recovery_changes_only_source_and_records_exact_basis(
    left, right, quote, mode
):
    response, package = adjacent_fixture(left, right, quote)
    untouched = deepcopy((response, package))
    adjusted, changes = resolve_citation_source_ids(response, package)
    assert (response, package) == untouched
    assert len(changes) == 1
    change = changes[0]
    assert (
        change["reason"] == "impossible_source_page_unique_family_adjacent_block_quote"
    )
    assert change["after"] == {**change["before"], "source_id": "si"}
    assert change["evidence"]["block_ids"] == ["b1", "b2"]
    assert change["evidence"]["page"] == 3
    assert change["evidence"]["match_mode"] == mode
    assert len(change["evidence"]["block_text_sha256"]) == 2
    restored = deepcopy(adjusted)
    restored["claims"][0]["citations"][0] = change["before"]
    assert (
        restored == response
    )  # Every value, quote, page and original block ID is unchanged.


@pytest.mark.parametrize(
    "failure",
    [
        "other_family",
        "ambiguous_family",
        "different_page",
        "not_supplied",
        "missing_quote",
        "original_page_legal",
        "quote_only_in_second",
        "three_blocks",
        "duplicate_anchor",
        "exponent_changed",
        "digits_joined",
        "hyphen_deleted",
        "within_block_hyphen",
    ],
)
def test_adjacent_recovery_refuses_nonliteral_unbounded_or_ambiguous_matches(failure):
    response, package = adjacent_fixture()
    main, si = package["documents"]
    citation = response["claims"][0]["citations"][0]
    if failure == "other_family":
        si["source"]["parent"]["article_id"] = "unrelated"
    elif failure == "ambiguous_family":
        duplicate = deepcopy(si)
        duplicate["id"] = "si2"
        package["documents"].append(duplicate)
    elif failure == "different_page":
        si["blocks"][1]["page"] = 4
    elif failure == "not_supplied":
        si["pages_requested"] = [4]
    elif failure == "missing_quote":
        citation["quote"] = ""
    elif failure == "original_page_legal":
        main["source"]["page_count"] = 3
    elif failure == "quote_only_in_second":
        citation["quote"] = si["blocks"][1]["text"]
    elif failure == "three_blocks":
        si["blocks"][1]["text"] = "response was"
        si["blocks"].append({"page": 3, "id": "b3", "text": "observed."})
    elif failure == "duplicate_anchor":
        si["blocks"].append(deepcopy(si["blocks"][0]))
    elif failure == "exponent_changed":
        si["blocks"][0]["text"] = "Measured 5 m²"
        citation["quote"] = "5 m2 response was observed."
    elif failure == "digits_joined":
        si["blocks"][0]["text"] = "Measured 1"
        si["blocks"][1]["text"] = "23 units."
        citation["quote"] = "123 units."
    elif failure == "hyphen_deleted":
        si["blocks"][0]["text"] = "An image after continuous-"
        si["blocks"][1]["text"] = "flow operation."
        citation["quote"] = "continuousflow operation."
    else:
        si["blocks"][0]["text"] = "An image after continuous- flow operation."
        citation["quote"] = "continuous-flow operation."
    untouched = deepcopy((response, package))
    adjusted, changes = resolve_citation_source_ids(response, package)
    assert adjusted == response and changes == []
    assert (response, package) == untouched
