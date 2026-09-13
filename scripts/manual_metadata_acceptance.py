from collections import Counter

from aletheia_nexus.acquire.metadata import (
    MetadataStatus,
    get_metadata_batch,
)


TEST_INPUTS = [
    # Crossref：经典 Nature 论文
    "10.1038/171737a0",

    # 与上一条相同，但故意使用 URL + 大写。
    # 默认 deduplicate=True 时应该被标准化后去重。
    "https://doi.org/10.1038/171737A0",

    # Crossref：使用 DOI: 前缀
    "DOI: 10.1038/nphys1170",

    # DataCite：Zenodo 对象
    "10.5281/zenodo.31780",

    # DataCite：DataCite 官方文档对象
    "https://doi.org/10.14454/QDD3-PS68",

    # 语法上像 DOI，但预期没有真实元数据
    "10.9999/this-doi-should-not-exist-20260913",

    # 非法 DOI
    "not a doi",

    # 非字符串非法输入
    None,
]


def shorten(
    value: object,
    width: int,
) -> str:
    """Shorten text for compact terminal display."""

    if value is None:
        text = "-"

    elif isinstance(value, tuple):
        text = ", ".join(
            str(item)
            for item in value
        )

    else:
        text = str(value)

    text = " ".join(
        text.split()
    )

    if len(text) <= width:
        return text

    return (
        text[: width - 3]
        + "..."
    )


def print_separator(
    width: int = 118,
) -> None:
    print("-" * width)


def print_result_table(
    results,
) -> None:
    """Print one compact summary row per result."""

    print()
    print("=" * 118)
    print("Aletheia Nexus — Metadata Manual Acceptance Test")
    print("=" * 118)

    header = (
        f"{'#':<3} "
        f"{'STATUS':<19} "
        f"{'DOI':<35} "
        f"{'YEAR':<6} "
        f"{'TYPE':<18} "
        f"{'TITLE':<30}"
    )

    print(header)
    print_separator()

    for index, result in enumerate(
        results,
        start=1,
    ):
        metadata = result.metadata

        year = (
            metadata.year
            if metadata
            else None
        )

        work_type = (
            metadata.work_type
            if metadata
            else None
        )

        title = (
            metadata.title
            if metadata
            else result.error
        )

        print(
            f"{index:<3} "
            f"{result.status.value:<19} "
            f"{shorten(result.doi, 35):<35} "
            f"{shorten(year, 6):<6} "
            f"{shorten(work_type, 18):<18} "
            f"{shorten(title, 30):<30}"
        )

    print_separator()


def print_success_details(
    results,
) -> None:
    """Print readable details for successful records."""

    successful = [
        result
        for result in results
        if result.status
        == MetadataStatus.SUCCESS
    ]

    if not successful:
        return

    print()
    print("SUCCESS DETAILS")
    print("=" * 80)

    for index, result in enumerate(
        successful,
        start=1,
    ):
        paper = result.metadata

        print(
            f"\n[{index}] {paper.title or '-'}"
        )

        print(
            f"    DOI:       {paper.doi}"
        )

        print(
            "    Authors:   "
            + (
                ", ".join(paper.authors)
                if paper.authors
                else "-"
            )
        )

        print(
            f"    Journal:   {paper.journal or '-'}"
        )

        print(
            f"    Year:      {paper.year or '-'}"
        )

        print(
            f"    Type:      {paper.work_type or '-'}"
        )

        print(
            f"    Publisher: {paper.publisher or '-'}"
        )

        publication_parts = []

        if paper.volume:
            publication_parts.append(
                f"volume={paper.volume}"
            )

        if paper.issue:
            publication_parts.append(
                f"issue={paper.issue}"
            )

        if paper.pages:
            publication_parts.append(
                f"pages={paper.pages}"
            )

        print(
            "    Publication: "
            + (
                ", ".join(
                    publication_parts
                )
                if publication_parts
                else "-"
            )
        )


def print_failures(
    results,
) -> None:
    """Print errors separately from successful metadata."""

    failures = [
        result
        for result in results
        if result.status
        != MetadataStatus.SUCCESS
    ]

    if not failures:
        return

    print()
    print("NON-SUCCESS DETAILS")
    print("=" * 80)

    for result in failures:
        print(
            f"\n[{result.status.value}]"
        )

        print(
            f"    Input: {result.input_value!r}"
        )

        print(
            f"    DOI:   {result.doi or '-'}"
        )

        print(
            f"    Error: {result.error or '-'}"
        )


def run_acceptance_checks(
    results,
) -> bool:
    """
    Check high-level behavior independently from implementation details.
    """

    checks = []

    returned_dois = [
        result.doi
        for result in results
        if result.doi
    ]


    # 1. Duplicate Nature DOI should appear only once and succeed.
    checks.append(
        (
            "Normalized duplicate DOI was removed and resolved",
            sum(
                result.doi == "10.1038/171737a0"
                and result.status == MetadataStatus.SUCCESS
                for result in results
            )
            == 1,
        )
    )

    # 2. Nature Physics DOI should succeed.
    checks.append(
        (
            "Crossref journal article resolved",
            any(
                result.doi
                == "10.1038/nphys1170"
                and result.status
                == MetadataStatus.SUCCESS
                for result in results
            ),
        )
    )

    # 3. Zenodo DOI should succeed.
    checks.append(
        (
            "DataCite Zenodo object resolved",
            any(
                result.doi
                == "10.5281/zenodo.31780"
                and result.status
                == MetadataStatus.SUCCESS
                for result in results
            ),
        )
    )

    # 4. DataCite documentation DOI should succeed.
    checks.append(
        (
            "DataCite documentation object resolved",
            any(
                result.doi
                == "10.14454/qdd3-ps68"
                and result.status
                == MetadataStatus.SUCCESS
                for result in results
            ),
        )
    )

    # 5. Plain invalid text should become INVALID_DOI.
    checks.append(
        (
            "Invalid text was isolated",
            any(
                result.input_value
                == "not a doi"
                and result.status
                == MetadataStatus.INVALID_DOI
                for result in results
            ),
        )
    )

    # 6. None should also be isolated instead of crashing the batch.
    checks.append(
        (
            "Non-string invalid input was isolated",
            any(
                result.input_value is None
                and result.status
                == MetadataStatus.INVALID_DOI
                for result in results
            ),
        )
    )

    # 7. Syntactically valid but nonexistent DOI should be NOT_FOUND.
    checks.append(
        (
            "Nonexistent DOI was reported as NOT_FOUND",
            any(
                result.doi
                == "10.9999/this-doi-should-not-exist-20260913"
                and result.status
                == MetadataStatus.NOT_FOUND
                for result in results
            ),
        )
    )

    print()
    print("ACCEPTANCE CHECKS")
    print("=" * 80)

    all_passed = True

    for description, passed in checks:
        symbol = (
            "PASS"
            if passed
            else "FAIL"
        )

        print(
            f"[{symbol:<4}] {description}"
        )

        if not passed:
            all_passed = False

    return all_passed


def print_summary(
    results,
) -> None:
    """Print status counts."""

    counts = Counter(
        result.status.value
        for result in results
    )

    print()
    print("SUMMARY")
    print("=" * 80)

    print(
        f"Input values:     {len(TEST_INPUTS)}"
    )

    print(
        f"Returned results: {len(results)}"
    )

    print(
        "Note: returned results can be fewer than inputs "
        "because normalized duplicates are removed."
    )

    print()

    for status in MetadataStatus:
        count = counts.get(
            status.value,
            0,
        )

        if count:
            print(
                f"{status.value:<20} {count}"
            )


def main() -> None:
    print(
        "Running real-network metadata acceptance test..."
    )

    print(
        "This may take several seconds."
    )

    results = get_metadata_batch(
        TEST_INPUTS,
        deduplicate=True,
        max_attempts=3,
        backoff_base=0.5,
    )

    print_result_table(
        results
    )

    print_summary(
        results
    )

    print_success_details(
        results
    )

    print_failures(
        results
    )

    passed = run_acceptance_checks(
        results
    )

    print()
    print("=" * 80)

    if passed:
        print(
            "FINAL RESULT: PASS"
        )

        print(
            "Manual metadata acceptance test completed successfully."
        )

    else:
        print(
            "FINAL RESULT: FAIL"
        )

        print(
            "At least one expected behavior was not observed."
        )

    print("=" * 80)


if __name__ == "__main__":
    main()