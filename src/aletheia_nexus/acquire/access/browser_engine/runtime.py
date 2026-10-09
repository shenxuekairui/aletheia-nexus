"""Select safe runtimes without touching profiles or clearing download history."""

import ctypes
import os
import sys
from pathlib import Path

# Chromium issue 556160935: DevToolsDownloadManagerDelegate history-loading UAF.
_AFFECTED_DOWNLOAD_MAJORS = frozenset({152, 153, 154})


def affected_download_version(version: str) -> bool:
    try:
        return int(version.split(".", 1)[0]) in _AFFECTED_DOWNLOAD_MAJORS
    except (ValueError, AttributeError):
        return False


def windows_browser_major(path: Path) -> int | None:
    """Read PE version resources; never execute a binary to inspect its version."""
    if os.name != "nt" or not path.is_file():
        return None
    try:
        api = ctypes.WinDLL("version", use_last_error=True)
        api.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        api.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
        api.GetFileVersionInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        api.VerQueryValueW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        size = api.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not api.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        value, length = ctypes.c_void_p(), ctypes.c_uint32()
        if not api.VerQueryValueW(
            data, "\\", ctypes.byref(value), ctypes.byref(length)
        ):
            return None
        if length.value < 16:
            return None
        fixed = ctypes.string_at(value.value, 16)
        if int.from_bytes(fixed[:4], "little") != 0xFEEF04BD:
            return None
        return int.from_bytes(fixed[8:12], "little") >> 16
    except (OSError, AttributeError, ValueError):
        return None


def installed_browser_candidates():
    """Stable channels only; preview browsers require an explicit channel."""
    for channel, vendor, product, binary in (
        ("msedge", "Microsoft", "Edge", "msedge.exe"),
        ("chrome", "Google", "Chrome", "chrome.exe"),
    ):
        for root in (
            Path.home() / "AppData/Local",
            Path("C:/Program Files (x86)"),
            Path("C:/Program Files"),
        ):
            yield channel, root / vendor / product / "Application" / binary


def fixed_installed_browser() -> tuple[str, Path] | None:
    if os.name == "nt":
        for channel, path in installed_browser_candidates():
            major = windows_browser_major(path)
            if major is not None and major >= 155:
                return channel, path
    return None


def fixed_portable_browser() -> Path | None:
    """Use only an already-provisioned AN-owned Chrome for Testing runtime."""
    if os.name != "nt" and not sys.platform.startswith("linux"):
        return None
    root = Path.home() / ".aletheia-nexus/browser-runtimes"
    candidates = []
    suffix = "chrome-win64/chrome.exe" if os.name == "nt" else "chrome-linux64/chrome"
    for path in root.glob(f"chrome-*/{suffix}"):
        if os.name == "nt":
            major = windows_browser_major(path)
        else:
            # Provisioning validated the binary; launch checks its actual version
            # again before navigation. Folder names are only selection hints.
            try:
                major = int(path.parents[1].name.removeprefix("chrome-").split(".")[0])
            except ValueError:
                major = None
        if major is not None and major >= 155:
            candidates.append((major, path))
    return (
        max(candidates, key=lambda item: (item[0], str(item[1])))[1]
        if candidates
        else None
    )
