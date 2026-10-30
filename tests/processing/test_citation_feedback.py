"""Self-authored locator fixtures; matching text is not scientific support."""

from copy import deepcopy

import pytest

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.processing.results import _matching_locations, check_response


def document(identifier, *, role="ARTICLE", parent=None, text="Measured 5 μmol."):
    return {
        "id": identifier,
        "source": {
            "document_role": role,
            "pdf_sha256": identifier + "-hash",
            "article_id": identifier + "-article",
            "parent": parent,
        },
        "blocks": [{"id": "b1", "page": 1, "text": text}],
        "pages_requested": [1],
    }


@pytest.fixture
def family():
    main = document("main", text="Main methods.")
    parent = {"pdf_sha256": "main-hash", "article_id": "main-article"}
    supplement = document("si", role="SUPPLEMENT", parent=parent)
    citation = {"source_id": "main", "block_id": "b1", "page": 99, "quote": "5 μmol"}
    return [main, supplement], citation


def test_invalid_citation_stays_rejected_with_family_feedback(family):
    documents, citation = family
    package = {"documents": documents, "images": []}
    response = {
        "claims": [
            {"text": "Measured 5 μmol.", "nature": "reported", "citations": [citation]}
        ],
        "issues": [],
    }
    original = deepcopy((response, package))
    with pytest.raises(ProcessingError, match="invalid_citation") as caught:
        check_response(response, {}, package, comparison=True)
    assert caught.value.diagnostics["errors"][0]["exact_quote_locations"] == [
        {"source_id": "si", "block_id": "b1", "page": 1}
    ]
    assert (response, package) == original


@pytest.mark.parametrize("missing", ["pdf_sha256", "article_id", "parent"])
def test_missing_parent_identity_does_not_broaden_search(family, missing):
    documents, citation = family
    if missing == "parent":
        documents[1]["source"]["parent"] = None
    else:
        documents[1]["source"]["parent"].pop(missing)
    assert _matching_locations(citation, documents) == []


@pytest.mark.parametrize("mismatch", ["pdf_sha256", "article_id"])
def test_both_parent_identifiers_must_match(family, mismatch):
    documents, citation = family
    documents[1]["source"]["parent"][mismatch] = "different"
    documents.append(document("other-paper"))
    assert _matching_locations(citation, documents) == []


def test_missing_or_duplicate_main_keeps_only_same_document(family):
    documents, citation = family
    duplicate = deepcopy(documents[0])
    duplicate["id"] = "duplicate-main"
    for source_id in ("main", "si"):
        citation["source_id"] = source_id
        matches = _matching_locations(citation, [*documents, duplicate])
        assert matches == (
            [{"source_id": "si", "block_id": "b1", "page": 1}]
            if source_id == "si"
            else []
        )
    sibling = deepcopy(documents[1])
    sibling["id"] = "sibling"
    documents[1]["blocks"][0]["text"] = "No matching quote."
    assert _matching_locations(citation, [documents[1], sibling]) == []


def test_supplement_can_suggest_supplied_main_and_sibling(family):
    documents, citation = family
    citation["source_id"] = "si"
    documents[0]["blocks"][0]["text"] = "Measured 5 μmol."
    sibling = deepcopy(documents[1])
    sibling["id"] = "another-si"
    documents[1]["blocks"][0]["text"] = "Different measurement."
    expected = [
        {"source_id": "another-si", "block_id": "b1", "page": 1},
        {"source_id": "main", "block_id": "b1", "page": 1},
    ]
    assert _matching_locations(citation, [*documents, sibling]) == expected
    assert _matching_locations(citation, [sibling, *reversed(documents)]) == expected


def test_same_document_first_and_three_matches_in_total(family):
    documents, citation = family
    documents[0]["blocks"][0]["text"] = "5 μmol"
    documents[1]["blocks"] = [
        {"id": f"s{i}", "page": 1, "text": "5 μmol"} for i in range(5)
    ]
    assert _matching_locations(citation, documents) == [
        {"source_id": "main", "block_id": "b1", "page": 1},
        {"source_id": "si", "block_id": "s0", "page": 1},
        {"source_id": "si", "block_id": "s1", "page": 1},
    ]


def test_unselected_pages_and_cross_block_quotes_are_not_suggested(family):
    documents, citation = family
    documents[1]["pages_requested"] = []
    assert _matching_locations(citation, documents) == []
    documents[1]["pages_requested"] = [1]
    documents[1]["blocks"] = [
        {"id": "first", "page": 1, "text": "Measured 5"},
        {"id": "second", "page": 1, "text": "μmol."},
    ]
    assert _matching_locations(citation, documents) == []


@pytest.mark.parametrize(
    "quote,text",
    [
        ("5 mmol", "5 μmol"),
        ("5 µmol", "5 μmol"),
        ("−5 °C", "~5 °C"),
        ("CO2", "CO₂"),
        ("pretreated", "pre-treated"),
        ("5 μmol", "five μmol"),
    ],
)
def test_no_scientific_character_repair_or_fuzzy_match(family, quote, text):
    documents, citation = family
    documents[1]["blocks"][0]["text"] = text
    citation["quote"] = quote
    assert _matching_locations(citation, documents) == []


def test_existing_presentation_equivalence_and_unknown_source(family):
    documents, citation = family
    documents[1]["blocks"][0]["text"] = "ﬁlm\n contains 5 μmol."
    citation["quote"] = "film contains 5 μmol"
    assert _matching_locations(citation, documents) == [
        {"source_id": "si", "block_id": "b1", "page": 1}
    ]
    citation["quote"] = " "
    assert _matching_locations(citation, documents) == []
    citation.update(source_id="unknown", quote="5 μmol")
    assert _matching_locations(citation, documents) == []
