"""Focused title entry uses the real edit/cache services without paid requests."""

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter

from aletheia_nexus.workbench import ui_title_translation as module
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.settings import SettingsStore, atomic_json
from aletheia_nexus.workbench.translation import TranslationService, translation_options


class Context:
    def checkpoint(self):
        pass

    def progress(self, *args, **kwargs):
        pass

    def record(self, *args, **kwargs):
        pass


@pytest.fixture
def controller(tmp_path):
    library = LibraryService(tmp_path / "library")
    papers = []
    for index in range(3):
        source = tmp_path / f"incoming-{index}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200 + index, height=200)
        writer.add_metadata({"/Title": f"Fixture title {index}"})
        with source.open("wb") as handle:
            writer.write(handle)
        papers.append(library.import_pdf(source, title=f"Fixture title {index}"))

    def forbidden(_):
        pytest.fail("Focused edit/cache tests must never send HTTP")

    translation = TranslationService(
        library, tmp_path / "workspace", transport=httpx.MockTransport(forbidden)
    )
    jobs, submitted = {}, []

    def submit(kind, label, ids, worker, parameters):
        job = {
            "id": str(len(submitted)),
            "kind": kind,
            "label": label,
            "status": "QUEUED",
        }
        jobs[job["id"]] = job
        submitted.append(
            {"ids": list(ids), "worker": worker, "parameters": deepcopy(parameters)}
        )
        return job

    return SimpleNamespace(
        ctx=SimpleNamespace(
            library=library,
            translation=translation,
            settings=SettingsStore(tmp_path / "workspace"),
            jobs=SimpleNamespace(get=lambda key: deepcopy(jobs[key])),
        ),
        submit=submit,
        task_dialog=lambda: None,
        papers=papers,
        submitted=submitted,
    )


def test_missing_scope_preserves_every_existing_and_manual_title(controller):
    library, service = controller.ctx.library, controller.ctx.translation
    a, b, c = [paper["id"] for paper in controller.papers]
    library.update_metadata(b, title_zh="既有模型译名", translation={"source": "model"})
    service.edit(c, "人工确认译名", confirmed=True)
    only_missing = module.title_translation_scope(library, [a, b, c, a])
    assert only_missing["eligible"] == [a]
    assert only_missing["existing"] == [b] and only_missing["protected"] == [c]
    reviewed = module.title_translation_scope(library, [a, b, c], only_missing=False)
    assert reviewed["eligible"] == [a, b] and reviewed["protected"] == [c]
    with pytest.raises(ValueError, match="勾选一篇或多篇"):
        module.title_translation_scope(library, [])


def render(controller, ids, monkeypatch):
    ui = pytest.importorskip("nicegui").ui
    actions = {}
    original_guard = module.guard

    def capture(callback):
        actions[callback.__name__] = callback
        return original_guard(callback)

    monkeypatch.setattr(module, "guard", capture)
    before = set(ui.context.client.elements)
    dialog = module.render_title_translation_dialog(controller, ids)
    elements = [
        value for key, value in dialog.client.elements.items() if key not in before
    ]
    return dialog, elements, actions


def run_action(dialog, callback):
    async def run():
        with dialog:
            await callback()

    asyncio.run(run())


def test_single_manual_title_save_preserves_original_pdf_and_source(
    controller, monkeypatch
):
    ui = pytest.importorskip("nicegui").ui
    paper = controller.papers[0]
    paths = [Path(paper["pdf_path"]), Path(paper["sidecar_path"])]
    before = [path.read_bytes() for path in paths]
    dialog, elements, actions = render(controller, [paper["id"]], monkeypatch)
    try:
        text = next(
            item
            for item in elements
            if isinstance(item, ui.textarea) and item.label == "中文标题"
        )
        confirmed = next(
            item
            for item in elements
            if isinstance(item, ui.checkbox) and item.text == "我已核对并确认此译名"
        )
        text.set_value("保留 Cu(I) 与 CO₂ 的人工中文标题")
        confirmed.set_value(True)
        run_action(dialog, actions["save_manual"])
        current = controller.ctx.library.get(paper["id"])
        assert current["title_original"] == "Fixture title 0"
        assert current["title_zh"] == "保留 Cu(I) 与 CO₂ 的人工中文标题"
        assert (
            current["translation"]["source"] == "manual"
            and current["translation"]["confirmed"] is True
        )
        assert [path.read_bytes() for path in paths] == before
        assert not controller.submitted
    finally:
        dialog.delete()


def test_batch_defaults_to_missing_only_and_reuses_actual_cache_without_consent(
    controller, monkeypatch
):
    library, service = controller.ctx.library, controller.ctx.translation
    a, b, c = [paper["id"] for paper in controller.papers]
    library.update_metadata(
        b, title_zh="保留未确认译名", translation={"source": "model"}
    )
    service.edit(c, "保留人工译名", confirmed=True)
    configuration = translation_options()
    key = service._key("Fixture title 0", configuration)
    atomic_json(
        service.directory / "cache" / (key + ".json"),
        {
            "cache_key": key,
            "original": "Fixture title 0",
            "title": "缓存中文标题",
            "model": configuration["model"]["name"],
            "target_language": "zh-CN",
        },
    )
    paths = [
        Path(paper[field])
        for paper in controller.papers
        for field in ("pdf_path", "sidecar_path")
    ]
    before = [path.read_bytes() for path in paths]
    dialog, _, actions = render(controller, [a, b, c], monkeypatch)
    try:
        with dialog:
            actions["submit"]()
        assert controller.submitted[0]["ids"] == [a]
        assert controller.submitted[0]["parameters"]["title_entry"] == "focused"
        report = controller.submitted[0]["worker"](Context())
        assert report["status"] == "COMPLETED" and report["calls"] == []
        assert report["items"][0]["status"] == "CACHED"
        assert library.get(a)["title_zh"] == "缓存中文标题"
        assert library.get(b)["title_zh"] == "保留未确认译名"
        assert library.get(c)["title_zh"] == "保留人工译名"
        assert [path.read_bytes() for path in paths] == before
    finally:
        dialog.delete()


def test_manual_title_save_does_not_depend_on_valid_model_budget(
    controller, monkeypatch
):
    ui = pytest.importorskip("nicegui").ui
    paper = controller.papers[0]
    dialog, elements, actions = render(controller, [paper["id"]], monkeypatch)
    try:
        text = next(
            e for e in elements if isinstance(e, ui.textarea) and e.label == "中文标题"
        )
        cost = next(
            e
            for e in elements
            if isinstance(e, ui.number) and e.label.startswith("本次费用上限")
        )
        text.set_value("无需模型的人工标题")
        cost.set_value(-1)
        run_action(dialog, actions["save_manual"])
        assert (
            controller.ctx.library.get(paper["id"])["title_zh"] == "无需模型的人工标题"
        )
        assert not controller.submitted
    finally:
        dialog.delete()


def test_new_naming_default_prefers_saved_chinese_and_falls_back_without_charges(
    controller,
):
    from aletheia_nexus.workbench.defaults import ui_workflow_defaults

    library, service = controller.ctx.library, controller.ctx.translation
    paper = controller.papers[0]
    library.update_metadata(paper["id"], year=2026, journal="Fixture journal")
    template = ui_workflow_defaults()["template"]
    before = Path(paper["pdf_path"]).read_bytes()
    fallback = library.preview_rename([paper["id"]], template)
    assert (
        fallback["items"][0]["new_name"] == "2026-Fixture journal-Fixture title 0.pdf"
    )
    service.edit(paper["id"], "人工中文标题", confirmed=True)
    chinese = library.preview_rename([paper["id"]], template)
    assert chinese["items"][0]["new_name"] == "2026-Fixture journal-人工中文标题.pdf"
    assert Path(paper["pdf_path"]).read_bytes() == before
    assert not controller.submitted


def test_remote_title_requires_consent_and_queued_manual_edit_wins(
    controller, monkeypatch
):
    ui = pytest.importorskip("nicegui").ui
    paper = controller.papers[0]
    dialog, elements, actions = render(controller, [paper["id"]], monkeypatch)
    try:
        with dialog, pytest.raises(ValueError, match="本次授权"):
            actions["submit"]()
        assert not controller.submitted
        consent = next(
            item
            for item in elements
            if isinstance(item, ui.checkbox) and item.text.startswith("我授权仅将")
        )
        consent.set_value(True)
        with dialog:
            actions["submit"]()
        assert consent.value is False
        controller.ctx.translation.edit(paper["id"], "排队时人工补充", confirmed=False)
        report = controller.submitted[0]["worker"](Context())
        assert report["status"] == "COMPLETED" and not report["calls"]
        assert controller.ctx.library.get(paper["id"])["title_zh"] == "排队时人工补充"
    finally:
        dialog.delete()
