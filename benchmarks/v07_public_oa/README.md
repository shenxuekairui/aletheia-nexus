# v0.7 public OA qualification

This manifest defines a small, reproducible real-layout qualification set. The
PDFs are fetched on demand from the official PMC Article Datasets bucket and
verified against fixed SHA-256 digests. They are deliberately not committed to
the repository: open access is recorded, but source licensing and downstream
redistribution obligations still matter.

The manually selected gold assertions cover title/section text, conservative
minimum reference/figure/table counts, page count, full anchor coverage, and
parser status. They are qualification evidence,
not a complete transcription or claims of semantic understanding. Raster-only OCR is covered by the
self-authored executable smoke fixture in `benchmarks/v07_fixtures`.

Run:

```text
python scripts/qualify_v07_public_oa.py --output qualification.json
```
