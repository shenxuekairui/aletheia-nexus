"""Public title metadata uses local grants; no model, real network or automatic acquisition."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_research_acquisition import make_app
from test_research_acquisition import public_network as public_network

from aletheia_nexus.acquire.metadata import crossref
from aletheia_nexus.acquire.metadata.exceptions import (
    MetadataNetworkError,
    MetadataParseError,
)
from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import read_json
from aletheia_nexus.research_ask import main as authorize_main


def works():
    return [
        {
            "DOI": "10.5555/first",
            "title": ["First possible match"],
            "author": [{"given": "A", "family": "Researcher"}],
            "published": {"date-parts": [[2024]]},
        },
        {"DOI": "10.5555/second", "title": ["Self-authored public acquisition test"]},
    ]


def test_crossref_query_is_fixed_bounded_and_returns_unverified_candidates(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return {
            "message": {"items": [*works(), deepcopy(works()[0]), {"DOI": "not-a-doi"}]}
        }

    monkeypatch.setattr(crossref, "get_json", get)
    result = crossref.search_crossref_candidates("  自编 α & β title  ", limit=5)
    assert calls[0][0] == "https://api.crossref.org/v1/works"
    assert calls[0][1]["params"] == {
        "query.bibliographic": "自编 α & β title",
        "rows": 5,
    }
    assert [x["doi"] for x in result["candidates"]] == [
        "10.5555/first",
        "10.5555/second",
    ]
    assert all(not x["identity_verified"] for x in result["candidates"])
    assert result["selection_required"] and result["status"] == "PARTIAL"
    assert [x["reason"] for x in result["skipped_records"]] == [
        "duplicate_doi",
        "malformed_metadata_record",
    ]


@pytest.mark.parametrize(
    "query,limit", [("", 5), ("x", 0), ("x", 6), ("x", True), ("x" * 1001, 5)]
)
def test_invalid_title_scope_is_rejected_without_http(monkeypatch, query, limit):
    monkeypatch.setattr(
        crossref, "get_json", lambda *a, **k: pytest.fail("must not query")
    )
    with pytest.raises(ValueError):
        crossref.search_crossref_candidates(query, limit=limit)


def test_empty_malformed_and_network_error_are_distinct(monkeypatch):
    monkeypatch.setattr(
        crossref, "get_json", lambda *a, **k: {"message": {"items": []}}
    )
    assert crossref.search_crossref_candidates("Synthetic title")["status"] == "EMPTY"
    monkeypatch.setattr(
        crossref, "get_json", lambda *a, **k: {"message": {"items": {}}}
    )
    with pytest.raises(MetadataParseError):
        crossref.search_crossref_candidates("Synthetic title")

    def timeout(*args, **kwargs):
        raise MetadataNetworkError("Synthetic timeout")

    monkeypatch.setattr(crossref, "get_json", timeout)
    with pytest.raises(MetadataNetworkError):
        crossref.search_crossref_candidates("Synthetic title")


def test_discovery_network_switch_one_use_scope_and_selected_doi_acquisition(
    tmp_path, monkeypatch, public_network, capsys
):
    calls, state = public_network
    metadata_calls = []
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def query(*args, **kwargs):
        metadata_calls.append(kwargs["params"])
        return {"message": {"items": works()}}

    monkeypatch.setattr(crossref, "get_json", query)
    app = make_app(tmp_path)
    try:
        with pytest.raises(ProcessingError, match="network_disabled"):
            app.find_paper_candidates("Synthetic title")
        app.network = True
        preview = app.find_paper_candidates("Synthetic title", limit=2)
        assert (
            preview["status"] == "AUTHORIZATION_REQUIRED"
            and metadata_calls == calls == []
        )
        request = read_json(Path(preview["authorization_request"]))
        assert request["scope"] == "discover" and not app.remote
        assert (
            authorize_main(
                [
                    "authorize",
                    preview["authorization_request"],
                    "--approve-fingerprint",
                    request["binding"],
                ]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "查询书目候选" in output and "不调用模型" in output
        token = output.strip().splitlines()[-1]
        with pytest.raises(ProcessingError, match="expired_or_changed"):
            app.find_paper_candidates("Different title", limit=2, authorization=token)
        with pytest.raises(ProcessingError, match="expired_or_changed"):
            app.acquire_documents(
                {"papers": [{"doi": "10.5555/second"}]},
                authorization=token,
                background=False,
            )
        result = app.find_paper_candidates(
            "Synthetic title", limit=2, authorization=token
        )
        assert result["downloads"] == result["model_calls"] == 0 and calls == []
        assert len(metadata_calls) == 1 and Path(result["result_file"]).is_file()
        with pytest.raises(ProcessingError, match="missing_or_used"):
            app.find_paper_candidates("Synthetic title", limit=2, authorization=token)
        selected = result["candidates"][1]
        payload = {"papers": [{"doi": selected["doi"], "title": selected["title"]}]}
        challenge = app.acquire_documents(payload)
        assert challenge["status"] == "AUTHORIZATION_REQUIRED" and calls == []
        state["second_available"] = True
        acquired = app.acquire_documents(
            payload, authorization=app.authorize("acquire", payload), background=False
        )
        assert acquired["status"] == "COMPLETED" and calls == ["10.5555/second"]
    finally:
        app.close()


def test_authorized_metadata_timeout_retains_query_and_failure_history(
    tmp_path, monkeypatch
):
    app = make_app(tmp_path, network=True)
    payload = {"title_query": "Synthetic timeout", "limit": 5}

    def fail(*args, **kwargs):
        raise MetadataNetworkError("Synthetic timeout")

    monkeypatch.setattr(crossref, "get_json", fail)
    try:
        with pytest.raises(MetadataNetworkError):
            app.find_paper_candidates(
                payload["title_query"], authorization=app.authorize("discover", payload)
            )
        result = read_json(next((app.workspace / "discovery").glob("*/result.json")))
        assert (
            result["status"] == "FAILED" and result["error"] == "MetadataNetworkError"
        )
        assert result["model_calls"] == 0
    finally:
        app.close()
