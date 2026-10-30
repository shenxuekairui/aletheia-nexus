"""Automatic parsing uses the exact local defaults reviewed before submission."""

import runpy
from copy import deepcopy
from pathlib import Path

import pytest

pytest.importorskip("nicegui")

from aletheia_nexus.workbench.research import WorkbenchResearch
from aletheia_nexus.workbench.settings import SettingsStore
from aletheia_nexus.workbench.ui_acquisition import acquisition_postprocess_snapshot


def test_automatic_parsing_keeps_submission_snapshot_after_defaults_change(tmp_path):
    fixture = runpy.run_path(str(Path(__file__).with_name("test_ui_workflows.py")))
    page, *_ = fixture["setup_workflow"](tmp_path)
    settings = SettingsStore(tmp_path / "settings")
    settings.set(
        "parsing",
        {"ocr": True, "ocr_languages": "eng+chi_sim", "ocr_dpi": 240, "max_pages": 2},
    )
    snapshot = acquisition_postprocess_snapshot(
        {"auto_parse": True},
        WorkbenchResearch.parser_options(),
        settings.get("parsing"),
    )
    captured = []

    def parse(ids, *, options=None, **kwargs):
        captured.append(deepcopy(options))
        return {"status": "COMPLETED", "items": []}

    page.ctx.settings = settings
    page.ctx.research.parse = parse
    worker = page.acquisition_worker([], {"include_si": True}, snapshot)
    settings.set("parsing", {"ocr": False, "ocr_languages": "eng", "max_pages": 40})
    snapshot["parse_options"]["max_pages"] = 99
    worker(fixture["Context"]())
    assert captured[0]["ocr"] is True
    assert captured[0]["ocr_languages"] == "eng+chi_sim"
    assert captured[0]["ocr_dpi"] == 240 and captured[0]["max_pages"] == 2


def test_legacy_worker_never_reads_current_global_parsing_settings(tmp_path):
    fixture = runpy.run_path(str(Path(__file__).with_name("test_ui_workflows.py")))
    page, *_ = fixture["setup_workflow"](tmp_path)

    class NoSettings:
        def get(self, *args):
            pytest.fail("worker must not read global settings at execution time")

    page.ctx.settings = NoSettings()
    captured = []
    page.ctx.research.parse = lambda ids, *, options=None, **kwargs: (
        captured.append(options) or {"status": "COMPLETED", "items": []}
    )
    report = page.acquisition_worker([], {"include_si": False}, {"auto_parse": True})(
        fixture["Context"]()
    )
    assert captured == [None]
    assert any("历史任务未记录解析配置" in message for message in report["warnings"])
