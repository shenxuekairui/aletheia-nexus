"""Real stdio server with ONLY its public HTTP acquisition layer replaced by a fixture."""

import shutil
import sys
from pathlib import Path

from aletheia_nexus.acquire.access import service
from aletheia_nexus.acquire.discovery.models import DiscoveryResult, FullTextCandidate
from aletheia_nexus.acquire.fulltext.models import AcquisitionResult, AcquisitionStatus
from aletheia_nexus.acquire.fulltext.orchestration.models import (
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
)
from aletheia_nexus.core.artifact_paths import acquisition_sidecar_path
from aletheia_nexus.mcp_server import main

fixture, marker = Path(sys.argv[1]), Path(sys.argv[2])


def public(doi, *, output_dir, **kwargs):
    with marker.open("a", encoding="utf-8") as output:
        output.write(doi + "\n")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pdf = directory / "verified.pdf"
    shutil.copyfile(fixture, pdf)
    sidecar = acquisition_sidecar_path(pdf)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(acquisition_sidecar_path(fixture), sidecar)
    candidate = FullTextCandidate(
        doi=doi, url="https://example.org/self-authored.pdf", provenance=()
    )
    result = AcquisitionResult(
        candidate=candidate, status=AcquisitionStatus.VERIFIED, file_path=pdf
    )
    return MultiRouteAcquisitionResult(
        doi=doi,
        status=FullTextAcquisitionStatus.VERIFIED,
        discovery=DiscoveryResult(doi=doi, candidates=(candidate,), providers=()),
        verified_result=result,
    )


service.acquire_full_text = public
raise SystemExit(main(sys.argv[3:]))
