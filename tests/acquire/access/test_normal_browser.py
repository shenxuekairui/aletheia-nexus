"""Default launch and profile ownership without real authentication/network."""

import json
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.browser_engine import launcher
from aletheia_nexus.acquire.access.models import (
    BrowserAccessAttempt,
    BrowserAccessConfig,
    BrowserAttemptStatus,
)
from aletheia_nexus.acquire.discovery.models import FullTextCandidate


def test_profile_lease_excludes_other_clients_and_releases(tmp_path):
    first = launcher.ProfileLease(tmp_path)
    try:
        with pytest.raises(launcher.NormalBrowserError, match="another acquisition"):
            launcher.ProfileLease(tmp_path)
    finally:
        first.close()
        first.close()
    second = launcher.ProfileLease(tmp_path)
    second.close()


@pytest.mark.parametrize("system_proxy", [False, True])
def test_ordinary_launch_uses_minimal_flags_and_reuses_exact_profile(
    monkeypatch, tmp_path, system_proxy
):
    binary = tmp_path / "browser.exe"
    binary.touch()
    chromium = SimpleNamespace(executable_path=str(binary))
    launches = []
    endpoint = "ws://127.0.0.1:43210/devtools/browser/owned-id"
    monkeypatch.setattr(launcher, "_executable", lambda *a, **kw: binary)
    monkeypatch.setattr(
        launcher, "_active_endpoint", lambda p: endpoint if launches else None
    )

    def launch(args, **kwargs):
        launches.append(args)
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(launcher.subprocess, "Popen", launch)
    for _ in range(2):
        assert (
            launcher.normal_browser_endpoint(
                chromium, tmp_path, use_system_proxy=system_proxy
            )
            == endpoint
        )
    assert len(launches) == 1
    flags = launches[0]
    assert "--remote-debugging-address=127.0.0.1" in flags
    assert "--remote-debugging-port=0" in flags
    assert f"--user-data-dir={tmp_path.resolve()}" in flags
    assert ("--no-proxy-server" in flags) is not system_proxy
    assert not any("disable-features" in arg or "automation" in arg for arg in flags)
    assert not any("headless" in arg for arg in flags)


@pytest.mark.parametrize("mismatch", ["unregistered", "network", "runtime"])
def test_existing_browser_is_never_silently_restarted_or_reconfigured(
    monkeypatch, tmp_path, mismatch
):
    endpoint = "ws://127.0.0.1:43210/devtools/browser/owned-id"
    monkeypatch.setattr(launcher, "_active_endpoint", lambda p: endpoint)
    monkeypatch.setattr(launcher, "_executable", lambda *a, **kw: tmp_path / "new.exe")
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not restart")
    )
    if mismatch != "unregistered":
        (tmp_path / ".an-normal-browser.json").write_text(
            json.dumps(
                {
                    "endpoint": endpoint,
                    "use_system_proxy": mismatch == "network",
                    "executable": str(tmp_path / "old.exe"),
                }
            ),
            encoding="utf-8",
        )
    with pytest.raises(launcher.NormalBrowserError):
        launcher.normal_browser_endpoint(
            object(),
            tmp_path,
            executable_path="new.exe" if mismatch == "runtime" else None,
        )


def test_startup_failure_does_not_terminate_browser_or_remove_profile(
    monkeypatch, tmp_path
):
    history = tmp_path / "History"
    history.write_bytes(b"preserved")
    monkeypatch.setattr(launcher, "_active_endpoint", lambda p: None)
    monkeypatch.setattr(
        launcher, "_executable", lambda *a, **kw: tmp_path / "chrome.exe"
    )
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(poll=lambda: 0)
    )
    with pytest.raises(launcher.NormalBrowserError, match="profile may already"):
        launcher.normal_browser_endpoint(object(), tmp_path)
    assert history.read_bytes() == b"preserved"


@pytest.mark.parametrize("source", ["explicit", "installed", "portable", "bundled"])
def test_normal_runtime_selection_is_explicit_or_safe_default(
    monkeypatch, tmp_path, source
):
    paths = {
        key: tmp_path / f"{key}.exe"
        for key in ("explicit", "installed", "portable", "bundled")
    }
    for path in paths.values():
        path.touch()
    monkeypatch.setattr(
        launcher,
        "fixed_installed_browser",
        lambda: (
            ("chrome", paths["installed"])
            if source in {"explicit", "installed"}
            else None
        ),
    )
    monkeypatch.setattr(
        launcher,
        "fixed_portable_browser",
        lambda: paths["portable"] if source == "portable" else None,
    )
    selected = launcher._executable(
        SimpleNamespace(executable_path=str(paths["bundled"])),
        channel="chromium" if source == "bundled" else None,
        executable_path=paths["explicit"] if source == "explicit" else None,
    )
    assert selected == paths[source].resolve()


def test_normal_runtime_never_silently_changes_an_unsupported_channel():
    with pytest.raises(launcher.NormalBrowserError, match="another channel"):
        launcher._executable(object(), channel="chrome-beta", executable_path=None)


@pytest.mark.parametrize(
    "kind", ["valid", "wrong_id", "remote", "bad_port", "credentials"]
)
def test_active_endpoint_checks_browser_identity_and_loopback(
    monkeypatch, tmp_path, kind
):
    (tmp_path / "DevToolsActivePort").write_text("43210\n/devtools/browser/owned-id\n")
    websocket = {
        "valid": "ws://127.0.0.1:43210/devtools/browser/owned-id",
        "wrong_id": "ws://127.0.0.1:43210/devtools/browser/another-id",
        "remote": "ws://example.org:43210/devtools/browser/owned-id",
        "bad_port": "ws://127.0.0.1:1234/devtools/browser/owned-id",
        "credentials": "ws://user:secret@127.0.0.1:43210/devtools/browser/owned-id",
    }[kind]

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            return json.dumps({"webSocketDebuggerUrl": websocket}).encode()

    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], launcher._NoRedirect)
        return SimpleNamespace(open=lambda *a, **kw: Response())

    monkeypatch.setattr(launcher, "build_opener", opener)
    assert launcher._active_endpoint(tmp_path) == (
        websocket if kind == "valid" else None
    )


@pytest.mark.parametrize(
    "content", ["invalid", "0\n/devtools/browser/id", "43210\n/other", "9" * 2000]
)
def test_invalid_active_port_never_connects(monkeypatch, tmp_path, content):
    (tmp_path / "DevToolsActivePort").write_text(content)
    monkeypatch.setattr(
        launcher, "build_opener", lambda *a: pytest.fail("invalid endpoint")
    )
    assert launcher._active_endpoint(tmp_path) is None


class _Page:
    url = "about:blank"
    closed = False

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True

    def on(self, *args):
        pass


class _Context:
    def __init__(self):
        self.pages = [_Page()]
        self.closed = False
        self.routes = []

    def set_default_timeout(self, value):
        pass

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def on(self, *args):
        pass

    def new_page(self):
        page = _Page()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class _Manager:
    def __init__(self, *, version="155.0.1", fail_attach=False):
        self.context = _Context()
        self.calls = []
        self.closed = False

        def connect(endpoint, **kwargs):
            self.calls.append(endpoint)
            if fail_attach:
                raise RuntimeError("private credentials must not enter diagnostics")
            return SimpleNamespace(contexts=[self.context], version=version)

        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(
                connect_over_cdp=connect,
                launch_persistent_context=lambda **kw: pytest.fail(
                    "must not use managed"
                ),
            )
        )

    def __enter__(self):
        return self.playwright

    def __exit__(self, *args):
        self.closed = True


def test_default_session_launches_normal_and_preserves_window_on_exit(
    monkeypatch, tmp_path
):
    manager = _Manager()
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)
    launches = []

    def launch(chromium, profile, **kwargs):
        launches.append((profile, kwargs))
        return "ws://127.0.0.1:43210/devtools/browser/owned-id"

    monkeypatch.setattr(browser, "normal_browser_endpoint", launch)
    attempts = []

    def attempt(context, page, *, source, **kwargs):
        assert kwargs["_navigate_source"] is True
        attempts.append(page)
        return BrowserAccessAttempt(
            source_candidate=source,
            final_url=source.url,
            status=BrowserAttemptStatus.NO_FILE_CANDIDATES,
        )

    monkeypatch.setattr(browser, "attempt_browser_route", attempt)
    config = BrowserAccessConfig(profile_root=tmp_path)
    with browser.BrowserSession(config) as session:
        for suffix in ("first", "second"):
            doi = f"10.1000/{suffix}"
            session.acquire(
                doi=doi,
                routes=[
                    FullTextCandidate(
                        doi=doi,
                        url=f"https://publisher.example/{suffix}",
                        provenance=(),
                    )
                ],
                output_dir=tmp_path / "out",
            )
        with pytest.raises(launcher.NormalBrowserError):
            launcher.ProfileLease(session.profile_dir)
        session.wait_until_closed()  # no artificial CLI hang in normal mode
        assert session._attached_external
    assert len(launches) == 1
    assert launches[0][1]["use_system_proxy"] is False
    assert manager.context.routes  # URL guard preserved
    assert len(attempts) == 2 and all(p.closed for p in attempts)
    assert not manager.context.closed and not manager.context.pages[0].closed
    assert manager.closed
    launcher.ProfileLease(session.profile_dir).close()


@pytest.mark.parametrize("failure", ["launch", "attach", "unsafe_version", "setup"])
def test_normal_startup_failures_release_lease_without_closing_window(
    monkeypatch, tmp_path, failure
):
    manager = _Manager(
        version="154.0.1" if failure == "unsafe_version" else "155.0.1",
        fail_attach=failure == "attach",
    )
    if failure == "setup":
        manager.context.set_default_timeout = lambda value: (_ for _ in ()).throw(
            RuntimeError()
        )
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)

    def launch(*args, **kwargs):
        if failure == "launch":
            raise RuntimeError("private credentials must not enter diagnostics")
        return "ws://127.0.0.1:43210/devtools/browser/owned-id"

    monkeypatch.setattr(browser, "normal_browser_endpoint", launch)
    session = browser.BrowserSession(BrowserAccessConfig(profile_root=tmp_path))
    with pytest.raises(browser.BrowserCapabilityUnavailable) as error:
        session._ensure_started()
    assert "private credentials" not in str(error.value)
    assert manager.closed and not manager.context.closed
    launcher.ProfileLease(session.profile_dir).close()


@pytest.mark.parametrize("mode", ["invalid", "", None, 1])
def test_launch_mode_is_validated(mode):
    with pytest.raises(ValueError, match="launch_mode"):
        browser.BrowserSession(BrowserAccessConfig(launch_mode=mode))


@pytest.mark.parametrize("attach_fails", [False, True])
def test_profile_lease_released_even_when_driver_disconnect_fails(
    monkeypatch, tmp_path, attach_fails
):
    class BrokenDisconnect(_Manager):
        def __exit__(self, *args):
            raise RuntimeError("driver disconnect failed")

    manager = BrokenDisconnect(fail_attach=attach_fails)
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)
    monkeypatch.setattr(
        browser,
        "normal_browser_endpoint",
        lambda *a, **kw: "ws://127.0.0.1:43210/devtools/browser/owned-id",
    )
    session = browser.BrowserSession(BrowserAccessConfig(profile_root=tmp_path))
    with pytest.raises(RuntimeError, match="disconnect failed"):
        session._ensure_started()
        session.close()
    assert not manager.context.closed
    launcher.ProfileLease(session.profile_dir).close()


def test_explicit_normal_mode_rejects_headless():
    with pytest.raises(ValueError, match="visible browser"):
        browser.BrowserSession(
            BrowserAccessConfig(
                launch_mode="normal",
                headless=True,
                interactive=False,
            )
        )


def test_auto_headless_still_uses_managed_launch(monkeypatch, tmp_path):
    manager = _Manager()
    calls = []

    def launch(**kwargs):
        calls.append(kwargs)
        return manager.context

    manager.playwright.chromium.launch_persistent_context = launch
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)
    monkeypatch.setattr(browser, "fixed_portable_browser", lambda: None)
    monkeypatch.setattr(
        browser, "normal_browser_endpoint", lambda *a, **kw: pytest.fail("not visible")
    )
    with browser.BrowserSession(
        BrowserAccessConfig(profile_root=tmp_path, headless=True, interactive=False)
    ) as session:
        session._ensure_started()
        assert not session._attached_external
    assert calls[0]["headless"] is True
    assert manager.context.closed and manager.closed
    assert not manager.calls


def test_explicit_cdp_bypasses_normal_launch_and_profile_lease(monkeypatch, tmp_path):
    manager = _Manager()
    monkeypatch.setattr(browser, "_load_playwright", lambda: lambda: manager)
    monkeypatch.setattr(
        browser, "normal_browser_endpoint", lambda *a, **kw: pytest.fail("already open")
    )
    config = BrowserAccessConfig(
        profile_root=tmp_path, cdp_endpoint="http://127.0.0.1:9222"
    )
    with browser.BrowserSession(config) as session:
        session._ensure_started()
        assert session._normal_lease is None
        assert not manager.context.routes
    assert manager.calls == [config.cdp_endpoint]
    assert manager.closed and not manager.context.closed
