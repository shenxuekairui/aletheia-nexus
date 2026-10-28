"""Invalid acquisition parameters must fail before any engine/network work."""

import math

import pytest

from aletheia_nexus.workbench import acquisition
from aletheia_nexus.workbench.acquisition import AcquisitionService, _options


@pytest.mark.parametrize(
    "options",
    [
        {"timeout": 0},
        {"max_route_attempts": 0},
        {"max_file_attempts": 0},
        {"max_route_expansions_per_page": 0},
        {"discovery_max_attempts": 0},
        {"metadata_max_attempts": 0},
        {"max_attempts_per_route": 0},
        {"max_attempts_per_file": 0},
        {"max_si_files": 101},
        {"max_item_attempts": 0},
        {"si_max_bytes": 0},
        {"browser": {"navigation_timeout": 0}},
        {"browser": {"request_timeout": 0}},
        {"browser": {"poll_interval": 0}},
        {"browser": {"max_source_routes": 0}},
        {"browser": {"max_pdf_candidates": 0}},
        {"browser": {"cnki_max_results": 0}},
        {"browser": {"max_bytes": 0}},
        {"browser": {"max_request_redirects": -1}},
        {"browser": {"cnki_paper_interval": -1}},
        {"browser": {"navigation_timeout": math.inf}},
        {"browser": {"request_timeout": math.nan}},
        {"browser": {"max_source_routes": True}},
        {"browser": {"launch_mode": "unavailable-mode"}},
        {"browser": {"headless": True, "interactive": True}},
        {"browser": {"direct_connection": True, "use_system_proxy": True}},
        {"browser": {"cdp_endpoint": "https://external.example/browser"}},
    ],
)
def test_invalid_parameters_never_reach_batch_engine(tmp_path, monkeypatch, options):
    monkeypatch.setattr(
        acquisition,
        "acquire_full_text_batch_maximized",
        lambda *a, **k: pytest.fail(
            "must reject before metadata or acquisition network"
        ),
    )
    with pytest.raises((ValueError, TypeError)):
        AcquisitionService(tmp_path).run(["10.1000/preflight"], options)
    assert not list(
        (tmp_path / ".an-workbench" / "acquisition").glob("*.checkpoint.json")
    )


def test_real_zero_boundaries_and_si_upper_boundary_remain_supported():
    result = _options(
        {
            "max_route_depth": 0,
            "bulk_interval": 0,
            "backoff_base": 0,
            "retry_backoff": 0,
            "interaction_timeout": 0,
            "max_si_files": 100,
            "browser": {
                "max_request_redirects": 0,
                "auto_challenge_grace": 0,
                "cnki_paper_interval": 0,
            },
        }
    )
    assert result["max_si_files"] == 100 and result["interaction_timeout"] == 0
    assert result["browser"]["cnki_paper_interval"] == 0


def test_skip_policy_validates_the_effective_browser_configuration():
    # The existing adapter disables interactive handoff for the skip policy;
    # validate that effective configuration, not an impossible intermediate one.
    assert (
        _options({"interaction_policy": "skip", "browser": {"headless": True}})[
            "browser"
        ]["headless"]
        is True
    )


def test_range_error_identifies_the_exact_setting_in_chinese():
    with pytest.raises(ValueError, match="公共获取与 SI 请求超时"):
        _options({"timeout": 0})
    with pytest.raises(ValueError, match="关联附件数量上限.*100"):
        _options({"max_si_files": 101})
