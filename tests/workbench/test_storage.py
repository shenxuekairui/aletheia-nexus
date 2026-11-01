import time
from pathlib import Path
from threading import Event

import pytest
from test_research_app import write_pdf
from test_research_revision_app import save_fixture_result

from aletheia_nexus.storage_paths import PathPreferences, StoragePaths, relocate_path
from aletheia_nexus.ui_cli import create_context
from aletheia_nexus.workbench import storage


def close(ctx):
    ctx.jobs.close(wait=True)
    ctx.research.close()


@pytest.fixture
def configured(tmp_path):
    prefs = PathPreferences(tmp_path / "user-config")
    paths = StoragePaths(
        tmp_path / "library",
        tmp_path / "library" / ".an-workbench",
        tmp_path / "workspace",
    )
    prefs.save(paths)
    ctx = create_context(
        paths.library, paths.workspace, paths.library_state_dir, preferences=prefs
    )
    yield ctx, prefs, paths
    close(ctx)


def wait(ctx, receipt):
    for _ in range(500):
        row = ctx.jobs.get(receipt["id"])
        if row["status"] == "COMPLETED":
            return row
        time.sleep(0.01)
    raise AssertionError(row)


@pytest.mark.parametrize("kind", ["library", "library_state_dir", "workspace"])
def test_migrate_reopen_and_use_papers_index_tasks_parses_results(
    configured, tmp_path, kind
):
    ctx, prefs, paths = configured
    incoming = tmp_path / "input.pdf"
    write_pdf(
        incoming,
        [[(50, 650, 12, "A sample was measured at 25 C for 2 h.")]],
        title="Storage fixture",
    )
    paper = ctx.library.import_pdf(
        incoming, title="Storage fixture", tags=["保留标签"], folder="化学"
    )
    attachment = Path(paper["pdf_path"]).parent / "SI" / "data.txt"
    attachment.parent.mkdir()
    attachment.write_text("supplement", encoding="utf-8")
    ctx.library.register_attachment(paper["pdf_path"], attachment)
    ctx.library.save_collection("历史集合", [paper["id"]])
    ctx.library.update_metadata(paper["id"], custom_name="我的论文")
    parsed = ctx.research.parse([paper["id"]], include_si=False)
    assert parsed["status"] == "COMPLETED"
    versions = ctx.research.versions(paper["id"])[0]["versions"]
    result_path, result = save_fixture_result(ctx.research.app, Path(paper["pdf_path"]))
    original_result = result_path.read_bytes()
    task = ctx.jobs.submit(
        "fixture", "历史任务", [], lambda _: {"outputs": [str(result_path)]}
    )
    wait(ctx, task)
    source = getattr(paths, kind)
    before = {
        p.relative_to(source): p.read_bytes()
        for p in source.rglob("*")
        if p.is_file() and p.name not in {"library.lock", ".owner.lock", ".owner"}
    }
    lease = ctx.lease()
    target = tmp_path / ("new-" + kind)
    report = ctx.storage.change(kind, target)
    assert report["restart_required"] and report["files"] == len(before)
    assert all(
        (target / name).read_bytes() == content for name, content in before.items()
    )
    assert all(
        (source / name).read_bytes() == content for name, content in before.items()
    )
    with pytest.raises(ValueError, match="重新启动"):
        lease.library
    with pytest.raises(ValueError, match="重新启动"):
        ctx.jobs.submit("fixture", "blocked", [], lambda _: None)
    close(ctx)
    # Original copies can be offline after migration. Nothing may fall back to them.
    offline = source.with_name(source.name + "-offline")
    source.rename(offline)
    resolved = prefs.resolve()
    assert getattr(resolved, kind) == target
    reopened = create_context(
        resolved.library,
        resolved.workspace,
        resolved.library_state_dir,
        preferences=prefs,
    )
    try:
        row = reopened.library.get(paper["id"])
        assert row["custom_name"] == "我的论文" and row["tags"] == ["保留标签"]
        assert row["attachments"][0]["exists"]
        assert reopened.library.collections()["历史集合"] == [paper["id"]]
        reopened.library.update_tags([paper["id"]], add=["迁移后"])
        assert "迁移后" in reopened.library.get(paper["id"])["tags"]
        new_versions = reopened.research.versions(paper["id"])[0]["versions"]
        assert len(new_versions) == len(versions)
        reopened.research.app.check_document(
            new_versions[0]["document"], "parsed"
        ).verify()
        old_output = reopened.jobs.get(task["id"])["result"]["outputs"][0]
        assert Path(old_output).is_file()
        new_result = relocate_path(result_path, prefs.read()["relocations"])
        assert new_result.read_bytes() == original_result
        assert (
            reopened.research.app.read_research_result(str(result_path))["artifact_id"]
            == result["artifact_id"]
        )
        assert reopened.research.app.export_research_results(
            [str(result_path)], "after-move"
        )["outputs"]
        citation = {
            "id": result["package"]["documents"][0]["id"],
            **result["package"]["documents"][0]["locators"],
        }
        reopened.research.app.check_document(citation, "parsed").verify()
    finally:
        close(reopened)


@pytest.mark.parametrize("kind", ["library", "library_state_dir", "workspace"])
def test_empty_directory_switch_does_not_copy(configured, tmp_path, kind):
    ctx, prefs, paths = configured
    target = tmp_path / ("empty-" + kind)
    target.mkdir()
    ctx.storage.change(kind, target, migrate=False)
    assert not list(target.iterdir())
    assert getattr(prefs.resolve(), kind) == target
    assert not prefs.read()["relocations"]
    if kind == "library":
        assert prefs.resolve().library_state_dir == target / ".an-workbench"


@pytest.mark.parametrize(
    "bad", ["nonempty", "nested", "same", "parent", "relative", "file"]
)
def test_reject_unusable_destinations_without_switching(configured, tmp_path, bad):
    ctx, prefs, paths = configured
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    candidates = {
        "nonempty": target,
        "nested": paths.workspace / "nested",
        "same": paths.workspace,
        "parent": tmp_path,
        "relative": "relative",
        "file": target / "keep.txt",
    }
    before = prefs.path.read_bytes()
    with pytest.raises((ValueError, OSError)):
        ctx.storage.change("workspace", candidates[bad])
    assert prefs.path.read_bytes() == before and not ctx.storage.restart_required
    assert not ctx.jobs.storage_blocked
    assert (target / "keep.txt").read_text() == "keep"


@pytest.mark.parametrize("failure", ["copy", "hash", "save"])
def test_failed_migration_keeps_original_and_configuration(
    configured, tmp_path, monkeypatch, failure
):
    ctx, prefs, paths = configured
    (paths.workspace / "data.txt").write_text("valuable")
    before = prefs.path.read_bytes()
    if failure == "copy":
        monkeypatch.setattr(
            storage.shutil,
            "copyfileobj",
            lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        )
    elif failure == "save":
        monkeypatch.setattr(
            prefs,
            "save",
            lambda *_, **__: (_ for _ in ()).throw(OSError("config write failed")),
        )
    else:
        original = storage.sha256_file
        monkeypatch.setattr(
            storage,
            "sha256_file",
            lambda p: (
                "bad" if Path(p).is_relative_to(tmp_path / "target") else original(p)
            ),
        )
    with pytest.raises((OSError, ValueError)):
        ctx.storage.change("workspace", tmp_path / "target")
    assert prefs.path.read_bytes() == before
    assert (paths.workspace / "data.txt").read_text() == "valuable"
    assert not ctx.storage.restart_required and not ctx.jobs.storage_blocked


def test_running_task_blocks_migration(configured, tmp_path):
    ctx, prefs, paths = configured
    release, started = Event(), Event()

    def worker(_):
        started.set()
        assert release.wait(10)

    task = ctx.jobs.submit("fixture", "running", [], worker)
    assert started.wait(3)
    try:
        with pytest.raises(ValueError, match="等待"):
            ctx.storage.change("library", tmp_path / "new")
        assert not (tmp_path / "new").exists()
    finally:
        release.set()
    wait(ctx, task)


@pytest.mark.parametrize("nested", [False, True])
def test_native_research_or_mcp_owner_blocks_migration(configured, tmp_path, nested):
    from aletheia_nexus.research_app import _lock_job_owner

    ctx, prefs, paths = configured
    base = paths.workspace / "research-workspace" if nested else paths.workspace
    owner_path = base / "jobs" / "native-job" / ".owner"
    owner_path.parent.mkdir(parents=True)
    owner = _lock_job_owner(owner_path, create=True)
    try:
        with pytest.raises(ValueError, match="MCP"):
            ctx.storage.change("workspace", tmp_path / "target")
        assert not ctx.jobs.storage_blocked
        assert prefs.resolve() == paths
    finally:
        owner.close()
    assert ctx.storage.change("workspace", tmp_path / "target")["restart_required"]


def test_workspace_migration_preserves_windows_credential_scope(configured, tmp_path):
    from test_api_settings import FakeStore

    from aletheia_nexus.workbench.api_settings import credential_target

    ctx, prefs, paths = configured
    backend = FakeStore()
    secret = "fixture-secret-only-in-credential-store"
    backend.values[credential_target(paths.workspace)] = secret
    ctx.api_settings.backend = backend
    ctx.settings.set("api", {"storage": "windows"})
    target = tmp_path / "new-workspace"
    ctx.storage.change("workspace", target)
    assert backend.values[credential_target(target)] == secret
    assert backend.values[credential_target(paths.workspace)] == secret
    assert secret not in prefs.path.read_text(encoding="utf-8")
    assert all(
        secret not in p.read_text(encoding="utf-8") for p in target.rglob("*.json")
    )
