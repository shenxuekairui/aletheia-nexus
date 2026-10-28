"""Installed optional UI renders a real page, without browser/login/API access."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("nicegui")


def test_local_server_renders_and_rejects_external_origin(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    log_path = tmp_path / "server.log"
    environment = dict(os.environ)
    # A real subprocess must take NiceGUI's production path, not its in-process
    # pytest/screen fixture path inherited from the test runner.
    environment.pop("PYTEST_CURRENT_TEST", None)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "aletheia_nexus.ui_cli",
                "--library",
                str(tmp_path / "library"),
                "--workspace",
                str(tmp_path / "workspace"),
                "--port",
                str(port),
                "--no-open",
            ],
            cwd=tmp_path,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            url = f"http://127.0.0.1:{port}/"
            deadline = time.monotonic() + 35
            with httpx.Client(trust_env=False, timeout=2) as client:
                while True:
                    if process.poll() is not None:
                        pytest.fail(log_path.read_text(encoding="utf-8"))
                    try:
                        response = client.get(url)
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        if time.monotonic() > deadline:
                            pytest.fail(log_path.read_text(encoding="utf-8"))
                        time.sleep(0.1)
                assert response.status_code == 200, log_path.read_text(encoding="utf-8")
                assert "ALETHEIA NEXUS" in response.text
                assert (
                    client.get(
                        url, headers={"Origin": "https://external.invalid"}
                    ).status_code
                    == 403
                )
                assert (
                    client.get(url, headers={"Host": "external.invalid"}).status_code
                    == 403
                )
                assert client.get(url + "an-file/unknown").status_code == 404
                assert client.get(url + "an-file/..%2F.env").status_code == 404
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    assert Path(tmp_path / "workspace" / "settings.json").exists()


def test_old_page_lease_cannot_target_a_different_library(tmp_path):
    from aletheia_nexus.ui_cli import create_context

    context = create_context(tmp_path / "one", tmp_path / "workspace")
    try:
        page = context.lease()
        assert page.library.root == (tmp_path / "one").resolve()
        context.switch_root(tmp_path / "two")
        with pytest.raises(ValueError, match="刷新"):
            page.library.import_pdf("unused")
        assert context.lease().library.root == (tmp_path / "two").resolve()
    finally:
        context.jobs.close(wait=True)
        context.research.close()
