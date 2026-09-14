"""Manual real-network benchmark for full-text discovery.

This script is intentionally outside the automated test suite. It exercises
real provider APIs and is useful for validating behavior, coverage, provider
contribution, and latency against live data.
"""

import argparse
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from aletheia_nexus.acquire.discovery import (
    AccessType,
    CandidateUrlType,
    DiscoveryStatus,
    HostType,
    discover_full_text_batch,
    summarize_provider_contributions,
)

DEFAULT_DOIS = ("10.1038/nphys1170",)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real-network Aletheia Nexus discovery benchmark checks."
    )
    parser.add_argument(
        "dois",
        nargs="*",
        help="DOIs to test. A small default set is used when omitted.",
    )
    parser.add_argument(
        "--doi-file",
        help="Optional UTF-8 file with one DOI per line; # comment lines are ignored.",
    )
    parser.add_argument(
        "--unpaywall-email",
        default=os.getenv("UNPAYWALL_EMAIL"),
        help="Unpaywall email. Defaults to UNPAYWALL_EMAIL when set.",
    )
    parser.add_argument(
        "--openalex-api-key",
        default=os.getenv("OPENALEX_API_KEY"),
        help="OpenAlex API key. Defaults to OPENALEX_API_KEY when set.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum attempts for temporary provider failures.",
    )
    parser.add_argument(
        "--backoff-base",
        type=float,
        default=1.0,
        help="Base seconds for exponential retry backoff.",
    )
    parser.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="Do not deduplicate equivalent normalized DOI inputs.",
    )
    parser.add_argument(
        "--baseline-seconds",
        type=float,
        help="Optional previous batch runtime used to report measured speedup.",
    )
    return parser


def _load_doi_file(path: str) -> list[str]:
    values: list[str] = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            values.append(line)
    return values


def _resolve_dois(args: argparse.Namespace) -> list[str]:
    values = list(args.dois)
    if args.doi_file:
        values.extend(_load_doi_file(args.doi_file))
    return values or list(DEFAULT_DOIS)


def _print_result(result) -> None:
    print("=" * 80)
    print(f"input:   {result.input_value}")
    print(f"doi:     {result.doi}")
    print(f"status:  {result.status}")
    print(f"elapsed: {result.elapsed_seconds:.3f} s")

    if result.error:
        print(f"error:   {result.error}")

    if result.discovery is None:
        return

    print(f"discovery elapsed: {result.discovery.elapsed_seconds:.3f} s")
    print("providers:")
    for provider in result.discovery.providers:
        line = (
            f"  - {provider.provider.value}: {provider.status} "
            f"(attempts={provider.attempts}, elapsed={provider.elapsed_seconds:.3f} s)"
        )
        print(line)
        if provider.error:
            print(f"    error: {provider.error}")

    print("candidates:")
    if not result.discovery.candidates:
        print("  - none")
        return

    for candidate in result.discovery.candidates:
        provenance = ",".join(provider.value for provider in candidate.provenance)
        print(f"  - {candidate.url}")
        print(
            "    "
            f"type={candidate.url_type} access={candidate.access_type} "
            f"version={candidate.version} host={candidate.host_type} "
            f"provenance={provenance}"
        )
        print(
            "    "
            f"source={candidate.source_name or '-'} "
            f"license={candidate.license or '-'} is_best={candidate.is_best}"
        )


def _print_counter(title: str, counter: Counter) -> None:
    print(title)
    if not counter:
        print("  - none")
        return
    for key, count in sorted(counter.items()):
        print(f"  {key:<20} {count}")


def _print_work_coverage(results) -> None:
    discoveries = [
        result.discovery for result in results if result.discovery is not None
    ]

    def has_candidate(predicate) -> int:
        return sum(
            any(predicate(candidate) for candidate in result.candidates)
            for result in discoveries
        )

    print()
    print("work-level discovery coverage")
    print(
        f"  works with candidates       {sum(bool(r.candidates) for r in discoveries)}"
    )
    print(
        "  works with OA candidate     "
        f"{has_candidate(lambda c: c.access_type == AccessType.OPEN_ACCESS)}"
    )
    print(
        "  works with PDF candidate    "
        f"{has_candidate(lambda c: c.url_type == CandidateUrlType.PDF)}"
    )
    print(
        "  works with non-resolver     "
        f"{has_candidate(lambda c: c.host_type != HostType.RESOLVER)}"
    )
    print(
        "  works with pub/repository   "
        f"{has_candidate(lambda c: c.host_type in {HostType.PUBLISHER, HostType.REPOSITORY})}"
    )


def _print_provider_contributions(results) -> None:
    discoveries = [
        result.discovery for result in results if result.discovery is not None
    ]
    contributions = summarize_provider_contributions(discoveries)

    print()
    print("provider contribution")
    if not contributions:
        print("  - none")
        return

    for contribution in contributions:
        print(f"  {contribution.provider.value}")
        print(f"    candidate routes          {contribution.candidate_routes}")
        print(f"    unique routes             {contribution.unique_routes}")
        print(f"    shared routes             {contribution.shared_routes}")
        print(f"    exclusive metadata       {contribution.exclusive_metadata_total}")
        print(f"      access_type             {contribution.exclusive_access_type}")
        print(f"      version                 {contribution.exclusive_version}")
        print(f"      host_type               {contribution.exclusive_host_type}")
        print(f"      license                 {contribution.exclusive_license}")
        print(f"      source_name             {contribution.exclusive_source_name}")
        print(f"      is_best                 {contribution.exclusive_is_best}")
        print(f"    metadata disagreements   {contribution.metadata_disagreements}")


def _print_timing(
    results, batch_elapsed: float, baseline_seconds: float | None
) -> None:
    item_times = [result.elapsed_seconds for result in results]
    print()
    print(f"batch elapsed:             {batch_elapsed:.3f} s")
    if item_times:
        print(f"mean / result:             {mean(item_times):.3f} s")
        print(f"median / result:           {median(item_times):.3f} s")
        print(f"max / result:              {max(item_times):.3f} s")

    if baseline_seconds is not None:
        reduction = 100 * (1 - batch_elapsed / baseline_seconds)
        speedup = baseline_seconds / batch_elapsed
        print(f"baseline elapsed:          {baseline_seconds:.3f} s")
        print(f"measured speedup:          {speedup:.2f}x")
        print(f"elapsed reduction:         {reduction:.1f}%")

    provider_times = defaultdict(list)
    provider_statuses = defaultdict(Counter)
    provider_attempts = Counter()
    provider_work_elapsed = 0.0
    provider_critical_path = 0.0
    discovery_wall_total = 0.0
    coordination_estimate = 0.0

    for result in results:
        if result.discovery is None:
            continue

        discovery_wall_total += result.discovery.elapsed_seconds
        active_times: list[float] = []

        for provider in result.discovery.providers:
            provider_statuses[provider.provider.value][provider.status.value] += 1
            provider_attempts[provider.provider.value] += provider.attempts
            if provider.attempts > 0:
                provider_times[provider.provider.value].append(provider.elapsed_seconds)
                provider_work_elapsed += provider.elapsed_seconds
                active_times.append(provider.elapsed_seconds)

        if active_times:
            critical = max(active_times)
            provider_critical_path += critical
            coordination_estimate += max(
                0.0, result.discovery.elapsed_seconds - critical
            )

    batch_wrapper_overhead = max(0.0, batch_elapsed - sum(item_times))

    print(f"provider work sum:         {provider_work_elapsed:.3f} s")
    print(f"provider critical path:    {provider_critical_path:.3f} s")
    if provider_critical_path > 0:
        print(
            "provider overlap factor:   "
            f"{provider_work_elapsed / provider_critical_path:.2f}x"
        )
    print(f"discovery wall sum:        {discovery_wall_total:.3f} s")
    print(f"coordination estimate:     {coordination_estimate:.3f} s")
    print(f"batch wrapper overhead:    {batch_wrapper_overhead:.3f} s")

    for provider_name in sorted(provider_statuses):
        print()
        print(provider_name)
        for status, count in sorted(provider_statuses[provider_name].items()):
            print(f"  {status:<18} {count}")
        print(f"  attempts           {provider_attempts[provider_name]}")

        times = provider_times[provider_name]
        if times:
            print(f"  total elapsed      {sum(times):.3f} s")
            print(f"  mean elapsed       {mean(times):.3f} s")
            print(f"  median elapsed     {median(times):.3f} s")
            print(f"  max elapsed        {max(times):.3f} s")


def _print_summary(
    results,
    batch_elapsed: float,
    baseline_seconds: float | None,
) -> None:
    print()
    print("=" * 80)
    print("DISCOVERY BENCHMARK SUMMARY")
    print("=" * 80)

    status_counts = Counter(result.status.value for result in results)
    print(f"returned results: {len(results)}")
    for status in DiscoveryStatus:
        count = status_counts.get(status.value, 0)
        if count:
            print(f"{status.value:<20} {count}")

    candidates = [
        candidate
        for result in results
        if result.discovery is not None
        for candidate in result.discovery.candidates
    ]
    print(f"candidates:       {len(candidates)}")
    print(
        "open access:      "
        f"{sum(candidate.access_type == AccessType.OPEN_ACCESS for candidate in candidates)}"
    )
    print(
        "pdf candidates:   "
        f"{sum(candidate.url_type == CandidateUrlType.PDF for candidate in candidates)}"
    )

    print()
    _print_counter(
        "candidate host types", Counter(c.host_type.value for c in candidates)
    )
    _print_counter("candidate versions", Counter(c.version.value for c in candidates))

    _print_work_coverage(results)
    _print_provider_contributions(results)
    _print_timing(results, batch_elapsed, baseline_seconds)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.baseline_seconds is not None and args.baseline_seconds <= 0:
        parser.error("--baseline-seconds must be greater than zero")

    dois = _resolve_dois(args)

    batch_started_at = time.perf_counter()
    results = discover_full_text_batch(
        dois,
        unpaywall_email=args.unpaywall_email,
        openalex_api_key=args.openalex_api_key,
        deduplicate=not args.keep_duplicates,
        max_attempts=args.max_attempts,
        backoff_base=args.backoff_base,
    )
    batch_elapsed = time.perf_counter() - batch_started_at

    for result in results:
        _print_result(result)

    _print_summary(results, batch_elapsed, args.baseline_seconds)

    severe = {
        DiscoveryStatus.INVALID_DOI,
        DiscoveryStatus.ERROR,
    }
    return int(any(result.status in severe for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
