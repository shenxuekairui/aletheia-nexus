from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext import service
from aletheia_nexus.acquire.fulltext.exceptions import AcquisitionAccessBlockedError
from aletheia_nexus.acquire.fulltext.models import AcquisitionStatus


def _candidate():
    return FullTextCandidate(
        doi="10.1000/blocked",
        url="https://example.org/paper.pdf",
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
    )


def test_access_blocked_failure_is_not_overstated_as_auth_required(
    tmp_path, monkeypatch
):
    def fail(*args, **kwargs):
        raise AcquisitionAccessBlockedError("access blocked")

    monkeypatch.setattr(service, "retrieve_to_temp", fail)

    result = service.acquire_direct_pdf(_candidate(), output_dir=tmp_path)

    assert result.status == AcquisitionStatus.ACCESS_BLOCKED
    assert result.attempts == 1
    assert result.error == "access blocked"
