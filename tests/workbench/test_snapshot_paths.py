from pathlib import Path

import pytest

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.research_app import _snapshot_paths


def test_long_windows_snapshot_uses_short_locator_and_keeps_full_sidecar_hash():
    workspace = Path("C:/") / ("project" * 11) / "workbench-state/research-workspace"
    pdf_hash, sidecar_hash = "a" * 64, "b" * 64
    original = (
        workspace
        / "materials"
        / pdf_hash
        / "json"
        / (sidecar_hash + ".acquisition.json")
    )
    assert len(str(original)) >= 240
    pdf, sidecar = _snapshot_paths(workspace, pdf_hash, sidecar_hash, windows=True)
    assert len(str(sidecar)) < 240
    assert sidecar.name == sidecar_hash + ".acquisition.json"
    assert pdf.parent == sidecar.parent.parent


def test_short_or_non_windows_snapshot_preserves_existing_layout():
    workspace = Path("root")
    for windows in (True, False):
        pdf, sidecar = _snapshot_paths(workspace, "a" * 64, "b" * 64, windows=windows)
        assert pdf == workspace / "materials" / ("a" * 64) / "paper.pdf"
        assert sidecar.parent == pdf.parent / "json"


def test_excessively_long_workspace_has_specific_error_before_copy():
    with pytest.raises(ProcessingError, match="workspace_path_too_long"):
        _snapshot_paths(Path("root") / ("x" * 200), "a" * 64, "b" * 64, windows=True)
