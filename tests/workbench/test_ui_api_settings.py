"""Actual API settings widgets use fake credentials and only a mock models route."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("nicegui")

from nicegui import run, ui

from aletheia_nexus.workbench import ui_api_settings
from aletheia_nexus.workbench.api_settings import ApiSettingsService
from aletheia_nexus.workbench.settings import SettingsStore

OLD = "fixture-old-key-not-real"
NEW = "fixture-new-key-not-real"


class FakeCredentialStore:
    def __init__(self):
        self.writes = []

    def write(self, target, value):
        self.writes.append((target, value))


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    callbacks, requests = {}, []
    original = ui.button

    def button(*args, **kwargs):
        element = original(*args, **kwargs)
        callbacks[args[0] if args else kwargs.get("text")] = (
            kwargs.get("on_click"),
            element,
        )
        return element

    allowed = {"value": True}
    settings = SettingsStore(tmp_path)
    environ = {"DEEPSEEK_API_KEY": OLD}
    backend = FakeCredentialStore()
    api = ApiSettingsService(
        settings,
        tmp_path,
        can_change=lambda: allowed["value"],
        environ=environ,
        credential_backend=backend,
    )
    original_check = api.check_connection

    def endpoint(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path.endswith("/models")
        assert not request.content
        return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})

    api.check_connection = lambda **kwargs: original_check(
        **kwargs, transport=httpx.MockTransport(endpoint)
    )

    async def io_bound(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(ui, "button", button)
    monkeypatch.setattr(ui_api_settings, "guard", lambda callback: callback)
    monkeypatch.setattr(run, "io_bound", io_bound)
    context = SimpleNamespace(
        settings=settings,
        workspace=tmp_path,
        api_settings=api,
        jobs=SimpleNamespace(list=lambda: []),
    )
    before = set(ui.context.client.elements)
    ui_api_settings.render_api_settings(context)

    def elements():
        return [
            element
            for key, element in ui.context.client.elements.items()
            if key not in before and not element.is_deleted
        ]

    def labeled(label):
        return next(
            element
            for element in elements()
            if getattr(element, "label", None) == label
        )

    return SimpleNamespace(
        api=api,
        allowed=allowed,
        settings=settings,
        environ=environ,
        backend=backend,
        callbacks=callbacks,
        requests=requests,
        elements=elements,
        key=labeled("新的 DeepSeek API 密钥（留空保留现有）"),
        base=labeled("接口基础地址"),
    )


def test_opening_card_never_checks_network_or_prefills_existing_key(mounted):
    fixture = mounted
    assert fixture.key.value == "" and fixture.key._props["type"] == "password"
    assert not fixture.requests and not fixture.backend.writes
    assert not fixture.settings.path.exists()
    assert any(
        "环境变量" in getattr(element, "text", "") for element in fixture.elements()
    )
    assert all(
        OLD
        not in str(getattr(element, "text", "")) + str(getattr(element, "value", ""))
        for element in fixture.elements()
    )


def test_save_clears_password_and_changes_actual_session_defaults_without_model_call(
    mounted,
):
    fixture = mounted
    fixture.key.set_value(NEW)
    fixture.base.set_value("https://api.deepseek.com/v1")
    asyncio.run(fixture.callbacks["保存 API 配置"][0]())
    assert fixture.environ["DEEPSEEK_API_KEY"] == NEW
    assert fixture.environ["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com/v1"
    assert fixture.settings.get("api")["base_url"] == "https://api.deepseek.com/v1"
    assert (
        fixture.key.value == "" and not fixture.requests and not fixture.backend.writes
    )
    assert NEW not in fixture.settings.path.read_text(encoding="utf-8")
    assert any(
        "本次设置的会话密钥" in getattr(element, "text", "")
        for element in fixture.elements()
    )


def test_check_button_only_queries_models_and_does_not_save_typed_key(mounted):
    fixture = mounted
    fixture.key.set_value(NEW)
    fixture.base.set_value("https://api.deepseek.com/v1")
    asyncio.run(fixture.callbacks["检查连接（不发论文）"][0]())
    assert len(fixture.requests) == 1
    assert fixture.requests[0].headers["Authorization"] == "Bearer " + NEW
    assert fixture.environ == {"DEEPSEEK_API_KEY": OLD}
    assert not fixture.settings.path.exists() and not fixture.backend.writes
    assert any(
        "检查不会保存输入" in getattr(element, "text", "")
        for element in fixture.elements()
    )


def test_active_work_blocks_save_and_failure_unlocks_for_explicit_retry(mounted):
    fixture = mounted
    fixture.allowed["value"] = False
    fixture.key.set_value(NEW)
    with pytest.raises(ValueError, match="仍有任务"):
        asyncio.run(fixture.callbacks["保存 API 配置"][0]())
    assert (
        fixture.environ == {"DEEPSEEK_API_KEY": OLD}
        and not fixture.settings.path.exists()
    )
    assert fixture.key.value == "" and fixture.callbacks["保存 API 配置"][1].enabled
    fixture.allowed["value"] = True
    fixture.key.set_value(NEW)
    asyncio.run(fixture.callbacks["保存 API 配置"][0]())
    assert fixture.environ["DEEPSEEK_API_KEY"] == NEW


def test_double_save_is_one_snapshotted_operation(mounted, monkeypatch):
    fixture = mounted
    fixture.key.set_value(NEW)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def delayed(function, *args, **kwargs):
            calls.append(kwargs.copy())
            entered.set()
            await release.wait()
            return function(*args, **kwargs)

        monkeypatch.setattr(run, "io_bound", delayed)
        callback, button = fixture.callbacks["保存 API 配置"]
        first = asyncio.create_task(callback())
        await entered.wait()
        assert not button.enabled and not fixture.key.enabled
        await callback()
        assert len(calls) == 1 and fixture.environ["DEEPSEEK_API_KEY"] == OLD
        release.set()
        await first
        assert fixture.environ["DEEPSEEK_API_KEY"] == NEW and button.enabled

    asyncio.run(scenario())
