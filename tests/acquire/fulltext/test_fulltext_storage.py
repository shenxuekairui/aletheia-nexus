import hashlib
import json
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.fulltext.models import RetrievedResource
from aletheia_nexus.acquire.fulltext.storage import (
    is_verified_record,
    organized_output,
    output_metadata,
    promote_resource,
    write_json_sidecar,
)
from aletheia_nexus.core.paper_request import PaperRequest


def _promote(tmp_path, *, doi="10.1000/target", **kwargs):
    temporary = tmp_path / "download.part"
    body = b"test resource"
    temporary.write_bytes(body)
    return promote_resource(
        RetrievedResource(
            "",
            "",
            200,
            "application/pdf",
            len(body),
            hashlib.sha256(body).hexdigest(),
            temporary,
        ),
        doi=doi,
        output_dir=tmp_path / "out",
        **kwargs,
    )[0]


@pytest.mark.parametrize(
    "year,journal,title,prefix",
    [
        (2024, "化学试剂", "论文标题", "2024-化学试剂-论文标题--"),
        (None, "化学试剂", "论文标题", "化学试剂-论文标题--"),
        (2024, None, "论文标题", "2024-论文标题--"),
        (None, None, "论文标题", "论文标题--"),
        (2024, "A/B: Journal", "What? <Paper>", "2024-A_B_ Journal-What_ _Paper_--"),
        (2024, "化学试剂", None, "2024-化学试剂-10.1000_target--"),
        (None, None, None, "10.1000_target-"),
    ],
)
def test_default_filename_order_without_classification(
    tmp_path, year, journal, title, prefix
):
    path = _promote(tmp_path, year=year, journal=journal, title=title)
    assert path.name.startswith(prefix)
    assert path.suffix == ".pdf"


def test_input_bibliography_and_custom_name_take_precedence(tmp_path):
    request = PaperRequest(
        doi="10.1000/target", title="论文标题", year=2024, journal="化学试剂"
    )
    with organized_output(request):
        path = _promote(tmp_path, year=2023, journal="Other journal")
    assert path.name.startswith("2024-化学试剂-论文标题--")
    with organized_output(PaperRequest(doi=request.doi, filename="我的命名.pdf")):
        custom = _promote(tmp_path, year=2024, journal="化学试剂", title="论文标题")
    assert custom.name.startswith("我的命名--")


def test_resolved_metadata_is_scoped_and_bound_to_doi(tmp_path):
    metadata = SimpleNamespace(doi="10.1000/target", year=2024, journal="化学试剂")
    with output_metadata(metadata):
        path = _promote(tmp_path, title="论文标题")
        wrong_doi = _promote(tmp_path, doi="10.1000/other", title="Other paper")
        with output_metadata(None):
            nested = _promote(tmp_path, title="Nested paper")
        restored = _promote(tmp_path, title="Restored paper")
    subsequent = _promote(tmp_path, title="Subsequent paper")
    assert path.name.startswith("2024-化学试剂-论文标题--")
    assert wrong_doi.name.startswith("Other paper--")
    assert nested.name.startswith("Nested paper--")
    assert restored.name.startswith("2024-化学试剂-Restored paper--")
    assert subsequent.name.startswith("Subsequent paper--")


def test_observed_publication_fields_are_recorded_in_organization(tmp_path):
    with organized_output(PaperRequest(title="论文标题", folder="化学")):
        path = _promote(
            tmp_path, doi="cnki:cjfd:example", year=2024, journal="化学试剂"
        )
        record = write_json_sidecar(
            path,
            {"target": {"doi": None, "expected_title": "论文标题"}},
            year=2024,
            journal="化学试剂",
        )
    organization = json.loads(record.read_text(encoding="utf-8"))["organization"]
    assert path.name.startswith("2024-化学试剂-论文标题--")
    assert organization["filename"] == path.name
    assert organization["year"] == 2024 and organization["journal"] == "化学试剂"


def test_sidecar_partial_file_is_cleaned_if_serialization_fails(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")

    with pytest.raises(TypeError):
        write_json_sidecar(pdf, {"not_json": object()})

    sidecar = tmp_path / "json" / "paper.acquisition.json"
    assert not sidecar.exists()
    assert not list(tmp_path.rglob("*.part"))


def test_sidecar_is_valid_json_and_replaces_atomically(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")

    path = write_json_sidecar(pdf, {"status": "VERIFIED", "attempts": 1})

    assert path == tmp_path / "json" / "paper.acquisition.json"
    assert not pdf.with_suffix(".acquisition.json").exists()
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "attempts": 1,
        "status": "VERIFIED",
    }
    assert not path.with_suffix(path.suffix + ".part").exists()


def test_sidecar_write_never_truncates_a_preexisting_partial_file(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    (tmp_path / "json").mkdir()
    partial = tmp_path / "json" / "paper.acquisition.json.part"
    partial.write_bytes(b"another writer owns this")
    write_json_sidecar(pdf, {"status": "VERIFIED"})
    assert partial.read_bytes() == b"another writer owns this"


@pytest.mark.parametrize("payload", [None, [], {"schema": []}, {"status": "VERIFIED"}])
def test_incomplete_records_are_never_verified(payload):
    assert not is_verified_record(payload)


@pytest.mark.parametrize("layout", ["legacy", "json"])
def test_conflicting_existing_provenance_is_preserved(tmp_path, layout):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"fixture")
    directory = tmp_path / "json" if layout == "json" else tmp_path
    directory.mkdir(exist_ok=True)
    sidecar = directory / "paper.acquisition.json"
    original = b'{"status":"MISMATCH"}'
    sidecar.write_bytes(original)
    with pytest.raises(FileExistsError):
        write_json_sidecar(pdf, {"status": "VERIFIED"}, preserve_existing=True)
    assert sidecar.read_bytes() == original
