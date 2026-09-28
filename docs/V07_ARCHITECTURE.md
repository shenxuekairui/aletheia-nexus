# v0.7 parsing architecture

v0.7 is the boundary between a verified acquisition artifact and reusable,
source-linked document structure. It is deliberately a pipeline rather than a
single PDF helper so alternative layout/OCR implementations can improve byte
interpretation without weakening acquisition evidence or changing downstream
objects.

```text
VERIFIED PDF + acquisition sidecar
        │
        ▼
fail-closed input gate ── DOI / role / schema / SHA-256 / pages
        │
        ▼
ExtractionBackend ────── PageLayout(lines, page objects, warnings)
        │
        ▼
native-layout-and-block-assembly
        │                 reading order, page-furniture suppression,
        │                 paragraph/heading merge, anchors, budgets
        ▼
sections-references-and-objects
        │                 hierarchy, semantic sections, citations,
        │                 image/caption links, positioned table cells
        ▼
quality-classification ─ coverage, unresolved counts, PARSED/PARTIAL/FAILED
        │
        ▼
parsed-document/v2 ───── immutable new artifact
        │
        ├── ParsedArtifact.search() → block + section + PDF page/bbox
        ├── ParsedArtifact.locate() → source evidence
        └── ParsedArtifact.verify_local_sources() → fresh hash checks
```

## Module boundaries

| Module | Ownership |
| --- | --- |
| `content.gate` | Trust transition from acquisition; recognizes explicit acquisition schemas and raises typed input errors. |
| `content.backends` | Pluggable byte/layout interpretation. The bundled backend reads native PDF text matrices, font-weight evidence, and placements of image resources actually painted by the page content stream without decoding or publishing image bytes. |
| `content.pipeline` | Ordered, request-local stages. Stage identities are persisted in parser provenance. |
| `content.parser` | Block assembly, structure, reference/object links, resource budgets, quality classification, and v2 document construction. |
| `content.schema` | Cross-reference, hash, coverage, anchor, object, and table-cell validation plus deterministic serialization. |
| `content.artifact` | Read-only consumer API for section text, local integrity checks, and source-linked search. |
| `content.evaluation` | Offline measurement against frozen, rights-cleared fixture hashes and gold annotations. |

No parser stage calls discovery, HTTP acquisition, a browser, or entitlement
logic. The service hashes the PDF and acquisition sidecar both before and after
parsing; a concurrent change aborts without writing output.

## Extension contract

An extraction backend implements `name`, `version`, and
`extract_page(page, page_number) -> PageLayout`. Native text, OCR, or a model
layout backend must return the same backend-neutral lines/objects and expose
uncertainty rather than writing parsed JSON directly. Backend identity,
pipeline stages, configuration fingerprint, and an overall execution
fingerprint are recorded in every artifact.

Backends may improve coordinates or add page objects, but cannot:

- bypass the verified-artifact input gate;
- mutate or replace the acquisition PDF/sidecar;
- declare scientific claims true;
- convert unavailable coordinates into invented boxes;
- silently truncate at resource limits.

The bundled native backend is complete for the v0.7 deterministic contract.
Scanned pages remain explicit `PARTIAL` unless a caller supplies an alternate
backend; v0.7 does not make an unverified OCR engine a mandatory dependency.

## Quality and budgets

`quality` reports page and anchor coverage, text volume, object counts,
unresolved references/figures, table-cell recovery, repeated page furniture
suppressed from semantic output, painted images left unassociated, and early termination.
`ParserConfig` bounds pages, blocks, and extracted characters. Hitting a bound
adds a machine-readable warning, records `stopped_early`, and produces
`PARTIAL`; it never returns a silently incomplete `PARSED` result.

`PARSED` only states that the configured pipeline completed without extraction
warnings or errors. It does not establish factual correctness, entitlement,
claim validity, or knowledge-graph correctness.
