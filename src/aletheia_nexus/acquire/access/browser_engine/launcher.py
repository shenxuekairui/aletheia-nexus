"""Ordinary dedicated-browser launch, profile ownership and safe CDP reuse.

The browser outlives the acquisition client. Only the short-lived profile lease
is released on disconnect; cookies, browser windows and history are untouched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from .runtime import (
    fixed_installed_browser,
    fixed_portable_browser,
    installed_browser_candidates,
)


class NormalBrowserError(RuntimeError):
    """An actionable launcher error without credentials or raw browser output."""


class ProfileLease:
    """An OS-released lock: two AN clients must not acquire in one profile."""

    def __init__(self, profile: Path):
        self._handle = None
        handle = (profile / ".an-acquisition.lock").open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise NormalBrowserError(
                "This AN profile is already in use by another acquisition task. "
                "Wait for it to finish or select a different --profile."
            ) from exc
        self._handle = handle

    def close(self):
        handle, self._handle = self._handle, None
        if handle is not None:
            # Closing releases both Windows byte locks and POSIX flock locks,
            # including after a failed launch. Do not delete the lock inode.
            handle.close()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _active_endpoint(profile: Path) -> str | None:
    """Match the profile's browser ID, not just a potentially recycled port."""
    try:
        active_port = profile / "DevToolsActivePort"
        if active_port.stat().st_size > 1024:
            return None
        lines = active_port.read_text(encoding="utf-8").splitlines()
        port, browser_path = int(lines[0]), lines[1]
        if not 1 <= port <= 65535 or not re.fullmatch(
            r"/devtools/browser/[A-Za-z0-9-]{1,128}", browser_path
        ):
            return None
        endpoint = f"http://127.0.0.1:{port}"
        # Never send this local control request through the OS proxy or follow
        # a redirect to a different endpoint.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(f"{endpoint}/json/version", timeout=0.5) as response:
            payload = json.loads(response.read(65536))
        websocket = urlsplit(payload["webSocketDebuggerUrl"])
        if (
            websocket.scheme != "ws"
            or websocket.hostname not in {"127.0.0.1", "localhost", "::1"}
            or websocket.port != port
            or websocket.path != browser_path
            or websocket.username
            or websocket.password
            or websocket.query
            or websocket.fragment
        ):
            return None
        return f"ws://127.0.0.1:{port}{browser_path}"
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def _executable(chromium, *, channel: str | None, executable_path) -> Path:
    if executable_path is not None:
        selected = Path(executable_path).expanduser()
    elif channel == "chromium":
        selected = Path(chromium.executable_path)
    else:
        if channel not in {None, "chrome", "msedge"}:
            raise NormalBrowserError(
                "Normal launch supports chrome, msedge or chromium channels. "
                "For another channel use --executable-path or "
                "--browser-launch-mode managed."
            )
        installed = fixed_installed_browser()
        portable = fixed_portable_browser()
        if channel is None and installed:
            selected = installed[1]
        elif channel is None and portable:
            selected = portable
        else:
            candidates = []
            if os.name == "nt":
                candidates = [
                    path
                    for name, path in installed_browser_candidates()
                    if channel is None or name == channel
                ]
            elif sys.platform == "darwin":
                candidates = [
                    Path("/Applications") / product / "Contents/MacOS" / binary
                    for name, product, binary in (
                        ("chrome", "Google Chrome.app", "Google Chrome"),
                        ("msedge", "Microsoft Edge.app", "Microsoft Edge"),
                    )
                    if channel is None or name == channel
                ]
            else:
                candidates = [
                    Path(found)
                    for name, binary in (
                        ("chrome", "google-chrome"),
                        ("chrome", "google-chrome-stable"),
                        ("msedge", "microsoft-edge"),
                        ("msedge", "microsoft-edge-stable"),
                    )
                    if (channel is None or name == channel)
                    and (found := shutil.which(binary))
                ]
            selected = next((p for p in candidates if p.is_file()), None)
            if selected is None and channel is None:
                selected = Path(chromium.executable_path)
    if selected is None or not selected.is_file():
        raise NormalBrowserError(
            "No browser executable is available for normal launch. "
            "Install a supported Chrome/Edge or set --executable-path."
        )
    return selected.resolve()


def normal_browser_endpoint(
    chromium,
    profile: Path,
    *,
    channel=None,
    executable_path=None,
    use_system_proxy: bool = False,
    timeout: float = 20.0,
) -> str:
    """Reuse a registered browser, or launch one with ordinary minimal flags.

    The caller must hold ProfileLease until its Playwright client disconnects.
    Do not silently restart, switch proxy settings, or fall back to managed mode.
    """
    endpoint = _active_endpoint(profile)
    metadata_path = profile / ".an-normal-browser.json"
    if endpoint:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict) or metadata.get("endpoint") != endpoint:
            raise NormalBrowserError(
                "An unregistered browser is already using this profile. "
                "Attach explicitly with --cdp-endpoint, or close only that AN "
                "browser before trying normal launch."
            )
        changed = metadata.get("use_system_proxy") != use_system_proxy
        if executable_path is not None or channel is not None:
            selected = _executable(
                chromium, channel=channel, executable_path=executable_path
            )
            changed |= str(selected) != metadata.get("executable")
        if changed:
            raise NormalBrowserError(
                "The existing AN browser uses different network/runtime settings. "
                "Close that dedicated browser to apply the requested settings; "
                "AN will not interrupt authentication or restart it automatically."
            )
        return endpoint

    selected = _executable(chromium, channel=channel, executable_path=executable_path)
    args = [
        str(selected),
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not use_system_proxy:
        args.append("--no-proxy-server")
    args.append("about:blank")
    options = (
        {"start_new_session": True}
        if os.name != "nt"
        else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
        }
    )
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **options,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        endpoint = _active_endpoint(profile)
        if endpoint:
            metadata_path.write_text(
                json.dumps(
                    {
                        "endpoint": endpoint,
                        "executable": str(selected),
                        "use_system_proxy": use_system_proxy,
                    }
                ),
                encoding="utf-8",
            )
            return endpoint
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise NormalBrowserError(
        "The normal browser did not expose its local control endpoint. "
        "The profile may already be open in another browser; use --cdp-endpoint "
        "to attach explicitly or close only the dedicated AN browser."
    )
