import json

from aletheia_nexus.acquire.access.models import (
    MaximizedAcquisitionResult,
    MaximizedAcquisitionStatus,
)
from aletheia_nexus.acquire.discovery.models import (
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    ProviderDiscoveryResult,
    ProviderDiscoveryStatus,
)
from aletheia_nexus.acquire.fulltext.models import (
    AcquisitionResult,
    AcquisitionStatus,
)
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FileAttempt,
    FileCandidateOrigin,
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    RouteAttempt,
    RouteCandidateOrigin,
)
from aletheia_nexus.acquire.fulltext.resolution.models import (
    PageType,
    ResolutionStatus,
    RouteResolutionResult,
)
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
                "access_family": "publisher-a",
            },
            {
                "id": "entitled-two",
                "doi": "10.1000/xyz",
                "title": "Second title",
                "access_family": "publisher-b",
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
    assert first["access_family"] == "publisher-a"
    assert first["sources"] == ["stress.json", "entitled.json"]


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
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=3,
        require_entitled_controls=True,
    )

    assert code == 2
    assert "1 manually confirmed entitled control" in message


def test_freeze_gate_requires_three_positive_controls():
    code, message = acceptance._freeze_gate(
        entitled_controls=2,
        entitled_verified=2,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=2,
        require_entitled_controls=True,
    )

    assert code == 3
    assert "at least 3 entitled positive controls" in message


def test_freeze_gate_passes_only_when_access_ceiling_is_met():
    code, message = acceptance._freeze_gate(
        entitled_controls=4,
        entitled_verified=4,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=4,
        stress_cases=20,
        v06_only_recoveries=1,
        require_entitled_controls=True,
    )

    assert code == 0
    assert message is None


def test_freeze_gate_rejects_runner_errors():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=3,
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
        "access_family": None,
        "sources": ["benchmark.json"],
    }
    record = acceptance._runner_error_record(
        doi="10.1000/target",
        case=case,
        exc=RuntimeError("failed at https://publisher.example/pdf?token=super-secret"),
    )

    serialized = json.dumps(record)
    assert record["status"] == "RUNNER_ERROR"
    assert record["runner_error_type"] == "RuntimeError"
    assert "super-secret" not in serialized
    assert "publisher.example" not in serialized


def test_freeze_gate_requires_two_access_families():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a",),
        entitled_controls_with_family=3,
        require_entitled_controls=True,
    )

    assert code == 6
    assert "at least 2 distinct publisher/access families" in message


def test_conflicting_access_family_for_same_doi_is_rejected(tmp_path):
    first = _write(
        tmp_path / "first.json",
        [
            {
                "doi": "10.1000/target",
                "title": "Target",
                "access_family": "publisher-a",
            }
        ],
    )
    second = _write(
        tmp_path / "second.json",
        [
            {
                "doi": "10.1000/target",
                "title": "Target",
                "access_family": "publisher-b",
            }
        ],
    )

    try:
        acceptance._load_cases([], [first, second], [], [])
    except ValueError as exc:
        assert "Conflicting access_family values" in str(exc)
    else:
        raise AssertionError("conflicting access families must be rejected")


def test_freeze_gate_requires_family_on_every_control():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=2,
        require_entitled_controls=True,
    )

    assert code == 5
    assert "access_family on every entitled positive control" in message


def test_access_family_is_case_normalized(tmp_path):
    entitled = _write(
        tmp_path / "entitled.json",
        [
            {
                "doi": "10.1000/target",
                "title": "Target",
                "access_family": " Elsevier-ScienceDirect ",
            }
        ],
    )

    cases = acceptance._load_cases([], [entitled], [], [])

    assert cases[0]["access_family"] == "elsevier-sciencedirect"


def test_freeze_gate_requires_full_stress_corpus():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=3,
        stress_cases=19,
        v06_only_recoveries=1,
        require_entitled_controls=True,
    )

    assert code == 7
    assert "at least 20 stress cases" in message


def test_freeze_gate_requires_real_v06_only_recovery():
    code, message = acceptance._freeze_gate(
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=3,
        stress_cases=20,
        v06_only_recoveries=0,
        require_entitled_controls=True,
    )

    assert code == 8
    assert "at least one real v0.6-only recovery" in message


def test_report_distinguishes_entitled_controls_from_full_freeze_gate(tmp_path):
    config = acceptance.BrowserAccessConfig(profile_root=tmp_path)

    payload = acceptance._report_payload(
        records=[],
        stress_paths=[],
        entitled_paths=[],
        config=config,
        base_verified=0,
        verified=3,
        stress_base_verified=0,
        stress_verified=0,
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=3,
        stress_cases=19,
        v06_only_recoveries=0,
        elsevier_enabled=False,
        elsevier_recovered=0,
        browser_recovered=0,
        interaction_cases=0,
        runner_errors=0,
        final_statuses=acceptance.Counter(),
        challenge_kinds=acceptance.Counter(),
    )

    assert payload["summary"]["entitled_controls_passed"] is True
    assert payload["summary"]["freeze_gate_passed"] is False


def test_report_marks_full_freeze_gate_only_when_every_machine_gate_passes(tmp_path):
    config = acceptance.BrowserAccessConfig(profile_root=tmp_path)

    payload = acceptance._report_payload(
        records=[],
        stress_paths=[],
        entitled_paths=[],
        config=config,
        base_verified=6,
        verified=7,
        stress_base_verified=6,
        stress_verified=7,
        entitled_controls=3,
        entitled_verified=3,
        entitled_access_families=("publisher-a", "publisher-b"),
        entitled_controls_with_family=3,
        stress_cases=20,
        v06_only_recoveries=1,
        elsevier_enabled=True,
        elsevier_recovered=1,
        browser_recovered=0,
        interaction_cases=1,
        runner_errors=0,
        final_statuses=acceptance.Counter({"VERIFIED": 7}),
        challenge_kinds=acceptance.Counter({"SSO": 1}),
    )

    assert payload["summary"]["entitled_controls_passed"] is True
    assert payload["summary"]["freeze_gate_passed"] is True
    assert payload["summary"]["v0.6_only_recoveries"] == 1
    assert payload["summary"]["stress_uplift_count"] == 1
    assert payload["summary"]["stress_v0.5_verified_rate"] == 0.3
    assert payload["summary"]["stress_v0.6_verified_rate"] == 0.35
    assert payload["corpus"]["stress_case_count"] == 20


def test_acceptance_report_preserves_redacted_v05_trace():
    candidate = FullTextCandidate(
        doi="10.1000/trace",
        url="https://publisher.example/article?ticket=super-secret",
        provenance=(),
    )
    provider = ProviderDiscoveryResult(
        provider=DiscoveryProvider.OPENALEX,
        status=ProviderDiscoveryStatus.SUCCESS,
        candidates=(candidate,),
        attempts=1,
    )
    discovery = DiscoveryResult(
        doi="10.1000/trace",
        candidates=(candidate,),
        providers=(provider,),
    )
    route_result = RouteResolutionResult(
        source_candidate=candidate,
        status=ResolutionStatus.NO_FILE_CANDIDATES,
        page_type=PageType.ARTICLE,
    )
    route_attempt = RouteAttempt(
        candidate=candidate,
        origin=RouteCandidateOrigin.DISCOVERY,
        result=route_result,
        depth=1,
        parent_url="https://resolver.example/path?token=parent-secret",
    )
    file_result = AcquisitionResult(
        candidate=candidate,
        status=AcquisitionStatus.INVALID_PDF,
    )
    file_attempt = FileAttempt(
        candidate=candidate,
        origin=FileCandidateOrigin.DISCOVERY,
        result=file_result,
        parent_url="https://publisher.example/article?token=parent-secret",
    )
    base = MultiRouteAcquisitionResult(
        doi="10.1000/trace",
        status=FullTextAcquisitionStatus.EXHAUSTED,
        discovery=discovery,
        route_attempts=(route_attempt,),
        file_attempts=(file_attempt,),
        duplicate_file_candidates_skipped=1,
        page_route_attempts=1,
    )
    result = MaximizedAcquisitionResult(
        doi="10.1000/trace",
        status=MaximizedAcquisitionStatus.EXHAUSTED,
        base_result=base,
    )

    record = acceptance._serialize(result)
    trace = record["base_trace"]

    assert trace["discovery"]["candidate_count"] == 1
    assert trace["discovery"]["providers"][0]["status"] == "SUCCESS"
    assert trace["route_attempts"][0]["status"] == "NO_FILE_CANDIDATES"
    assert trace["route_attempts"][0]["depth"] == 1
    assert trace["route_attempts"][0]["page_type"] == "ARTICLE"
    assert trace["file_attempts"][0]["status"] == "INVALID_PDF"
    assert trace["stats"]["duplicate_file_candidates_skipped"] == 1
    assert trace["stats"]["page_route_attempts"] == 1

    serialized = json.dumps(record)
    assert "super-secret" not in serialized
    assert "parent-secret" not in serialized
    assert "%5Bredacted%5D" in serialized


def test_report_path_hides_absolute_local_directories(tmp_path):
    absolute = tmp_path / "private" / "controls.json"

    rendered = acceptance._report_path(absolute)

    assert rendered == "controls.json"
    assert str(tmp_path) not in rendered


def test_report_path_keeps_useful_relative_benchmark_path():
    rendered = acceptance._report_path(
        acceptance.Path("benchmarks/cdi_acquisition_10.json")
    )

    assert rendered == "benchmarks/cdi_acquisition_10.json"
