"""Offline safeguards for the browser-backed institution acceptance report."""

from scripts import verify_institutional_acceptance as review


def _report():
    stress = [
        {
            "doi": f"10.1000/stress-{index}",
            "stress_case": True,
            "entitled_control": False,
            "status": "EXHAUSTED",
        }
        for index in range(20)
    ]
    controls = [
        {
            "doi": f"10.1000/control-{index}",
            "stress_case": False,
            "entitled_control": True,
            "access_family": family,
            "status": "VERIFIED",
            "base_status": "ACCESS_BLOCKED",
            "elsevier_attempt": None,
            "browser_attempts": [{"status": "VERIFIED"}],
        }
        for index, family in enumerate(("acs", "elsevier", "wiley"))
    ]
    return {
        "schema": review.SCHEMA,
        "aletheia_nexus_version": "0.6.1",
        "source_revision": {"commit": "a" * 40, "dirty": False},
        "browser": {
            "profile_name": "ucas-test",
            "headless": False,
            "interactive": True,
            "external_cdp_attach": False,
            "launch_mode": "an_playwright",
        },
        "official_api": {"elsevier_enabled": False},
        "corpus": {
            "case_count": 23,
            "stress_case_count": 20,
            "entitled_positive_control_count": 3,
        },
        "summary": {
            "runner_errors": 0,
            "freeze_gate_passed": True,
            "v0.6_only_recoveries": 3,
        },
        "records": stress + controls,
    }


def _evaluate(payload):
    return review.evaluate(payload, institution_id="ucas", expected_profile="ucas-test")


def test_all_three_nonpublic_browser_controls_pass_machine_gate():
    result = _evaluate(_report())
    assert result["machine_gate_passed"] is True
    assert result["browser_verified_controls"] == 3
    assert result["manual_pdf_and_session_review"] == "pending"
    assert result["scope"].startswith("single-institution")


def test_public_or_api_control_cannot_prove_browser_entitlement():
    payload = _report()
    payload["records"][-1]["base_status"] = "VERIFIED"
    result = _evaluate(payload)
    assert result["machine_gate_passed"] is False
    assert "public base path" in result["issues"][-1]

    payload = _report()
    payload["records"][-1]["elsevier_attempt"] = {"status": "VERIFIED"}
    result = _evaluate(payload)
    assert result["machine_gate_passed"] is False
    assert "official API" in result["issues"][-1]


def test_wrong_profile_and_missing_browser_attempt_fail():
    payload = _report()
    payload["browser"]["profile_name"] = "other-institution"
    payload["records"][-1]["browser_attempts"] = []
    result = _evaluate(payload)
    assert result["machine_gate_passed"] is False
    assert any("profile" in issue for issue in result["issues"])
    assert any("verified browser attempt" in issue for issue in result["issues"])


def test_summary_does_not_copy_sensitive_browser_trace():
    payload = _report()
    payload["records"][-1]["browser_attempts"][-1]["secret"] = (
        "https://publisher.invalid/pdf?token=super-secret"
    )
    result = _evaluate(payload)
    assert "super-secret" not in str(result)


def test_an_dedicated_cdp_passes_but_existing_cdp_does_not():
    payload = _report()
    payload["browser"]["external_cdp_attach"] = True
    payload["browser"]["launch_mode"] = "an_dedicated_cdp"
    assert _evaluate(payload)["machine_gate_passed"] is True

    payload["browser"]["launch_mode"] = "attached_existing_cdp"
    result = _evaluate(payload)
    assert result["machine_gate_passed"] is False
    assert any("AN-dedicated" in issue for issue in result["issues"])


def test_dirty_or_unidentified_code_does_not_pass():
    payload = _report()
    payload["source_revision"]["dirty"] = True
    assert _evaluate(payload)["machine_gate_passed"] is False
    payload["source_revision"] = {"commit": None, "dirty": None}
    assert _evaluate(payload)["machine_gate_passed"] is False
