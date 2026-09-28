# Benchmark corpus provenance

`user_20260923_20_with_titles.json` is the **raw realistic input** from the
2026-09-23 user run. Despite its historical filename, only two of its 20 rows
have an explicit title. Keep the file unchanged: it exercises DOI-only metadata
resolution as well as acquisition. Its reported cumulative 19/20 `VERIFIED`
included resumed attempts and user-completed authentication; it is not a fresh
one-pass success rate.

`user_20260923_20_frozen.json` is a **separate, reproducible acquisition
corpus** containing the same 20 unique DOIs in the same order, with a fixed
article title, publisher and publication year for every row. Use it to compare
acquisition/identity behavior without changing the expected titles whenever a
live metadata provider changes. The batch CLI and manual v0.6 acceptance runner
consume the fixed `title`; `publisher` and `year` are audit fields, not claims
about access rights. Live publisher access, browser challenges and entitlement
still vary, so the frozen input does not make an end-to-end network run fully
deterministic.

The frozen fields were checked on 2026-09-24 against the DOI-deposit metadata
at `https://api.crossref.org/works/{doi}`. Titles are plain-text renderings of
the deposited article titles (for example, Wiley's superscript markup is
rendered as `15N`). `year` means the article publication year, not the year
embedded in a DOI, the benchmark creation date, or a copyright date. For
`10.1055/a-2508-9744`, the [publisher article page](https://www.thieme-connect.com/products/ejournals/pdf/10.1055/a-2508-9744.pdf)
specifies article publication online in February 2025 and volume year 2025;
Crossref's 2024 date corresponds to the accepted manuscript, so this corpus
records 2025. Do not silently refresh these fields on future runs: any
correction should be reviewed and documented as a benchmark revision.
`python scripts/verify_frozen_benchmark.py` checks the two inputs still have
the same ordered, unique DOI set and that all 20 frozen rows retain their
required fields. The local RC script and hosted fast CI run this guard.

Use one corpus consistently for a comparison and record its filename, commit,
environment, time, whether authentication was user-assisted, and whether the
result is a single run or cumulative follow-up. Never reinterpret a failure
to access a publisher as a PDF identity failure.
