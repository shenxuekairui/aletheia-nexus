"""Manual real-network acceptance checks for full-text discovery.

This script is intentionally outside the automated test suite. It exercises
real provider APIs and is useful for validating behavior against live data.
"""

import argparse
import os

from aletheia_nexus.acquire.discovery import (
    DiscoveryStatus,
    discover_full_text_batch,
)

DEFAULT_DOIS = (
    "10.1038/nphys1170",
)


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
    print(f"input:  {result.input_value}")
    print(f"doi:    {result.doi}")
    print(f"status: {result.status}")

    if result.error:
        print(f"error:  {result.error}")

    if result.discovery is None:
        return

    print("providers:")
    for provider in result.discovery.providers:
        line = (
            f"  - {provider.provider.value}: {provider.status} "
            f"(attempts={provider.attempts})"
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


def main() -> int:
    args = _build_parser().parse_args()
    dois = args.dois or list(DEFAULT_DOIS)

    results = discover_full_text_batch(
        dois,
        unpaywall_email=args.unpaywall_email,
        openalex_api_key=args.openalex_api_key,
        deduplicate=not args.keep_duplicates,
        max_attempts=args.max_attempts,
        backoff_base=args.backoff_base,
    )

    for result in results:
        _print_result(result)

    severe = {
        DiscoveryStatus.INVALID_DOI,
        DiscoveryStatus.ERROR,
    }
    return int(any(result.status in severe for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
