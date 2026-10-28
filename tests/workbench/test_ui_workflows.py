"""UI orchestration still uses real file operations and independent title calls."""

import runpy
from pathlib import Path
from types import SimpleNamespace

from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.ui_acquisition import AcquisitionPage


class Context:
    def __init__(self):
        self.updates = []

    def checkpoint(self):
        pass

    def progress(self, *args, **values):
        self.updates.append(values)

    def record(self, *args, **values):
        pass


def setup_workflow(tmp_path):
    write_pdf = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/generate_v07_fixtures.py")
    )["_write_pdf"]
    source = tmp_path / "incoming.pdf"
    write_pdf(
        source, [[(50, 700, 12, "Self-authored experiment")]], title="Alpha catalysis"
    )
    library = LibraryService(tmp_path / "library")
    paper = library.import_pdf(source, title="Alpha catalysis", folder="original")
    library.update_metadata(paper["id"], year=2026, journal="Fixture journal")
    si = tmp_path / "data.csv"
    si.write_text("name,value\na,1\n", encoding="utf-8")
    attachment = library.import_attachment(paper["id"], si)

    class Acquisition:
        def run(self, requests, options, **kwargs):
            return {
                "status": "COMPLETED",
                "checkpoint": "fixture-checkpoint",
                "items": [
                    {
                        "status": "VERIFIED",
                        "pdf": paper["pdf_path"],
                        "sidecar": paper["sidecar_path"],
                        "request": {"filename": None},
                        "supplements": {
                            "items": [
                                {
                                    "path": attachment["path"],
                                    "sha256": attachment["sha256"],
                                    "role": "SUPPLEMENT",
                                }
                            ]
                        },
                    }
                ],
            }

    class Translation:
        calls = 0

        def translate(self, ids, options, *, consent, context):
            assert consent
            self.calls += 1
            assert ids == [paper["id"]]
            library.update_metadata(
                paper["id"], title_zh="催化测试", translation={"source": "model"}
            )
            return {"status": "COMPLETED", "calls": [], "billing_uncertain": False}

    class Research:
        def parse(self, ids, **kwargs):
            return {"status": "PARTIAL", "items": [{"status": "PARTIAL"}]}

    page = AcquisitionPage()
    translation = Translation()
    page.ctx = SimpleNamespace(
        library=library,
        acquisition=Acquisition(),
        translation=translation,
        research=Research(),
    )
    return page, paper, attachment, translation


def test_download_metadata_then_translate_then_rename_main_and_si(tmp_path):
    page, paper, attachment, translation = setup_workflow(tmp_path)
    content = Path(paper["pdf_path"]).read_bytes()
    si_content = Path(attachment["path"]).read_bytes()
    worker = page.acquisition_worker(
        [],
        {"include_si": True},
        {
            "template": "{year}-{journal}-{title_zh}",
            "auto_parse": True,
            "collection": "验收集合",
            "title_translation": {
                "enabled": True,
                "consent": True,
                "options": {"max_cost": 1},
            },
        },
    )
    report = worker(Context())
    current = page.ctx.library.get(paper["id"])
    assert Path(current["pdf_path"]).name == "2026-Fixture journal-催化测试.pdf"
    assert Path(current["pdf_path"]).read_bytes() == content
    assert Path(current["attachments"][0]["path"]).read_bytes() == si_content
    assert report["status"] == "PARTIAL"  # main succeeded, parsing was partial
    assert report["items"][0]["pdf"] == current["pdf_path"]
    assert (
        report["items"][0]["supplements"]["items"][0]["path"]
        == current["attachments"][0]["path"]
    )
    assert report["translation"]["status"] == "COMPLETED" and translation.calls == 1
    assert page.ctx.library.collections()["验收集合"] == [paper["id"]]


def test_automatic_translation_is_opt_in_and_failure_keeps_acquired_main(tmp_path):
    page, paper, _, translation = setup_workflow(tmp_path)
    assert (
        page.acquisition_worker([], {"include_si": False}, {})(Context())["status"]
        == "COMPLETED"
    )
    assert translation.calls == 0

    def failed(*args, **kwargs):
        from aletheia_nexus.processing.provider import ProcessingError

        raise ProcessingError("missing_api_key")

    translation.translate = failed
    result = page.acquisition_worker(
        [],
        {"include_si": False},
        {
            "title_translation": {
                "enabled": True,
                "consent": True,
                "options": {"max_cost": 1},
            }
        },
    )(Context())
    assert result["status"] == "PARTIAL"
    assert result["translation"]["status"] == "FAILED"
    assert result["items"][0]["status"] == "VERIFIED"
    assert Path(page.ctx.library.get(paper["id"])["pdf_path"]).is_file()
