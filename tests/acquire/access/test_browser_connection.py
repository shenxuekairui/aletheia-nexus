"""Connection diagnostics do not mutate or expose the user's browser state."""

import json
from types import SimpleNamespace

import pytest

from aletheia_nexus.acquire.access import browser
from aletheia_nexus.acquire.access.browser_engine import connection
from aletheia_nexus.acquire.access.models import BrowserAccessConfig


class Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, count):
        return self.body[:count]


def probe(monkeypatch, *, version=None, targets=None):
    requests = []
    version = version or {
        "webSocketDebuggerUrl": "ws://127.0.0.1:54321/devtools/browser/private-id"
    }
    targets = targets if targets is not None else []

    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], connection._NoRedirect)

        def read(url, *, timeout):
            requests.append(url)
            assert timeout == 0.5
            return Response(targets if url.endswith("/json/list") else version)

        return SimpleNamespace(open=read)

    monkeypatch.setattr(connection, "build_opener", opener)
    return requests


def test_probe_keeps_only_aggregate_counts_and_reads_only_local_control(monkeypatch):
    calls = probe(
        monkeypatch,
        targets=[
            {
                "type": "page",
                "url": "https://publisher.test/a?token=private",
                "id": "private-target",
            },
            {"type": "page", "url": "https://publisher.test/a.pdf?signature=secret"},
            {
                "type": "page",
                "url": "chrome-extension://viewer/?id=secret",
                "title": "private.pdf",
            },
            {"type": "service_worker", "url": "https://publisher.test/worker"},
        ],
    )
    result = connection.inspect_local_endpoint(
        "ws://127.0.0.1:54321/devtools/browser/private-id"
    )
    assert result == {
        "endpoint_reachable": True,
        "page_count": 3,
        "pdf_like_page_count": 2,
        "endpoint_probe": "COMPLETED",
    }
    assert calls == [
        "http://127.0.0.1:54321/json/version",
        "http://127.0.0.1:54321/json/list",
    ]
    assert not any(
        word in json.dumps(result) for word in ("private", "secret", "publisher")
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://publisher.test/",
        "http://127.0.0.1:1234/?token=secret",
        "http://name:password@127.0.0.1:1234/",
        "ws://127.0.0.1:1234/devtools/page/target",
        "http://127.0.0.1:1234/custom-control-prefix/",
        "file:///json/version",
    ],
)
def test_invalid_probe_shape_never_opens_a_socket(monkeypatch, endpoint):
    monkeypatch.setattr(
        connection, "build_opener", lambda *args: pytest.fail("not local control")
    )
    assert connection.inspect_local_endpoint(endpoint) == {
        "endpoint_probe": "UNSUPPORTED_ENDPOINT_SHAPE"
    }


@pytest.mark.parametrize(
    "websocket",
    [
        "ws://127.0.0.1:54321/devtools/browser/recycled-id",
        "ws://publisher.test:54321/devtools/browser/private-id",
        "ws://127.0.0.1:54322/devtools/browser/private-id",
        "ws://name:secret@127.0.0.1:54321/devtools/browser/private-id",
    ],
)
def test_probe_does_not_confuse_recycled_or_redirected_endpoint(monkeypatch, websocket):
    calls = probe(monkeypatch, version={"webSocketDebuggerUrl": websocket})
    assert connection.inspect_local_endpoint(
        "ws://127.0.0.1:54321/devtools/browser/private-id"
    ) == {"endpoint_reachable": False, "endpoint_probe": "IDENTITY_MISMATCH"}
    assert len(calls) == 1


@pytest.mark.parametrize("targets", [None, {}, "not-a-list"])
def test_malformed_target_inventory_is_safe_and_retains_endpoint_evidence(
    monkeypatch, targets
):
    calls = probe(monkeypatch, targets=targets if targets is not None else {})
    result = connection.inspect_local_endpoint("http://127.0.0.1:54321/")
    assert result == {
        "endpoint_reachable": True,
        "endpoint_probe": "FAILED",
        "probe_error_type": "ValueError",
    }
    assert len(calls) == 2


def test_timeout_explains_handshake_without_claiming_pdf_cause_or_retaining_log(
    monkeypatch,
):
    probe(
        monkeypatch, targets=[{"type": "page", "url": "https://site.test/private.pdf"}]
    )
    error = TimeoutError(
        "Timeout45000 <ws connected> ws://127.0.0.1:54321/devtools/browser/private-id signed=secret"
    )
    result = connection.connection_failure_diagnostic(
        error,
        endpoint="http://127.0.0.1:54321",
        stage="cdp_attach",
        timeout_seconds=45,
        elapsed_seconds=45.027,
    )
    assert result["code"] == "browser_cdp_attach_timeout"
    assert result["websocket_connected"] and result["endpoint_reachable"]
    assert result["automatic_retry"] is False and result["user_state_preserved"]
    assert "尚不能确认" in result["message"] and "45 秒" in result["message"]
    assert "secret" not in json.dumps(result) and "private" not in json.dumps(result)
    assert result["recovery_actions"][0]["action"] == "review_pdf_tabs"
    assert "先保存阅读进度" in result["recovery_actions"][0]["description"]


def test_context_setup_failure_is_distinct_from_cdp_connect_failure(monkeypatch):
    probe(monkeypatch)
    result = connection.connection_failure_diagnostic(
        RuntimeError("private-token"),
        endpoint="http://127.0.0.1:54321",
        stage="context_setup",
        timeout_seconds=45,
        elapsed_seconds=0.125,
    )
    assert result["code"] == "browser_context_setup_failed"
    assert "文件事件监听初始化" in result["message"]
    assert "private-token" not in json.dumps(result)


def test_opaque_sdk_error_does_not_claim_handshake_failed(monkeypatch):
    probe(monkeypatch)
    result = connection.connection_failure_diagnostic(
        TimeoutError("Timeout, no public connection call-log available"),
        endpoint="http://127.0.0.1:54321",
        stage="cdp_attach",
        timeout_seconds=45,
        elapsed_seconds=45,
    )
    assert result["websocket_connected"] is None


def test_capability_exception_keeps_runtime_error_constructor_compatibility():
    assert browser.BrowserCapabilityUnavailable().args == ()
    assert browser.BrowserCapabilityUnavailable("a", "b").args == ("a", "b")


def test_local_probe_distinguishes_implicit_ws_and_wss_ports(monkeypatch):
    probe(
        monkeypatch,
        version={"webSocketDebuggerUrl": "wss://127.0.0.1/devtools/browser/id"},
    )
    assert (
        connection.inspect_local_endpoint("http://127.0.0.1")["endpoint_probe"]
        == "IDENTITY_MISMATCH"
    )


def test_diagnostic_probe_caps_response_size_without_retaining_payload(monkeypatch):
    class Oversized(Response):
        def read(self, count):
            return b"x" * count

    monkeypatch.setattr(
        connection,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *a, **kw: Oversized(None)),
    )
    assert connection.inspect_local_endpoint("http://127.0.0.1:54321") == {
        "endpoint_reachable": False,
        "endpoint_probe": "FAILED",
        "probe_error_type": "ValueError",
    }


def test_diagnostic_probe_socket_failure_is_not_an_unhandled_exception(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("secret-proxy-or-local-detail")

    monkeypatch.setattr(connection, "build_opener", unavailable)
    result = connection.inspect_local_endpoint("http://127.0.0.1:54321")
    assert (
        result["endpoint_probe"] == "FAILED" and result["probe_error_type"] == "OSError"
    )
    assert "secret" not in json.dumps(result)


def test_failed_session_does_not_reconnect_until_explicit_close_and_preserves_context(
    monkeypatch, tmp_path
):
    launches, exits, attempts = [], [], []
    context = SimpleNamespace(
        pages=[],
        set_default_timeout=lambda value: None,
        close=lambda: pytest.fail("must not close the user's context"),
    )
    fail = [True]

    def attach(endpoint, **kwargs):
        attempts.append(kwargs)
        if fail[0]:
            raise TimeoutError("<ws connected> private-browser-endpoint")
        return SimpleNamespace(contexts=[context], version="155.0.1")

    class Manager:
        def __enter__(self):
            launches.append("driver")
            return SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=attach))

        def __exit__(self, *args):
            exits.append("disconnect")

    monkeypatch.setattr(browser, "_load_playwright", lambda: Manager)
    monkeypatch.setattr(
        connection,
        "inspect_local_endpoint",
        lambda endpoint: {"endpoint_reachable": True},
    )
    config = BrowserAccessConfig(
        profile_root=tmp_path, cdp_endpoint="http://127.0.0.1:54321"
    )
    session = browser.BrowserSession(config)
    for _ in range(3):
        with pytest.raises(browser.BrowserCapabilityUnavailable) as caught:
            session._ensure_started()
        assert caught.value.diagnostic["code"] == "browser_cdp_attach_timeout"
    assert len(attempts) == len(launches) == len(exits) == 1
    assert attempts == [{"timeout": 45000, "no_defaults": True}]
    snapshot = session.connection_diagnostic
    snapshot["message"] = "must not mutate stored diagnostic"
    assert session.connection_diagnostic["message"] != snapshot["message"]
    session.close()
    assert session.connection_diagnostic is None
    fail[0] = False
    assert session._ensure_started() is context
    session.close()
    assert len(attempts) == len(launches) == len(exits) == 2
