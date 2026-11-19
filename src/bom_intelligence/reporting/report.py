"""Document complexity and failure analysis report.

Everything here is computed from stored ``results.jsonl`` (plus optional metrics),
so every number can be reproduced from structured outputs.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from bom_intelligence import __version__
from bom_intelligence.models.diagnostics import (
    FAILURE_CODE_INFO,
    FailureCode,
    FailureGroup,
    Severity,
    failure_group,
)
from bom_intelligence.pipeline.contracts import ROUTE_BUCKET, RouteStrategy
from bom_intelligence.pipeline.run import DocumentResult

COMPLEXITY_WEIGHTS: dict[FailureCode, tuple[str, float]] = {
    FailureCode.MULTIPLE_TABLES: ("multiple_tables", 2.0),
    FailureCode.MERGED_LAYOUT: ("merged_regions", 2.0),
    FailureCode.HEADER_NOT_FOUND: ("header_ambiguity", 2.0),
    FailureCode.HEADER_VARIATION: ("header_ambiguity", 1.0),
    FailureCode.MULTIPLE_PART_FIELDS: ("multiple_candidate_fields", 1.5),
    FailureCode.MULTIPLE_COST_FIELDS: ("multiple_candidate_fields", 1.5),
    FailureCode.MULTIPLE_SCHEDULE_FIELDS: ("multiple_candidate_fields", 1.5),
    FailureCode.IMAGE_ONLY: ("image_content", 3.0),
    FailureCode.EMBEDDED_OBJECT: ("embedded_objects", 2.0),
    FailureCode.FREEFORM_LAYOUT: ("spatial_freeform_layout", 2.0),
    FailureCode.SEMANTIC_AMBIGUITY: ("semantic_ambiguity", 2.0),
    FailureCode.SHIFTED_LAYOUT: ("shifted_layout", 0.5),
    FailureCode.HIDDEN_CONTENT: ("hidden_content", 0.5),
    FailureCode.FORMULA_DEPENDENCY: ("formula_dependency", 0.5),
    FailureCode.EXTERNAL_LINK_DEPENDENCY: ("external_links", 1.0),
    FailureCode.UNKNOWN: ("unclassified", 2.0),
}
"""Prioritization aid, not a scientific measure. Access failures are not scored."""

BUCKET_LABELS = {
    "deterministic": "deterministic",
    "semantic_candidate": "semantic candidate",
    "ocr_or_human": "OCR/human review required",
    "unsupported": "unsupported/unreadable",
}
EXAMPLES_PER_CODE = 2
EXAMPLE_TEXT_LIMIT = 40


def _pct(num: int, den: int) -> float:
    return 0.0 if den == 0 else round(100.0 * num / den, 1)


def complexity(result: DocumentResult) -> tuple[float | None, list[str]]:
    codes = {d.code for d in result.diagnostics}
    if any(failure_group(c) is FailureGroup.ACCESS for c in codes):
        return None, ["not assessable: " + ",".join(sorted(c.value for c in codes))]
    factors: dict[str, float] = {}
    for code in sorted(codes, key=lambda c: c.value):
        if code in COMPLEXITY_WEIGHTS:
            name, weight = COMPLEXITY_WEIGHTS[code]
            factors[name] = max(factors.get(name, 0.0), weight)
    score = round(sum(factors.values()), 2)
    return score, [f"{name}+{weight:g}" for name, weight in sorted(factors.items())]


def _sanitize(text: str | None) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text if len(text) <= EXAMPLE_TEXT_LIMIT else text[: EXAMPLE_TEXT_LIMIT - 1] + "…"


def build_summary(
    results: list[DocumentResult], metrics: dict[str, object] | None = None
) -> dict[str, object]:
    total = len(results)
    formats = Counter(r.document_type.value for r in results)
    dup_groups = {r.duplicate_group for r in results if r.duplicate_group}
    dup_files = sum(1 for r in results if r.duplicate_group)
    codes_per_doc = [{d.code for d in r.diagnostics} for r in results]
    layouts = Counter(r.layout_hint or "n/a" for r in results)

    strategies = Counter(r.decision.strategy for r in results)
    buckets = Counter(ROUTE_BUCKET[r.decision.strategy] for r in results)
    routed_det = [r for r in results if ROUTE_BUCKET[r.decision.strategy] == "deterministic"]
    succeeded = [r for r in routed_det if r.records]

    taxonomy: list[dict[str, object]] = []
    for code in FailureCode:
        docs = [r for r, codes in zip(results, codes_per_doc, strict=True) if code in codes]
        if not docs:
            continue
        severities = Counter(
            d.severity.value for r in docs for d in r.diagnostics if d.code is code
        )
        taxonomy.append(
            {
                "code": code.value,
                "group": failure_group(code).value,
                "documents": len(docs),
                "percent_of_documents": _pct(len(docs), total),
                "severity": dict(sorted(severities.items())),
                "description": FAILURE_CODE_INFO[code][1],
            }
        )
    taxonomy.sort(key=lambda t: (-int(str(t["documents"])), str(t["code"])))

    group_docs: dict[str, int] = {}
    for group in FailureGroup:
        group_docs[group.value] = sum(
            1
            for r in results
            if any(
                failure_group(d.code) is group and d.severity is Severity.ERROR
                for d in r.diagnostics
            )
        )

    examples: dict[str, list[dict[str, object]]] = defaultdict(list)
    for r in results:
        for d in r.diagnostics:
            bucket = examples[d.code.value]
            if len(bucket) >= EXAMPLES_PER_CODE or any(e["path"] == r.path for e in bucket):
                continue
            first = (d.evidence or d.candidates or (None,))[0]
            bucket.append(
                {
                    "path": r.path,
                    "message": d.message,
                    "location": None if first is None else first.location.label(),
                    "text": None if first is None else _sanitize(first.text),
                }
            )

    scores = []
    for r in results:
        score, factors = complexity(r)
        scores.append({"path": r.path, "score": score, "factors": factors})
    scored = [s for s in scores if s["score"] is not None]

    bucket_pct = {b: _pct(buckets.get(b, 0), total) for b in BUCKET_LABELS}
    statement = ", ".join(f"{bucket_pct[b]}% {label}" for b, label in BUCKET_LABELS.items())
    return {
        "tool_version": __version__,
        "documents": total,
        "formats": dict(sorted(formats.items())),
        "duplicates": {
            "files_in_duplicate_groups": dup_files,
            "duplicate_groups": len(dup_groups),
            "redundant_copies": dup_files - len(dup_groups),
        },
        "access": {
            "unreadable": sum(FailureCode.UNREADABLE_FILE in c for c in codes_per_doc),
            "password_protected": sum(FailureCode.PASSWORD_PROTECTED in c for c in codes_per_doc),
            "unsupported_format": sum(FailureCode.UNSUPPORTED_FORMAT in c for c in codes_per_doc),
        },
        "structural_patterns": dict(sorted(layouts.items())),
        "deterministic": {
            "routed": len(routed_det),
            "succeeded": len(succeeded),
            "success_rate_of_routed": _pct(len(succeeded), len(routed_det)),
            "success_rate_of_all_documents": _pct(len(succeeded), total),
            "records": sum(len(r.records) for r in results),
        },
        "blocking_documents_by_group": group_docs,
        "failure_taxonomy": taxonomy,
        "top_failure_causes": [t["code"] for t in taxonomy[:5]],
        "routing": {s.value: strategies.get(s, 0) for s in RouteStrategy},
        "routing_buckets": {b: buckets.get(b, 0) for b in BUCKET_LABELS},
        "routing_buckets_percent": bucket_pct,
        "headline": statement,
        "complexity": {
            "weights": {c.value: w for c, (_, w) in COMPLEXITY_WEIGHTS.items()},
            "mean_score": (
                round(sum(float(str(s["score"])) for s in scored) / len(scored), 2)
                if scored
                else None
            ),
            "documents": scores,
        },
        "examples": dict(sorted(examples.items())),
        "evaluation": None
        if metrics is None
        else {k: v for k, v in metrics.items() if k != "details"},
    }


def _write_csvs(results: list[DocumentResult], output: Path) -> None:
    with (output / "documents.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "path",
                "document_type",
                "layout_hint",
                "strategy",
                "bucket",
                "records",
                "complexity_score",
                "complexity_factors",
                "codes",
            ]
        )
        for r in results:
            score, factors = complexity(r)
            writer.writerow(
                [
                    r.path,
                    r.document_type.value,
                    r.layout_hint or "",
                    r.decision.strategy.value,
                    ROUTE_BUCKET[r.decision.strategy],
                    len(r.records),
                    "" if score is None else score,
                    "; ".join(factors),
                    ";".join(sorted({d.code.value for d in r.diagnostics})),
                ]
            )
    with (output / "diagnostics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["path", "code", "group", "severity", "suggested_strategy", "location", "message"]
        )
        for r in results:
            for d in r.diagnostics:
                first = (d.evidence or d.candidates or (None,))[0]
                writer.writerow(
                    [
                        r.path,
                        d.code.value,
                        d.group.value,
                        d.severity.value,
                        d.suggested_strategy.value,
                        "" if first is None else first.location.label(),
                        d.message,
                    ]
                )


def _markdown(summary: dict[str, object]) -> str:
    s = summary
    det = s["deterministic"]
    dup = s["duplicates"]
    acc = s["access"]
    assert isinstance(det, dict) and isinstance(dup, dict) and isinstance(acc, dict)
    lines = [
        "# BOM document complexity and failure analysis",
        "",
        f"**Headline:** {s['headline']}.",
        "",
        "All numbers below are recomputed from `results.jsonl` by `bom report`.",
        "",
        "## Document estate",
        "",
        f"- Documents: {s['documents']}",
        "- Formats: " + ", ".join(f"{k} {v}" for k, v in dict(s["formats"]).items()),  # type: ignore[call-overload]
        f"- Duplicates: {dup['files_in_duplicate_groups']} files in "
        f"{dup['duplicate_groups']} groups ({dup['redundant_copies']} redundant copies)",
        f"- Unreadable: {acc['unreadable']}, password protected: {acc['password_protected']}, "
        f"unsupported format: {acc['unsupported_format']}",
        "",
        "## Structural patterns",
        "",
        "| Pattern | Documents |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in dict(s["structural_patterns"]).items()]  # type: ignore[call-overload]
    lines += [
        "",
        "## Deterministic extraction",
        "",
        f"- Routed to deterministic extractors: {det['routed']}",
        f"- Succeeded: {det['succeeded']} ({det['success_rate_of_routed']}% of routed, "
        f"{det['success_rate_of_all_documents']}% of all documents)",
        f"- Records extracted: {det['records']}",
        "",
        "## Structural vs semantic blockers",
        "",
        "Documents with at least one blocking (error) diagnostic, by group:",
        "",
        "| Group | Documents |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in dict(s["blocking_documents_by_group"]).items()]  # type: ignore[call-overload]
    lines += [
        "",
        "## Failure taxonomy",
        "",
        "| Code | Group | Documents | % of documents | Severity |",
        "|---|---|---|---|---|",
    ]
    for t in list(s["failure_taxonomy"]):  # type: ignore[call-overload]
        sev = ", ".join(f"{k} {v}" for k, v in t["severity"].items())
        lines.append(
            f"| `{t['code']}` | {t['group']} | {t['documents']} | "
            f"{t['percent_of_documents']} | {sev} |"
        )
    lines += ["", "## Routing", "", "| Strategy | Documents |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in dict(s["routing"]).items()]  # type: ignore[call-overload]
    lines += [
        "",
        "## Complexity",
        "",
        "Score = sum of weighted factors observed in the document. It is a prioritization "
        "aid, not a measurement; the factors are listed so each score can be checked.",
        "",
        "| Document | Score | Factors |",
        "|---|---|---|",
    ]
    complexity_info = s["complexity"]
    assert isinstance(complexity_info, dict)
    for d in sorted(
        complexity_info["documents"],
        key=lambda x: (-(x["score"] if x["score"] is not None else -1), x["path"]),
    ):
        score = "n/a" if d["score"] is None else d["score"]
        lines.append(f"| {d['path']} | {score} | {', '.join(d['factors'])} |")
    lines += ["", "## Representative examples", ""]
    for code, items in dict(s["examples"]).items():  # type: ignore[call-overload]
        lines.append(f"- `{code}`")
        for e in items:
            where = f" at {e['location']}" if e["location"] else ""
            text = f' ("{e["text"]}")' if e["text"] else ""
            lines.append(f"  - {e['path']}{where}{text}: {e['message']}")
    evaluation = s.get("evaluation")
    if isinstance(evaluation, dict):
        lines += ["", "## Evaluation against gold set", "", "| Metric | Value |", "|---|---|"]
        for k, v in evaluation.items():
            if not isinstance(v, dict):
                lines.append(f"| {k} | {v} |")
    return "\n".join(lines) + "\n"


def write_report(
    results: list[DocumentResult], output: Path, metrics: dict[str, object] | None = None
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    summary = build_summary(results, metrics)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csvs(results, output)
    (output / "report.md").write_text(_markdown(summary), encoding="utf-8")
    return summary
