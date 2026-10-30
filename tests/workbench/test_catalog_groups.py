"""Paper presentation must not merge raw sources, trust, scope or attachments."""

from copy import deepcopy

import pytest

from aletheia_nexus.workbench.catalog_groups import catalog_groups


def source(identity, **updates):
    return {
        "id": identity,
        "doi": "10.1039/d1cy02168k",
        "pdf_sha256": "0" * 64,
        "document_role": "ARTICLE",
        "identity_basis": "acquisition_verified",
        "integrity": "verified",
        "title_original": "Original parent title",
        "authors": [],
        "tags": [],
        "folder": "",
        "parse_status": "UNPARSED",
        "attachments": [],
        **updates,
    }


def test_same_verified_rsc_pdf_is_one_row_with_authors_and_both_exact_sources():
    rows = [
        source("first"),
        source("second", authors=["Actual author"], first_author="Actual author"),
    ]
    original = deepcopy(rows)
    groups = catalog_groups(rows)
    assert len(groups) == 1 and groups[0]["id"] == "first"
    assert groups[0]["member_ids"] == ["first", "second"]
    assert groups[0]["authors"] == ["Actual author"]
    assert groups[0]["field_sources"] == {"authors": "second", "first_author": "second"}
    assert groups[0]["variants"] == original and rows == original
    groups[0]["variants"][0]["authors"].append("UI-only change")
    assert rows == original


@pytest.mark.parametrize(
    "difference",
    [
        {"pdf_sha256": "1" * 64},
        {"doi": "10.1039/other"},
        {"doi": None},
        {"doi": "not a doi"},
        {"identity_basis": "local_declared"},
        {"document_role": "SUPPLEMENT"},
        {"integrity": "hash_mismatch"},
        {"integrity": "missing"},
        {"pdf_sha256": "bad hash"},
    ],
)
def test_unverified_versions_declared_or_different_pdf_sources_stay_separate(
    difference,
):
    assert len(catalog_groups([source("one"), source("two", **difference)])) == 2


def test_two_declared_sources_are_not_folded_even_when_doi_and_pdf_match():
    assert (
        len(
            catalog_groups(
                [
                    source("one", identity_basis="local_declared"),
                    source("two", identity_basis="local_declared"),
                ]
            )
        )
        == 2
    )


def test_normalized_doi_and_hash_case_share_display_key_without_changing_values():
    first = source("one", doi="10.1039/D1CY02168K", pdf_sha256="a" * 64)
    second = source(
        "two", doi="https://doi.org/10.1039/d1cy02168k", pdf_sha256="A" * 64
    )
    row = catalog_groups([first, second])[0]
    assert row["member_ids"] == ["one", "two"]
    assert row["variants"] == [first, second]
    assert row["catalog_key"] == catalog_groups([second, first])[0]["catalog_key"]


def test_filtered_membership_and_existing_selection_do_not_gain_another_source():
    rows = [
        source("one", tags=["a"], folder="A"),
        source("two", tags=["b"], folder="B"),
    ]
    row = catalog_groups(rows, matching_ids=["two"], selected_ids=["one"])[0]
    assert row["id"] == "two" and row["member_ids"] == ["two"]
    assert row["all_member_ids"] == ["one", "two"] and not row["selected_member_ids"]
    assert row["tags"] == ["b"] and row["folder"] == "B"
    assert row["source_count"] == 1 and row["all_source_count"] == 2
    assert not catalog_groups(rows, matching_ids=[])
    assert catalog_groups(rows, matching_ids=["one"], selected_ids=["one"])[0][
        "selected_member_ids"
    ] == ["one"]


def test_parse_state_and_attachment_ownership_are_not_merged_into_representative():
    rows = [
        source(
            "one",
            parse_status="PARSED",
            attachments=[{"id": "si-one", "parent_id": "one"}],
        ),
        source(
            "two",
            parse_status="FAILED",
            attachments=[{"id": "si-two", "parent_id": "two"}],
        ),
    ]
    row = catalog_groups(rows)[0]
    assert row["parse_status"] == "PARSED"
    assert row["mixed_fields"] == ["parse_status"]
    assert row["attachments"] == rows[0]["attachments"]
    assert row["variants"][1]["attachments"][0]["parent_id"] == "two"


def test_conflicting_metadata_is_visible_without_replacing_values_or_manual_translation():
    rows = [
        source("one", year=2020, title_zh="人工译名", translation={"confirmed": True}),
        source("two", year=2021, title_zh="另一译名"),
    ]
    row = catalog_groups(rows)[0]
    assert row["year"] == 2020 and row["title_zh"] == "人工译名"
    assert row["translation"] == {"confirmed": True}
    assert set(row["metadata_conflicts"]) == {"year", "title_zh"}
    assert row["metadata_conflicts"]["year"] == [
        {"paper_id": "one", "value": 2020},
        {"paper_id": "two", "value": 2021},
    ]
