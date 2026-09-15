import hashlib
import json
import os
import re
from pathlib import Path

from aletheia_nexus.acquire.fulltext.models import RetrievedResource

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _doi_stem(doi: str) -> str:
    stem = _SAFE_FILENAME.sub("_", doi).strip("._")
    return stem[:120] or "paper"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def promote_resource(
    resource: RetrievedResource,
    *,
    doi: str,
    output_dir: str | Path,
    subdirectory: str | None = None,
) -> Path:
    """Atomically promote a temporary file into deterministic local storage."""

    directory = Path(output_dir)
    if subdirectory:
        directory = directory / subdirectory
    directory.mkdir(parents=True, exist_ok=True)

    final_path = directory / f"{_doi_stem(doi)}-{resource.sha256[:12]}.pdf"

    if final_path.exists():
        if _sha256_file(final_path) != resource.sha256:
            raise OSError(
                f"Existing file hash conflicts with target path: {final_path}"
            )
        resource.local_path.unlink(missing_ok=True)
        return final_path

    os.replace(resource.local_path, final_path)
    return final_path


def write_json_sidecar(
    pdf_path: str | Path,
    payload: dict[str, object],
) -> Path:
    """Atomically write acquisition provenance next to a stored PDF."""

    pdf = Path(pdf_path)
    sidecar = pdf.with_suffix(".acquisition.json")
    temporary = sidecar.with_suffix(sidecar.suffix + ".part")

    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    os.replace(temporary, sidecar)
    return sidecar
