import json

from scripts.manual_v06_access_acceptance import _load_cases


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
        ["DOI: 10.1000/test"],
        ["10.1000/TEST"],
    )

    assert len(cases) == 1
    assert cases[0]["doi"] == "10.1000/test"
    assert cases[0]["entitled_control"] is True


def test_v06_acceptance_adds_entitled_control_not_in_benchmark(tmp_path):
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("[]", encoding="utf-8")

    cases = _load_cases(
        [benchmark],
        [],
        ["https://doi.org/10.1000/entitled"],
    )

    assert cases == [
        {
            "doi": "10.1000/entitled",
            "title": None,
            "id": "10.1000/entitled",
            "entitled_control": True,
        }
    ]
