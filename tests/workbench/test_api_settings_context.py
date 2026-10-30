"""Context API wiring uses fake credentials and never starts a remote request."""

import threading

import pytest

from aletheia_nexus.ui_cli import create_context
from aletheia_nexus.workbench import api_settings
from aletheia_nexus.workbench.settings import SettingsStore


class FakeStore:
    def __init__(self):
        self.reads = []

    def read(self, target):
        self.reads.append(target)
        return "fixture-workspace-key"


@pytest.fixture
def context(tmp_path, monkeypatch):
    backend = FakeStore()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "")
    monkeypatch.setattr(api_settings, "_backend", lambda _: backend)
    settings = SettingsStore(tmp_path / "workspace")
    settings.set("api", {"base_url": "https://api.deepseek.com/v1"})
    context = create_context(tmp_path / "library", tmp_path / "workspace")
    try:
        yield context, backend
    finally:
        context.jobs.close(wait=True)
        context.research.close()


def test_startup_loads_workspace_credentials_once_and_shares_service_across_leases(
    context,
):
    ctx, store = context
    assert store.reads == [api_settings.credential_target(ctx.workspace)]
    assert ctx.api_credentials["source"] == "windows"
    assert ctx.api_settings.status()["base_url"] == "https://api.deepseek.com/v1"
    assert ctx.api_settings.status()["configured"] is True
    assert ctx.lease().api_settings is ctx.lease().api_settings is ctx.api_settings
    assert "fixture-workspace-key" not in ctx.settings.path.read_text(encoding="utf-8")
    before = ctx.api_settings
    ctx.switch_root(ctx.root.parent / "other-library")
    assert ctx.api_settings is before and len(store.reads) == 1


def test_configuration_change_is_blocked_until_any_active_work_is_terminal(context):
    ctx, _ = context
    entered, release = threading.Event(), threading.Event()

    def waiting(_):
        entered.set()
        assert release.wait(3)
        return {"status": "COMPLETED"}

    receipt = ctx.jobs.submit("parse", "仅本地合成门禁测试", [], waiting)
    try:
        assert entered.wait(2)
        before = ctx.settings.path.read_bytes()
        assert ctx.can_change_api_configuration() is False
        with pytest.raises(ValueError, match="仍有任务"):
            ctx.api_settings.save(
                base_url="https://api.deepseek.com", api_key="fixture-new-key"
            )
        assert ctx.settings.path.read_bytes() == before
    finally:
        release.set()
        ctx.jobs._futures[receipt["id"]].result(timeout=3)
    assert ctx.can_change_api_configuration() is True
    assert (
        ctx.api_settings.save(base_url="https://api.deepseek.com")["base_url"]
        == "https://api.deepseek.com"
    )
