"""Catalogue display never substitutes or adds scientific material identities."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from aletheia_nexus.workbench.ui_catalog_sources import (
    catalog_hit_rows,
    resolve_catalog_choices,
    source_choice_groups,
    submit_catalog_sources,
)


def source(identity, **overrides):
    return {
        "id": identity,
        "doi": "10.1039/d1cy02168k",
        "pdf_sha256": "a" * 64,
        "integrity": "verified",
        "identity_basis": "acquisition_verified",
        "document_role": "ARTICLE",
        "title": "Actual source title",
        "pdf_path": f"/library/{identity}.pdf",
        "authors": ["Actual author"],
        "parse_status": "PARSED",
        "attachments": [{"id": identity + "_si"}],
        **overrides,
    }


def test_choices_only_use_explicit_members_and_preserve_order_and_original_rows():
    rows = [source("first"), source("second"), source("unselected")]
    rows.append(source("different", pdf_sha256="b" * 64))
    original = deepcopy(rows)
    ids = ["different", "second", "first", "second"]
    groups = source_choice_groups(rows, ids)
    assert len(groups) == 1
    assert groups[0]["member_ids"] == ["first", "second"]
    assert "unselected" in groups[0]["all_member_ids"]
    chosen = resolve_catalog_choices(rows, ids, {groups[0]["catalog_key"]: "first"})
    assert chosen == ["different", "first"]
    assert rows == original
    assert source_choice_groups(rows, ["second", "different"]) == []
    assert resolve_catalog_choices(rows, ["second", "different"], {}) == [
        "second",
        "different",
    ]


@pytest.mark.parametrize("choice", [None, "unselected", "missing"])
def test_missing_or_unselected_choice_cannot_enter_task(choice):
    rows = [source("first"), source("second"), source("unselected")]
    key = source_choice_groups(rows, ["first", "second"])[0]["catalog_key"]
    with pytest.raises(ValueError, match="本次已明确选中"):
        resolve_catalog_choices(rows, ["first", "second"], {key: choice})


def test_missing_source_and_incomplete_or_extra_group_choices_are_rejected():
    rows = [source("first"), source("second")]
    with pytest.raises(ValueError, match="已不在文库"):
        source_choice_groups(rows, ["first", "missing"])
    for choices in ({}, {"invented_group": "first"}):
        with pytest.raises(ValueError, match="每篇"):
            resolve_catalog_choices(rows, ["first", "second"], choices)


@pytest.mark.parametrize(
    "different",
    [
        {"doi": "10.1234/other"},
        {"pdf_sha256": "b" * 64},
        {"identity_basis": "local_declared"},
        {"integrity": "failed"},
        {"document_role": "SUPPLEMENT"},
    ],
)
def test_other_versions_or_declared_materials_are_not_silently_deduplicated(different):
    rows = [source("first"), source("second", **different)]
    assert resolve_catalog_choices(rows, ["first", "second"], {}) == [
        "first",
        "second",
    ]


def test_paper_view_retains_all_raw_hit_sources_and_excludes_unhit_variant():
    rows = [source("first"), source("second"), source("unselected")]
    rows.append(source("other", pdf_sha256="b" * 64))
    hits = [
        {"id": "main", "paper_id": "first", "pages": [1], "text": "Main quote"},
        {"id": "si", "paper_id": "second", "pages": [3], "text": "SI quote"},
        {"id": "other", "paper_id": "other", "pages": [7], "text": "Other quote"},
    ]
    original_rows, original_hits = deepcopy(rows), deepcopy(hits)
    projected = catalog_hit_rows(rows, hits)
    assert len(projected) == 2
    assert projected[0]["member_ids"] == ["first", "second"]
    assert projected[0]["source_count"] == projected[0]["current_page_hits"] == 2
    assert projected[0]["pages"] == "1,3"
    assert projected[1]["member_ids"] == ["other"]
    assert rows == original_rows and hits == original_hits


def test_single_source_submission_is_immediate_and_does_not_scan():
    controller = SimpleNamespace(ctx=SimpleNamespace(library=SimpleNamespace(root="A")))
    submissions, finished = [], []
    assert (
        submit_catalog_sources(
            controller,
            ["selected"],
            lambda chosen: submissions.append(chosen) or "submitted",
            on_finish=lambda: finished.append(True),
        )
        == "submitted"
    )
    assert submissions == [["selected"]] and finished == [True]


@pytest.mark.parametrize("cancel", [False, True])
def test_review_waits_before_submission_and_cancel_never_creates_task(
    monkeypatch, cancel
):
    from aletheia_nexus.workbench import ui_catalog_sources

    controller = SimpleNamespace(ctx=SimpleNamespace(library=SimpleNamespace(root="A")))
    submissions, finished, reviewed = [], [], []

    async def choose(library, ids):
        reviewed.append(list(ids))
        assert not submissions
        return None if cancel else ["second"]

    monkeypatch.setattr(ui_catalog_sources, "choose_catalog_sources", choose)
    pending = submit_catalog_sources(
        controller,
        ["first", "second"],
        lambda chosen: submissions.append(chosen),
        on_finish=lambda: finished.append(True),
    )
    assert not submissions and not reviewed
    asyncio.run(pending)
    assert reviewed == [["first", "second"]]
    assert submissions == ([] if cancel else [["second"]])
    assert finished == [True]


def test_root_switch_during_review_rejects_submission_and_unlocks(monkeypatch):
    from aletheia_nexus.workbench import ui_catalog_sources

    controller = SimpleNamespace(ctx=SimpleNamespace(library=SimpleNamespace(root="A")))
    submissions, finished = [], []

    async def choose(library, ids):
        controller.ctx.library = SimpleNamespace(root="B")
        return ["second"]

    monkeypatch.setattr(ui_catalog_sources, "choose_catalog_sources", choose)
    with pytest.raises(ValueError, match="文库已切换"):
        asyncio.run(
            submit_catalog_sources(
                controller,
                ["first", "second"],
                lambda chosen: submissions.append(chosen),
                on_finish=lambda: finished.append(True),
            )
        )
    assert not submissions and finished == [True]


def test_unambiguous_multiple_papers_continue_without_opening_dialog(monkeypatch):
    pytest.importorskip("nicegui")
    from nicegui import run, ui

    from aletheia_nexus.workbench.ui_catalog_sources import choose_catalog_sources

    async def io_bound(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    def no_dialog(*_, **__):
        pytest.fail("Ordinary material selection must not add a confirmation step")

    monkeypatch.setattr(run, "io_bound", io_bound)
    monkeypatch.setattr(ui, "dialog", no_dialog)
    rows = [source("first"), source("second", pdf_sha256="b" * 64)]
    assert asyncio.run(
        choose_catalog_sources(
            SimpleNamespace(scan=lambda **_: {"items": rows}), ["second", "first"]
        )
    ) == ["second", "first"]


def test_real_dialog_shows_selected_source_details_and_returns_explicit_choice(
    monkeypatch,
):
    pytest.importorskip("nicegui")
    from nicegui import run, ui

    from aletheia_nexus.workbench.ui_catalog_sources import choose_catalog_sources

    rows = [source("first"), source("second"), source("unselected")]
    submitted = []
    actions = {}
    original_button = ui.button

    def button(*args, **kwargs):
        actions[args[0]] = kwargs.get("on_click")
        return original_button(*args, **kwargs)

    container = ui.column()
    before = set(ui.context.client.elements)

    async def io_bound(callback, *args, **kwargs):
        return callback(*args, **kwargs)

    async def interact(dialog):
        elements = [
            element
            for key, element in ui.context.client.elements.items()
            if key not in before
        ]
        radios = [element for element in elements if isinstance(element, ui.radio)]
        assert len(radios) == 1 and radios[0].value is None
        assert set(radios[0].options) == {"first", "second"}
        assert "Actual author" in radios[0].options["first"]
        assert "/library/first.pdf" in radios[0].options["first"]
        assert "解析：已解析" in radios[0].options["first"]
        assert "附件（含 SI）：1 份" in radios[0].options["first"]
        radios[0].set_value("second")
        await actions["使用所选来源继续"]()
        return submitted[0]

    monkeypatch.setattr(run, "io_bound", io_bound)
    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui.dialog, "__await__", lambda self: interact(self).__await__())
    monkeypatch.setattr(
        ui.dialog, "submit", lambda self, value: submitted.append(value)
    )

    async def open_dialog():
        with container:
            return await choose_catalog_sources(
                SimpleNamespace(scan=lambda **_: {"items": rows}), ["first", "second"]
            )

    result = asyncio.run(open_dialog())
    assert result == ["second"]
