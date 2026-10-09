from pathlib import Path
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.browser_engine import runtime as browser_engine
from aletheia_nexus.acquire.access.models import BrowserAccessConfig


@pytest.mark.parametrize("version", ["152.0.1", "153.0.8010.12", "154.0.4258.62"])
def test_known_crashing_download_versions_are_rejected(version):
    with pytest.raises(browser.BrowserCapabilityUnavailable, match="556160935"):
        browser._require_safe_download_browser(SimpleNamespace(version=version))


@pytest.mark.parametrize("version", ["151.0.1", "155.0.8059.39", "156.0.1"])
def test_versions_outside_regression_are_not_rejected(version):
    browser._require_safe_download_browser(SimpleNamespace(version=version))


@pytest.mark.skipif(browser_engine.os.name != "nt", reason="Windows PE discovery")
def test_default_channel_skips_unfixed_stable_browser(monkeypatch):
    edge, chrome = Path("edge.exe"), Path("chrome.exe")
    monkeypatch.setattr(
        browser_engine,
        "installed_browser_candidates",
        lambda: [("msedge", edge), ("chrome", chrome)],
    )
    monkeypatch.setattr(
        browser_engine, "windows_browser_major", lambda p: 154 if p == edge else 155
    )
    assert browser_engine.fixed_installed_browser() == ("chrome", chrome)


@pytest.mark.skipif(browser_engine.os.name != "nt", reason="Windows PE discovery")
def test_portable_runtime_ignores_affected_and_unknown_versions(monkeypatch, tmp_path):
    root = tmp_path / ".aletheia-nexus/browser-runtimes"
    paths = [root / f"chrome-{v}/chrome-win64/chrome.exe" for v in (153, 155, 156)]
    for path in paths:
        path.parent.mkdir(parents=True)
        path.touch()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        browser_engine,
        "windows_browser_major",
        lambda p: {paths[0]: 153, paths[1]: 155, paths[2]: None}[p],
    )
    assert browser_engine.fixed_portable_browser() == paths[1]


def test_explicit_executable_config_rejects_conflicting_channel(tmp_path):
    config = BrowserAccessConfig(
        executable_path=tmp_path / "chrome.exe", channel="msedge"
    )
    with pytest.raises(ValueError, match="executable_path"):
        browser._validate_config(config)
