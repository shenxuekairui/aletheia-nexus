import argparse

from aletheia_nexus.acquire.discovery.models import (
    CandidateUrlType,
    DiscoveryProvider,
    FullTextCandidate,
)
from aletheia_nexus.acquire.fulltext import acquire_direct_pdf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one real-network v0.5.0 direct PDF acquisition acceptance case."
    )
    parser.add_argument("--doi", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--title")
    parser.add_argument("--output-dir", default="downloads")
    parser.add_argument("--keep-unverified", action="store_true")
    args = parser.parse_args()

    candidate = FullTextCandidate(
        doi=args.doi,
        url=args.url,
        provenance=(DiscoveryProvider.OPENALEX,),
        url_type=CandidateUrlType.PDF,
    )

    result = acquire_direct_pdf(
        candidate,
        output_dir=args.output_dir,
        expected_title=args.title,
        keep_unverified=args.keep_unverified,
    )

    print(f"status:       {result.status.value}")
    print(f"attempts:     {result.attempts}")
    print(f"elapsed:      {result.elapsed_seconds:.3f} s")
    print(f"error:        {result.error or '-'}")
    print(f"file:         {result.file_path or '-'}")
    print(f"sidecar:      {result.sidecar_path or '-'}")

    if result.retrieved:
        print(f"final URL:    {result.retrieved.final_url}")
        print(f"bytes:        {result.retrieved.size_bytes}")
        print(f"sha256:       {result.retrieved.sha256}")
        print(f"redirects:    {len(result.retrieved.redirects)}")

    if result.pdf_validation:
        print(f"valid PDF:    {result.pdf_validation.valid_pdf}")
        print(f"pages:        {result.pdf_validation.page_count}")
        print(f"encrypted:    {result.pdf_validation.encrypted}")

    if result.identity_validation:
        print(f"identity:     {result.identity_validation.status.value}")
        print(f"role:         {result.identity_validation.document_role.value}")
        for evidence in result.identity_validation.evidence:
            print(f"evidence:     {evidence}")


if __name__ == "__main__":
    main()
