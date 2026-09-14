import time
from collections import Counter
from statistics import mean, median

from aletheia_nexus.acquire.metadata import (
    MetadataStatus,
    get_metadata_batch,
)

TEST_INPUTS = [
    # Crossref：经典 Nature 文献
    "10.1038/171737a0",
    # 与上一条等价，用于验证标准化后去重
    "https://doi.org/10.1038/171737A0",
    # Crossref：另一篇真实文献
    "DOI: 10.1038/nphys1170",
    # DataCite：Zenodo
    "10.5281/zenodo.31780",
    # DataCite：官方文档对象
    "https://doi.org/10.14454/QDD3-PS68",
    # 语法有效但预期不存在
    "10.9999/aletheia-nexus-nonexistent-20260913",
    # 非法 DOI
    "not a doi",
    # 非字符串非法输入
    None,
]


def shorten(
    value: object,
    width: int,
) -> str:
    """Return compact single-line terminal text."""

    if value is None:
        text = "-"
    else:
        text = str(value)

    text = " ".join(text.split())

    if len(text) <= width:
        return text

    return text[: width - 3] + "..."


def print_results(
    results,
) -> None:
    """Print a compact result table."""

    print()
    print("=" * 132)
    print("Aletheia Nexus — Metadata Manual Acceptance Test")
    print("=" * 132)

    print(
        f"{'#':<3} {'STATUS':<19} {'DOI':<38} {'TIME(s)':<9} "
        f"{'YEAR':<6} {'TYPE':<18} {'TITLE':<30}"
    )

    print("-" * 132)

    for index, result in enumerate(
        results,
        start=1,
    ):
        metadata = result.metadata

        year = metadata.year if metadata else None

        work_type = metadata.work_type if metadata else None

        title = metadata.title if metadata else result.error

        print(
            f"{index:<3} "
            f"{result.status.value:<19} "
            f"{shorten(result.doi, 38):<38} "
            f"{result.elapsed_seconds:<9.3f} "
            f"{shorten(year, 6):<6} "
            f"{shorten(work_type, 18):<18} "
            f"{shorten(title, 30):<30}"
        )

    print("-" * 132)


def find_result(
    results,
    *,
    doi: str | None = None,
    input_value: object = ...,
):
    """Find one result by normalized DOI or original input."""

    for result in results:
        if doi is not None and result.doi == doi:
            return result

        if input_value is not ... and result.input_value == input_value:
            return result

    return None


def run_checks(
    results,
) -> bool:
    """Validate important end-to-end behavior."""

    checks: list[tuple[str, bool]] = []

    dna_results = [result for result in results if result.doi == "10.1038/171737a0"]

    checks.append(
        (
            "Normalized duplicate DOI was removed",
            len(dna_results) == 1,
        )
    )

    checks.append(
        (
            "First Crossref DOI resolved",
            len(dna_results) == 1 and dna_results[0].status == MetadataStatus.SUCCESS,
        )
    )

    crossref = find_result(
        results,
        doi="10.1038/nphys1170",
    )

    checks.append(
        (
            "Second Crossref DOI resolved",
            crossref is not None and crossref.status == MetadataStatus.SUCCESS,
        )
    )

    zenodo = find_result(
        results,
        doi="10.5281/zenodo.31780",
    )

    checks.append(
        (
            "DataCite Zenodo object resolved",
            zenodo is not None and zenodo.status == MetadataStatus.SUCCESS,
        )
    )

    datacite_document = find_result(
        results,
        doi="10.14454/qdd3-ps68",
    )

    checks.append(
        (
            "DataCite documentation object resolved",
            datacite_document is not None
            and datacite_document.status == MetadataStatus.SUCCESS,
        )
    )

    nonexistent = find_result(
        results,
        doi=("10.9999/aletheia-nexus-nonexistent-20260913"),
    )

    checks.append(
        (
            "Nonexistent DOI reported as NOT_FOUND",
            nonexistent is not None and nonexistent.status == MetadataStatus.NOT_FOUND,
        )
    )

    invalid_text = find_result(
        results,
        input_value="not a doi",
    )

    checks.append(
        (
            "Invalid text isolated",
            invalid_text is not None
            and invalid_text.status == MetadataStatus.INVALID_DOI,
        )
    )

    invalid_none = find_result(
        results,
        input_value=None,
    )

    checks.append(
        (
            "Non-string invalid input isolated",
            invalid_none is not None
            and invalid_none.status == MetadataStatus.INVALID_DOI,
        )
    )

    checks.append(
        (
            "Runtime recorded for every returned result",
            all(result.elapsed_seconds >= 0 for result in results),
        )
    )

    print()
    print("ACCEPTANCE CHECKS")
    print("=" * 80)

    for description, passed in checks:
        status = "PASS" if passed else "FAIL"

        print(f"[{status:<4}] {description}")

    return all(passed for _, passed in checks)


def print_summary(
    results,
    batch_elapsed: float,
) -> None:
    """Print result counts and runtime statistics."""

    counts = Counter(result.status.value for result in results)

    print()
    print("SUMMARY")
    print("=" * 80)

    print(f"Input values:     {len(TEST_INPUTS)}")

    print(f"Returned results: {len(results)}")

    print("Normalized duplicates are omitted when deduplicate=True.")

    print()

    for status in MetadataStatus:
        count = counts.get(
            status.value,
            0,
        )

        if count:
            print(f"{status.value:<20} {count}")

    print()
    print(f"Batch elapsed:    {batch_elapsed:.3f} s")

    times = [result.elapsed_seconds for result in results]
    if times:
        print(f"Mean / result:    {mean(times):.3f} s")
        print(f"Median / result:  {median(times):.3f} s")
        print(f"Max / result:     {max(times):.3f} s")


def main() -> None:
    print("Running real-network metadata acceptance test...")

    batch_started_at = time.perf_counter()
    results = get_metadata_batch(
        TEST_INPUTS,
        deduplicate=True,
        max_attempts=3,
        backoff_base=0.5,
    )
    batch_elapsed = time.perf_counter() - batch_started_at

    print_results(results)
    print_summary(results, batch_elapsed)

    passed = run_checks(results)

    print()
    print("=" * 80)

    if passed:
        print("FINAL RESULT: PASS")
        print("Manual metadata acceptance test completed successfully.")
        print("=" * 80)
        return

    print("FINAL RESULT: FAIL")
    print("At least one required behavior was not observed.")
    print("=" * 80)

    raise SystemExit(1)


if __name__ == "__main__":
    main()
