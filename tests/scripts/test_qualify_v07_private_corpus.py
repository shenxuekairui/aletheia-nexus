import json
from pathlib import Path

import pytest

from scripts import qualify_v07_private_corpus as qualifier


@pytest.mark.parametrize("case", ["empty", "missing-sidecar", "changed-hash"])
def test_incomplete_corpus_cannot_pass_qualification(tmp_path, case):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    args = [
        str(inputs),
        str(tmp_path / "parsed"),
        "--report",
        str(tmp_path / "report.json"),
    ]
    if case == "missing-sidecar":
        (inputs / "article.pdf").write_bytes(b"%PDF-placeholder")
    elif case == "changed-hash":
        fixture = (
            Path(__file__).resolve().parents[2]
            / "benchmarks/v07_fixtures/native_article.pdf"
        )
        cohort = tmp_path / "cohort.json"
        cohort.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "pdf": str(fixture),
                            "sidecar": str(fixture.with_suffix(".acquisition.json")),
                            "pdf_sha256": "0" * 64,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        args += ["--cohort", str(cohort)]
    assert qualifier.main(args) == 1
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert len(report["records"]) == report["input_count"]
    if case != "empty":
        assert report["status_counts"] == {"RUNNER_ERROR": 1}
