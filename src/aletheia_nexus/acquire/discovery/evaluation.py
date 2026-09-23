from collections.abc import Iterable
from dataclasses import dataclass, field

from aletheia_nexus.acquire.discovery.models import (
    AccessType,
    DiscoveryProvider,
    DiscoveryResult,
    FullTextCandidate,
    FullTextVersion,
    HostType,
)
from aletheia_nexus.acquire.discovery.ranking import canonicalize_candidate_url

RouteKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class ProviderContribution:
    """Diagnostic contribution summary for one Discovery provider."""

    provider: DiscoveryProvider
    candidate_routes: int
    unique_routes: int
    shared_routes: int
    exclusive_access_type: int
    exclusive_version: int
    exclusive_host_type: int
    exclusive_license: int
    exclusive_source_name: int
    exclusive_is_best: int
    metadata_disagreements: int

    @property
    def exclusive_metadata_total(self) -> int:
        """Return the number of shared-route fields only this provider supplied."""

        return (
            self.exclusive_access_type
            + self.exclusive_version
            + self.exclusive_host_type
            + self.exclusive_license
            + self.exclusive_source_name
            + self.exclusive_is_best
        )


@dataclass(slots=True)
class _ContributionAccumulator:
    route_keys: set[RouteKey] = field(default_factory=set)
    unique_routes: int = 0
    shared_routes: int = 0
    exclusive_access_type: int = 0
    exclusive_version: int = 0
    exclusive_host_type: int = 0
    exclusive_license: int = 0
    exclusive_source_name: int = 0
    exclusive_is_best: int = 0
    metadata_disagreements: int = 0


_METADATA_FIELDS = (
    ("access_type", "exclusive_access_type"),
    ("version", "exclusive_version"),
    ("host_type", "exclusive_host_type"),
    ("license", "exclusive_license"),
    ("source_name", "exclusive_source_name"),
    ("is_best", "exclusive_is_best"),
)


def _informative_value(candidate: FullTextCandidate, field_name: str) -> object | None:
    value = getattr(candidate, field_name)

    if field_name == "access_type" and value == AccessType.UNKNOWN:
        return None
    if field_name == "version" and value == FullTextVersion.UNKNOWN:
        return None
    if field_name == "host_type" and value == HostType.UNKNOWN:
        return None
    if field_name in {"license", "source_name"}:
        return value if isinstance(value, str) and value else None
    if field_name == "is_best":
        return True if value is True else None

    return value


def _values_for_field(
    candidates: list[FullTextCandidate],
    field_name: str,
) -> set[object]:
    values: set[object] = set()
    for candidate in candidates:
        value = _informative_value(candidate, field_name)
        if value is not None:
            values.add(value)
    return values


def summarize_provider_contributions(
    results: Iterable[DiscoveryResult],
) -> tuple[ProviderContribution, ...]:
    """Measure route overlap and metadata-only provider contributions.

    Route identity is based on the same canonical URL rules used by candidate
    deduplication. Metadata contribution is intentionally conservative: on a
    route shared by multiple providers, a field counts as exclusive only when
    exactly one provider supplies any informative value for that field.

    Different informative values on the same shared route are recorded as
    disagreements rather than silently resolving one provider as authoritative.
    """

    routes: dict[
        RouteKey,
        dict[DiscoveryProvider, list[FullTextCandidate]],
    ] = {}
    accumulators: dict[DiscoveryProvider, _ContributionAccumulator] = {}

    for result in results:
        for provider_result in result.providers:
            provider = provider_result.provider
            accumulator = accumulators.setdefault(
                provider,
                _ContributionAccumulator(),
            )

            for candidate in provider_result.candidates:
                key = (
                    result.doi,
                    canonicalize_candidate_url(candidate.url),
                )
                accumulator.route_keys.add(key)
                provider_candidates = routes.setdefault(key, {}).setdefault(
                    provider, []
                )
                provider_candidates.append(candidate)

    for providers_for_route in routes.values():
        providers = tuple(providers_for_route)

        if len(providers) == 1:
            accumulators[providers[0]].unique_routes += 1
            continue

        for provider in providers:
            accumulators[provider].shared_routes += 1

        for field_name, accumulator_field in _METADATA_FIELDS:
            values_by_provider = {
                provider: _values_for_field(candidates, field_name)
                for provider, candidates in providers_for_route.items()
            }
            providers_with_values = [
                provider for provider, values in values_by_provider.items() if values
            ]

            if len(providers_with_values) == 1:
                provider = providers_with_values[0]
                accumulator = accumulators[provider]
                setattr(
                    accumulator,
                    accumulator_field,
                    getattr(accumulator, accumulator_field) + 1,
                )

            if len(providers_with_values) > 1:
                distinct_values = {
                    value for values in values_by_provider.values() for value in values
                }
                if len(distinct_values) > 1:
                    for provider in providers_with_values:
                        accumulators[provider].metadata_disagreements += 1

    return tuple(
        ProviderContribution(
            provider=provider,
            candidate_routes=len(accumulator.route_keys),
            unique_routes=accumulator.unique_routes,
            shared_routes=accumulator.shared_routes,
            exclusive_access_type=accumulator.exclusive_access_type,
            exclusive_version=accumulator.exclusive_version,
            exclusive_host_type=accumulator.exclusive_host_type,
            exclusive_license=accumulator.exclusive_license,
            exclusive_source_name=accumulator.exclusive_source_name,
            exclusive_is_best=accumulator.exclusive_is_best,
            metadata_disagreements=accumulator.metadata_disagreements,
        )
        for provider, accumulator in sorted(
            accumulators.items(),
            key=lambda item: item[0].value,
        )
    )
