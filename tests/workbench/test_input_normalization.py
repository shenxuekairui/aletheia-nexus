"""Source attribution, one-call authorization, and durable unknown billing."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import httpx
import pytest

from aletheia_nexus.workbench.input_normalization import (
    DEFAULT_OPTIONS,
    MAX_INPUT_CHARACTERS,
    InputNormalizationService,
    input_normalization_options,
)


def payload(request):
    body = json.loads(request.content)
    return json.loads(body["input"][0]["content"][0]["text"])


def paper(document, occurrence=None, **changes):
    source = occurrence or document["explicit_dois"][0]
    number = source["source_line"]
    quote = next(
        line["text"] for line in document["source_lines"] if line["line"] == number
    )
    row = {
        "id": source["id"],
        "doi": source["doi"],
        "title": None,
        "authors": [],
        "year": None,
        "journal": None,
        "folder": None,
        "tags": [],
        "source_lines": [number],
        "quote": quote,
        "organization_source_lines": [],
        "organization": {"folder": "none", "tags": "none"},
    }
    row.update(changes)
    return row


def response(papers, *, usage=True, status="completed"):
    value = {
        "status": status,
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"papers": papers, "warnings": []}, ensure_ascii=False
                        ),
                    }
                ],
            }
        ],
    }
    if usage:
        value["usage"] = {"input_tokens": 300, "output_tokens": 200}
    return httpx.Response(200, json=value)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-normalization-secret-key")


def service(tmp_path, handler):
    return InputNormalizationService(tmp_path, transport=httpx.MockTransport(handler))


def test_defaults_are_independent_and_no_consent_never_calls_http(tmp_path):
    original = deepcopy(DEFAULT_OPTIONS)
    checked = input_normalization_options({"model": {"name": "deepseek-flash"}})
    checked["model"]["max_retries"] = 2
    assert DEFAULT_OPTIONS == original
    run = service(tmp_path, lambda request: pytest.fail("no consent means no HTTP"))
    result = run.normalize("10.1000/a")
    assert result["status"] == "FAILED" and result["calls"] == []
    assert "授权" in result["diagnostics"][0]["message"]
    assert Path(result["receipt"]).exists()
    assert (
        json.loads(Path(result["receipt"]).read_text(encoding="utf-8"))["canonical"]
        is None
    )


def test_twenty_five_explicit_dois_are_complete_and_reversed_outputs_map_by_id(
    tmp_path,
):
    calls = []

    def handler(request):
        document = payload(request)
        calls.append(document)
        assert "PDF" not in document and not document.get("images")
        rows = [
            paper(document, occurrence)
            for occurrence in reversed(document["explicit_dois"])
        ]
        return response(rows)

    text = "\n".join(f"{i}. https://doi.org/10.9999/input-{i:02}" for i in range(1, 26))
    result = service(tmp_path, handler).normalize(text, consent=True)
    assert result["status"] == "COMPLETED", result["diagnostics"]
    assert len(calls) == len(result["calls"]) == 1
    assert result["preview"]["count"] == 25
    assert {p["doi"] for p in result["canonical"]["papers"]} == {
        f"10.9999/input-{i:02}" for i in range(1, 26)
    }
    assert all(not p["title"] for p in result["canonical"]["papers"])
    assert all(
        p["quote"] in text.splitlines()[p["source_lines"][0] - 1]
        and text[p["span"][0] : p["span"][1]] == p["quote"]
        for p in result["canonical"]["source_map"]
    )
    assert not result["billing_uncertain"] and result[
        "accounted_cost"
    ] == pytest.approx(0.0022)
    assert (
        len(result["input_sha256"]) == 64
        and result["canonical"]["requires_confirmation"]
    )
    assert {p.name for p in tmp_path.iterdir()} == {"input-normalization"}


@pytest.mark.parametrize(
    "mode", ["omit", "invent", "wrong_id", "duplicate", "invent_title"]
)
def test_missing_added_or_mismatched_bibliography_never_produces_canonical(
    tmp_path, mode
):
    def handler(request):
        document = payload(request)
        rows = [paper(document, d) for d in document["explicit_dois"]]
        if mode == "omit":
            rows.pop()
        if mode == "invent":
            rows[0]["doi"] = "10.1000/invented"
        if mode == "wrong_id":
            rows[0]["id"] = rows[1]["id"]
        if mode == "duplicate":
            rows.append(deepcopy(rows[0]))
        if mode == "invent_title":
            rows[0]["title"] = "A title recalled from model knowledge"
        return response(rows)

    result = service(tmp_path, handler).normalize("10.1000/a\n10.1000/b", consent=True)
    assert (
        result["status"] == "FAILED"
        and result["canonical"] is None
        and result["preview"] is None
    )
    assert len(result["calls"]) == 1 and result["accounted_cost"] > 0
    assert result["unvalidated_candidate"]


def test_explicit_groups_root_and_empty_tags_keep_manual_three_state_assignment(
    tmp_path,
):
    text = "A. 甲酸研究 | 标签=待读\n1. 10.1000/a\n2. 10.1000/b | 分类=/ | 标签=[]\nB. 其它\n3. 10.1000/c"

    def handler(request):
        document = payload(request)
        a, b, c = document["explicit_dois"]
        return response(
            [
                paper(
                    document,
                    a,
                    folder="甲酸研究",
                    tags=["待读"],
                    organization_source_lines=[1],
                    organization={"folder": "explicit", "tags": "explicit"},
                ),
                paper(
                    document,
                    b,
                    organization_source_lines=[3],
                    organization={"folder": "explicit", "tags": "explicit"},
                ),
                paper(
                    document,
                    c,
                    folder="其它",
                    organization_source_lines=[4],
                    organization={"folder": "explicit", "tags": "none"},
                ),
            ]
        )

    result = service(tmp_path, handler).normalize(text, consent=True)
    assert result["status"] == "COMPLETED", result["diagnostics"]
    assert [p["assignment"] for p in result["preview"]["items"]] == [
        {"folder_mode": "custom", "tags_mode": "custom"},
        {"folder_mode": "root", "tags_mode": "custom"},
        {"folder_mode": "custom", "tags_mode": "inherit"},
    ]
    assert result["canonical"]["papers"][1]["folder"] is None
    assert not result["canonical"]["papers"][1]["tags"]
    assert not (tmp_path / "甲酸研究").exists()


def test_proposed_organization_is_flagged_but_never_becomes_identity_evidence(tmp_path):
    result = service(
        tmp_path,
        lambda request: response(
            [
                paper(
                    payload(request),
                    folder="建议分类",
                    tags=["建议标签"],
                    organization={"folder": "proposed", "tags": "proposed"},
                )
            ]
        ),
    ).normalize("10.1000/a", consent=True)
    assert result["status"] == "COMPLETED"
    assert len(result["warnings"]) == 2
    assert all(row["code"] == "PROPOSED_ORGANIZATION" for row in result["warnings"])
    assert result["applied"] is False and result["canonical"]["requires_confirmation"]
    assert result["canonical"]["source_map"][0]["organization"]["folder"] == "proposed"


@pytest.mark.parametrize(
    "changes",
    [
        {
            "folder": "凭空分类",
            "organization": {"folder": "explicit", "tags": "none"},
            "organization_source_lines": [1],
        },
        {"folder": "../unsafe", "organization": {"folder": "proposed", "tags": "none"}},
        {"source_lines": [99], "title": "a"},
        {"quote": "not in source", "title": "a"},
        {"year": 2026},
        {"authors": ["Invented Author"]},
        {"journal": "Invented Journal"},
    ],
)
def test_invalid_fields_or_source_spans_are_not_accepted(tmp_path, changes):
    result = service(
        tmp_path, lambda r: response([paper(payload(r), **changes)])
    ).normalize("10.1000/a", consent=True)
    assert result["status"] == "FAILED" and result["canonical"] is None


def test_title_only_and_doi_metadata_require_literal_local_sources(tmp_path):
    text = "请整理以下文献\nElectrocatalytic reduction of acids — Jane Smith — 2025 — Example Journal\n10.1000/a"

    def handler(request):
        document = payload(request)
        title = paper(
            document,
            id="L0002",
            doi=None,
            title="Electrocatalytic reduction of acids",
            authors=["Jane Smith"],
            year=2025,
            journal="Example Journal",
            source_lines=[2],
            quote=text.splitlines()[1],
        )
        return response([paper(document), title])

    result = service(tmp_path, handler).normalize(text, consent=True)
    assert result["status"] == "COMPLETED", result["diagnostics"]
    assert result["canonical"]["papers"][1]["doi"] is None
    assert result["canonical"]["papers"][1]["year"] == 2025
    assert result["canonical"]["source_map"][1]["source_line_ids"] == ["L0002"]


def test_timeout_keeps_durable_reservation_and_does_not_retry(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        receipts = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in (tmp_path / "input-normalization").glob("*.json")
        ]
        assert receipts[-1]["calls"][0]["status"] == "started"
        raise httpx.ReadTimeout("secret test-normalization-secret-key must not persist")

    result = service(tmp_path, handler).normalize("10.1000/a", consent=True)
    assert len(calls) == 1 and result["status"] == "FAILED"
    assert result["billing_uncertain"] and result["reserved_cost"] > 0
    assert result["accounted_cost"] == result["reserved_cost"]
    assert "test-normalization-secret-key" not in Path(result["receipt"]).read_text(
        encoding="utf-8"
    )


def test_usage_unknown_and_model_incomplete_are_not_silent_success(tmp_path):
    def handler(request):
        return response([paper(payload(request))], usage=False, status="incomplete")

    result = service(tmp_path, handler).normalize("10.1000/a", consent=True)
    assert result["status"] == "FAILED" and result["error"] == "model_incomplete"
    assert result["canonical"] is None and result["billing_uncertain"]
    assert result["unvalidated_candidate_text"]


def test_budget_refuses_http_and_bad_options_are_durable(tmp_path):
    run = service(
        tmp_path,
        lambda request: pytest.fail(
            "invalid/budget-blocked requests must not reach HTTP"
        ),
    )
    result = run.normalize("10.1000/a", {"max_cost": 1e-8}, consent=True)
    assert (
        result["status"] == "FAILED"
        and result["error"] == "cost_budget_exhausted"
        and not result["calls"]
    )
    for options in [
        {"max_calls": 2},
        {"model": {"max_retries": 1}},
        {"max_output_tokens": 65537},
        {"max_cost": float("nan")},
    ]:
        with pytest.raises(ValueError):
            input_normalization_options(options)
        result = run.normalize("10.1000/a", options, consent=True)
        assert result["status"] == "FAILED" and Path(result["receipt"]).exists()
    assert (
        input_normalization_options({"max_output_tokens": 65536})["max_output_tokens"]
        == 65536
    )


def test_same_doi_in_two_explicit_groups_preserves_conflicting_alternatives(tmp_path):
    text = "[甲]\n10.1000/a\n[乙]\n10.1000/a"

    def handler(request):
        document = payload(request)
        a, b = document["explicit_dois"]
        return response(
            [
                paper(
                    document,
                    a,
                    folder="甲",
                    organization_source_lines=[1],
                    organization={"folder": "explicit", "tags": "none"},
                ),
                paper(
                    document,
                    b,
                    folder="乙",
                    organization_source_lines=[3],
                    organization={"folder": "explicit", "tags": "none"},
                ),
            ]
        )

    result = service(tmp_path, handler).normalize(text, consent=True)
    assert result["status"] == "COMPLETED", result["diagnostics"]
    assert result["preview"]["count"] == 2 and len(result["preview"]["conflicts"]) == 1
    assert len({item["id"] for item in result["canonical"]["source_map"]}) == 2


def test_input_limits_and_keys_block_before_http(tmp_path):
    run = service(
        tmp_path, lambda request: pytest.fail("invalid text must not reach HTTP")
    )
    for text in [
        "",
        None,
        "x" * (MAX_INPUT_CHARACTERS + 1),
        "test-normalization-secret-key",
    ]:
        assert run.normalize(text, consent=True)["status"] == "FAILED"


@pytest.mark.parametrize("field", ["folder", "tags"])
def test_proposed_label_cannot_bypass_explicit_original_assignment(tmp_path, field):
    def handler(request):
        values = {
            "folder": "甲",
            "tags": ["待读"],
            "organization_source_lines": [1],
            "organization": {"folder": "explicit", "tags": "explicit"},
        }
        values[field] = "另一个分类" if field == "folder" else ["另一个标签"]
        values["organization"][field] = "proposed"
        return response([paper(payload(request), **values)])

    result = service(tmp_path, handler).normalize(
        "[甲] | 标签=待读\n10.1000/a", consent=True
    )
    assert result["status"] == "FAILED" and result["canonical"] is None
    assert "分类或标签" in result["diagnostics"][0]["message"]


def test_three_concurrent_calls_have_independent_ledgers_and_no_global_http_lock(
    tmp_path,
):
    simultaneous = Barrier(3, timeout=10)

    def handler(request):
        simultaneous.wait()
        return response([paper(payload(request))])

    run = service(tmp_path, handler)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(lambda i: run.normalize(f"10.1000/a{i}", consent=True), range(3))
        )
    assert all(result["status"] == "COMPLETED" for result in results)
    assert len({result["id"] for result in results}) == 3
    assert all(len(result["calls"]) == 1 for result in results)
    assert len(list((tmp_path / "input-normalization").glob("*.json"))) == 3


def test_wrapped_doi_quote_can_bind_only_literal_core_and_crlf_is_preserved(tmp_path):
    result = service(
        tmp_path, lambda request: response([paper(payload(request), quote="10.1000/a")])
    ).normalize("说明\r\n(10.1000/a)\r\n", consent=True)
    assert result["status"] == "COMPLETED", result["diagnostics"]
    source = result["canonical"]["source_map"][0]
    assert source["source_lines"] == [2] and source["quote"] == "10.1000/a"
    assert result["canonical"]["unassigned_source_lines"] == [1]


def test_group_heading_cannot_become_an_extra_title_only_paper(tmp_path):
    def handler(request):
        document = payload(request)
        return response(
            [
                paper(document),
                paper(
                    document,
                    id="L0001",
                    doi=None,
                    title="分类标题",
                    source_lines=[1],
                    quote="[分类标题]",
                ),
            ]
        )

    result = service(tmp_path, handler).normalize("[分类标题]\n10.1000/a", consent=True)
    assert result["status"] == "FAILED" and result["canonical"] is None


def test_root_and_inherit_with_same_paper_fields_keep_distinct_source_bindings(
    tmp_path,
):
    def handler(request):
        document = payload(request)
        a, b = document["explicit_dois"]
        return response(
            [
                paper(document, a),
                paper(
                    document,
                    b,
                    organization_source_lines=[2],
                    organization={"folder": "explicit", "tags": "none"},
                ),
            ]
        )

    result = service(tmp_path, handler).normalize(
        "10.1000/a\n10.1000/a | 分类=/", consent=True
    )
    assert result["status"] == "COMPLETED"
    rows = result["preview"]["items"]
    assert rows[0]["normalization_ids"] != rows[1]["normalization_ids"]
    assert len(rows[0]["normalization_ids"]) == len(rows[1]["normalization_ids"]) == 1


@pytest.mark.parametrize("spliced", [True, False])
def test_group_header_cannot_be_spliced_over_another_paper_into_a_quote(
    tmp_path, spliced
):
    def handler(request):
        document = payload(request)
        first, second = document["explicit_dois"]
        rows = [
            paper(
                document,
                item,
                quote=item["doi"],
                folder="分组",
                organization_source_lines=[1],
                organization={"folder": "explicit", "tags": "none"},
            )
            for item in (first, second)
        ]
        if spliced:
            rows[1].update(source_lines=[1, 3], quote="A. 分组\n2. 10.1000/b")
        return response(rows)

    result = service(tmp_path, handler).normalize(
        "A. 分组\n1. 10.1000/a\n2. 10.1000/b", consent=True
    )
    assert result["status"] == "COMPLETED"
    if spliced:
        assert any(
            w["code"] == "SERVER_DOI_ANCHOR_REPAIRED" for w in result["warnings"]
        )
        assert result["canonical"]["source_map"][1]["submitted_model_source_lines"] == [
            1,
            3,
        ]
    assert [item["source_lines"] for item in result["canonical"]["source_map"]] == [
        [2],
        [3],
    ]
    assert all(
        item["anchor_basis"] == "server_explicit_doi_occurrence"
        and not item["model_quote_adopted"]
        for item in result["canonical"]["source_map"]
    )


def test_metadata_still_rejects_spliced_header_quote_instead_of_server_repair(tmp_path):
    def handler(request):
        document = payload(request)
        first, second = document["explicit_dois"]
        return response(
            [
                paper(
                    document,
                    first,
                    folder="分组",
                    organization_source_lines=[1],
                    organization={"folder": "explicit", "tags": "none"},
                ),
                paper(
                    document,
                    second,
                    title="Known title",
                    source_lines=[1, 3],
                    quote="A. 分组\n2. 10.1000/b Known title",
                    folder="分组",
                    organization_source_lines=[1],
                    organization={"folder": "explicit", "tags": "none"},
                ),
            ]
        )

    result = service(tmp_path, handler).normalize(
        "A. 分组\n1. 10.1000/a\n2. 10.1000/b Known title", consent=True
    )
    assert result["status"] == "FAILED" and result["canonical"] is None
    assert "跨过" in result["diagnostics"][0]["message"]
