import json

import pytest

from aletheia_nexus.acquire.fulltext.storage import write_json_sidecar


def test_sidecar_partial_file_is_cleaned_if_serialization_fails(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")

    with pytest.raises(TypeError):
        write_json_sidecar(pdf, {"not_json": object()})

    sidecar = pdf.with_suffix(".acquisition.json")
    partial = sidecar.with_suffix(sidecar.suffix + ".part")
    assert not sidecar.exists()
    assert not partial.exists()


def test_sidecar_is_valid_json_and_replaces_atomically(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")

    path = write_json_sidecar(pdf, {"status": "VERIFIED", "attempts": 1})

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "attempts": 1,
        "status": "VERIFIED",
    }
    assert not path.with_suffix(path.suffix + ".part").exists()
