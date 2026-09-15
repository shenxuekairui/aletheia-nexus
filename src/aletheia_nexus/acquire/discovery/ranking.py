from dataclasses import replace

from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    CandidateUrlType,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.urls import normalize_candidate_url

_VERSION_RANK = {
    FullTextVersion.PUBLISHED: 3,
    FullTextVersion.ACCEPTED: 2,
    FullTextVersion.SUBMITTED: 1,
    FullTextVersion.UNKNOWN: 0,
}

_HOST_RANK = {
    HostType.PUBLISHER: 4,
    HostType.REPOSITORY: 3,
    HostType.RESOLVER: 2,
    HostType.INDEX: 1,
    HostType.UNKNOWN: 0,
}


def canonicalize_candidate_url(url: str) -> str:
    """Normalize URL identity for deduplication."""

    return normalize_candidate_url(url)


def candidate_sort_key(candidate: FullTextCandidate) -> tuple[int, int, int, int, int]:
    """Return deterministic acquisition priority, not scholarly authority."""

    return (
        int(candidate.access_type == AccessType.OPEN_ACCESS),
        int(candidate.url_type == CandidateUrlType.PDF),
        _VERSION_RANK[candidate.version],
        _HOST_RANK[candidate.host_type],
        int(candidate.is_best),
    )


def _consistent_text(group: list[FullTextCandidate], field: str) -> str | None:
    """Return one shared non-empty text value, or None when providers conflict."""

    values = list(
        dict.fromkeys(
            value for candidate in group if (value := getattr(candidate, field))
        )
    )
    return values[0] if len(values) == 1 else None


def merge_and_rank_candidates(
    candidates: list[FullTextCandidate],
) -> tuple[FullTextCandidate, ...]:
    """Deduplicate routes and order them by acquisition priority.

    Ranking answers "which route should Acquisition try first?". It does not
    assert that the first candidate is the most authoritative scholarly version.

    Free-text metadata is merged conservatively. A shared ``license`` or
    ``source_name`` is retained only when all non-empty reports agree; conflicts
    remain unknown instead of silently selecting one provider's value.
    """

    grouped: dict[str, list[FullTextCandidate]] = {}

    for candidate in candidates:
        key = canonicalize_candidate_url(candidate.url)
        grouped.setdefault(key, []).append(candidate)

    merged: list[FullTextCandidate] = []

    for url, group in grouped.items():
        chosen = max(group, key=candidate_sort_key)
        provenance = tuple(
            dict.fromkeys(
                provider for candidate in group for provider in candidate.provenance
            )
        )
        merged.append(
            replace(
                chosen,
                url=url,
                provenance=provenance,
                license=_consistent_text(group, "license"),
                source_name=_consistent_text(group, "source_name"),
                is_best=any(candidate.is_best for candidate in group),
            )
        )

    return tuple(
        sorted(
            merged,
            key=lambda candidate: (candidate_sort_key(candidate), candidate.url),
            reverse=True,
        )
    )
