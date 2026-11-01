"""Real production HTTP startup from Windows System32 and other directories."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

from aletheia_nexus.storage_paths import PathPreferences, StoragePaths
from aletheia_nexus.ui_cli import create_context

pytest.importorskip("nicegui")


def launch(cwd, home, extra, log_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home))
    env.pop("PYTEST_CURRENT_TEST", None)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "aletheia_nexus.ui_cli",
                "--no-open",
                "--port",
                str(port),
                *extra,
            ],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 40
            with httpx.Client(trust_env=False, timeout=2) as client:
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text(encoding="utf-8")
                    try:
                        response = client.get(f"http://127.0.0.1:{port}/")
                        assert response.status_code == 200, response.text
                        assert "溯光" in response.text
                        return
                    except httpx.TransportError:
                        time.sleep(0.1)
                pytest.fail(log_path.read_text(encoding="utf-8"))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_real_default_startup_and_explicit_overrides(tmp_path):
    home = tmp_path / "isolated-home"
    home.mkdir()
    desktop = home / "Desktop"
    desktop.mkdir()
    system = (
        Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
        if os.name == "nt"
        else tmp_path
    )
    prefs = PathPreferences(home / ".aletheia-nexus")
    library = home / "AN-Library"
    launch(system, home, ["--library", str(library)], tmp_path / "system32.log")
    expected = prefs.resolve()
    assert expected.workspace == home / ".aletheia-nexus" / "workbench"
    assert expected.library == library
    for number, cwd in enumerate((desktop, Path(__file__).resolve().parents[2])):
        launch(cwd, home, [], tmp_path / f"restart-{number}.log")
        assert prefs.resolve() == expected
    custom = [
        "--library",
        str(home / "custom-library"),
        "--workspace",
        str(home / "custom-workspace"),
        "--library-state-dir",
        str(home / "custom-index"),
    ]
    launch(system, home, custom, tmp_path / "explicit.log")
    assert prefs.resolve().workspace == home / "custom-workspace"
    assert prefs.resolve().library_state_dir == home / "custom-index"


@pytest.mark.skipif(
    os.name != "nt" or not Path("D:/").is_dir(),
    reason="requires Windows C and D volumes",
)
def test_actual_c_to_d_and_restart(tmp_path):
    # TemporaryDirectory cleans up only these test-owned paths after handles close.
    with (
        tempfile.TemporaryDirectory(prefix="an082-source-") as source_name,
        tempfile.TemporaryDirectory(prefix="an082-target-", dir="D:/") as target_name,
    ):
        source, target = Path(source_name), Path(target_name)
        assert source.drive.upper() == "C:"
        prefs = PathPreferences(source / "config")
        paths = StoragePaths(source / "library", source / "index", source / "workspace")
        prefs.save(paths)
        from test_research_app import write_pdf
        from test_research_revision_app import save_fixture_result

        seeded = create_context(
            paths.library, paths.workspace, paths.library_state_dir, preferences=prefs
        )
        try:
            incoming = source / "input.pdf"
            write_pdf(
                incoming,
                [[(50, 650, 12, "A sample was measured at 25 C.")]],
                title="Cross-volume fixture",
            )
            paper = seeded.library.import_pdf(
                incoming, title="Cross-volume fixture", tags=["跨盘标签"]
            )
            seeded.library.save_collection("跨盘集合", [paper["id"]])
            assert (
                seeded.research.parse([paper["id"]], include_si=False)["status"]
                == "COMPLETED"
            )
            result_path, result = save_fixture_result(
                seeded.research.app, Path(paper["pdf_path"])
            )
            task = seeded.jobs.submit(
                "fixture", "跨盘任务", [], lambda _: {"outputs": [str(result_path)]}
            )
            for _ in range(300):
                if seeded.jobs.get(task["id"])["status"] == "COMPLETED":
                    break
                time.sleep(0.01)
            assert seeded.jobs.get(task["id"])["status"] == "COMPLETED"
        finally:
            seeded.jobs.close(wait=True)
            seeded.research.close()
        for kind in ("library", "library_state_dir", "workspace"):
            paths = prefs.resolve()
            ctx = create_context(
                paths.library,
                paths.workspace,
                paths.library_state_dir,
                preferences=prefs,
            )
            try:
                location = getattr(paths, kind)
                (location / "中文数据.txt").write_text(kind, encoding="utf-8")
                ctx.storage.change(kind, target / kind)
            finally:
                ctx.jobs.close(wait=True)
                ctx.research.close()
            again = prefs.resolve()
            assert (getattr(again, kind) / "中文数据.txt").read_text(
                encoding="utf-8"
            ) == kind
            assert (location / "中文数据.txt").is_file()
        reopened = create_context(
            again.library, again.workspace, again.library_state_dir, preferences=prefs
        )
        try:
            row = reopened.library.get(paper["id"])
            assert row["tags"] == ["跨盘标签"]
            assert Path(row["pdf_path"]).drive.upper() == "D:"
            assert reopened.library.collections()["跨盘集合"] == [paper["id"]]
            version = reopened.research.versions(paper["id"])[0]["versions"][0][
                "document"
            ]
            assert Path(version["artifact"]).drive.upper() == "D:"
            reopened.research.app.check_document(version, "parsed").verify()
            assert reopened.jobs.get(task["id"])["status"] == "COMPLETED"
            assert (
                reopened.research.app.read_research_result(str(result_path))[
                    "artifact_id"
                ]
                == result["artifact_id"]
            )
            assert reopened.research.app.export_research_results(
                [str(result_path)], "cross-volume"
            )["outputs"]
        finally:
            reopened.jobs.close(wait=True)
            reopened.research.close()
        assert all(
            Path(value).drive.upper() == "D:" for value in again.strings().values()
        )
        assert (
            json.loads(prefs.path.read_text(encoding="utf-8"))["paths"]
            == again.strings()
        )
