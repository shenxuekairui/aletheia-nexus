"""Bounded read workers perform every fresh authorization and byte check."""

import hashlib
import os
from collections import Counter
from threading import Lock

import pytest

from aletheia_nexus.processing.provider import ProcessingError
from aletheia_nexus.workbench.library import LibraryService
from aletheia_nexus.workbench.research import WorkbenchResearch


def test_parallel_boundaries_recheck_every_file_and_reject_same_stat_changes(
    tmp_path, monkeypatch
):
    from aletheia_nexus.workbench import research as module

    library = LibraryService(tmp_path / "library")
    service = WorkbenchResearch(library, tmp_path / "workspace")
    files = []
    for number in range(80):
        path = library.root / f"file-{number}.bin"
        path.write_bytes(f"original-{number:04}".encode())
        files.append(path)
    session = {
        "paths": [(str(path), path) for path in files],
        "files": [
            (path, hashlib.sha256(path.read_bytes()).hexdigest(), "source_changed")
            for path in files
        ],
        "documents": [],
    }
    original_path, original_hash = service.app.path, module.sha256_file
    calls, lock = Counter(), Lock()

    def authorize(path, **kwargs):
        with lock:
            calls[("path", str(path))] += 1
        return original_path(path, **kwargs)

    def fingerprint(path):
        with lock:
            calls[("hash", str(path))] += 1
        return original_hash(path)

    monkeypatch.setattr(service.app, "path", authorize)
    monkeypatch.setattr(module, "sha256_file", fingerprint)
    try:
        service._validate_search_session(session)
        service._validate_search_session(session)
        assert len(calls) == 160 and set(calls.values()) == {2}
        old = files[-1].stat()
        files[-1].write_bytes(b"changed--0079")
        assert files[-1].stat().st_size == old.st_size
        os.utime(files[-1], ns=(old.st_atime_ns, old.st_mtime_ns))
        with pytest.raises(ProcessingError, match="source_changed"):
            service._validate_search_session(session)

        def revoked(path, **kwargs):
            if str(path) == str(files[40]):
                raise ProcessingError("path_outside_allowed_directories")
            return original_path(path, **kwargs)

        monkeypatch.setattr(service.app, "path", revoked)
        with pytest.raises(ProcessingError, match="path_outside_allowed_directories"):
            service._validate_search_session(session)
    finally:
        service.close()
