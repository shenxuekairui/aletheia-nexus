"""Readable version labels must never substitute the actual material/artifact IDs."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_research import research as research_fixture


@pytest.fixture(name="research")
def source_fixture(tmp_path):
    yield from research_fixture.__wrapped__(tmp_path)


def test_version_projection_has_gated_title_and_role_without_changing_identity(
    research,
):
    research.parse(["p1"])
    material = research.versions("p1")[0]
    assert material["title"] == "Alpha catalysis"
    assert material["document_role"] == "ARTICLE"
    assert material["id"] == "p1"
    document = material["versions"][0]["document"]
    assert material["active_artifact"] == document["artifact"]
    assert document["id"] == material["id"]
    pdf = Path(research.library.get("p1")["pdf_path"])
    pdf.write_bytes(pdf.read_bytes() + b" changed after the trusted version")
    with pytest.raises((ValueError, RuntimeError)):
        research.versions("p1")


def test_version_widgets_show_actual_title_role_date_status_but_switch_exact_ids(
    tmp_path, monkeypatch
):
    pytest.importorskip("nicegui")
    from nicegui import ui

    from aletheia_nexus.workbench import ui_research
    from aletheia_nexus.workbench.labels import value_label
    from aletheia_nexus.workbench.research import WorkbenchResearch
    from aletheia_nexus.workbench.settings import SettingsStore

    materials = [
        {
            "id": "paper_actual_identity",
            "title": "Actual original paper title",
            "document_role": "ARTICLE",
            "active_artifact": "main-v1.parsed.json",
            "versions": [
                {
                    "document": {
                        "id": "paper_actual_identity",
                        "artifact": "main-v1.parsed.json",
                    },
                    "created_at": "2026-10-29T00:00:00Z",
                    "status": "PARSED",
                }
            ],
        },
        {
            "id": "attachment_actual_identity",
            "title": "Actual supplemental title",
            "document_role": "SUPPLEMENT",
            "active_artifact": "si-v1.parsed.json",
            "versions": [
                {
                    "document": {
                        "id": "attachment_actual_identity",
                        "artifact": "si-v1.parsed.json",
                    },
                    "created_at": "2026-10-29T00:01:00Z",
                    "status": "PARTIAL",
                }
            ],
        },
    ]
    switched = []

    class Controller(ui_research.ResearchPages):
        pass

    controller = Controller()
    controller.ctx = SimpleNamespace(
        settings=SettingsStore(tmp_path),
        research=SimpleNamespace(
            parser_options=WorkbenchResearch.parser_options,
            versions=lambda paper_id, **kwargs: materials,
            select_version=lambda *args, **kwargs: switched.append((args, kwargs)),
        ),
    )
    monkeypatch.setattr(ui_research, "guard", lambda callback: callback)
    monkeypatch.setattr(ui, "notify", lambda *_args, **_kwargs: None)
    before = set(ui.context.client.elements)
    controller.parse_dialog(["paper_actual_identity"])
    elements = [
        element
        for key, element in ui.context.client.elements.items()
        if key not in before
    ]
    texts = [getattr(element, "text", "") for element in elements]
    main = next(
        text for text in texts if text.startswith("Actual original paper title")
    )
    supplement = next(
        text for text in texts if text.startswith("Actual supplemental title")
    )
    assert "正文" in main and "2026-10-29T00:00:00Z" in main
    assert value_label("PARSED") in main and "当前版本" in main
    assert "补充信息（SI）" in supplement and value_label("PARTIAL") in supplement
    assert (
        "paper_actual_identity" not in main
        and "attachment_actual_identity" not in supplement
    )
    buttons = [
        element
        for element in elements
        if getattr(element, "text", "") == "使用此解析版本"
    ]
    for button in buttons:
        callback = next(
            listener.handler
            for listener in button._event_listeners.values()
            if listener.type == "click"
        )
        callback(None)
    assert switched == [
        (
            ("paper_actual_identity", "main-v1.parsed.json"),
            {"material_id": "paper_actual_identity"},
        ),
        (
            ("paper_actual_identity", "si-v1.parsed.json"),
            {"material_id": "attachment_actual_identity"},
        ),
    ]
