from pathlib import Path
from threading import Event
from types import SimpleNamespace

from pypdf import PdfWriter

from aletheia_nexus.content.gate import sha256_file
from aletheia_nexus.workbench.jobs import TaskManager
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage
from aletheia_nexus.workbench.ui_library import LibraryPage


class Page(LibraryPage, AcquisitionPage):
    pass


def pdf(path, title):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.add_metadata({"/Title": title})
    with path.open("wb") as output:
        writer.write(output)
    return path


def test_skip_during_one_import_skips_exactly_next_file_and_excludes_translation(
    tmp_path, monkeypatch
):
    library = LibraryService(tmp_path / "library")
    paths = [
        pdf(tmp_path / (name + ".pdf"), name) for name in ("first", "second", "third")
    ]
    before = {path: sha256_file(path) for path in paths}
    started, release = Event(), Event()
    actual_import = library.import_pdf

    def import_file(path, **options):
        if Path(path) == paths[0]:
            started.set()
            assert release.wait(5)
        return actual_import(path, **options)

    monkeypatch.setattr(library, "import_pdf", import_file)
    translated = []

    def translate(ids, options, *, consent, context):
        assert consent
        translated.extend(ids)
        return {"status": "COMPLETED", "calls": []}

    page = Page()
    page.ctx = SimpleNamespace(
        library=library, translation=SimpleNamespace(translate=translate)
    )
    manager = TaskManager(tmp_path / "workspace")
    try:
        job = manager.submit(
            "import",
            "three files",
            paths,
            page.import_worker(
                paths, folder="category", translation={"enabled": True, "consent": True}
            ),
        )
        assert started.wait(3)
        manager.control(job["id"], "skip")
        # The in-flight file is indivisible; skipping applies to the next one.
        release.set()
        manager._futures[job["id"]].result(timeout=10)
        receipt = manager.get(job["id"])
        assert receipt["status"] == "PARTIAL"
        assert [row["status"] for row in receipt["result"]["items"]] == [
            "REGISTERED",
            "SKIPPED",
            "REGISTERED",
        ]
        assert [
            row["item_id"] for row in receipt["records"] if row["status"] == "SKIPPED"
        ] == [str(paths[1])]
        rows = library.scan()["items"]
        assert {row["title_original"] for row in rows} == {"first", "third"}
        assert set(translated) == {row["id"] for row in rows}
        assert not (library.root / "category/second.pdf").exists()
        assert all(
            path.is_file() and sha256_file(path) == before[path] for path in paths
        )
    finally:
        release.set()
        manager.close(wait=True)


def test_queued_attachment_import_consumes_skip_before_creating_any_file(
    tmp_path, monkeypatch
):
    library = LibraryService(tmp_path / "library")
    parent = library.import_pdf(pdf(tmp_path / "main.pdf", "Parent"), title="Parent")
    source = pdf(tmp_path / "si.pdf", "Supplement")
    page = Page()
    page.ctx = SimpleNamespace(library=library)
    manager = TaskManager(tmp_path / "workspace", max_workers=1)
    blocking, release = Event(), Event()

    def blocker(context):
        blocking.set()
        assert release.wait(5)
        return {"status": "COMPLETED"}

    monkeypatch.setattr(
        library,
        "import_attachment",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("A skipped attachment must not be imported")
        ),
    )
    try:
        manager.submit("metadata", "hold worker", [], blocker)
        assert blocking.wait(3)
        job = manager.submit(
            "import",
            "local SI",
            [parent["id"]],
            page.attachment_import_worker(parent["id"], source),
        )
        manager.control(job["id"], "skip")
        release.set()
        manager._futures[job["id"]].result(timeout=10)
        receipt = manager.get(job["id"])
        assert receipt["status"] == "PARTIAL"
        assert receipt["result"]["items"][0]["status"] == "SKIPPED"
        assert library.get(parent["id"])["attachments"] == []
        assert source.is_file()
    finally:
        release.set()
        manager.close(wait=True)


def test_late_file_skip_never_becomes_post_import_title_batch_skip(tmp_path):
    library = LibraryService(tmp_path / "library")
    source = pdf(tmp_path / "main.pdf", "Main")
    entered, release = Event(), Event()
    observed = []

    def translate(ids, options, *, consent, context):
        entered.set()
        assert release.wait(5)
        observed.append(context.should_skip("title_batch"))
        return {"status": "COMPLETED", "calls": []}

    page = Page()
    page.ctx = SimpleNamespace(
        library=library, translation=SimpleNamespace(translate=translate)
    )
    manager = TaskManager(tmp_path / "workspace")
    try:
        job = manager.submit(
            "import",
            "import plus title step",
            [source],
            page.import_worker(
                [source], translation={"enabled": True, "consent": True}
            ),
        )
        assert entered.wait(3)
        assert manager.get(job["id"])["import_phase"] == "postprocess"
        # The UI hides this action now; a late/direct request is still scoped to files.
        manager.control(job["id"], "skip")
        release.set()
        manager._futures[job["id"]].result(timeout=10)
        receipt = manager.get(job["id"])
        assert receipt["status"] == "COMPLETED"
        assert observed == [False]
        assert "文件阶段已结束" in receipt["import_skip_notice"]
        assert not any(row["status"] == "SKIPPED" for row in receipt["records"])
    finally:
        release.set()
        manager.close(wait=True)
