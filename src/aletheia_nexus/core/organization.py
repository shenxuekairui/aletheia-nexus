"""Portable, relative library destinations; never interpret input as shell paths."""

import re
from pathlib import Path

_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def normalize_folder(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("folder must be a non-empty relative path")
    parts = value.replace("\\", "/").split("/")
    if (
        any(
            not p
            or p in {".", ".."}
            or p != p.strip().rstrip(".")
            or _INVALID.search(p)
            or _RESERVED.match(p)
            or len(p) > 80
            or p.casefold() in {"_unverified", "_browser-downloads", "_tmp"}
            for p in parts
        )
        or len(value) > 160
    ):
        raise ValueError(
            "folder must contain safe relative names, not absolute paths or '..'"
        )
    return "/".join(parts)


def destination(root: str | Path, folder: str | None) -> Path:
    base = Path(root).resolve()
    folder = normalize_folder(folder)
    target = (base / folder).resolve() if folder else base
    if not target.is_relative_to(base):
        raise ValueError("folder resolves outside the output directory")
    return target


def filename_stem(value: str) -> str:
    stem = _INVALID.sub("_", value)
    stem = " ".join(stem.split()).strip(" .")
    if not stem or _RESERVED.match(stem):
        stem = "paper_" + stem
    # Bound UTF-8 bytes too, so a Chinese title fits Linux filename limits.
    return stem.encode("utf-8")[:140].decode("utf-8", errors="ignore").rstrip(" .")
