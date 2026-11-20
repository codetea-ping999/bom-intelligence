"""Explicit, explainable strategy routing (no ML)."""

from __future__ import annotations

from bom_intelligence.models.diagnostics import (
    Diagnostic,
    FailureCode,
    Severity,
    SuggestedStrategy,
)
from bom_intelligence.models.document import DocumentType
from bom_intelligence.pipeline.contracts import RouteStrategy, StrategyDecision
from bom_intelligence.profiler.common import ProfileBase

_DETERMINISTIC_BY_KIND: dict[str, RouteStrategy] = {
    "excel": RouteStrategy.DETERMINISTIC_EXCEL,
    "powerpoint": RouteStrategy.DETERMINISTIC_PPT_TABLE,
}
_SPATIAL_CODES = frozenset({FailureCode.FREEFORM_LAYOUT})


def _codes(diagnostics: list[Diagnostic]) -> tuple[FailureCode, ...]:
    seen: dict[FailureCode, None] = {}
    for d in diagnostics:
        seen.setdefault(d.code, None)
    return tuple(seen)


def route(
    document_type: DocumentType,
    profile: ProfileBase | None,
    diagnostics: list[Diagnostic],
) -> StrategyDecision:
    reasons = _codes(diagnostics)
    if profile is None:
        if document_type in (DocumentType.PDF, DocumentType.IMAGE):
            return StrategyDecision(
                strategy=RouteStrategy.OCR,
                reasons=reasons or (FailureCode.UNSUPPORTED_FORMAT,),
                explanation=f"No native {document_type.value} adapter; OCR/document adapter.",
            )
        return StrategyDecision(
            strategy=RouteStrategy.UNSUPPORTED,
            reasons=reasons or (FailureCode.UNSUPPORTED_FORMAT,),
            explanation=f"No adapter for {document_type.value} files.",
        )
    if profile.read_error is not None:
        if profile.read_error.code is FailureCode.PASSWORD_PROTECTED:
            return StrategyDecision(
                strategy=RouteStrategy.HUMAN_REVIEW,
                reasons=reasons,
                explanation="Encrypted file; a person must supply an unprotected copy.",
            )
        return StrategyDecision(
            strategy=RouteStrategy.UNSUPPORTED,
            reasons=reasons,
            explanation="File could not be read.",
        )

    blockers = [d for d in diagnostics if d.severity is Severity.ERROR]
    if not blockers:
        deterministic = _DETERMINISTIC_BY_KIND.get(profile.kind)
        if deterministic is not None and profile.layout_hint in (
            "regular_table",
            "multi_table",  # one table per sheet; competing tables raise MULTIPLE_TABLES
            "table",
        ):
            return StrategyDecision(
                strategy=deterministic,
                reasons=reasons,
                explanation="Unambiguous table; deterministic extraction.",
            )
        return StrategyDecision(
            strategy=RouteStrategy.HUMAN_REVIEW,
            reasons=reasons,
            explanation="No blocking diagnostic but no recognized table either.",
        )

    suggested = {d.suggested_strategy for d in blockers}
    blocker_codes = {d.code for d in blockers}
    if SuggestedStrategy.OCR in suggested:
        strategy, why = RouteStrategy.OCR, "Content is image-only."
    elif SuggestedStrategy.HUMAN_REVIEW in suggested:
        strategy, why = RouteStrategy.HUMAN_REVIEW, "Unclassified or opaque content."
    elif blocker_codes & _SPATIAL_CODES:
        strategy, why = RouteStrategy.SPATIAL_SEMANTIC, "BOM labels laid out spatially."
    else:
        strategy, why = RouteStrategy.SEMANTIC_TEXT, "Structure found but meaning is ambiguous."
    blocking = ", ".join(sorted(c.value for c in blocker_codes))
    return StrategyDecision(
        strategy=strategy, reasons=reasons, explanation=f"{why} Blocked by: {blocking}."
    )
