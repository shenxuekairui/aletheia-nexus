import json

from scripts import manual_v06_access_acceptance as acceptance


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_acceptance_cases_merge_stress_and_entitled_controls(tmp_path):
    stress = _write(
        tmp_path / "stress.json",
        [
            {
                "id": "stress-one",
                "doi": "10.1000/ABC",
                "title": "Stress title",
            }
        ],
    )
    entitled = _write(
        tmp_path / "entitled.json",
        [
            {
                "id": "entitled-one",
                "doi": "10.1000/abc",
                "title": "Confirmed title",
            },
            {
                "id": "entitled-two",
                "doi": "10.1000/xyz",
                "title": "Second title",
            },
        ],
    )

    cases = acceptance._load_cases(
        [stress],
        [entitled],
        [],
        [],
    )

    assert [case["doi"] for case in cases] == ["10.1000/abc", "10.1000/xyz"]
    first = cases[0]
    assert first["stress_case"] is True
    assert first["entitled_control"] is True
    assert first["title"] == "Stress title"
    assert first["sources"] == [str(stress), str(entitled)]


def test_entitled_doi_promotes_existing_stress_case(tmp_path):
    stress = _write(
        tmp_path / "stress.json",
        [{"doi": "10.1000/target", "title": "Target"}],
    )

    cases = acceptance._load_cases(
        [stress],
        [],
        [],
        ["https://doi.org/10.1000/TARGET"],
    )

    assert len(cases) == 1
    assert cases[0]["entitled_control"] is True
    assert cases[0]["stress_case"] is True


def test_freeze_gate_requires_all_entitled_controls_to_verify():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=2,
        require_entitled_controls=True,
    )

    assert code == 2
    assert "1 manually confirmed entitled control" in message


def test_freeze_gate_can_require_nonempty_positive_controls():
    code, message = acceptance._freeze_gate(
        entitled_controls=0,
        entitled_verified=0,
        require_entitled_controls=True,
    )

    assert code == 3
    assert message == "no entitled positive controls were supplied."


def test_freeze_gate_passes_only_when_access_ceiling_is_met():
    code, message = acceptance._freeze_gate(
        entitled_controls=4,
        entitled_verified=4,
        require_entitled_controls=True,
    )

    assert code == 0
    assert message is None



def test_freeze_gate_rejects_runner_errors():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=3,
        require_entitled_controls=True,
        runner_errors=1,
    )

    assert code == 4
    assert "unexpected runner errors" in message


def test_runner_error_record_does_not_persist_exception_message():
    case = {
        "id": "case-one",
        "stress_case": True,
        "entitled_control": False,
        "sources": ["benchmark.json"],
    }
    record = acceptance._runner_error_record(
        doi="10.1000/target",
        case=case,
        exc=RuntimeError(
            "failed at https://publisher.example/pdf?token=super-secret"
        ),
    )

    serialized = json.dumps(record)
    assert record["status"] == "RUNNER_ERROR"
    assert record["runner_error_type"] == "RuntimeError"
    assert "super-secret" not in serialized
    assert "publisher.example" not in serialized
