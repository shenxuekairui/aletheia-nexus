# Aletheia Nexus

[中文 README](README.md) · [User Manual](docs/USER_MANUAL.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Release History](docs/RELEASE_HISTORY.md)

> **Turn scientific literature into verified, source-linked, AI-ready data.**

Aletheia Nexus (AN) is a **local-first scientific knowledge infrastructure** project. It starts from one of the most basic scientific objects—a paper—and turns literature handling into a verifiable, reusable pipeline:

```text
DOI / scientific object
        ↓
discovery and legitimate acquisition
        ↓
VERIFIED main article + provenance
        ↓
source-linked canonical document
        ↓
Markdown / JSONL / structure-aware chunks
        ↓
LLM / RAG / Workflow / Agent / Knowledge
```

AN does not treat “a PDF opened in a browser” as success, and it does not treat “text was extracted from a PDF” as trustworthy data. It asks whether the document is the intended main article, where the bytes came from, whether the source changed, whether parsed objects can return to page-level evidence, and whether failures and uncertainty remain explicit.

The long-term direction is deliberately layered: reliable evidence and data contracts first, then scientific semantics, knowledge, workflows, agents, and higher-level scientific intelligence.

---

## v0.7: from verified papers to AI-ready scientific data

v0.6 focused on:

> **Did I actually obtain the intended paper?**

v0.7 adds the next trust boundary:

> **Can machine-produced structure reliably return to the original evidence?**

```text
VERIFIED PDF
    ↓
strict DOI / role / schema / hash / page-count gate
    ↓
native-first extraction + optional OCR
    ↓
canonical PageGeometry
    ↓
sections / blocks / references / figures / tables
    ↓
page / bbox / source anchors
    ↓
parsed-document/v2
    ↓
Markdown / JSONL / structure-aware chunks
```

Here, **AI-ready** does not mean that a model has already “understood” the science. It means the document has a durable, model-agnostic representation with identity, provenance, structure, location, quality state, and uncertainty—ready for downstream LLM, RAG, Agent, or knowledge workflows without reparsing the PDF.

---

## Current capabilities

| Layer | Capability | Status |
| --- | --- | --- |
| Identity / Metadata | DOI normalization and Crossref / DataCite metadata | Implemented |
| Discovery | Metadata, OpenAlex, Unpaywall, PMC and related full-text leads | Implemented |
| Acquisition | Bounded public HTTP, official routes, persistent browser sessions, batch/resume | Implemented / Experimental |
| Verification | PDF structure, DOI/title identity, main-document role, SHA-256 and provenance | Implemented |
| Parse | Native-first blocks, sections, references, figure/table evidence, page/bbox anchors | Implemented |
| OCR | Optional real Poppler + Tesseract path with orientation, deskew and resource budgets | Implemented |
| Search | Search parsed artifacts with optional local source verification | Implemented |
| AI Export | Deterministic Markdown, JSONL and structure-aware chunks | Implemented |
| Scientific semantics | Entity / condition / measurement / claim / relation extraction | Planned |
| Knowledge / Workflow / Agent | Scientific memory, workflows and agent orchestration | Planned |

### Acquisition trust boundary

Only a fully validated target main document becomes `VERIFIED`.

AN does not provide subscriptions, bypass paywalls, answer CAPTCHAs, or invent user entitlement. When legitimate access requires login, MFA, institution selection, or a CAPTCHA, the user completes that step in their own visible browser and AN resumes from the resulting state.

Explicit non-success states include:

- `INTERACTION_REQUIRED`
- `ENTITLEMENT_REQUIRED`
- `EXHAUSTED`

These are meaningful workflow outcomes, not errors to hide.

### Parsing trust boundary

The v0.7 parser accepts only an unchanged `VERIFIED` artifact whose DOI, document role, PDF hash, acquisition-sidecar hash, readability, and page count still match.

The resulting `aletheia-nexus/parsed-document/v2` is a separate canonical artifact. It records stable source and parsed identities, sections, blocks, references, observed figure/table evidence, normalized page coordinates, extraction provenance, confidence/agreement, warnings, errors, and quality state.

**`PARSED` does not mean scientifically true.** Observing a caption, region, or positioned table cells is not the same as interpreting their scientific meaning.

---

## AI-ready exports

The canonical parsed artifact remains the Source of Truth. AI exports are deterministic derived views.

```bash
aletheia-nexus export PAPER.parsed.json --format markdown --output PAPER.ai.md
aletheia-nexus export PAPER.parsed.json --format jsonl --output PAPER.ai.jsonl
aletheia-nexus export PAPER.parsed.json --format chunks --output PAPER.chunks.json
```

Structure-aware chunking respects section, heading, caption, reference, equation, and table-object boundaries instead of blindly cutting every N tokens.

Each chunk independently retains:

```text
source_artifact_id
parsed_artifact_id
block_ids
anchor_ids
pages
page/bbox evidence
```

This preserves the chain:

```text
chunk → block → anchor → page/bbox → source artifact → PDF
```

AN core does not depend on a specific model provider, embedding API, tokenizer, or vector database. Those belong to downstream consumers.

---

## Quick start

Python 3.11+ is required.

### Install the latest published version

```bash
python -m pip install -U aletheia-nexus
aletheia-nexus --version
aletheia-nexus doctor
```

Check the [PyPI project](https://pypi.org/project/aletheia-nexus/) for the currently published version.

### Acquire a publicly reachable paper

```bash
aletheia-nexus acquire 10.1371/journal.pone.0310216 \
  --public-only \
  --output-dir downloads/first-paper
```

A valid `EXHAUSTED` result simply means the configured public routes did not yield a verified main article.

### Browser-assisted legitimate access

```bash
python -m pip install "aletheia-nexus[browser]"
python -m playwright install chromium

aletheia-nexus acquire papers.json \
  --output-dir downloads/papers \
  --fail-on-unverified
```

### Parse a VERIFIED artifact

```bash
aletheia-nexus parse downloads/paper.pdf --doi 10.1234/example
aletheia-nexus search PAPER.parsed.json QUERY --verify-sources
```

### Enable real OCR

Install Poppler and Tesseract, then:

```bash
aletheia-nexus parse downloads/paper.pdf \
  --doi 10.1234/example \
  --ocr
```

Native text remains authoritative. Optional OCR failure does not destroy already validated native evidence.

See the [User Manual](docs/USER_MANUAL.md) for detailed options and troubleshooting.

---

## Why not just convert PDF to Markdown?

For scientific workflows, the costly failures are often not formatting mistakes. They are provenance and identity failures:

- supporting information imported as the main article;
- a wrong PDF entering an Agent pipeline;
- OCR and native coordinates living in different frames;
- document identity depending on a machine-specific absolute path;
- a caption being mistaken for fully understood figure content;
- a new parser run silently overwriting old evidence;
- a RAG chunk that cannot return to the source passage.

AN treats these as scientific data-infrastructure problems.

The v0.7 trust chain is therefore:

```text
Identity
→ Integrity
→ Transformation
→ Location
→ Uncertainty
→ Consumption
```

---

## Verification evidence

The final v0.7 release-candidate PR verification includes:

- Python 3.11 deterministic suite: **889 passed / 8 skipped**;
- Windows/Python 3.11: **889 passed / 8 skipped**;
- Python 3.12 / 3.13 / 3.14 compatibility jobs: all green;
- Linux real Chromium: **7 passed**;
- Windows real Chromium: **7 passed**;
- real Poppler + Tesseract raster-only OCR smoke: **1 passed**;
- wheel/sdist build, `twine check`, clean-wheel install, `pip check`, CLI doctor: passed;
- frozen parser evaluator emits machine-readable qualification evidence in CI.

The self-authored frozen gold set records 4/4 gate decisions, 32/32 anchored blocks, 6/6 selected anchors, 10/10 sections, 18/18 structural assertions, and 886/886 gold characters with zero deletion/insertion/substitution errors.

Public real-layout evidence includes three hash-frozen OA papers fetched on demand from official sources. A separate private stress corpus covers **38 papers / 655 pages**. These results are evidence of parser completion, anchoring, and real-layout behavior—not claims of complete semantic correctness or universal visual-information recovery.

Independent user feedback has also demonstrated real local deployment and verified batch workflows (1/1, 3/3, and 6/6 in the reported batches). The stricter clean-PyPI three-minute onboarding goal remains unverified because the report did not capture a complete clean-install timing/environment record.

See [Release History](docs/RELEASE_HISTORY.md) for exact evidence boundaries.

---

## Project structure

```text
src/aletheia_nexus/
├── core/identifiers/
├── acquire/
│   ├── metadata/
│   ├── discovery/
│   ├── fulltext/
│   └── access/
└── content/
    ├── gate.py
    ├── geometry.py
    ├── backends/
    ├── parser.py
    ├── schema.py
    ├── artifact.py
    ├── export.py
    └── evaluation.py

benchmarks/
scripts/
tests/
```

---

## Engineering principles

AN favors correctness over automation, explicit failure over silent corruption, local ownership over platform lock-in, and stable data contracts over premature intelligence.

Stable capability belongs in tools and Skills; deterministic repeated processes belong in Workflows; open-ended decisions belong in Agents. Source evidence and canonical artifacts must remain auditable, portable, reproducible, and recoverable.

---

## Roadmap

```text
Identity / Metadata
        ↓
Discovery
        ↓
Acquisition
        ↓
Verification
        ↓
Canonical Document          ← v0.7
        ↓
AI Consumption Views        ← v0.7
        ↓
Scientific Semantic Layer   ← next
        ↓
Knowledge
        ↓
Workflow / Skill
        ↓
Agent
        ↓
Lab Scientific Intelligence
```

The next layer is scientific semantics: entities, methods, conditions, measurements, claims, and relations. Those capabilities are intentionally not claimed as part of v0.7.

---

## Documentation and participation

- [User Manual](docs/USER_MANUAL.md)
- [v0.7 Parsing Contract](docs/V07_PARSING_CONTRACT.md)
- [v0.7 Architecture](docs/V07_ARCHITECTURE.md)
- [v0.7 OCR](docs/V07_OCR.md)
- [v0.7.0 Release Notes](docs/RELEASE_NOTES_v0.7.0.md)
- [Release History](docs/RELEASE_HISTORY.md)
- [CI Architecture](docs/CI_ARCHITECTURE.md)
- [Benchmarks](benchmarks/README.md)

If you are trying AN for the first time, feedback is welcome in [Issue #3](https://github.com/shenxuekairui/aletheia-nexus/issues/3).

Do not post copyrighted PDFs, cookies, tokens, institutional login screenshots, signed URLs, or unredacted local paths in public issues. Use private vulnerability reporting for security problems.

---

## License

Code is released under the [Apache License 2.0](LICENSE). Third-party papers and supplementary materials remain subject to their own copyright, licenses, and access conditions.

*Aletheia* means truth; *Nexus* means connection.

AN is not trying to become a smarter download script. It is building a layer of scientific data infrastructure that can be trusted long enough for every later layer of AI to stand on.
