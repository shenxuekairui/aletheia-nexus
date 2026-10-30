"""Credentials use only fake stores/WinAPI and temporary environment mappings."""

import ctypes
import json

import httpx
import pytest

from aletheia_nexus.workbench.api_settings import (
    _CREDENTIALW,
    ApiSettingsService,
    WindowsCredentialStore,
    credential_target,
    load_saved_api_credentials,
)
from aletheia_nexus.workbench.settings import SettingsStore

OLD = "fixture-existing-secret-never-log"
NEW = "fixture-replacement-secret-never-log"


class FakeStore:
    def __init__(self):
        self.values, self.reads, self.writes = {}, [], []

    def read(self, target):
        self.reads.append(target)
        return self.values.get(target)

    def write(self, target, value):
        self.writes.append(target)
        self.values[target] = value


def service(tmp_path, *, allowed=True, backend=None, environ=None):
    settings = SettingsStore(tmp_path)
    environ = {"DEEPSEEK_API_KEY": OLD} if environ is None else environ
    return (
        ApiSettingsService(
            settings,
            tmp_path,
            can_change=lambda: allowed,
            credential_backend=backend,
            environ=environ,
        ),
        settings,
        environ,
    )


def test_session_save_does_not_persist_or_return_secret(tmp_path):
    api, settings, environ = service(tmp_path)
    result = api.save(base_url="https://api.deepseek.com/v1/", api_key=NEW)
    assert environ == {
        "DEEPSEEK_API_KEY": NEW,
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
    }
    assert result["source"] == "session" and result["configured"]
    assert settings.get("api") == {"base_url": "https://api.deepseek.com/v1"}
    for value in (
        json.dumps(result),
        settings.path.read_text(encoding="utf-8"),
        repr(api),
    ):
        assert OLD not in value and NEW not in value


def test_windows_save_and_reload_are_workspace_scoped_and_environment_wins(tmp_path):
    store = FakeStore()
    api, settings, environ = service(tmp_path / "one", backend=store)
    api.save(base_url="https://api.deepseek.com/v1", api_key=NEW, persist=True)
    assert store.writes == [credential_target(tmp_path / "one")]
    assert settings.get("api")["storage"] == "windows"
    fresh = {}
    report = load_saved_api_credentials(
        tmp_path / "one", settings, credential_backend=store, environ=fresh
    )
    assert fresh["DEEPSEEK_API_KEY"] == NEW and fresh["DEEPSEEK_BASE_URL"].endswith(
        "/v1"
    )
    assert report["source"] == "windows" and report["key_loaded"]
    assert NEW not in json.dumps(report)
    other = {}
    absent = load_saved_api_credentials(
        tmp_path / "other",
        SettingsStore(tmp_path / "other"),
        credential_backend=store,
        environ=other,
    )
    assert not absent["configured"] and "DEEPSEEK_API_KEY" not in other
    store.reads.clear()
    explicit = {
        "DEEPSEEK_API_KEY": OLD,
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    }
    external = load_saved_api_credentials(
        tmp_path / "one", settings, credential_backend=store, environ=explicit
    )
    assert not store.reads and explicit["DEEPSEEK_API_KEY"] == OLD
    assert explicit["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com"
    assert external["source"] == "environment" and not external["key_loaded"]


def test_unsupported_platform_does_not_claim_persistence(tmp_path):
    api, settings, environ = service(tmp_path, backend=None)
    assert api.status()["persistence_supported"] is False
    with pytest.raises(ValueError, match="当前平台不支持"):
        api.save(base_url="https://api.deepseek.com", api_key=NEW, persist=True)
    assert environ == {"DEEPSEEK_API_KEY": OLD} and not settings.path.exists()


def test_active_work_blocks_configuration_change_but_not_read_or_free_models_check(
    tmp_path,
):
    api, settings, environ = service(tmp_path, allowed=False)
    with pytest.raises(ValueError, match="仍有任务"):
        api.save(base_url="https://api.deepseek.com/v1", api_key=NEW)
    assert environ == {"DEEPSEEK_API_KEY": OLD} and not settings.path.exists()
    assert api.status()["configured"]
    requests = []

    def models(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/models"
        assert (
            request.content == b""
            and request.headers["Authorization"] == "Bearer " + OLD
        )
        return httpx.Response(200, json={"data": [{"id": OLD}]})

    report = api.check_connection(transport=httpx.MockTransport(models))
    assert report["ok"] and report["models_count"] == 1 and len(requests) == 1
    assert OLD not in json.dumps(report)
    assert environ == {"DEEPSEEK_API_KEY": OLD} and not settings.path.exists()


def test_unsaved_check_uses_only_models_without_mutating_configuration(tmp_path):
    api, settings, environ = service(tmp_path)

    def models(request):
        assert request.url == httpx.URL("https://api.deepseek.com/v1/models")
        assert request.method == "GET" and not request.content
        assert request.headers["Authorization"] == "Bearer " + NEW
        return httpx.Response(200, json={"data": []})

    report = api.check_connection(
        base_url="https://api.deepseek.com/v1",
        api_key=NEW,
        transport=httpx.MockTransport(models),
    )
    assert report["ok"] and report["models_count"] == 0
    assert environ == {"DEEPSEEK_API_KEY": OLD} and not settings.path.exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://api.deepseek.com",
        "https://127.0.0.1",
        "https://proxy.invalid",
        "https://api.deepseek.com/responses",
        "https://api.deepseek.com?api_key=" + NEW,
    ],
)
def test_invalid_endpoint_fails_before_transport_or_storage(tmp_path, url):
    api, settings, environ = service(tmp_path)

    def forbidden(_):
        pytest.fail("An invalid endpoint must never receive a credential")

    with pytest.raises(ValueError) as raised:
        api.check_connection(
            base_url=url, api_key=NEW, transport=httpx.MockTransport(forbidden)
        )
    assert NEW not in str(raised.value)
    with pytest.raises(ValueError):
        api.save(base_url=url, api_key=NEW)
    assert environ == {"DEEPSEEK_API_KEY": OLD} and not settings.path.exists()


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_http_failure_never_echoes_credentials_or_follows_redirect(tmp_path, status):
    api, _, _ = service(tmp_path)
    calls = []

    def endpoint(request):
        calls.append(request)
        return httpx.Response(
            status, text=OLD, headers={"Location": "https://untrusted.invalid/" + OLD}
        )

    result = api.check_connection(transport=httpx.MockTransport(endpoint))
    assert not result["ok"] and result["http_status"] == status and len(calls) == 1
    assert OLD not in json.dumps(result)


@pytest.mark.parametrize(
    "problem", ["exception", "not_json", "wrong_shape", "oversize"]
)
def test_check_failures_return_only_safe_recovery_messages(tmp_path, problem):
    api, _, _ = service(tmp_path)

    def endpoint(_):
        if problem == "exception":
            raise ValueError("transport echoed " + OLD)
        if problem == "not_json":
            return httpx.Response(200, text=OLD)
        if problem == "wrong_shape":
            return httpx.Response(200, json={"unexpected": OLD})
        return httpx.Response(200, content=(OLD + "x" * 131073).encode())

    with pytest.raises(ValueError) as raised:
        api.check_connection(transport=httpx.MockTransport(endpoint))
    assert OLD not in str(raised.value)


def test_persistence_failure_rolls_back_preferences_and_keeps_current_process_unchanged(
    tmp_path,
):
    class FailedStore(FakeStore):
        def write(self, target, value):
            raise RuntimeError("backend echoed " + value)

    api, settings, environ = service(tmp_path, backend=FailedStore())
    settings.set("api", {"base_url": "https://api.deepseek.com"})
    before = settings.path.read_bytes()
    with pytest.raises(ValueError, match="接口偏好已恢复") as raised:
        api.save(base_url="https://api.deepseek.com/v1", api_key=NEW, persist=True)
    assert NEW not in str(raised.value)
    assert settings.path.read_bytes() == before and environ == {"DEEPSEEK_API_KEY": OLD}


def test_failed_windows_read_does_not_prevent_local_startup_or_leak_diagnostic(
    tmp_path,
):
    class FailedRead(FakeStore):
        def read(self, target):
            raise RuntimeError("backend echoed " + OLD)

    environ = {}
    report = load_saved_api_credentials(
        tmp_path,
        SettingsStore(tmp_path),
        credential_backend=FailedRead(),
        environ=environ,
    )
    assert not report["configured"] and report["warning"]
    assert OLD not in json.dumps(report) and not environ


def test_header_injection_and_missing_key_fail_before_any_request(tmp_path):
    api, _, _ = service(tmp_path, environ={})

    def forbidden(_):
        pytest.fail("A missing or malformed key cannot cause a request")

    for candidate in ("", "fake-key\r\nInjected: true"):
        with pytest.raises(ValueError):
            api.check_connection(
                api_key=candidate, transport=httpx.MockTransport(forbidden)
            )


class FakeWinAPI:
    def __init__(self):
        self.values, self.handles, self.written, self.freed = {}, [], [], []
        self.error = 0

    def CredWriteW(self, pointer, flags):
        credential = ctypes.cast(pointer, ctypes.POINTER(_CREDENTIALW)).contents
        self.written.append((credential.Type, credential.Persist, credential.UserName))
        self.values[credential.TargetName] = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        )
        return 1

    def CredReadW(self, target, kind, flags, result):
        if target not in self.values:
            self.error = 1168
            return 0
        raw = self.values[target]
        blob = ctypes.create_string_buffer(raw)
        value = _CREDENTIALW()
        value.CredentialBlobSize = len(raw)
        value.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        pointer = ctypes.pointer(value)
        self.handles.append((blob, value, pointer))
        ctypes.cast(result, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)))[0] = pointer
        return 1

    def CredFree(self, pointer):
        self.freed.append(ctypes.addressof(pointer.contents))

    def CredDeleteW(self, target, kind, flags):
        if target not in self.values:
            self.error = 1168
            return 0
        del self.values[target]
        return 1

    def get_last_error(self):
        return self.error


def test_real_ctypes_credential_structure_roundtrip_uses_only_fake_winapi(tmp_path):
    winapi = FakeWinAPI()
    backend = WindowsCredentialStore(api=winapi)
    target = credential_target(tmp_path)
    assert backend.read(target) is None
    backend.write(target, NEW)
    assert winapi.written == [(1, 2, "AletheiaNexus")]
    assert winapi.values[target] == NEW.encode("utf-16-le")
    assert backend.read(target) == NEW and len(winapi.freed) == 1
    assert backend.delete(target) and backend.read(target) is None
    assert backend.delete(target) is False
    assert NEW not in target and str(tmp_path) not in target
