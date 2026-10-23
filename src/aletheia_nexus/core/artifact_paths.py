"""Keep generated JSON in a subdirectory while reading older flat downloads."""

from pathlib import Path


def json_output_path(flat_path: str | Path) -> Path:
    """Return the new location for a JSON file previously stored beside a PDF."""
    path = Path(flat_path)
    return path.parent / "json" / path.name


def find_json_path(flat_path: str | Path) -> Path:
    """Prefer the JSON directory, falling back to an existing legacy record.

    An invalid new record must not silently fall back to older evidence.
    """
    legacy = Path(flat_path)
    current = json_output_path(legacy)
    if current.exists() or current.is_symlink():
        return current
    if legacy.exists() or legacy.is_symlink():
        return legacy
    return current


def acquisition_sidecar_path(pdf_path: str | Path) -> Path:
    return find_json_path(Path(pdf_path).with_suffix(".acquisition.json"))
