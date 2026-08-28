# BOM Intelligence Roadmap

## Mission

Build an explainable document-intelligence pipeline that analyzes heterogeneous BOM-related documents, quantifies why fixed-position/macro-style extraction fails, extracts reliable cases deterministically, and escalates genuinely ambiguous cases to AI or human review.

## Architecture

```text
Documents
  ↓
Inventory / Scanner
  ↓
Profiler
  ↓
Deterministic Router
  ├─ deterministic parser/extractor
  ├─ semantic AI worker
  ├─ OCR / future adapter
  └─ human review
  ↓
Normalizer → Canonical BOM Schema
  ↓
Validator + Explainable Confidence
  ↓
Accept / Review / Reject
  ↓
Failure & Coverage Report
```

## Phase 0 — Foundation and contracts

**Goal:** establish stable interfaces before processing messy business documents.

- [Issue #1 — Python project foundation and quality gates](https://github.com/codetea-ping999/bom-intelligence/issues/1)
- [Issue #2 — Canonical BOM domain schema with provenance](https://github.com/codetea-ping999/bom-intelligence/issues/2)

### Gate 0

Proceed when:
- clean checkout, tests, lint, and type-check all work
- canonical schema represents part, cost, schedule, provenance, and extraction metadata
- real confidential company data is excluded from the repository

---

## Phase 1 — Discover and explain the document estate

**Goal:** answer what exists and why fixed-schema/macros fail.

- [Issue #3 — Recursive file inventory scanner](https://github.com/codetea-ping999/bom-intelligence/issues/3)
- [Issue #4 — Excel document profiler](https://github.com/codetea-ping999/bom-intelligence/issues/4)
- [Issue #5 — PowerPoint document profiler](https://github.com/codetea-ping999/bom-intelligence/issues/5)
- [Issue #6 — Failure taxonomy and structured diagnostics](https://github.com/codetea-ping999/bom-intelligence/issues/6)

### Gate 1 — Analysis PoC

Using a representative sanitized/local sample set, the system should report:
- format distribution
- structural patterns
- unreadable/unsupported files
- merged/multiple-table/layout complexity
- candidate BOM labels/locations
- structured failure reasons

AI is not required to pass Gate 1.

---

## Phase 2 — Deterministic extraction and measurable baseline

**Goal:** solve easy cases reliably and establish objective metrics.

- [Issue #7 — Document adapter contracts and strategy router](https://github.com/codetea-ping999/bom-intelligence/issues/7)
- [Issue #8 — Deterministic Excel BOM extractor](https://github.com/codetea-ping999/bom-intelligence/issues/8)
- [Issue #9 — Representative fixtures and evaluation harness](https://github.com/codetea-ping999/bom-intelligence/issues/9)
- [Issue #10 — Complexity and failure analysis report](https://github.com/codetea-ping999/bom-intelligence/issues/10)

### Gate 2 — Baseline PoC

Quantify:
- deterministic extraction success rate
- field-level accuracy / precision / recall as appropriate
- false positives
- provenance correctness
- failure-class distribution
- recommended strategy distribution

Target business output:

> X% deterministic, Y% semantic candidate, Z% OCR/human review required.

---

## Phase 3 — AI-assisted semantic escalation

**Goal:** use AI only where semantic ambiguity is the real blocker.

- [Issue #11 — Semantic extraction provider interface](https://github.com/codetea-ping999/bom-intelligence/issues/11)
- [Issue #12 — AI semantic mapper prototype](https://github.com/codetea-ping999/bom-intelligence/issues/12)
- [Issue #13 — Validation, confidence, and escalation policy](https://github.com/codetea-ping999/bom-intelligence/issues/13)

### Gate 3 — AI value proof

AI should advance only if evaluation demonstrates measurable improvement over the deterministic baseline with:
- improved coverage/accuracy
- controlled false-positive rate
- grounded provenance
- clean abstention when evidence is insufficient
- no auto-accept based solely on model self-confidence

If AI does not improve the metrics, do not force it into the architecture.

---

## Phase 4 — Human-in-the-loop and operational PoC

**Goal:** make the pipeline usable on larger batches while keeping uncertainty visible.

- [Issue #14 — Evidence-first human review UI](https://github.com/codetea-ping999/bom-intelligence/issues/14)
- [Issue #15 — Resumable batch runtime and observability](https://github.com/codetea-ping999/bom-intelligence/issues/15)
- [Issue #16 — Security/privacy/confidential-document policy](https://github.com/codetea-ping999/bom-intelligence/issues/16)

### Gate 4 — Operational PoC

A batch should be able to:
1. scan
2. profile
3. route
4. extract
5. validate
6. auto-accept safe cases
7. enqueue uncertain cases
8. generate an auditable report
9. resume after partial failure

---

## Phase 5 — Coverage expansion

**Goal:** extend formats only after the core pipeline is proven.

- [Issue #17 — PDF and image/OCR adapters](https://github.com/codetea-ping999/bom-intelligence/issues/17)
- [Issue #18 — Legacy Office compatibility strategy](https://github.com/codetea-ping999/bom-intelligence/issues/18)
- [Issue #19 — Benchmark native parsers vs general document engines](https://github.com/codetea-ping999/bom-intelligence/issues/19)

Potential later work:
- deterministic PowerPoint table extractor
- spatial relationship extraction for freeform slides
- approved/local multimodal model adapters
- PostgreSQL / API integration
- organization-specific vocabulary/config packs
- reviewed-correction feedback workflow
- selective Rust optimization after profiling proves a bottleneck

---

## MVP definition

The minimum valuable product covers primarily Phases 0–2 and can:
- inventory `.xlsx`, `.xlsm`, `.pptx`
- profile Excel/PowerPoint structure
- classify macro/fixed-schema failure causes
- extract clean Excel table cases deterministically
- preserve exact source provenance
- evaluate against synthetic/sanitized reference fixtures
- generate a reproducible failure/coverage report

## AI-assisted PoC definition

Phase 3 adds:
- semantic mapping for ambiguous cases only
- provider-neutral model interface
- validator + explainable confidence
- explicit abstain/review path

## Production-like PoC definition

Phase 4 adds:
- resumable batch processing
- structured run metadata/logging
- human review/audit trail
- approved confidential-data handling

---

## Monday kickoff

Recommended sequence:

1. #1 project foundation
2. #2 canonical schema
3. #3 inventory scanner
4. inspect a small representative local/sanitized document set
5. #4 Excel profiler
6. #5 PowerPoint profiler
7. refine #6 failure taxonomy using observed evidence

Do not start by wiring an LLM. First establish what kinds of documents and failure modes actually exist.

## Project invariants

1. Input formats may vary; canonical output schema remains stable.
2. Every extracted business value retains provenance.
3. Deterministic logic handles deterministic problems.
4. AI is an escalation strategy, not the default parser.
5. Uncertainty is surfaced, never silently guessed away.
6. Evaluation precedes architectural claims.
7. Real confidential documents never enter this public repository.
8. Parser/model/provider implementations remain replaceable behind interfaces.
9. One bad document must not stop a batch.
10. Reports are reproducible from structured evidence.
