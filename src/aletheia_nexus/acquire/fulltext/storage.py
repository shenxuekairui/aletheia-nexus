import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from aletheia_nexus.acquire.fulltext.models import RetrievedResource
from aletheia_nexus.core.models import PaperMetadata
from aletheia_nexus.core.organization import filename_stem
from aletheia_nexus.core.paper_request import PaperRequest

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_ORGANIZATION: ContextVar[PaperRequest | None] = ContextVar(
    "an_organization", default=None
)
_METADATA: ContextVar[PaperMetadata | None] = ContextVar(
    "an_output_metadata", default=None
)


@contextmanager
def organized_output(request: PaperRequest | None):
    """Scope storage policy to one acquisition without altering provider/identity APIs."""
    token = _ORGANIZATION.set(request)
    try:
        yield
    finally:
        _ORGANIZATION.reset(token)


@contextmanager
def output_metadata(metadata: PaperMetadata | None):
    """Reuse already-resolved bibliography for naming, without extra network work."""
    token = _METADATA.set(metadata)
    try:
        yield
    finally:
        _METADATA.reset(token)


def _publication_fields(doi, *, year=None, journal=None):
    organization = _ORGANIZATION.get()
    metadata = _METADATA.get()
    if metadata is not None and getattr(metadata, "doi", None) != doi:
        metadata = None
    return (
        (organization.year if organization else None)
        or year
        or getattr(metadata, "year", None),
        (organization.journal if organization else None)
        or journal
        or getattr(metadata, "journal", None),
    )


def _doi_stem(doi: str) -> str:
    stem = _SAFE_FILENAME.sub("_", doi).strip("._")
    return stem[:120] or "paper"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_verified_record(payload: object) -> bool:
    """Check recorded acquisition evidence, not a substitute for PDF validation."""
    if not isinstance(payload, dict):
        return False
    schema = payload.get("schema")
    if not isinstance(schema, str) or schema not in {
        "aletheia-nexus/acquisition-record/v1",
        "aletheia-nexus/access-acquisition-record/v1",
    }:
        return False
    fields = [
        payload.get(key)
        for key in ("target", "retrieval", "pdf_validation", "identity_validation")
    ]
    if not all(isinstance(field, dict) for field in fields):
        return False
    target, retrieval, pdf, identity = fields
    digest = retrieval.get("sha256")
    pages = pdf.get("page_count")
    return bool(
        payload.get("status") == "VERIFIED"
        and (target.get("doi") or target.get("article_id"))
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest)
        and pdf.get("valid_pdf") is True
        and type(pages) is int
        and pages > 0
        and identity.get("status") == "MATCH"
        and identity.get("document_role") == "ARTICLE"
    )


def promote_resource(
    resource: RetrievedResource,
    *,
    doi: str,
    output_dir: str | Path,
    subdirectory: str | None = None,
    title: str | None = None,
    year: int | None = None,
    journal: str | None = None,
) -> tuple[Path, bool]:
    """Atomically promote a temporary file into deterministic local storage.

    Returns ``(path, created_new)`` so callers can distinguish a newly promoted
    file from a previously verified identical file that was safely reused.
    """

    if resource.local_path is None:
        raise ValueError("Cannot promote a resource whose local file was removed")

    directory = Path(output_dir)
    if subdirectory:
        directory = directory / subdirectory
    directory.mkdir(parents=True, exist_ok=True)

    stem = _doi_stem(doi)
    organization = _ORGANIZATION.get()
    year, journal = _publication_fields(doi, year=year, journal=journal)
    custom_name = organization.filename if organization else None
    effective_title = title or (organization.title if organization else None)
    if organization is not None or effective_title or year or journal:
        label = custom_name or "-".join(
            str(part).strip()
            for part in (year, journal, effective_title or doi)
            if part is not None and str(part).strip()
        )
        # Identity + content prevent collisions even for identical titles.
        identity = hashlib.sha256(doi.encode()).hexdigest()[:10]
        stem = f"{filename_stem(label)}--{identity}"
    final_path = directory / f"{stem}-{resource.sha256[:12]}.pdf"

    if final_path.is_symlink():
        raise OSError("Refusing to use a symbolic link as an output PDF")
    if final_path.exists():
        if _sha256_file(final_path) != resource.sha256:
            raise OSError(
                f"Existing file hash conflicts with target path: {final_path}"
            )
        resource.local_path.unlink(missing_ok=True)
        return final_path, False

    os.replace(resource.local_path, final_path)
    return final_path, True


def write_json_sidecar(
    pdf_path: str | Path,
    payload: dict[str, object],
    *,
    year: int | None = None,
    journal: str | None = None,
    preserve_existing: bool = False,
) -> Path:
    """Atomically write acquisition provenance next to a stored PDF."""

    pdf = Path(pdf_path)
    organization = _ORGANIZATION.get()
    if organization is not None:
        year, journal = _publication_fields(
            payload.get("target", {}).get("doi"), year=year, journal=journal
        )
        payload = dict(payload)
        payload["organization"] = {
            "folder": organization.folder or "",
            "filename": pdf.name,
            "tags": list(organization.tags),
            "title": payload.get("target", {}).get("expected_title")
            or organization.title,
            "year": year,
            "journal": journal,
        }
    sidecar = pdf.with_suffix(".acquisition.json")
    if sidecar.is_symlink():
        raise OSError("Refusing a symbolic link as acquisition provenance")
    if preserve_existing and sidecar.exists():
        existing = json.loads(sidecar.read_text(encoding="utf-8"))
        # The first verified acquisition is evidence used by parsed artifacts.
        # Re-fetching identical bytes must not change its timestamp or provenance.
        if is_verified_record(existing) and is_verified_record(payload):
            old_target, new_target = existing["target"], payload["target"]
            identity_key = "doi" if new_target.get("doi") else "article_id"
            if (
                old_target.get(identity_key) == new_target.get(identity_key)
                and existing["retrieval"]["sha256"] == payload["retrieval"]["sha256"]
                and existing["pdf_validation"]["page_count"]
                == payload["pdf_validation"]["page_count"]
            ):
                return sidecar
        raise FileExistsError(
            "Existing acquisition evidence conflicts; it was not overwritten"
        )

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=sidecar.parent,
            prefix=f".{sidecar.name}.",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, sidecar)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise

    return sidecar
