from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)

_VERSION_RANK = {
    FullTextVersion.PUBLISHED: 3,
    FullTextVersion.ACCEPTED: 2,
    FullTextVersion.SUBMITTED: 1,
    FullTextVersion.UNKNOWN: 0,
}

_HOST_RANK = {
    HostType.PUBLISHER: 2,
    HostType.REPOSITORY: 1,
    HostType.UNKNOWN: 0,
}


def canonicalize_candidate_url(url: str) -> str:
    """Normalize URL identity without changing path or query semantics."""

    parts = urlsplit(url.strip())
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            "",
        )
    )


def candidate_sort_key(candidate: FullTextCandidate) -> tuple[int, int, int, int, int]:
    """Return a deterministic acquisition-oriented ranking key."""

    return (
        int(candidate.access_type == AccessType.OPEN_ACCESS),
        int(candidate.url_type == CandidateUrlType.PDF),
        _VERSION_RANK[candidate.version],
        _HOST_RANK[candidate.host_type],
        int(candidate.is_best),
    )


def merge_and_rank_candidates(
    candidates: list[FullTextCandidate],
) -> tuple[FullTextCandidate, ...]:
    """Deduplicate candidate URLs, preserve provenance, and rank the result."""

    grouped: dict[str, list[FullTextCandidate]] = {}

    for candidate in candidates:
        key = canonicalize_candidate_url(candidate.url)
        grouped.setdefault(key, []).append(candidate)

    merged: list[FullTextCandidate] = []

    for url, group in grouped.items():
        chosen = max(group, key=candidate_sort_key)
        provenance = tuple(
            dict.fromkeys(
                provider
                for candidate in group
                for provider in candidate.provenance
            )
        )
        merged.append(replace(chosen, url=url, provenance=provenance))

    return tuple(
        sorted(
            merged,
            key=lambda candidate: (candidate_sort_key(candidate), candidate.url),
            reverse=True,
        )
    )
