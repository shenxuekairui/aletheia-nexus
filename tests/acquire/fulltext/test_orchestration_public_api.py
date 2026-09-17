from aletheia_nexus.acquire.fulltext import (
    FileAttempt,
    FileCandidateOrigin,
    FullTextAcquisitionStatus,
    MultiRouteAcquisitionResult,
    RouteAttempt,
    RouteCandidateOrigin,
    TitleSource,
    acquire_from_discovery,
    acquire_full_text,
)


def test_v052_public_api_exports_are_importable():
    assert callable(acquire_full_text)
    assert callable(acquire_from_discovery)
    assert FullTextAcquisitionStatus.VERIFIED.value == "VERIFIED"
    assert FileCandidateOrigin.DISCOVERY.value == "DISCOVERY"
    assert RouteCandidateOrigin.DISCOVERY.value == "DISCOVERY"
    assert TitleSource.METADATA.value == "METADATA"
    assert MultiRouteAcquisitionResult.__name__ == "MultiRouteAcquisitionResult"
    assert FileAttempt.__name__ == "FileAttempt"
    assert RouteAttempt.__name__ == "RouteAttempt"
