"""First-use UI choices are useful, opt-in for costs, and isolated from CLI."""

import json
import subprocess
import sys
import tomllib
from copy import deepcopy
from pathlib import Path

import pytest

from aletheia_nexus.ui_cli import create_context
from aletheia_nexus.workbench import defaults
from aletheia_nexus.workbench.acquisition import _options, get_acquisition_defaults
from aletheia_nexus.workbench.settings import SettingsStore


def test_new_ui_uses_public_first_visible_institution_fallback_without_api_consent(
    monkeypatch,
):
    original = get_acquisition_defaults()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-an-authorization")
    monkeypatch.setenv("ELSEVIER_API_KEY", "not-an-authorization")
    ui = defaults.ui_acquisition_defaults()
    checked = _options(ui)
    assert checked["public_only"] is False and checked["browser_enabled"] is True
    assert checked["auto_official_api"] is False
    assert (
        checked["interaction_policy"] == "wait" and checked["interaction_timeout"] == 0
    )
    assert checked["bulk_interval"] == 1 and checked["include_si"] is True
    assert checked["resume"] is True and checked["max_item_attempts"] == 1
    browser = checked["browser"]
    assert browser["headless"] is False and browser["interactive"] is True
    assert browser["channel"] is None and browser["launch_mode"] == "auto"
    assert browser["use_system_proxy"] is None and browser["direct_connection"] is False
    assert (
        browser["profile_name"] == "human-handoff" and browser["profile_root"] is None
    )
    assert browser["cdp_endpoint"] is None
    assert get_acquisition_defaults() == original
    assert original["public_only"] is True and original["browser_enabled"] is False
    ui["browser"]["profile_name"] = "changed-only-in-caller"
    assert (
        defaults.ui_acquisition_defaults()["browser"]["profile_name"] == "human-handoff"
    )


def test_new_workflow_parses_natively_without_enabling_ocr_or_paid_titles():
    from aletheia_nexus.workbench.research import WorkbenchResearch
    from aletheia_nexus.workbench.ui_acquisition import acquisition_workflow_preferences

    workflow = acquisition_workflow_preferences(defaults.ui_workflow_defaults())
    assert workflow["auto_parse"] is True
    assert workflow["template"] == "{year}-{journal}-{title_zh}"
    assert workflow["title_translation"]["enabled"] is False
    parser = WorkbenchResearch.parser_options()
    assert parser["ocr"] is False and parser["new_version"] is False
    assert parser["max_pages"] == 2000 and parser["max_blocks"] == 200000
    assert "consent" not in workflow["title_translation"]


def test_bootstrap_is_persistent_and_does_not_rewrite_existing_defaults_or_presets(
    tmp_path,
):
    settings = SettingsStore(tmp_path)
    settings.save_preset(
        "acquisition", "仅公开", {"public_only": True, "browser_enabled": False}
    )
    preset = deepcopy(settings.presets("acquisition"))
    result = defaults.bootstrap_ui_defaults(settings)
    assert result["initialized"] == ["acquisition", "acquisition_workflow"]
    assert SettingsStore(tmp_path).get("acquisition")["browser_enabled"] is True
    assert SettingsStore(tmp_path).get("acquisition_workflow")["auto_parse"] is True
    first = settings.path.read_bytes()
    assert defaults.bootstrap_ui_defaults(settings)["initialized"] == []
    assert settings.path.read_bytes() == first
    assert settings.presets("acquisition") == preset


@pytest.mark.parametrize(
    "saved",
    [{}, None, {"public_only": True, "browser_enabled": False}, {"timeout": 12}],
)
def test_any_explicit_saved_acquisition_section_is_preserved(tmp_path, saved):
    settings = SettingsStore(tmp_path)
    settings.set("acquisition", saved)
    settings.set("acquisition_workflow", {"auto_parse": False, "folder": "旧分类"})
    before = settings.path.read_bytes()
    assert defaults.bootstrap_ui_defaults(settings)["initialized"] == []
    assert settings.path.read_bytes() == before
    assert settings.get("acquisition") == saved
    assert settings.get("acquisition_workflow") == {
        "auto_parse": False,
        "folder": "旧分类",
    }


def test_context_initializes_ui_preferences_without_starting_browser_or_model(
    tmp_path, monkeypatch
):
    from aletheia_nexus.acquire.access.browser import BrowserSession
    from aletheia_nexus.processing.provider import DeepSeekProvider

    def forbidden(*_, **__):
        pytest.fail("Context bootstrap must not start browsers or model requests")

    monkeypatch.setattr(BrowserSession, "_ensure_started", forbidden)
    monkeypatch.setattr(DeepSeekProvider, "generate", forbidden)
    context = create_context(tmp_path / "library", tmp_path / "workspace")
    try:
        assert context.settings.get("acquisition")["public_only"] is False
        assert context.settings.get("acquisition_workflow")["auto_parse"] is True
        assert context.jobs.list() == []
    finally:
        context.jobs.close(wait=True)
        context.research.close()


def test_first_use_wait_is_unlimited_at_real_acquisition_adapter_boundary(
    tmp_path, monkeypatch
):
    from aletheia_nexus.acquire.access import batch
    from aletheia_nexus.acquire.access.browser import BrowserSession
    from aletheia_nexus.acquire.access.models import ChallengeKind, ChallengeReport
    from aletheia_nexus.workbench.acquisition import AcquisitionService

    observed = []

    class Context:
        def checkpoint(self, *, pump=None):
            pass

        def progress(self, *args, **kwargs):
            pass

        def record(self, *args, **kwargs):
            pass

        def should_skip(self, *args):
            return False

        def wait_interaction(self, details, *, timeout, pump=None):
            observed.append((details, timeout))
            return "skip"

    def forbidden(*args, **kwargs):
        pytest.fail("This deterministic test must not launch a browser")

    def fetch(request, *, browser_session, **kwargs):
        assert browser_session.config.headless is False
        assert browser_session.config.interactive is True
        browser_session.config.interaction_callback(
            ChallengeReport(ChallengeKind.AUTHENTICATION),
            "https://publisher.example/login",
        )
        pytest.fail("An explicit user skip must leave the current attempt")

    monkeypatch.setattr(BrowserSession, "_ensure_started", forbidden)
    monkeypatch.setattr(batch, "_acquire_item", fetch)
    report = AcquisitionService(tmp_path).run(
        ["10.1000/default-login"], defaults.ui_acquisition_defaults(), Context()
    )
    assert report["items"][0]["status"] == "SKIPPED"
    assert len(observed) == 1 and observed[0][1] is None
    assert observed[0][0]["stage"] == "browser_interaction"


def test_readiness_distinguishes_dependency_detection_from_browser_and_rights(
    tmp_path, monkeypatch
):
    ui = defaults.ui_acquisition_defaults()
    before = deepcopy(ui)
    monkeypatch.setattr(defaults, "find_spec", lambda _: None)
    missing = defaults.browser_readiness(ui)
    assert (
        missing["status"] == "DEPENDENCY_MISSING"
        and missing["dependency_installed"] is False
    )
    assert (
        missing["runtime_checked"] is False
        and missing["institutional_access_verified"] is False
    )
    assert "install" in missing["install_command"]
    monkeypatch.setattr(defaults, "find_spec", lambda _: object())
    detected = defaults.browser_readiness(ui)
    assert detected["status"] == "READY_TO_ATTEMPT"
    assert (
        detected["runtime_checked"] is False
        and detected["institutional_access_verified"] is False
    )
    assert ui == before
    ui["browser"]["executable_path"] = str(tmp_path / "missing-browser.exe")
    assert defaults.browser_readiness(ui)["status"] == "EXECUTABLE_MISSING"


def test_readiness_keeps_explicit_public_and_headless_preferences(monkeypatch):
    monkeypatch.setattr(defaults, "find_spec", lambda _: object())
    public = get_acquisition_defaults()
    assert defaults.browser_readiness(public)["status"] == "DISABLED"
    ui = defaults.ui_acquisition_defaults()
    ui["browser"]["headless"] = True
    assert defaults.browser_readiness(ui)["status"] == "MANUAL_LOGIN_NOT_VISIBLE"
    assert ui["browser"]["headless"] is True


def test_ui_extra_includes_browser_python_dependency_but_core_stays_optional():
    project = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text("utf-8")
    )["project"]
    extras = project["optional-dependencies"]
    assert extras["browser"][0] in extras["ui"]
    assert all(
        "playwright" not in dep.lower() and "nicegui" not in dep.lower()
        for dep in project["dependencies"]
    )


def test_core_cli_help_does_not_load_nicegui_or_playwright():
    code = """
import importlib.abc,sys,json
class BlockOptional(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'nicegui','playwright'}:
   raise ImportError('Optional UI/browser unavailable in core test')
sys.meta_path.insert(0,BlockOptional())
from aletheia_nexus.cli import entrypoint
try: entrypoint(['--help'])
except SystemExit as exc: assert exc.code==0
assert not {'nicegui','playwright'} & set(sys.modules)
print(json.dumps({'core_lazy':True}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout.splitlines()[-1]) == {"core_lazy": True}
