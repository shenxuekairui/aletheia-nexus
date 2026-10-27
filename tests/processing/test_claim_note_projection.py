"""Known empty provider metadata never changes a scientific claim or its raw history."""

import json
from copy import deepcopy

import pytest
from test_provider import metadata_example

from aletheia_nexus.processing.contracts import CLAIM, array, obj, response_schema
from aletheia_nexus.processing.provider import ProjectedResponse, project_response


@pytest.mark.parametrize("note", [None, "", "not_a_field"])
def test_empty_claim_note_preserves_science_raw_and_exact_replay(note):
    request, schema, raw, expected = metadata_example("claims")
    raw["claims"][0]["citations_note"] = note
    before = deepcopy(raw)
    text = json.dumps(raw, ensure_ascii=False)
    result = project_response(raw, schema, request.get("targets"), raw_text=text)
    assert raw == before
    assert result == expected
    assert isinstance(result, ProjectedResponse)
    assert result.metadata["raw_text"] == text
    assert any(
        c["reason"] == "empty_or_placeholder_claim_note"
        for c in result.metadata["changes"]
    )
    replay = project_response(
        json.loads(text), schema, request.get("targets"), raw_text=text
    )
    assert replay == result and replay.metadata == result.metadata


def test_nonempty_claim_note_is_not_discarded():
    _, schema, raw, _ = metadata_example("claims")
    raw["claims"][0]["citations_note"] = (
        "A scientific condition whose scope requires review."
    )
    with pytest.raises(ValueError, match="unknown keys"):
        project_response(raw, schema)


@pytest.mark.parametrize("kind", ["comparison", "revision"])
def test_empty_claim_note_in_comparison_and_targeted_revision(kind):
    _, _, _, original = metadata_example("claims")
    claim = deepcopy(original["claims"][0])
    claim["citations_note"] = None
    if kind == "comparison":
        schema = response_schema({}, comparison=True)
        raw = {"claims": [claim], "issues": []}
        expected = {"claims": [original["claims"][0]], "issues": []}
    else:
        schema = obj(
            {
                "replacements": obj({"claim:0": CLAIM}),
                "issues": array(obj({})),
                "requests": array(obj({})),
            }
        )
        raw = {"replacements": {"claim:0": claim}, "issues": [], "requests": []}
        expected = {
            "replacements": {"claim:0": original["claims"][0]},
            "issues": [],
            "requests": [],
        }
    result = project_response(raw, schema)
    assert result == expected
    assert isinstance(result, ProjectedResponse)
