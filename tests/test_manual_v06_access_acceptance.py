import json

from scripts.manual_v06_access_acceptance import (
    _freeze_gate,
    _load_cases,
)


def test_v06_acceptance_normalizes_and_deduplicates_dois(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps(
            [
                {
                    "doi": "https://doi.org/10.1000/Test",
                    "title": "Example",
                    "id": "A",
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = _load_cases(
        [benchmark],
        [],
        ["DOI: 10.1000/test"],
        ["10.1000/TEST"],
    )

    assert len(cases) == 1
    assert cases[0]["doi"] == "10.1000/test"
    assert cases[0]["stress_case"] is True
    assert cases[0]["entitled_control"] is True


def test_v06_acceptance_adds_entitled_control_not_in_stress_corpus(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("[]", encoding="utf-8")

    cases = _load_cases(
        [benchmark],
        [],
        [],
        ["https://doi.org/10.1000/entitled"],
    )

    assert len(cases) == 1
    assert cases[0]["doi"] == "10.1000/entitled"
    assert cases[0]["stress_case"] is False
    assert cases[0]["entitled_control"] is True


def test_v06_freeze_gate_requires_all_entitled_controls_to_verify():
    code, message = _freeze_gate(
        entitled_controls=3,
        entitled_verified=2,
        require_entitled_controls=True,
    )
    assert code == 2
    assert "not VERIFIED" in message


def test_v06_freeze_gate_can_require_positive_controls():
    code, message = _freeze_gate(
        entitled_controls=0,
        entitled_verified=0,
        require_entitled_controls=True,
    )
    assert code == 3
    assert "no entitled positive controls" in message
