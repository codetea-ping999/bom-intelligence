# bom-intelligence

Explainable BOM document intelligence for heterogeneous Excel, PowerPoint, PDF, and image-based source documents.

## Why this project exists

Real-world BOM-related documents often contain part numbers, cost information, and schedule/milestone data in inconsistent layouts and formats. Fixed-position macros work only when the input structure is predictable. This project aims to **measure and explain where that assumption breaks**, then apply the simplest reliable extraction strategy for each case.

The intended pipeline is:

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
Canonical BOM Schema
  ↓
Validator + Explainable Confidence
  ↓
Accept / Review / Reject
  ↓
Failure & Coverage Report
```

## Core principles

1. **Python first for V1.** Rust is reserved for measured performance bottlenecks; shell is for operational glue.
2. **Input formats may vary; the canonical output contract stays stable.**
3. **Every extracted business value must retain exact source provenance.**
4. **Deterministic logic handles deterministic problems.**
5. **AI is an escalation strategy, not the default parser.**
6. **Uncertainty is surfaced instead of silently guessed away.**
7. **Evaluation comes before architecture claims.**
8. **Parser/model/provider implementations stay replaceable behind interfaces.**
9. **One malformed document must not stop a batch.**
10. **Reports must be reproducible from structured evidence.**

## Current status

**Planning / Phase 0.** The repository roadmap and implementation backlog are defined. Development should begin with project foundations, the canonical BOM schema, and document inventory before adding AI.

See:
- [ROADMAP.md](./ROADMAP.md)
- [Master Roadmap Issue #20](https://github.com/codetea-ping999/bom-intelligence/issues/20)
- [Open Issues](https://github.com/codetea-ping999/bom-intelligence/issues)

## Initial MVP

The first useful PoC should be able to:

- inventory `.xlsx`, `.xlsm`, and `.pptx` document sets
- profile Excel and PowerPoint structures
- classify why fixed-schema/macro-style extraction fails
- extract clean Excel table cases deterministically
- preserve exact source provenance
- evaluate results against synthetic/sanitized reference fixtures
- generate a reproducible failure/coverage report

AI is **not required** for the first analysis PoC.

## Planned package shape

```text
src/bom_intelligence/
  cli.py
  models/
  scanner/
  profiler/
  extractor/
  analyzer/
  validator/
  reporting/
tests/
samples/
reports/
```

## Data safety

This is a public repository. **Do not commit real company BOM, cost, schedule, supplier, or other confidential documents/data.** Use synthetic or explicitly sanitized fixtures only.

The planned runtime will also support deterministic/offline execution so confidential-document handling can be separated from external AI-provider access.

## Recommended first implementation order

1. Issue #1 — project foundation and quality gates
2. Issue #2 — canonical BOM schema with provenance
3. Issue #3 — recursive file inventory scanner
4. inspect a small representative local/sanitized document set
5. Issue #4 — Excel profiler
6. Issue #5 — PowerPoint profiler
7. Issue #6 — refine failure taxonomy from observed evidence

The first engineering question is not **which LLM to use**. It is **what document patterns and failure modes actually exist**.
