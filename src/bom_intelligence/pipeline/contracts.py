"""Stable adapter contracts: profilers, extractors, and routing decisions.

New formats plug in by implementing these protocols and registering with an
:class:`AdapterRegistry`; the canonical BOM models never change for a new format.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from bom_intelligence.models.bom import BOMRecord
from bom_intelligence.models.diagnostics import Diagnostic, FailureCode
from bom_intelligence.models.document import DocumentType
from bom_intelligence.profiler.common import ProfileBase


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DocumentRef(_Model):
    """A document to process: where it is and how it was identified."""

    path: Path
    """Absolute path on disk (not serialized into results)."""
    relative_path: str
    sha256: str | None
    document_type: DocumentType


class ExtractionResult(_Model):
    extractor: str
    records: tuple[BOMRecord, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def succeeded(self) -> bool:
        return bool(self.records)


class RouteStrategy(StrEnum):
    DETERMINISTIC_EXCEL = "deterministic_excel"
    DETERMINISTIC_PPT_TABLE = "deterministic_ppt_table"
    SEMANTIC_TEXT = "semantic_text"
    SPATIAL_SEMANTIC = "spatial_semantic"
    OCR = "ocr"
    HUMAN_REVIEW = "human_review"
    UNSUPPORTED = "unsupported"


ROUTE_BUCKET: dict[RouteStrategy, str] = {
    RouteStrategy.DETERMINISTIC_EXCEL: "deterministic",
    RouteStrategy.DETERMINISTIC_PPT_TABLE: "deterministic",
    RouteStrategy.SEMANTIC_TEXT: "semantic_candidate",
    RouteStrategy.SPATIAL_SEMANTIC: "semantic_candidate",
    RouteStrategy.OCR: "ocr_or_human",
    RouteStrategy.HUMAN_REVIEW: "ocr_or_human",
    RouteStrategy.UNSUPPORTED: "unsupported",
}


class StrategyDecision(_Model):
    strategy: RouteStrategy
    reasons: tuple[FailureCode, ...] = ()
    explanation: str

    @property
    def bucket(self) -> str:
        return ROUTE_BUCKET[self.strategy]


@runtime_checkable
class DocumentProfiler(Protocol):
    name: str

    def supports(self, document: DocumentRef) -> bool: ...

    def profile(self, document: DocumentRef) -> ProfileBase: ...

    def diagnose(self, profile: ProfileBase) -> list[Diagnostic]: ...


@runtime_checkable
class DocumentExtractor(Protocol):
    name: str
    strategy: RouteStrategy

    def supports(self, document: DocumentRef) -> bool: ...

    def extract(self, document: DocumentRef, profile: ProfileBase) -> ExtractionResult: ...


class AdapterRegistry:
    """Ordered lists of adapters; the first adapter that supports a document wins."""

    def __init__(
        self,
        profilers: list[DocumentProfiler] | None = None,
        extractors: list[DocumentExtractor] | None = None,
    ) -> None:
        self.profilers: list[DocumentProfiler] = list(profilers or [])
        self.extractors: list[DocumentExtractor] = list(extractors or [])

    def register_profiler(self, profiler: DocumentProfiler) -> None:
        self.profilers.append(profiler)

    def register_extractor(self, extractor: DocumentExtractor) -> None:
        self.extractors.append(extractor)

    def profiler_for(self, document: DocumentRef) -> DocumentProfiler | None:
        return next((p for p in self.profilers if p.supports(document)), None)

    def extractor_for(
        self, document: DocumentRef, strategy: RouteStrategy
    ) -> DocumentExtractor | None:
        return next(
            (e for e in self.extractors if e.strategy is strategy and e.supports(document)),
            None,
        )
