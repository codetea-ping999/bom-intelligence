"""Failure taxonomy and structured diagnostics.

Diagnostics are a primary deliverable: aggregated, they quantify *why* fixed-position
extraction fails across a document estate. Codes are stable machine-readable
identifiers; descriptions may evolve. See ``docs/failure-codes.md``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from bom_intelligence.models.document import DocumentType


class FailureCode(StrEnum):
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNREADABLE_FILE = "UNREADABLE_FILE"
    PASSWORD_PROTECTED = "PASSWORD_PROTECTED"
    HEADER_NOT_FOUND = "HEADER_NOT_FOUND"
    HEADER_VARIATION = "HEADER_VARIATION"
    SHIFTED_LAYOUT = "SHIFTED_LAYOUT"
    MERGED_LAYOUT = "MERGED_LAYOUT"
    MULTIPLE_TABLES = "MULTIPLE_TABLES"
    MULTIPLE_PART_FIELDS = "MULTIPLE_PART_FIELDS"
    MULTIPLE_COST_FIELDS = "MULTIPLE_COST_FIELDS"
    MULTIPLE_SCHEDULE_FIELDS = "MULTIPLE_SCHEDULE_FIELDS"
    SEMANTIC_AMBIGUITY = "SEMANTIC_AMBIGUITY"
    FREEFORM_LAYOUT = "FREEFORM_LAYOUT"
    HIDDEN_CONTENT = "HIDDEN_CONTENT"
    IMAGE_ONLY = "IMAGE_ONLY"
    EMBEDDED_OBJECT = "EMBEDDED_OBJECT"
    FORMULA_DEPENDENCY = "FORMULA_DEPENDENCY"
    EXTERNAL_LINK_DEPENDENCY = "EXTERNAL_LINK_DEPENDENCY"
    UNKNOWN = "UNKNOWN"


class FailureGroup(StrEnum):
    """Coarse grouping used by reports to separate structure from meaning."""

    ACCESS = "access"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """``error`` blocks deterministic extraction; ``warning`` and ``info`` do not."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class SuggestedStrategy(StrEnum):
    RULE = "rule"
    SEMANTIC = "semantic"
    OCR = "ocr"
    HUMAN_REVIEW = "human_review"
    UNSUPPORTED = "unsupported"


FAILURE_CODE_INFO: dict[FailureCode, tuple[FailureGroup, str]] = {
    FailureCode.UNSUPPORTED_FORMAT: (
        FailureGroup.ACCESS,
        "No adapter exists for this file format yet.",
    ),
    FailureCode.UNREADABLE_FILE: (
        FailureGroup.ACCESS,
        "The file could not be opened or parsed (corrupt, truncated, or wrong format).",
    ),
    FailureCode.PASSWORD_PROTECTED: (
        FailureGroup.ACCESS,
        "The file is encrypted / password protected and cannot be inspected.",
    ),
    FailureCode.HEADER_NOT_FOUND: (
        FailureGroup.SEMANTIC,
        "No row/table contains recognizable BOM header labels.",
    ),
    FailureCode.HEADER_VARIATION: (
        FailureGroup.SEMANTIC,
        "Header labels only partially match known aliases (extra words, variants).",
    ),
    FailureCode.SHIFTED_LAYOUT: (
        FailureGroup.STRUCTURAL,
        "The table does not start at A1, so fixed-position macros read the wrong cells.",
    ),
    FailureCode.MERGED_LAYOUT: (
        FailureGroup.STRUCTURAL,
        "Merged cells overlap the table, breaking one-row-per-record semantics.",
    ),
    FailureCode.MULTIPLE_TABLES: (
        FailureGroup.STRUCTURAL,
        "More than one candidate table exists in the same sheet/slide.",
    ),
    FailureCode.MULTIPLE_PART_FIELDS: (
        FailureGroup.SEMANTIC,
        "More than one column/field looks like a part number.",
    ),
    FailureCode.MULTIPLE_COST_FIELDS: (
        FailureGroup.SEMANTIC,
        "More than one column/field looks like a cost; which one is meant is unclear.",
    ),
    FailureCode.MULTIPLE_SCHEDULE_FIELDS: (
        FailureGroup.SEMANTIC,
        "More than one column/field looks like a schedule date.",
    ),
    FailureCode.SEMANTIC_AMBIGUITY: (
        FailureGroup.SEMANTIC,
        "Values exist but their meaning cannot be determined structurally.",
    ),
    FailureCode.FREEFORM_LAYOUT: (
        FailureGroup.STRUCTURAL,
        "BOM labels are placed in free-form text boxes/shapes rather than a table.",
    ),
    FailureCode.HIDDEN_CONTENT: (
        FailureGroup.STRUCTURAL,
        "Hidden sheets, rows, or columns contain content that may matter.",
    ),
    FailureCode.IMAGE_ONLY: (
        FailureGroup.STRUCTURAL,
        "Content appears to be images only; text is not machine-readable without OCR.",
    ),
    FailureCode.EMBEDDED_OBJECT: (
        FailureGroup.STRUCTURAL,
        "Embedded/OLE objects hold content that is not inspected.",
    ),
    FailureCode.FORMULA_DEPENDENCY: (
        FailureGroup.STRUCTURAL,
        "Values are formulas; results depend on cached values or recalculation.",
    ),
    FailureCode.EXTERNAL_LINK_DEPENDENCY: (
        FailureGroup.STRUCTURAL,
        "Values depend on links to other workbooks that are not available.",
    ),
    FailureCode.UNKNOWN: (
        FailureGroup.UNKNOWN,
        "Not yet classified. Evidence is kept for taxonomy refinement.",
    ),
}


def failure_group(code: FailureCode) -> FailureGroup:
    return FAILURE_CODE_INFO[code][0]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Location(_Model):
    """Format-neutral location inside a document."""

    sheet: str | None = None
    cell_range: str | None = None
    slide: int | None = None
    shape_id: int | None = None
    page: int | None = None

    def label(self) -> str:
        parts: list[str] = []
        if self.sheet is not None:
            parts.append(f"{self.sheet}!{self.cell_range}" if self.cell_range else self.sheet)
        if self.slide is not None:
            parts.append(f"slide {self.slide}")
        if self.page is not None:
            parts.append(f"page {self.page}")
        if self.shape_id is not None:
            parts.append(f"shape {self.shape_id}")
        return " ".join(parts) or "document"


class Observation(_Model):
    """A located piece of evidence (or a candidate value)."""

    location: Location
    text: str | None = None


class Diagnostic(_Model):
    file: str
    document_type: DocumentType
    code: FailureCode
    severity: Severity
    message: str
    suggested_strategy: SuggestedStrategy
    evidence: tuple[Observation, ...] = ()
    candidates: tuple[Observation, ...] = ()

    @property
    def group(self) -> FailureGroup:
        return failure_group(self.code)

    @property
    def blocks_deterministic(self) -> bool:
        return self.severity is Severity.ERROR
