"""Provision official stable Chrome for Testing into AN's private runtime folder.

No system installation, profile cleanup, security changes or browser restart.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
from zipfile import ZipFile

from aletheia_nexus.acquire.access.browser_engine.runtime import windows_browser_major

_MANIFEST = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)
_MAX_ARCHIVE = 700 * 1024 * 1024


def _runtime_platform() -> tuple[str, str]:
    if os.name == "nt":
        return "win64", "chrome-win64/chrome.exe"
    if sys.platform.startswith("linux"):
        import platform

        if platform.machine() in {"x86_64", "AMD64"}:
            return "linux64", "chrome-linux64/chrome"
    raise RuntimeError("Portable runtime provisioning supports Windows and Linux x64")


def _runtime_major(executable: Path, platform_name: str) -> int | None:
    if platform_name == "win64":
        return windows_browser_major(executable)
    result = subprocess.run(
        [str(executable), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    match = re.search(r"\b(\d+)\.\d+\.\d+\.\d+", result.stdout)
    return int(match[1]) if match else None


def _trusted_archive_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.netloc != "storage.googleapis.com"
        or not parts.path.startswith("/chrome-for-testing-public/")
        or not any(
            parts.path.endswith(f"/{kind}/chrome-{kind}.zip")
            for kind in ("win64", "linux64")
        )
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Unexpected Chrome for Testing archive URL")
    return url


def main() -> int:
    platform_name, binary_suffix = _runtime_platform()
    with urlopen(_MANIFEST, timeout=30) as response:
        stable = json.loads(response.read(2 * 1024 * 1024))["channels"]["Stable"]
    version = stable["version"]
    if (
        not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version)
        or int(version.split(".")[0]) < 155
    ):
        raise ValueError("Stable manifest does not contain a fixed browser >=155")
    url = _trusted_archive_url(
        next(
            row["url"]
            for row in stable["downloads"]["chrome"]
            if row["platform"] == platform_name
        )
    )
    root = Path.home() / ".aletheia-nexus/browser-runtimes"
    destination = root / f"chrome-{version}"
    executable = destination / binary_suffix
    if destination.exists():
        if _runtime_major(executable, platform_name) != int(version.split(".")[0]):
            raise RuntimeError("Existing runtime is incomplete; refusing to overwrite")
        print(f"AN runtime already available: {executable}")
        return 0
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="an-runtime-", dir=root) as temporary:
        stage = Path(temporary)
        if stage.resolve().parent != root.resolve():
            raise ValueError("Temporary runtime directory is outside AN runtime root")
        archive = stage / "chrome.zip"
        print(f"Downloading official Chrome for Testing {version} for AN", flush=True)
        with urlopen(url, timeout=30) as response, archive.open("wb") as output:
            _trusted_archive_url(response.geturl())
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_ARCHIVE:
                    raise ValueError("Browser archive exceeds size limit")
                output.write(chunk)
        unpacked = stage / "unpacked"
        unpacked.mkdir()
        with ZipFile(archive) as bundle:
            total = 0
            for entry in bundle.infolist():
                target = (unpacked / entry.filename).resolve()
                if not target.is_relative_to(unpacked.resolve()):
                    raise ValueError("Browser archive contains an unsafe path")
                total += entry.file_size
                if total > 2 * _MAX_ARCHIVE:
                    raise ValueError("Expanded browser archive exceeds size limit")
            bundle.extractall(unpacked)
            if platform_name == "linux64":
                for entry in bundle.infolist():
                    target = unpacked / entry.filename
                    if target.is_file():
                        # Restore executable bits, never set setuid/setgid bits.
                        target.chmod((entry.external_attr >> 16) & 0o777 or 0o644)
        unpacked_executable = unpacked / binary_suffix
        if _runtime_major(unpacked_executable, platform_name) != int(
            version.split(".")[0]
        ):
            raise ValueError("Downloaded binary version does not match manifest")
        # Move only our new staging directory; never replace an existing runtime.
        if destination.exists():
            raise RuntimeError(
                "Runtime appeared during provisioning; refusing overwrite"
            )
        if (
            not unpacked.resolve().is_relative_to(stage.resolve())
            or destination.resolve().parent != root.resolve()
        ):
            raise ValueError("Runtime move would leave its validated directory")
        unpacked.rename(destination)
    print(f"AN runtime ready: {executable}")
    return 0
