"""Manual real-network acceptance checks for full-text discovery.

This script is intentionally outside the automated test suite. It exercises
real provider APIs and is useful for validating behavior against live data.
"""

import argparse
import os
import time
from collections import Counter, defaultdict
from statistics import mean, median

from aletheia_nexus.acquire.discovery import (
    DiscoveryStatus,
    discover_full_text_batch,
)

DEFAULT_DOIS = ("10.1038/nphys1170",)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real-network Aletheia Nexus discovery acceptance checks."
    )
    parser.add_argument(
        "dois",
        nargs="*",
        help="DOIs to test. A small default set is used when omitted.",
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
    return parser


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


def _print_summary(results, batch_elapsed: float) -> None:
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
        f"{sum(candidate.access_type.value == 'open_access' for candidate in candidates)}"
    )
    print(
        "pdf candidates:   "
        f"{sum(candidate.url_type.value == 'pdf' for candidate in candidates)}"
    )

    item_times = [result.elapsed_seconds for result in results]
    print()
    print(f"batch elapsed:    {batch_elapsed:.3f} s")
    if item_times:
        print(f"mean / result:    {mean(item_times):.3f} s")
        print(f"median / result:  {median(item_times):.3f} s")
        print(f"max / result:     {max(item_times):.3f} s")

    provider_times = defaultdict(list)
    provider_statuses = defaultdict(Counter)
    provider_attempts = Counter()

    for result in results:
        if result.discovery is None:
            continue
        for provider in result.discovery.providers:
            provider_statuses[provider.provider.value][provider.status.value] += 1
            provider_attempts[provider.provider.value] += provider.attempts
            if provider.attempts > 0:
                provider_times[provider.provider.value].append(provider.elapsed_seconds)

    for provider_name in sorted(provider_statuses):
        print()
        print(provider_name)
        for status, count in sorted(provider_statuses[provider_name].items()):
            print(f"  {status:<18} {count}")
        print(f"  attempts           {provider_attempts[provider_name]}")

        times = provider_times[provider_name]
        if times:
            print(f"  mean elapsed       {mean(times):.3f} s")
            print(f"  median elapsed     {median(times):.3f} s")
            print(f"  max elapsed        {max(times):.3f} s")


def main() -> int:
    args = _build_parser().parse_args()
    dois = args.dois or list(DEFAULT_DOIS)

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

    _print_summary(results, batch_elapsed)

    severe = {
        DiscoveryStatus.INVALID_DOI,
        DiscoveryStatus.ERROR,
    }
    return int(any(result.status in severe for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
